#!/usr/bin/env python3
"""
Conversion Controller Module for PyMPEG
Handles the core conversion logic, process management, and conversion workflow
"""

import os
import time
from typing import Dict, List, Optional
from PySide6.QtCore import QObject, Signal, QProcess

from process_manager import ProcessManager
from codec_helpers import CodecHelpers
from config import EncodingConfig
from logging_config import get_logger


class ConversionController(QObject):
    """Controls the conversion process workflow and codec management"""

    # Signals for communication with UI
    conversion_started = Signal()
    conversion_finished = Signal()
    conversion_stopped = Signal()
    log_message = Signal(str)  # For main log messages
    progress_updated = Signal()  # For UI progress updates

    def __init__(self, process_manager: ProcessManager, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self.process_manager = process_manager
        self.process_monitor = None  # Will be set later
        self.file_list_widget = None  # Will be set later

        # Conversion state
        self.is_converting = False
        self.auto_balance_enabled = False
        self.file_codec_assignments: Dict[str, int] = {}
        self.queue: List[str] = []
        self.current_path: Optional[str] = None
        self.batch_start_time: Optional[float] = None

        # Connect process manager signals
        self.process_manager.process_finished.connect(self._on_process_finished)
        self.process_manager.update_progress.connect(self.progress_updated.emit)

    def set_process_monitor(self, process_monitor):
        """Set the process monitor after it's created"""
        self.process_monitor = process_monitor

    def set_file_list_widget(self, file_list_widget):
        """Set the file list widget for status updates"""
        self.file_list_widget = file_list_widget

    def start_conversion(
        self,
        file_paths: List[str],
        codec_idx: int,
        hwdecode_idx: int,
        crf_value: int,
        parallel_enabled: bool,
        max_parallel: int,
        delete_source: bool,
        overwrite_mode: bool,
    ) -> bool:
        """Start the conversion process with given parameters"""
        if self.is_converting:
            self.log_message.emit("⚠️ Conversion already in progress")
            return False

        if not file_paths:
            self.log_message.emit("⚠️ No files selected for conversion")
            return False

        self.is_converting = True
        self.queue = list(file_paths)
        self.batch_start_time = time.time()

        # Perform auto-balance if enabled
        if self.auto_balance_enabled:
            self._auto_balance_workload(file_paths, codec_idx)

        # Start batch in process manager
        self.process_manager.start_batch(file_paths, parallel_enabled, max_parallel)

        # Store conversion settings
        self.codec_idx = codec_idx
        self.hwdecode_idx = hwdecode_idx
        self.crf_value = crf_value
        self.parallel_enabled = parallel_enabled
        self.max_parallel = max_parallel
        self.delete_source = delete_source
        self.overwrite_mode = overwrite_mode

        self.log_message.emit(f"🚀 Starting conversion of {len(file_paths)} files...")
        self.conversion_started.emit()

        # Start processing
        self._process_next()
        return True

    def stop_conversion(self) -> None:
        """Stop the current conversion process"""
        if not self.is_converting:
            return

        self.log_message.emit("🛑 Stopping conversion...")
        self.is_converting = False

        # Stop all processes
        stopped_processes = self.process_manager.stop_all_processes()
        self.log_message.emit(f"Stopped {len(stopped_processes)} processes")

        self.conversion_stopped.emit()

    def _process_next(self) -> None:
        """Process the next file in the queue"""
        if not self.is_converting or not self.queue:
            if self.is_converting and not self.queue:
                self._finish_conversion()
            return

        # For parallel processing, process multiple files up to the limit
        while self.queue and getattr(self, 'parallel_enabled', False):
            # Check if we can start more processes
            active_count = len(self.process_manager.processes)
            if active_count >= getattr(self, 'max_parallel', 1):
                break  # Wait for a process to finish

            # Process one file
            self._process_single_file()

        # For non-parallel processing, process just one file
        if not getattr(self, 'parallel_enabled', False) and self.queue:
            active_count = len(self.process_manager.processes)
            if active_count < getattr(self, 'max_parallel', 1):
                self._process_single_file()

    def _process_single_file(self) -> None:
        """Process a single file from the queue"""
        if not self.queue:
            return

        # Get next file
        file_path = self.queue.pop(0)
        self.current_path = file_path

        # Determine codec for this file
        codec_idx = self._get_codec_for_path(file_path)

        # Build FFmpeg arguments
        ffmpeg_args = self._build_ffmpeg_args(file_path, codec_idx)

        self.log_message.emit(f"📂 Processing: {os.path.basename(file_path)}")

        # Update file list status to processing
        if self.file_list_widget:
            self.file_list_widget.set_status(file_path, "processing")

        # Start the process
        process = self.process_manager.start_process(file_path, ffmpeg_args)

        # Create process widget if monitor is available
        if self.process_monitor and process.state() != QProcess.ProcessState.NotRunning:
            self.process_monitor.create_process_widget(process, file_path)

    def _build_ffmpeg_args(self, input_path: str, codec_idx: int) -> List[str]:
        """Build FFmpeg command arguments for the given file and codec"""
        args = ["-y"]  # Overwrite output files

        # Add hardware acceleration if enabled
        hw_args, hw_message = CodecHelpers.get_hardware_acceleration_args(
            self.hwdecode_idx
        )
        args.extend(hw_args)
        if hw_message:
            self.log_message.emit(f"🔧 {hw_message}")

        # Input file
        args.extend(["-i", input_path])

        # Get audio codec configuration
        audio_args, audio_message = CodecHelpers.get_audio_codec_args(
            input_path, codec_idx
        )
        args.extend(audio_args)
        if audio_message:
            self.log_message.emit(f"🎵 {audio_message}")

        # Get video encoder configuration
        thread_count = self._optimize_threads_for_codec(codec_idx)
        encoder_args, encoder_message = CodecHelpers.get_encoder_configuration(
            codec_idx, thread_count, self.parallel_enabled, self.crf_value
        )
        args.extend(encoder_args)
        if encoder_message:
            self.log_message.emit(f"🎬 {encoder_message}")

        # Output file
        output_ext = CodecHelpers.get_output_extension(codec_idx)
        input_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(
            os.path.dirname(input_path), f"{input_name}_RC{output_ext}"
        )
        args.append(output_path)

        return args

    def _get_codec_for_path(self, path: str) -> int:
        """Get the codec index for a specific path (auto-balance or default)"""
        if self.auto_balance_enabled and path in self.file_codec_assignments:
            return self.file_codec_assignments[path]
        return self.codec_idx

    def _optimize_threads_for_codec(self, codec_idx: Optional[int] = None) -> int:
        """Optimize thread count based on codec and parallel processing"""
        if codec_idx is None:
            codec_idx = self.codec_idx

        return CodecHelpers.optimize_threads_for_codec(
            codec_idx, self.parallel_enabled, self.file_codec_assignments
        )

    def _auto_balance_workload(self, file_paths: List[str], default_codec: int) -> None:
        """Auto-balance workload between GPU and CPU encoders"""
        self.log_message.emit("⚖️ Auto-balancing workload between GPU and CPU...")

        total_files = len(file_paths)
        gpu_count = int(total_files * EncodingConfig.GPU_RATIO_DEFAULT)
        cpu_count = total_files - gpu_count

        # Assign GPU encoding to first N files
        for i, path in enumerate(file_paths):
            if i < gpu_count:
                # Use NVENC H.264 for GPU (codec index 0)
                self.file_codec_assignments[path] = 0
            else:
                # Use software x264 for CPU (codec index 3)
                self.file_codec_assignments[path] = 3

        self.log_message.emit(f"📊 Balanced: {gpu_count} GPU, {cpu_count} CPU")

    def _on_process_finished(
        self, process: QProcess, exit_code: int, process_path: str
    ) -> None:
        """Handle process completion"""
        if exit_code == 0:
            self.log_message.emit(f"✅ Completed: {os.path.basename(process_path)}")

            # Update file list status to completed
            if self.file_list_widget:
                # Ensure progress shows 100% before marking as completed
                self.file_list_widget.update_progress(process_path, 100)
                self.file_list_widget.set_status(process_path, "completed")

            # Handle source file deletion if enabled
            if self.delete_source:
                try:
                    os.remove(process_path)
                    self.log_message.emit(
                        f"🗑️ Deleted source: {os.path.basename(process_path)}"
                    )
                except OSError as e:
                    self.log_message.emit(f"⚠️ Could not delete {process_path}: {e}")
        else:
            self.log_message.emit(
                f"❌ Failed: {os.path.basename(process_path)} (exit code: {exit_code})"
            )

            # Update file list status to failed
            if self.file_list_widget:
                self.file_list_widget.set_status(process_path, "failed")

        # Continue with next file if parallel processing
        if self.parallel_enabled and self.queue:
            self._process_next()
        elif not self.parallel_enabled:
            self._process_next()

    def _finish_conversion(self) -> None:
        """Finish the conversion process"""
        # Log batch performance metrics
        if self.batch_start_time:
            batch_duration = time.time() - self.batch_start_time
            self.logger.log_performance(
                "batch_conversion",
                batch_duration,
                {
                    "total_files": len(self.file_codec_assignments)
                    if self.file_codec_assignments
                    else 0
                },
            )

        self.is_converting = False
        self.current_path = None
        self.queue.clear()
        self.file_codec_assignments.clear()
        self.batch_start_time = None

        self.log_message.emit("🎉 Conversion completed!")
        self.conversion_finished.emit()

    def enable_auto_balance(self, enabled: bool) -> None:
        """Enable or disable auto-balance mode"""
        self.auto_balance_enabled = enabled
        if enabled:
            self.log_message.emit("⚖️ Auto-balance mode enabled")
        else:
            self.log_message.emit("⚖️ Auto-balance mode disabled")
            self.file_codec_assignments.clear()
