#!/usr/bin/env python3
"""
pytest configuration and fixtures for PyFFMPEG tests
Provides common test fixtures and utilities for unit and integration tests
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch

# Import Qt for GUI testing
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
import sys

# Import project modules for testing
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from codec_helpers import CodecHelpers
from process_manager import ProcessManager


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for Qt widget testing"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Don't quit app as it may be used by other tests


@pytest.fixture
def temp_video_file():
    """Create a temporary video file for testing"""
    with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as f:
        # Write minimal TS file header
        f.write(b"\x47" + b"\x00" * 187)  # Basic TS packet
        temp_path = f.name

    yield temp_path

    # Cleanup
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


@pytest.fixture
def temp_output_dir():
    """Create temporary directory for output files"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def mock_ffmpeg_subprocess():
    """Mock subprocess calls for FFmpeg operations"""
    with (
        patch("subprocess.run") as mock_run,
        patch("subprocess.check_output") as mock_check_output,
        patch("subprocess.Popen") as mock_popen,
    ):
        # Default successful FFmpeg responses
        mock_run.return_value = Mock(returncode=0, stdout="ffmpeg output", stderr="")

        mock_check_output.return_value = "h264_nvenc\nhevc_nvenc\nlibx264\n"

        # Mock process for Popen
        mock_process = Mock()
        mock_process.communicate.return_value = ("output", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        yield {
            "run": mock_run,
            "check_output": mock_check_output,
            "popen": mock_popen,
            "process": mock_process,
        }


@pytest.fixture
def mock_qprocess():
    """Mock QProcess for testing process management"""
    mock_process = Mock(spec=QProcess)
    mock_process.state.return_value = QProcess.ProcessState.NotRunning
    mock_process.waitForStarted.return_value = True
    mock_process.start = Mock()
    mock_process.kill = Mock()
    mock_process.readAllStandardOutput.return_value = b"test output"

    return mock_process


@pytest.fixture
def mock_nvidia_smi():
    """Mock nvidia-smi calls for GPU detection testing"""
    gpu_info = """
GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-123-456)
    Product Name: NVIDIA GeForce RTX 4090
    Product Brand: GeForce
    """

    with patch("subprocess.check_output") as mock_check:
        mock_check.return_value = gpu_info.encode("utf-8")
        yield mock_check


@pytest.fixture
def sample_ffmpeg_output():
    """Sample FFmpeg output for progress tracking tests"""
    return [
        "ffmpeg version 4.4.0",
        "Input #0, mpegts, from 'input.ts':",
        "  Duration: 00:10:30.00, start: 0.000000, bitrate: 1000 kb/s",
        "    Stream #0:0[0x100]: Video: h264",
        "    Stream #0:1[0x101]: Audio: aac",
        "Output #0, mp4, to 'output.mp4':",
        "frame=  100 fps= 25 q=28.0 size=    1024kB time=00:00:04.00 bitrate=2048.0kbits/s speed=1.0x",
        "frame=  200 fps= 25 q=28.0 size=    2048kB time=00:00:08.00 bitrate=2048.0kbits/s speed=1.0x",
        "frame=  250 fps= 25 q=28.0 size=    2560kB time=00:00:10.00 bitrate=2048.0kbits/s speed=1.0x",
    ]


@pytest.fixture
def codec_helpers_with_cache():
    """Provide CodecHelpers with pre-populated cache for testing"""
    # Clear any existing cache
    CodecHelpers.clear_cache()

    # Pre-populate with test data
    CodecHelpers._encoder_cache = (
        "h264_nvenc\nhevc_nvenc\nav1_nvenc\nlibx264\nprores_ks"
    )
    CodecHelpers._gpu_info_cache = "GPU 0: NVIDIA GeForce RTX 4090"
    CodecHelpers._rtx40_detection_cache = True

    yield CodecHelpers

    # Cleanup cache after test
    CodecHelpers.clear_cache()


@pytest.fixture
def mock_settings():
    """Mock QSettings for testing settings persistence"""
    settings_data = {}

    def mock_value(key, default=None, type=None):
        value = settings_data.get(key, default)
        if type and value is not None:
            return type(value)
        return value

    def mock_set_value(key, value):
        settings_data[key] = value

    with patch("PySide6.QtCore.QSettings") as mock_qsettings:
        mock_instance = Mock()
        mock_instance.value = mock_value
        mock_instance.setValue = mock_set_value
        mock_qsettings.return_value = mock_instance

        yield mock_instance


@pytest.fixture
def conversion_test_data():
    """Test data for conversion scenarios"""
    return {
        "files": ["/test/input1.ts", "/test/input2.ts", "/test/input3.ts"],
        "settings": {
            "codec_idx": 0,  # H.264 NVENC
            "hwdecode_idx": 1,  # NVIDIA CUDA
            "crf_value": 18,
            "parallel_enabled": True,
            "max_parallel": 4,
            "delete_source": False,
            "overwrite_mode": True,
        },
        "expected_outputs": [
            "/test/input1_RC.mp4",
            "/test/input2_RC.mp4",
            "/test/input3_RC.mp4",
        ],
    }


@pytest.fixture
def progress_test_scenarios():
    """Test scenarios for progress tracking"""
    return {
        "duration_probe": {
            "input": "/test/video.ts",
            "ffprobe_output": "630.000000",  # 10:30 duration
            "expected_duration": 630.0,
        },
        "progress_parsing": [
            {
                "ffmpeg_line": "frame=  100 fps= 25 q=28.0 size=1024kB time=00:01:40.00 bitrate=1024.0kbits/s speed=1.0x",
                "duration": 600.0,  # 10 minutes
                "expected_progress": 16.67,  # 100 seconds / 600 seconds * 100
            },
            {
                "ffmpeg_line": "frame=  300 fps= 30 q=25.0 size=3072kB time=00:05:00.00 bitrate=1024.0kbits/s speed=1.2x",
                "duration": 600.0,
                "expected_progress": 50.0,  # 300 seconds / 600 seconds * 100
            },
        ],
    }


# Utility functions for tests
def create_mock_process_manager(parent=None):
    """Create a mock ProcessManager for testing"""
    mock_pm = Mock(spec=ProcessManager)
    mock_pm.processes = []
    mock_pm.process_logs = {}
    mock_pm.process_outputs = {}
    mock_pm.queue = []
    mock_pm.total = 0
    mock_pm.completed = 0
    return mock_pm


def assert_ffmpeg_args_contain(args, expected_flags):
    """Helper to assert FFmpeg arguments contain expected flags"""
    args_str = " ".join(args)
    for flag in expected_flags:
        assert flag in args_str, (
            f"Expected flag '{flag}' not found in FFmpeg args: {args_str}"
        )


def assert_codec_configuration(args, codec_name):
    """Helper to assert correct codec configuration in FFmpeg args"""
    assert "-c:v" in args, "Video codec flag not found"
    codec_idx = args.index("-c:v") + 1
    assert codec_idx < len(args), "Video codec value not found"
    assert args[codec_idx] == codec_name, (
        f"Expected codec {codec_name}, got {args[codec_idx]}"
    )
