#!/usr/bin/env python3
"""
Mock objects and utilities for PyFFMPEG testing
Provides specialized mocks for hardware detection, FFmpeg processes, and Qt components
"""

from unittest.mock import Mock
from typing import Dict, List
from PySide6.QtCore import QProcess
import subprocess


class MockFFmpegProcess:
    """Mock FFmpeg process that simulates realistic behavior"""
    
    def __init__(self, duration: float = 600.0, fps: int = 25, success: bool = True):
        self.duration = duration
        self.fps = fps
        self.success = success
        self.progress_frames = 0
        self.max_frames = int(duration * fps)
        
    def get_progress_output(self, frame_number: int) -> str:
        """Generate realistic FFmpeg progress output"""
        time_seconds = frame_number / self.fps
        hours = int(time_seconds // 3600)
        minutes = int((time_seconds % 3600) // 60)
        seconds = time_seconds % 60
        
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"
        bitrate = 1024.0 + (frame_number * 0.1)  # Varying bitrate
        speed = 1.0 + (frame_number * 0.001)  # Slight speed increase
        
        return (
            f"frame={frame_number:5d} fps={self.fps:3d} q=28.0 "
            f"size={frame_number * 4}kB time={time_str} "
            f"bitrate={bitrate:.1f}kbits/s speed={speed:.1f}x"
        )
    
    def simulate_conversion(self) -> List[str]:
        """Simulate complete conversion with progress updates"""
        output_lines = [
            "ffmpeg version 4.4.0",
            "Input #0, mpegts, from 'input.ts':",
            f"  Duration: {self.duration:.2f}, start: 0.000000, bitrate: 1000 kb/s",
            "    Stream #0:0[0x100]: Video: h264",
            "    Stream #0:1[0x101]: Audio: aac",
            "Output #0, mp4, to 'output.mp4':",
        ]
        
        # Generate progress updates every 10% of completion
        for i in range(0, 11):
            frame_number = int((i / 10.0) * self.max_frames)
            if frame_number > 0:
                output_lines.append(self.get_progress_output(frame_number))
        
        if self.success:
            output_lines.append("video:1024kB audio:256kB subtitle:0kB other streams:0kB")
            output_lines.append("Conversion completed successfully")
        else:
            output_lines.append("Error: Conversion failed")
            
        return output_lines


class MockGPUDetection:
    """Mock GPU detection scenarios for testing hardware fallbacks"""
    
    @staticmethod
    def rtx4090_detected():
        """Mock RTX 4090 detection"""
        return """
GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-123-456-789)
Product Name: NVIDIA GeForce RTX 4090
Product Brand: GeForce
Display Mode: Enabled
Display Active: Disabled
Persistence Mode: Disabled
"""

    @staticmethod
    def rtx3080_detected():
        """Mock RTX 3080 detection (no AV1 support)"""
        return """
GPU 0: NVIDIA GeForce RTX 3080 (UUID: GPU-987-654-321)
Product Name: NVIDIA GeForce RTX 3080
Product Brand: GeForce
Display Mode: Enabled
Display Active: Disabled
Persistence Mode: Disabled
"""

    @staticmethod
    def intel_gpu_detected():
        """Mock Intel integrated graphics"""
        return """
GPU 0: Intel(R) UHD Graphics 770
"""

    @staticmethod
    def no_gpu_detected():
        """Mock no GPU scenario"""
        raise subprocess.CalledProcessError(1, "nvidia-smi", "NVIDIA-SMI has failed")


class MockEncoderDetection:
    """Mock encoder detection for different system configurations"""
    
    @staticmethod
    def full_nvenc_support():
        """System with full NVENC support"""
        return """
 V..... h264_nvenc         NVIDIA NVENC H.264 encoder (codec h264)
 V..... hevc_nvenc         NVIDIA NVENC hevc encoder (codec hevc)
 V..... av1_nvenc          NVIDIA NVENC AV1 encoder (codec av1)
 V..... libx264           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V..... prores_ks         Apple ProRes (iCodec Pro) (codec prores)
"""

    @staticmethod
    def limited_nvenc_support():
        """Older NVENC without AV1"""
        return """
 V..... h264_nvenc         NVIDIA NVENC H.264 encoder (codec h264)
 V..... hevc_nvenc         NVIDIA NVENC hevc encoder (codec hevc)
 V..... libx264           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V..... prores_ks         Apple ProRes (iCodec Pro) (codec prores)
"""

    @staticmethod
    def software_only():
        """Software encoders only"""
        return """
 V..... libx264           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V..... libx265           libx265 H.265 / HEVC (codec hevc)
 V..... prores_ks         Apple ProRes (iCodec Pro) (codec prores)
"""

    @staticmethod
    def qsv_support():
        """Intel QSV support"""
        return """
 V..... h264_qsv          H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration) (codec h264)
 V..... hevc_qsv          HEVC (Intel Quick Sync Video acceleration) (codec hevc)
 V..... libx264           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
"""


class MockQProcessManager:
    """Advanced mock for QProcess management testing"""
    
    def __init__(self):
        self.processes: Dict[str, Mock] = {}
        self.process_states: Dict[str, QProcess.ProcessState] = {}
        self.output_buffers: Dict[str, List[bytes]] = {}
        
    def create_mock_process(self, process_id: str, will_succeed: bool = True) -> Mock:
        """Create a mock QProcess with realistic behavior"""
        mock_process = Mock(spec=QProcess)
        
        # Set initial state
        self.process_states[process_id] = QProcess.ProcessState.NotRunning
        self.output_buffers[process_id] = []
        
        # Configure mock methods
        mock_process.state.side_effect = lambda: self.process_states[process_id]
        mock_process.waitForStarted.return_value = True
        
        def mock_start(program, arguments):
            self.process_states[process_id] = QProcess.ProcessState.Running
            # Simulate some output
            self.output_buffers[process_id].extend([
                b"ffmpeg output line 1\n",
                b"ffmpeg output line 2\n"
            ])
        
        def mock_kill():
            self.process_states[process_id] = QProcess.ProcessState.NotRunning
            
        def mock_read_output():
            if self.output_buffers[process_id]:
                return self.output_buffers[process_id].pop(0)
            return b""
        
        mock_process.start.side_effect = mock_start
        mock_process.kill.side_effect = mock_kill
        mock_process.readAllStandardOutput.side_effect = mock_read_output
        
        self.processes[process_id] = mock_process
        return mock_process
    
    def simulate_process_finish(self, process_id: str, exit_code: int = 0):
        """Simulate process completion"""
        if process_id in self.process_states:
            self.process_states[process_id] = QProcess.ProcessState.NotRunning
            # Trigger finished signal if needed
            if hasattr(self.processes[process_id], 'finished'):
                self.processes[process_id].finished.emit(exit_code)


class MockProgressScenarios:
    """Predefined scenarios for progress tracking tests"""
    
    @staticmethod
    def normal_conversion():
        """Normal conversion scenario"""
        return {
            'duration': 600.0,  # 10 minutes
            'progress_updates': [
                'frame=   75 fps= 25 q=28.0 size=  300kB time=00:00:03.00 bitrate= 819.2kbits/s speed=1.0x',
                'frame=  250 fps= 25 q=28.0 size= 1000kB time=00:00:10.00 bitrate= 819.2kbits/s speed=1.0x',
                'frame=  750 fps= 25 q=28.0 size= 3000kB time=00:00:30.00 bitrate= 819.2kbits/s speed=1.0x',
                'frame= 1500 fps= 25 q=28.0 size= 6000kB time=00:01:00.00 bitrate= 819.2kbits/s speed=1.0x',
                'frame= 7500 fps= 25 q=28.0 size=30000kB time=00:05:00.00 bitrate= 819.2kbits/s speed=1.0x',
                'frame=15000 fps= 25 q=28.0 size=60000kB time=00:10:00.00 bitrate= 819.2kbits/s speed=1.0x',
            ],
            'expected_percentages': [0.5, 1.67, 5.0, 10.0, 50.0, 100.0]
        }
    
    @staticmethod
    def slow_conversion():
        """Slow conversion with variable speed"""
        return {
            'duration': 300.0,  # 5 minutes
            'progress_updates': [
                'frame=  125 fps= 25 q=28.0 size=  500kB time=00:00:05.00 bitrate= 819.2kbits/s speed=0.5x',
                'frame=  375 fps= 25 q=28.0 size= 1500kB time=00:00:15.00 bitrate= 819.2kbits/s speed=0.75x',
                'frame= 1250 fps= 25 q=28.0 size= 5000kB time=00:00:50.00 bitrate= 819.2kbits/s speed=0.8x',
                'frame= 3750 fps= 25 q=28.0 size=15000kB time=00:02:30.00 bitrate= 819.2kbits/s speed=0.9x',
                'frame= 7500 fps= 25 q=28.0 size=30000kB time=00:05:00.00 bitrate= 819.2kbits/s speed=1.0x',
            ],
            'expected_percentages': [1.67, 5.0, 16.67, 50.0, 100.0]
        }


def create_hardware_test_matrix():
    """Create test matrix for different hardware configurations"""
    return [
        {
            'name': 'RTX_4090_Full_Support',
            'gpu_detection': MockGPUDetection.rtx4090_detected,
            'encoder_detection': MockEncoderDetection.full_nvenc_support,
            'expected_av1_support': True,
            'expected_primary_codec': 'av1_nvenc'
        },
        {
            'name': 'RTX_3080_Limited_Support',
            'gpu_detection': MockGPUDetection.rtx3080_detected,
            'encoder_detection': MockEncoderDetection.limited_nvenc_support,
            'expected_av1_support': False,
            'expected_primary_codec': 'hevc_nvenc'
        },
        {
            'name': 'Intel_QSV_Support',
            'gpu_detection': MockGPUDetection.intel_gpu_detected,
            'encoder_detection': MockEncoderDetection.qsv_support,
            'expected_av1_support': False,
            'expected_primary_codec': 'h264_qsv'
        },
        {
            'name': 'Software_Only',
            'gpu_detection': MockGPUDetection.no_gpu_detected,
            'encoder_detection': MockEncoderDetection.software_only,
            'expected_av1_support': False,
            'expected_primary_codec': 'libx264'
        }
    ]