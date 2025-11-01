#!/usr/bin/env python3
"""
Codec and encoding helpers for PyFFMPEG
Provides utility functions for codec selection, hardware acceleration detection,
and encoder configuration to reduce duplication in the main application.
"""

import os
import subprocess
import json
from typing import Dict, Optional

from config import ProcessConfig, HardwareConfig, EncodingConfig, FileConfig


class CodecHelpers:
    """Helper class for codec selection, hardware acceleration, and encoder configuration"""

    # Cache for expensive detection operations
    _encoder_cache = None
    _gpu_info_cache = None
    _rtx40_detection_cache = None

    @staticmethod
    def get_output_extension(codec_idx):
        """Determine output file extension based on codec index"""
        if codec_idx in [0, 1, 2, 3, 5, 6]:  # H.264, HEVC, AV1, QSV, VAAPI
            return ".mp4"
        elif codec_idx == 4:  # ProRes
            return ".mov"
        return ".mp4"  # Default

    @staticmethod
    def get_hardware_acceleration_args(hwdecode_idx):
        """Get hardware acceleration arguments based on selected hardware decode option
        Returns a tuple of (args_list, message_for_log)
        """
        args = []
        message = ""

        try:
            if hwdecode_idx == 0:  # Auto
                # Use cached GPU detection for better performance
                gpu_info = CodecHelpers._get_gpu_info()
                if gpu_info and "GPU" in gpu_info:
                    args.extend(["-hwaccel", "cuda"])
                    message = "Using CUDA hardware acceleration (cached detection)"
                else:
                    # Try Intel QSV if NVIDIA not found
                    args.extend(["-hwaccel", "auto"])
                    message = "Using auto hardware acceleration"
            elif hwdecode_idx == 1:  # NVIDIA
                args.extend(["-hwaccel", "cuda"])
                message = "Using CUDA hardware acceleration"
            elif hwdecode_idx == 2:  # Intel QSV
                args.extend(["-hwaccel", "qsv"])
                message = "Using QSV hardware acceleration"
            elif hwdecode_idx == 3:  # VAAPI
                # Only on Linux systems
                if os.name == "posix":
                    args.extend(
                        ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]
                    )
                    message = "Using VAAPI hardware acceleration"
                else:
                    args.extend(["-hwaccel", "auto"])
                    message = "VAAPI not available, falling back to auto"
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as e:
            # If any error occurs, fall back to software decoding
            message = (
                f"Hardware acceleration error: {e}, falling back to software decoding"
            )
            # No hwaccel arguments

        return args, message

    @staticmethod
    def get_audio_codec_args(path, codec_idx):
        """Get audio codec configuration arguments based on input file and selected video codec
        Returns a tuple of (args_list, message_for_log)
        """
        args = []
        message = ""

        try:
            # Check for existing audio - try to pass through when possible
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-show_entries",
                    "stream=codec_name",
                    "-select_streams",
                    "a:0",
                    "-of",
                    "default=nokey=1:noprint_wrappers=1",
                    path,
                ],
                text=True,
                capture_output=True,
                timeout=ProcessConfig.SUBPROCESS_TIMEOUT,
            )
            audio_codec = probe.stdout.strip()

            # Copy AC-3/AAC audio to skip needless re-encode
            if audio_codec in ("aac", "ac3", "eac3"):
                args.extend(["-c:a", "copy"])
                message = f"Detected {audio_codec} audio - using passthrough"
            else:
                # Handle ProRes special case, otherwise AAC
                if codec_idx == 4:  # ProRes
                    args.extend(["-c:a", "pcm_s16le"])
                    message = "Using PCM audio for ProRes"
                else:
                    args.extend(
                        [
                            "-c:a",
                            "aac",
                            "-b:a",
                            f"{EncodingConfig.AUDIO_BITRATE_DEFAULT}k",
                        ]
                    )
                    message = f"Converting audio to AAC {EncodingConfig.AUDIO_BITRATE_DEFAULT}k"
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
            # Fallback to default encoding on error
            if codec_idx == 4:  # ProRes
                args.extend(["-c:a", "pcm_s16le"])
                message = "Fallback to PCM audio for ProRes"
            else:
                args.extend(
                    ["-c:a", "aac", "-b:a", f"{EncodingConfig.AUDIO_BITRATE_DEFAULT}k"]
                )
                message = (
                    f"Fallback to AAC {EncodingConfig.AUDIO_BITRATE_DEFAULT}k audio"
                )

        return args, message

    @staticmethod
    def get_encoder_configuration(
        codec_idx,
        thread_count,
        is_parallel_enabled,
        crf_value,
        hevc_10bit=False,
        nvenc_settings=None,
    ):
        """Get encoder configuration arguments based on codec index
        Returns a tuple of (args_list, message_for_log)

        Codec mapping:
        0 = H.264 NVENC
        1 = HEVC NVENC
        2 = AV1 NVENC
        3 = x264 CPU
        4 = ProRes CPU
        5 = H.264 QSV
        6 = H.264 VAAPI
        """
        args = []
        message = ""

        try:
            # Get cached or detect available encoders
            available_encoders = CodecHelpers._get_available_encoders()

            # H.264 NVENC
            if codec_idx == 0 and "h264_nvenc" in available_encoders:
                args.extend(
                    [
                        "-c:v",
                        "h264_nvenc",
                        "-preset",
                        "p7",  # High quality preset
                        "-profile:v",
                        "high",
                        "-rc",
                        "vbr",  # Use standard vbr mode
                        "-cq",
                        str(crf_value),
                        "-b:v",
                        "0",  # Required for VBR mode
                        "-bf",
                        "4",
                        "-b_ref_mode",
                        "middle",
                        "-temporal-aq",
                        "1",
                        "-spatial-aq",
                        "1",
                        "-rc-lookahead",
                        "32",
                    ]
                )
                message = "Using H.264 NVENC hardware encoding"

            # HEVC NVENC
            elif codec_idx == 1 and "hevc_nvenc" in available_encoders:
                args.extend(
                    [
                        "-c:v",
                        "hevc_nvenc",
                        "-preset",
                        "p7",
                        "-profile:v",
                        "main10" if hevc_10bit else "main",
                        "-rc",
                        "vbr",  # Use standard vbr mode
                        "-cq",
                        str(crf_value),
                        "-b:v",
                        "0",  # Required for VBR mode
                        "-bf",
                        "4",
                        "-b_ref_mode",
                        "middle",
                        "-temporal-aq",
                        "1",
                        "-spatial-aq",
                        "1",
                        "-rc-lookahead",
                        "32",
                    ]
                )
                if hevc_10bit:
                    args.extend(["-pix_fmt", "p010le"])
                message = "Using HEVC NVENC hardware encoding"

            # AV1 NVENC
            elif codec_idx == 2 and "av1_nvenc" in available_encoders:
                args.extend(
                    [
                        "-c:v",
                        "av1_nvenc",
                        "-preset",
                        "p7",
                        "-rc",
                        "vbr",  # AV1 NVENC uses 'vbr' not 'vbr_hq'
                        "-cq",
                        str(crf_value),
                        "-b:v",
                        "0",  # Required for VBR mode
                        "-temporal-aq",
                        "1",
                        "-spatial-aq",
                        "1",
                        "-rc-lookahead",
                        "32",
                        "-highbitdepth",
                        "1",
                    ]
                )
                message = "Using AV1 NVENC hardware encoding"

            # x264 CPU
            elif codec_idx == 3:
                args.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-crf",
                        str(crf_value),
                        "-preset",
                        "medium",
                        "-pix_fmt",
                        "yuv420p",
                    ]
                )
                if thread_count > 0:
                    args.extend(["-threads", str(thread_count)])
                message = "Using x264 CPU encoding"

            # ProRes
            elif codec_idx == 4:
                args.extend(
                    [
                        "-c:v",
                        "prores_ks",
                        "-profile:v",
                        "3",
                        "-vendor",
                        "ap10",
                        "-pix_fmt",
                        "yuv422p10le",
                    ]
                )
                if thread_count > 0:
                    args.extend(["-threads", str(thread_count)])
                message = "Using ProRes 422 encoding"

            # H.264 QSV
            elif codec_idx == 5 and "h264_qsv" in available_encoders:
                args.extend(
                    [
                        "-c:v",
                        "h264_qsv",
                        "-preset",
                        "medium",
                        "-global_quality",
                        str(crf_value),
                    ]
                )
                message = "Using H.264 QSV hardware encoding"

            # H.264 VAAPI
            elif codec_idx == 6 and "h264_vaapi" in available_encoders:
                args.extend(
                    [
                        "-c:v",
                        "h264_vaapi",
                        "-profile:v",
                        "high",
                        "-rc_mode",
                        "CQP",
                        "-qp",
                        str(crf_value),
                    ]
                )
                message = "Using H.264 VAAPI hardware encoding"

            else:
                # Fallback to basic h264
                args.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-crf",
                        str(EncodingConfig.DEFAULT_CRF_FALLBACK),
                        "-preset",
                        "medium",
                        "-pix_fmt",
                        "yuv420p",
                    ]
                )
                if thread_count > 0:
                    args.extend(["-threads", str(thread_count)])
                message = f"Selected codec not available (codec_idx={codec_idx}), falling back to libx264"

        except Exception as e:
            # Ultimate fallback
            message = f"Error selecting codec: {e}, using safe defaults"
            args.extend(
                [
                    "-c:v",
                    "libx264",
                    "-crf",
                    "23",
                    "-preset",
                    "medium",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            if thread_count > 0:
                args.extend(["-threads", str(thread_count)])

        return args, message

    @staticmethod
    def optimize_threads_for_codec(
        codec_idx, is_parallel_enabled, file_codec_assignments=None
    ):
        """Optimize thread count based on selected codec and parallel processing mode"""
        # NVENC encoders - minimal CPU usage
        if codec_idx in (0, 1, 2):  # Any NVENC encoder
            return 2

        # Hardware encoders (QSV, VAAPI) - moderate CPU usage
        if codec_idx in (5, 6):  # QSV, VAAPI
            return 4

        # Single CPU job - let encoder use most threads but leave some for system
        if not is_parallel_enabled:
            cpu_count = os.cpu_count() or ProcessConfig.OPTIMAL_CPU_THREADS
            return max(2, cpu_count - 4)  # Leave 4 threads for system

        # Parallel CPU jobs - divide threads efficiently
        # For auto-balance: assume worst case of all CPU jobs running simultaneously
        if file_codec_assignments:
            cpu_jobs = max(
                1, sum(1 for c in file_codec_assignments.values() if c in (3, 4))
            )  # x264, ProRes
        else:
            cpu_jobs = 2  # Conservative estimate for parallel processing

        cpu_count = os.cpu_count() or ProcessConfig.OPTIMAL_CPU_THREADS
        threads_per_job = max(
            2, (cpu_count - 2) // cpu_jobs
        )  # Leave 2 threads for system
        return threads_per_job

    @staticmethod
    def _get_available_encoders():
        """Get available encoders with caching for performance"""
        if CodecHelpers._encoder_cache is not None:
            return CodecHelpers._encoder_cache

        try:
            encoders_output = subprocess.check_output(
                ["ffmpeg", "-encoders"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=ProcessConfig.SUBPROCESS_TIMEOUT,
            )
            CodecHelpers._encoder_cache = encoders_output.lower()
            return CodecHelpers._encoder_cache
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
            # Cache the failure to avoid repeated attempts
            CodecHelpers._encoder_cache = ""
            return ""

    @staticmethod
    def _get_gpu_info():
        """Get GPU information with caching"""
        if CodecHelpers._gpu_info_cache is not None:
            return CodecHelpers._gpu_info_cache

        try:
            gpu_info = subprocess.check_output(
                ["nvidia-smi", "-q"], timeout=HardwareConfig.GPU_DETECTION_TIMEOUT
            ).decode("utf-8")
            CodecHelpers._gpu_info_cache = gpu_info
            return gpu_info
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
            CodecHelpers._gpu_info_cache = ""
            return ""

    @staticmethod
    def detect_rtx40_series():
        """Detect if system has RTX 40 series GPU for AV1 encoding support with caching"""
        if CodecHelpers._rtx40_detection_cache is not None:
            return CodecHelpers._rtx40_detection_cache

        try:
            gpu_info = CodecHelpers._get_gpu_info()
            has_rtx40 = any(gpu in gpu_info for gpu in HardwareConfig.RTX40_MODELS)
            CodecHelpers._rtx40_detection_cache = has_rtx40
            return has_rtx40
        except Exception:
            CodecHelpers._rtx40_detection_cache = False
            return False

    @staticmethod
    def clear_cache():
        """Clear all cached detection results - useful for testing or system changes"""
        CodecHelpers._encoder_cache = None
        CodecHelpers._gpu_info_cache = None
        CodecHelpers._rtx40_detection_cache = None

    @staticmethod
    def extract_video_metadata(file_path: str) -> Optional[Dict]:
        """Extract video metadata using ffprobe

        Returns:
            Dict with keys: duration, width, height, codec, bitrate, format_name
            None if extraction fails
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=ProcessConfig.SUBPROCESS_TIMEOUT,
            )

            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)

            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                return None

            # Extract format info
            format_info = data.get("format", {})

            # Parse duration
            duration_str = format_info.get("duration", "0")
            try:
                duration_seconds = float(duration_str)
                duration_formatted = CodecHelpers._format_duration(duration_seconds)
            except (ValueError, TypeError):
                duration_formatted = "Unknown"
                duration_seconds = 0

            # Extract video properties
            width = video_stream.get("width", 0)
            height = video_stream.get("height", 0)
            codec_name = video_stream.get("codec_name", "Unknown")

            # Calculate bitrate
            bitrate_bps = None
            if "bit_rate" in video_stream:
                try:
                    bitrate_bps = int(video_stream["bit_rate"])
                except (ValueError, TypeError):
                    pass

            if not bitrate_bps and "bit_rate" in format_info:
                try:
                    bitrate_bps = int(format_info["bit_rate"])
                except (ValueError, TypeError):
                    pass

            bitrate_formatted = (
                CodecHelpers._format_bitrate(bitrate_bps) if bitrate_bps else "Unknown"
            )

            return {
                "duration": duration_formatted,
                "duration_seconds": duration_seconds,
                "width": width,
                "height": height,
                "codec": codec_name.upper(),
                "bitrate": bitrate_formatted,
                "bitrate_bps": bitrate_bps,
                "format_name": format_info.get("format_name", "Unknown"),
            }

        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            OSError,
            Exception,
        ):
            return None

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration from seconds to HH:MM:SS"""
        if seconds <= 0:
            return "00:00:00"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_bitrate(bitrate_bps: Optional[int]) -> str:
        """Format bitrate from bits per second to human readable"""
        if not bitrate_bps or bitrate_bps <= 0:
            return "Unknown"

        # Convert to Mbps
        mbps = bitrate_bps / 1_000_000

        if mbps >= 1000:
            return f"{mbps / 1000:.1f} Gbps"
        elif mbps >= 1:
            return f"{mbps:.1f} Mbps"
        else:
            # Convert to Kbps
            kbps = bitrate_bps / 1000
            return f"{kbps:.0f} Kbps"

    @staticmethod
    def estimate_output_size(
        input_metadata: Dict, codec_idx: int, crf_value: int
    ) -> Optional[str]:
        """Estimate output file size based on input metadata and encoding settings

        Args:
            input_metadata: Metadata dict from extract_video_metadata
            codec_idx: Codec index (0=H.264 NVENC, 1=HEVC NVENC, etc.)
            crf_value: Quality setting

        Returns:
            Formatted size string like "850 MB" or None if calculation fails
        """
        duration_seconds = input_metadata.get("duration_seconds", 0)
        if duration_seconds <= 0:
            return None

        # Get base size factor from config
        size_factors = {
            0: FileConfig.SIZE_FACTOR_H264,  # H.264 NVENC
            1: FileConfig.SIZE_FACTOR_HEVC,  # HEVC NVENC
            2: FileConfig.SIZE_FACTOR_AV1,  # AV1 NVENC
            3: FileConfig.SIZE_FACTOR_X264,  # x264
            4: FileConfig.SIZE_FACTOR_PRORES_422
            if crf_value <= 20
            else FileConfig.SIZE_FACTOR_PRORES_4444,  # ProRes
            5: FileConfig.SIZE_FACTOR_H264,  # H.264 QSV
            6: FileConfig.SIZE_FACTOR_H264,  # H.264 VAAPI
        }

        base_factor = size_factors.get(codec_idx, FileConfig.SIZE_FACTOR_DEFAULT)

        # Apply quality multiplier based on CRF
        # Lower CRF = higher quality = larger file
        if crf_value <= 15:
            quality_multiplier = 1.5
        elif crf_value <= 18:
            quality_multiplier = 1.2
        elif crf_value <= 23:
            quality_multiplier = 1.0
        elif crf_value <= 28:
            quality_multiplier = 0.8
        else:
            quality_multiplier = 0.6

        # Calculate size in MB
        duration_minutes = duration_seconds / 60
        estimated_mb = duration_minutes * base_factor * quality_multiplier

        return CodecHelpers._format_file_size(
            estimated_mb * 1_000_000
        )  # Convert to bytes

    @staticmethod
    def _format_file_size(size_bytes: float) -> str:
        """Format file size in bytes to human readable"""
        if size_bytes < 1024:
            return f"{size_bytes:.0f} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.0f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
