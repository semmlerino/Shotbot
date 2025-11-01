"""Tests for edge cases in undistortion integration."""

from pathlib import Path
from unittest.mock import Mock, patch

from nuke_script_generator import NukeScriptGenerator
from undistortion_finder import UndistortionFinder


class TestUndistortionEdgeCases:
    """Test edge cases for undistortion integration."""

    def test_create_plate_script_with_undistortion_empty_plate_path(self, tmp_path):
        """Test script generation with empty plate path."""
        # Create undistortion file
        undist_file = tmp_path / "undist_v001.nk"
        undist_file.write_text("# Nuke script\nLensDistortion { file test }")

        # Test with empty string
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            "", str(undist_file), "test_shot"
        )

        assert script_path is not None
        assert Path(script_path).exists()

        with open(script_path, "r") as f:
            content = f.read()

        # Should have undistortion but no plate Read node
        assert "name undistortion_import" in content
        assert "name plate_read" not in content
        assert "test_shot_comp" in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_none_plate_path(self, tmp_path):
        """Test script generation with None plate path."""
        # Create undistortion file
        undist_file = tmp_path / "undist_v002.nk"
        undist_file.write_text("# Nuke script\nLensDistortion { file test }")

        # Test with None
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            None, str(undist_file), "test_shot"
        )

        assert script_path is not None
        assert Path(script_path).exists()

        with open(script_path, "r") as f:
            content = f.read()

        # Should handle None gracefully
        assert "name undistortion_import" in content
        assert "test_shot_comp" in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_empty_undist_path(self, tmp_path):
        """Test script generation with empty undistortion path."""
        # Create plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        for frame in [1001, 1002]:
            plate_file = plate_dir / f"test.{frame:04d}.exr"
            plate_file.write_text("dummy")

        plate_path = str(plate_dir / "test.%04d.exr")

        # Test with empty undistortion path
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, "", "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should have plate but no undistortion
        assert "name plate_read" in content
        assert "undistortion_import" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_none_undist_path(self, tmp_path):
        """Test script generation with None undistortion path."""
        # Create plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test.1001.exr"
        plate_file.write_text("dummy")

        plate_path = str(plate_dir / "test.%04d.exr")

        # Test with None undistortion path
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, None, "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should have plate but no undistortion
        assert "name plate_read" in content
        assert "undistortion_import" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_both_empty(self):
        """Test script generation with both paths empty."""
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            "", "", "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should create minimal Nuke script with just Root and Viewer
        assert "test_shot_comp" in content
        assert "Root {" in content
        assert "Viewer {" in content
        assert "name plate_read" not in content
        assert "undistortion_import" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_both_none(self):
        """Test script generation with both paths None."""
        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            None, None, "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should create minimal Nuke script
        assert "test_shot_comp" in content
        assert "Root {" in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_nonexistent_undist_file(
        self, tmp_path
    ):
        """Test script generation with non-existent undistortion file."""
        # Create plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test.1001.exr"
        plate_file.write_text("dummy")

        plate_path = str(plate_dir / "test.%04d.exr")
        nonexistent_undist = "/does/not/exist/undist.nk"

        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, nonexistent_undist, "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should have plate but skip non-existent undistortion
        assert "name plate_read" in content
        assert "undistortion_import" not in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_with_undistortion_permission_denied_undist(
        self, tmp_path
    ):
        """Test handling of permission denied on undistortion file."""
        # Create plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test.1001.exr"
        plate_file.write_text("dummy")

        # Create undistortion file and remove read permissions
        undist_file = tmp_path / "no_access_undist.nk"
        undist_file.write_text("# Nuke script")
        undist_file.chmod(0o000)  # No permissions

        plate_path = str(plate_dir / "test.%04d.exr")

        try:
            script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
                plate_path, str(undist_file), "test_shot"
            )

            # Should still generate script without undistortion
            assert script_path is not None

            with open(script_path, "r") as f:
                content = f.read()

            # Should have plate but no undistortion due to access error
            assert "name plate_read" in content

            # Cleanup
            Path(script_path).unlink()

        finally:
            # Restore permissions for cleanup
            try:
                undist_file.chmod(0o644)
            except (OSError, PermissionError):
                pass

    def test_create_plate_script_with_undistortion_corrupted_undist_file(
        self, tmp_path
    ):
        """Test handling of corrupted/invalid undistortion file."""
        # Create plate files
        plate_dir = tmp_path / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test.1001.exr"
        plate_file.write_text("dummy")

        # Create corrupted undistortion file (binary data)
        undist_file = tmp_path / "corrupted_undist.nk"
        undist_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")

        plate_path = str(plate_dir / "test.%04d.exr")

        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), "test_shot"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should still include undistortion reference (file exists)
        assert "name plate_read" in content
        assert str(undist_file) in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_special_characters_in_paths(self, tmp_path):
        """Test handling of special characters in file paths."""
        # Create directory with special characters
        special_dir = tmp_path / "test with spaces & symbols"
        special_dir.mkdir()

        plate_dir = special_dir / "plates"
        plate_dir.mkdir()

        plate_file = plate_dir / "test shot.1001.exr"
        plate_file.write_text("dummy")

        undist_file = special_dir / "undist & correction.nk"
        undist_file.write_text("# Nuke script")

        plate_path = str(plate_dir / "test shot.%04d.exr")

        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), "test_shot_special"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should handle special characters in paths
        assert plate_path in content
        assert str(undist_file) in content

        # Cleanup
        Path(script_path).unlink()

    def test_create_plate_script_very_long_paths(self, tmp_path):
        """Test handling of very long file paths."""
        # Create nested directory structure
        deep_dir = tmp_path
        for i in range(10):  # Create deep nesting
            deep_dir = deep_dir / f"very_long_directory_name_level_{i:02d}"
            deep_dir.mkdir()

        plate_dir = deep_dir / "plates"
        plate_dir.mkdir()

        plate_file = (
            plate_dir / "very_long_plate_filename_with_many_characters.1001.exr"
        )
        plate_file.write_text("dummy")

        undist_file = (
            deep_dir / "very_long_undistortion_filename_with_many_characters_v001.nk"
        )
        undist_file.write_text("# Nuke script")

        plate_path = str(
            plate_dir / "very_long_plate_filename_with_many_characters.%04d.exr"
        )

        script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
            plate_path, str(undist_file), "test_shot_long_paths"
        )

        assert script_path is not None

        with open(script_path, "r") as f:
            content = f.read()

        # Should handle long paths correctly
        assert "test_shot_long_paths_comp" in content

        # Cleanup
        Path(script_path).unlink()

    def test_undistortion_finder_edge_cases(self, tmp_path):
        """Test UndistortionFinder with various edge cases."""
        # Test with non-existent workspace path
        result = UndistortionFinder.find_latest_undistortion(
            "/non/existent/path", "test_shot", "test_user"
        )
        assert result is None

        # Test with empty shot name
        result = UndistortionFinder.find_latest_undistortion(
            str(tmp_path), "", "test_user"
        )
        assert result is None

        # Test with None username (should use default)
        shot_workspace = str(tmp_path)
        result = UndistortionFinder.find_latest_undistortion(
            shot_workspace, "test_shot", None
        )
        # Should not crash, may return None if path structure doesn't exist

    def test_get_version_from_path_edge_cases(self, tmp_path):
        """Test version extraction from various path formats."""
        # Test with non-existent path
        result = UndistortionFinder.get_version_from_path(Path("/non/existent/path"))
        assert result is None

        # Test with path that has no version
        no_version_path = tmp_path / "undist.nk"
        no_version_path.write_text("# test")
        result = UndistortionFinder.get_version_from_path(no_version_path)
        assert result is None

        # Test with multiple version patterns
        multi_version_path = tmp_path / "v001" / "test_v002.nk"
        multi_version_path.parent.mkdir()
        multi_version_path.write_text("# test")
        result = UndistortionFinder.get_version_from_path(multi_version_path)
        # Should extract first/most relevant version

    def test_script_generation_with_invalid_shot_names(self, tmp_path):
        """Test script generation with invalid/special shot names."""
        undist_file = tmp_path / "undist.nk"
        undist_file.write_text("# test")

        # Test with shot name containing special characters
        special_shot_names = [
            "shot with spaces",
            "shot-with-dashes",
            "shot_with_underscores",
            "shot.with.dots",
            "SHOT_WITH_CAPS",
            "shot123_456",
            "",  # Empty shot name
        ]

        for shot_name in special_shot_names:
            script_path = NukeScriptGenerator.create_plate_script_with_undistortion(
                "", str(undist_file), shot_name
            )

            assert script_path is not None

            with open(script_path, "r") as f:
                content = f.read()

            # Should handle special characters in shot names
            if shot_name:  # Non-empty shot name
                assert (
                    f"{shot_name}_comp" in content
                    or shot_name.replace(" ", "_") in content
                )

            # Cleanup
            Path(script_path).unlink()

    def test_temporary_file_creation_failure(self, tmp_path):
        """Test handling of temporary file creation failure."""
        # Mock tempfile.NamedTemporaryFile to raise an exception
        with patch("nuke_script_generator.tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp.side_effect = OSError("Permission denied")

            result = NukeScriptGenerator.create_plate_script_with_undistortion(
                "", "/test/undist.nk", "test_shot"
            )

            # Should handle file creation failure gracefully
            assert result is None

    @patch("nuke_script_generator.Path")
    def test_file_operations_with_permissions_error(self, mock_path, tmp_path):
        """Test handling of file permission errors during operations."""
        undist_file = tmp_path / "undist.nk"
        undist_file.write_text("# test")

        # Mock Path.exists() to raise PermissionError
        mock_path_instance = Mock()
        mock_path_instance.exists.side_effect = PermissionError("Access denied")
        mock_path.return_value = mock_path_instance

        # Should handle permission errors gracefully
        NukeScriptGenerator.create_plate_script_with_undistortion(
            "", str(undist_file), "test_shot"
        )

        # May return None or handle gracefully without crashing
        # The key requirement is no uncaught exceptions
