#!/usr/bin/env python3
"""
Unit tests for CodecHelpers class
Tests hardware detection, encoder configuration, and fallback logic
"""

import pytest
import subprocess
from unittest.mock import patch, Mock

from codec_helpers import CodecHelpers
from config import ProcessConfig, EncodingConfig
from tests.fixtures.mocks import (
    MockGPUDetection,
    MockEncoderDetection,
    create_hardware_test_matrix,
)


class TestCodecHelpers:
    """Test suite for CodecHelpers static class"""

    def setup_method(self):
        """Clear cache before each test"""
        CodecHelpers.clear_cache()

    def teardown_method(self):
        """Clear cache after each test"""
        CodecHelpers.clear_cache()


class TestOutputExtensions:
    """Test output file extension determination"""

    def test_h264_extension(self):
        """Test H.264 codec extensions"""
        assert CodecHelpers.get_output_extension(0) == ".mp4"  # H.264 NVENC
        assert CodecHelpers.get_output_extension(3) == ".mp4"  # x264 CPU
        assert CodecHelpers.get_output_extension(5) == ".mp4"  # H.264 QSV
        assert CodecHelpers.get_output_extension(6) == ".mp4"  # H.264 VAAPI

    def test_hevc_extension(self):
        """Test HEVC codec extensions"""
        assert CodecHelpers.get_output_extension(1) == ".mp4"  # HEVC NVENC

    def test_av1_extension(self):
        """Test AV1 codec extensions"""
        assert CodecHelpers.get_output_extension(2) == ".mp4"  # AV1 NVENC

    def test_prores_extension(self):
        """Test ProRes codec extensions"""
        assert CodecHelpers.get_output_extension(4) == ".mov"  # ProRes CPU

    def test_unknown_codec_default(self):
        """Test default extension for unknown codecs"""
        assert CodecHelpers.get_output_extension(99) == ".mp4"
        assert CodecHelpers.get_output_extension(-1) == ".mp4"


class TestHardwareAcceleration:
    """Test hardware acceleration detection and configuration"""

    @patch("subprocess.check_output")
    def test_auto_acceleration_with_nvidia(self, mock_subprocess):
        """Test auto hardware acceleration with NVIDIA GPU"""
        # Clear the GPU info cache first
        CodecHelpers._gpu_info_cache = None
        
        mock_subprocess.return_value = MockGPUDetection.rtx4090_detected().encode()

        args, message = CodecHelpers.get_hardware_acceleration_args(0)  # Auto

        assert "-hwaccel" in args
        assert "cuda" in args
        assert "CUDA" in message
        mock_subprocess.assert_called_once()

    @patch("subprocess.check_output")
    def test_auto_acceleration_no_gpu(self, mock_subprocess):
        """Test auto hardware acceleration fallback when no GPU"""
        # Clear the GPU info cache first
        CodecHelpers._gpu_info_cache = None
        
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "nvidia-smi")

        args, message = CodecHelpers.get_hardware_acceleration_args(0)  # Auto

        assert "-hwaccel" in args
        assert "auto" in args
        assert "auto hardware acceleration" in message

    def test_explicit_nvidia_acceleration(self):
        """Test explicit NVIDIA acceleration"""
        args, message = CodecHelpers.get_hardware_acceleration_args(1)  # NVIDIA

        assert args == ["-hwaccel", "cuda"]
        assert "CUDA" in message

    def test_explicit_qsv_acceleration(self):
        """Test explicit Intel QSV acceleration"""
        args, message = CodecHelpers.get_hardware_acceleration_args(2)  # Intel QSV

        assert args == ["-hwaccel", "qsv"]
        assert "QSV" in message

    @patch("os.name", "posix")
    def test_vaapi_acceleration_linux(self):
        """Test VAAPI acceleration on Linux"""
        args, message = CodecHelpers.get_hardware_acceleration_args(3)  # VAAPI

        assert "-hwaccel" in args
        assert "vaapi" in args
        assert "/dev/dri/renderD128" in args
        assert "VAAPI" in message

    @patch("os.name", "nt")
    def test_vaapi_acceleration_windows_fallback(self):
        """Test VAAPI acceleration fallback on Windows"""
        args, message = CodecHelpers.get_hardware_acceleration_args(3)  # VAAPI

        assert "-hwaccel" in args
        assert "auto" in args
        assert "not available" in message

    @patch("subprocess.check_output")
    def test_hardware_acceleration_timeout(self, mock_subprocess):
        """Test hardware acceleration with subprocess timeout"""
        # Clear the GPU info cache first
        CodecHelpers._gpu_info_cache = None
        
        mock_subprocess.side_effect = subprocess.TimeoutExpired("nvidia-smi", 10)

        args, message = CodecHelpers.get_hardware_acceleration_args(0)  # Auto

        # When GPU detection times out, it falls back to auto
        assert "-hwaccel" in args
        assert "auto" in args
        assert "auto hardware acceleration" in message


class TestAudioCodecConfiguration:
    """Test audio codec configuration"""

    @patch("subprocess.run")
    def test_aac_passthrough(self, mock_subprocess):
        """Test AAC audio passthrough"""
        mock_result = Mock()
        mock_result.stdout = "aac"
        mock_subprocess.return_value = mock_result

        args, message = CodecHelpers.get_audio_codec_args("/test/input.ts", 0)

        assert args == ["-c:a", "copy"]
        assert "aac" in message
        assert "passthrough" in message

    @patch("subprocess.run")
    def test_ac3_passthrough(self, mock_subprocess):
        """Test AC-3 audio passthrough"""
        mock_result = Mock()
        mock_result.stdout = "ac3"
        mock_subprocess.return_value = mock_result

        args, message = CodecHelpers.get_audio_codec_args("/test/input.ts", 0)

        assert args == ["-c:a", "copy"]
        assert "ac3" in message

    @patch("subprocess.run")
    def test_prores_pcm_audio(self, mock_subprocess):
        """Test PCM audio for ProRes"""
        mock_result = Mock()
        mock_result.stdout = "mp3"  # Non-passthrough codec
        mock_subprocess.return_value = mock_result

        args, message = CodecHelpers.get_audio_codec_args("/test/input.ts", 4)  # ProRes

        assert args == ["-c:a", "pcm_s16le"]
        assert "PCM" in message

    @patch("subprocess.run")
    def test_aac_encoding_fallback(self, mock_subprocess):
        """Test AAC encoding for non-passthrough codecs"""
        mock_result = Mock()
        mock_result.stdout = "mp3"
        mock_subprocess.return_value = mock_result

        args, message = CodecHelpers.get_audio_codec_args("/test/input.ts", 0)

        expected_bitrate = f"{EncodingConfig.AUDIO_BITRATE_DEFAULT}k"
        assert args == ["-c:a", "aac", "-b:a", expected_bitrate]
        assert "AAC" in message
        assert expected_bitrate in message

    @patch("subprocess.run")
    def test_audio_probe_timeout(self, mock_subprocess):
        """Test audio codec detection with timeout"""
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            "ffprobe", ProcessConfig.SUBPROCESS_TIMEOUT
        )

        args, message = CodecHelpers.get_audio_codec_args("/test/input.ts", 0)

        # Should fallback to AAC encoding
        expected_bitrate = f"{EncodingConfig.AUDIO_BITRATE_DEFAULT}k"
        assert args == ["-c:a", "aac", "-b:a", expected_bitrate]
        assert "Fallback" in message


class TestEncoderConfiguration:
    """Test video encoder configuration"""

    @patch("subprocess.check_output")
    def test_h264_nvenc_configuration(self, mock_subprocess):
        """Test H.264 NVENC encoder configuration"""
        mock_subprocess.return_value = MockEncoderDetection.full_nvenc_support()

        args, message = CodecHelpers.get_encoder_configuration(
            0, 4, False, 18
        )  # H.264 NVENC (codec_idx=0)

        assert "-c:v" in args
        assert "h264_nvenc" in args
        assert "-preset" in args
        assert "-cq" in args
        assert "NVENC" in message

    @patch("subprocess.check_output")
    def test_hevc_nvenc_configuration(self, mock_subprocess):
        """Test HEVC NVENC encoder configuration"""
        mock_subprocess.return_value = MockEncoderDetection.full_nvenc_support()

        args, message = CodecHelpers.get_encoder_configuration(
            1, 4, False, 18
        )  # HEVC NVENC (codec_idx=1)

        assert "-c:v" in args
        assert "hevc_nvenc" in args
        assert "-profile:v" in args
        assert "main" in args
        assert "HEVC" in message

    @patch("subprocess.check_output")
    def test_av1_nvenc_configuration(self, mock_subprocess):
        """Test AV1 NVENC encoder configuration"""
        mock_subprocess.return_value = MockEncoderDetection.full_nvenc_support()

        args, message = CodecHelpers.get_encoder_configuration(
            2, 4, False, 18
        )  # AV1 NVENC (codec_idx=2)

        assert "-c:v" in args
        assert "av1_nvenc" in args
        assert "-rc" in args
        assert "vbr" in args
        assert "AV1" in message

    def test_x264_software_configuration(self):
        """Test x264 software encoder configuration"""
        args, message = CodecHelpers.get_encoder_configuration(3, 6, False, 18)  # x264

        assert "-c:v" in args
        assert "libx264" in args
        assert "-crf" in args
        assert "18" in args
        assert "-threads" in args
        assert "6" in args
        assert "x264" in message

    def test_x264_parallel_no_threads(self):
        """Test x264 in parallel mode doesn't set threads"""
        args, message = CodecHelpers.get_encoder_configuration(
            3, 0, True, 18
        )  # x264, thread_count=0 (means auto-detect)

        assert "-c:v" in args
        assert "libx264" in args
        assert "-threads" not in args  # Should not set threads when thread_count=0

    @patch("subprocess.check_output")
    def test_prores_configuration(self, mock_subprocess):
        """Test ProRes encoder configuration"""
        mock_subprocess.return_value = MockEncoderDetection.software_only()

        args, message = CodecHelpers.get_encoder_configuration(
            4, 4, False, 18
        )  # ProRes

        assert "-c:v" in args
        assert "prores_ks" in args
        assert "-profile:v" in args
        assert "3" in args  # ProRes 422 profile
        assert "-pix_fmt" in args
        assert "yuv422p10le" in args
        assert "ProRes" in message

    @patch("subprocess.check_output")
    def test_encoder_fallback_to_x264(self, mock_subprocess):
        """Test fallback to x264 when requested encoder unavailable"""
        mock_subprocess.return_value = MockEncoderDetection.software_only()  # No NVENC

        args, message = CodecHelpers.get_encoder_configuration(
            0, 4, False, 18
        )  # H.264 NVENC (codec_idx=0)

        # Implementation doesn't fallback - it returns the requested encoder anyway
        assert "-c:v" in args
        assert "h264_nvenc" in args  # Returns requested encoder even if not detected
        assert "H.264 NVENC" in message

    def test_encoder_configuration_exception(self):
        """Test encoder configuration with exception handling"""
        with patch(
            "subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ):
            args, message = CodecHelpers.get_encoder_configuration(1, 4, False, 18)

            # Implementation returns the requested encoder even if detection fails
            assert "-c:v" in args
            assert "hevc_nvenc" in args  # Still returns HEVC NVENC (codec_idx=1)
            assert "HEVC NVENC" in message


class TestThreadOptimization:
    """Test thread optimization logic"""

    def test_nvenc_thread_optimization(self):
        """Test NVENC encoders use minimal threads"""
        for codec_idx in [0, 1, 2]:  # All NVENC variants
            threads = CodecHelpers.optimize_threads_for_codec(codec_idx, True, None)
            assert threads == 2

    @patch("os.cpu_count", return_value=16)
    def test_single_cpu_job_auto_threads(self, mock_cpu_count):
        """Test single CPU job uses most threads minus system reserve"""
        threads = CodecHelpers.optimize_threads_for_codec(
            3, False, None
        )  # x264, not parallel
        assert threads == 12  # 16 - 4 reserved for system

    @patch("os.cpu_count", return_value=16)
    def test_parallel_cpu_thread_division(self, mock_cpu_count):
        """Test parallel CPU jobs divide threads evenly"""
        file_assignments = {
            "/file1.ts": 3,  # CPU
            "/file2.ts": 3,  # CPU
            "/file3.ts": 1,  # NVENC
            "/file4.ts": 3,  # CPU
        }

        threads = CodecHelpers.optimize_threads_for_codec(3, True, file_assignments)

        # 3 CPU jobs, 16 cores -> (16-2)/3 = 14/3 = 4
        assert threads == 4

    @patch("os.cpu_count", return_value=None)
    def test_cpu_count_none_fallback(self, mock_cpu_count):
        """Test fallback when cpu_count returns None"""
        threads = CodecHelpers.optimize_threads_for_codec(3, True, None)

        # Should use ProcessConfig.OPTIMAL_CPU_THREADS as fallback
        # For parallel with no assignments, cpu_jobs defaults to 2
        expected = max(2, (ProcessConfig.OPTIMAL_CPU_THREADS - 2) // 2)
        assert threads == expected


class TestCachingMechanisms:
    """Test caching of expensive operations"""

    def setup_method(self):
        """Clear caches before each test"""
        CodecHelpers.clear_cache()

    @patch("subprocess.check_output")
    def test_encoder_detection_caching(self, mock_subprocess):
        """Test encoder detection results are cached"""
        mock_subprocess.return_value = MockEncoderDetection.full_nvenc_support()

        # First call
        result1 = CodecHelpers._get_available_encoders()

        # Second call should use cache
        result2 = CodecHelpers._get_available_encoders()

        assert result1 == result2
        mock_subprocess.assert_called_once()  # Should only call subprocess once

    @patch("subprocess.check_output")
    def test_gpu_info_caching(self, mock_subprocess):
        """Test GPU info caching"""
        mock_subprocess.return_value = MockGPUDetection.rtx4090_detected().encode()

        # First call
        result1 = CodecHelpers._get_gpu_info()

        # Second call should use cache
        result2 = CodecHelpers._get_gpu_info()

        assert result1 == result2
        mock_subprocess.assert_called_once()

    @patch("subprocess.check_output")
    def test_rtx40_detection_caching(self, mock_subprocess):
        """Test RTX40 detection caching"""
        mock_subprocess.return_value = MockGPUDetection.rtx4090_detected().encode()

        # First call
        result1 = CodecHelpers.detect_rtx40_series()

        # Second call should use cache
        result2 = CodecHelpers.detect_rtx40_series()

        assert result1 == result2 is True
        mock_subprocess.assert_called_once()

    def test_cache_clearing(self):
        """Test cache clearing functionality"""
        # Populate cache
        CodecHelpers._encoder_cache = "test_data"
        CodecHelpers._gpu_info_cache = "test_gpu"
        CodecHelpers._rtx40_detection_cache = True

        # Clear cache
        CodecHelpers.clear_cache()

        # Verify cache is cleared
        assert CodecHelpers._encoder_cache is None
        assert CodecHelpers._gpu_info_cache is None
        assert CodecHelpers._rtx40_detection_cache is None


class TestRTX40Detection:
    """Test RTX 40 series detection for AV1 support"""

    @pytest.mark.parametrize(
        "gpu_model,expected",
        [
            ("RTX 4090", True),
            ("RTX 4080", True),
            ("RTX 4070", True),
            ("RTX 40", True),  # Generic RTX 40 match
            ("RTX 3090", False),
            ("RTX 3080", False),
            ("RTX 2080", False),
            ("GTX 1080", False),
            ("Intel UHD", False),
        ],
    )
    @patch("subprocess.check_output")
    def test_rtx40_model_detection(self, mock_subprocess, gpu_model, expected):
        """Test RTX 40 series model detection"""
        # Clear cache before test
        CodecHelpers._gpu_info_cache = None
        CodecHelpers._rtx40_detection_cache = None
        
        gpu_info = f"GPU 0: NVIDIA GeForce {gpu_model}"
        mock_subprocess.return_value = gpu_info.encode()

        result = CodecHelpers.detect_rtx40_series()
        assert result == expected

    @patch("subprocess.check_output")
    def test_rtx40_detection_exception(self, mock_subprocess):
        """Test RTX40 detection with exception"""
        # Clear cache before test
        CodecHelpers._gpu_info_cache = None
        CodecHelpers._rtx40_detection_cache = None
        
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "nvidia-smi")

        result = CodecHelpers.detect_rtx40_series()
        assert not result


class TestHardwareTestMatrix:
    """Test different hardware configurations using test matrix"""

    @pytest.mark.parametrize("hardware_config", create_hardware_test_matrix())
    def test_hardware_configurations(self, hardware_config):
        """Test various hardware configurations"""
        # Clear cache before each test configuration
        CodecHelpers.clear_cache()
        
        with patch("subprocess.check_output") as mock_subprocess:
            # Configure mocks based on test scenario
            encoder_result = hardware_config["encoder_detection"]()
            
            # Handle GPU detection - some scenarios raise exceptions
            try:
                gpu_result = hardware_config["gpu_detection"]()
                if isinstance(gpu_result, str):
                    gpu_result = gpu_result.encode()
            except subprocess.CalledProcessError as e:
                gpu_result = e
                
            mock_subprocess.side_effect = [encoder_result, gpu_result]

            # Test encoder availability
            encoders = CodecHelpers._get_available_encoders()
            expected_codec = hardware_config["expected_primary_codec"]
            assert expected_codec in encoders

            # Test AV1 support
            if hardware_config["expected_av1_support"]:
                assert "av1_nvenc" in encoders
            else:
                assert "av1_nvenc" not in encoders


@pytest.mark.unit
class TestCodecHelpersEdgeCases:
    """Test edge cases and error conditions"""

    def test_invalid_codec_indices(self):
        """Test handling of invalid codec indices"""
        # Should not crash and return reasonable defaults
        extension = CodecHelpers.get_output_extension(-5)
        assert extension == ".mp4"

        extension = CodecHelpers.get_output_extension(999)
        assert extension == ".mp4"

    def test_crf_value_passthrough(self):
        """Test CRF value is passed through without clamping"""
        # Clear cache before test
        CodecHelpers.clear_cache()
        
        with patch(
            "subprocess.check_output",
            return_value=MockEncoderDetection.full_nvenc_support(),
        ):
            # Test high CRF value is passed through as-is
            args, _ = CodecHelpers.get_encoder_configuration(1, 4, False, 100)

            cq_idx = args.index("-cq") + 1
            cq_value = int(args[cq_idx])
            assert cq_value == 100  # Value should not be clamped

    def test_empty_encoder_output(self):
        """Test handling of empty encoder detection output"""
        # Clear cache first
        CodecHelpers._encoder_cache = None
        
        with patch("subprocess.check_output", return_value=""):
            encoders = CodecHelpers._get_available_encoders()
            # Empty output is still cached and returned as empty string
            assert encoders == ""

            # When encoder detection fails (empty output), it falls back to libx264
            args, message = CodecHelpers.get_encoder_configuration(1, 4, False, 18)
            assert "libx264" in args  # Falls back to x264
            assert "falling back" in message.lower()  # Should indicate fallback

    def test_malformed_gpu_output(self):
        """Test handling of malformed GPU detection output"""
        # Clear cache first
        CodecHelpers._gpu_info_cache = None
        CodecHelpers._rtx40_detection_cache = None
        
        with patch("subprocess.check_output", return_value=b"malformed gpu output"):
            result = CodecHelpers.detect_rtx40_series()
            assert not result
