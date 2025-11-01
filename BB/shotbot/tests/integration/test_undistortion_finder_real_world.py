"""Integration tests for undistortion finder with real-world scenarios."""

from undistortion_finder import UndistortionFinder


class TestUndistortionFinderRealWorld:
    """Test undistortion finder with real-world path structures."""

    def test_find_undistortion_bc01_plate_with_extra_nesting(self, tmp_path):
        """Test finding undistortion in BC01 directory with extra nesting level."""
        shot_name = "GF_256_0620"

        # Create the complex nested structure from real example
        base = (
            tmp_path
            / "shows"
            / "jack_ryan"
            / "shots"
            / "GF_256"
            / shot_name
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "BC01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v043"

        # Note the extra nesting level here
        shot_dir = version_dir / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v001"
        extra_nested = shot_dir / f"{shot_name}_mm_default_LD_v043"
        extra_nested.mkdir(parents=True)

        # Create the .nk file with correct name
        nk_file = extra_nested / f"{shot_name}_mm_default_LD_v043.nk"
        nk_file.write_text("""# 3DE Lens Distortion v043
LensDistortion {
 inputs 1
 distortion 0.02
 name LensDistortion_BC01_v043
}""")

        # Find undistortion
        workspace_path = (
            tmp_path / "shows" / "jack_ryan" / "shots" / "GF_256" / shot_name
        )
        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_path), shot_name
        )

        assert result == nk_file
        assert "BC01" in str(result)
        assert "v043" in str(result)

    def test_find_undistortion_fg01_standard_structure(self, tmp_path):
        """Test finding undistortion in FG01 with standard structure."""
        shot_name = "GF_256_0020"

        # Create standard structure
        base = (
            tmp_path
            / "shows"
            / "jack_ryan"
            / "shots"
            / "GF_256"
            / shot_name
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "FG01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v001"
        shot_dir.mkdir(parents=True)

        # Create the .nk file
        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
        nk_file.write_text("""# 3DE Lens Distortion v001
LensDistortion {
 inputs 1
 distortion 0.015
 name LensDistortion_FG01_v001
}""")

        # Find undistortion
        workspace_path = (
            tmp_path / "shows" / "jack_ryan" / "shots" / "GF_256" / shot_name
        )
        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_path), shot_name
        )

        assert result == nk_file
        assert "FG01" in str(result)
        assert "v001" in str(result)

    def test_prefer_fg_over_bc_with_same_version(self, tmp_path):
        """Test that FG01 is preferred over BC01 when both have same version."""
        shot_name = "test_shot"
        workspace_base = tmp_path / "shows" / "test" / "shots" / "100" / shot_name

        # Create both FG01 and BC01 with same version
        for plate_type in ["FG01", "BC01"]:
            base = (
                workspace_base
                / "user"
                / "gabriel-h"
                / "mm"
                / "3de"
                / "mm-default"
                / "exports"
                / "scene"
                / plate_type
                / "nuke_lens_distortion"
            )
            version_dir = base / "v010"
            shot_dir = (
                version_dir / f"{shot_name}_turnover-plate_{plate_type}_aces_v001"
            )
            shot_dir.mkdir(parents=True)

            nk_file = shot_dir / f"{shot_name}_mm_default_LD_v010.nk"
            nk_file.write_text(f"# Lens distortion for {plate_type}")

        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_base), shot_name
        )

        # Should prefer FG01 over BC01
        assert result is not None
        assert "FG01" in str(result)
        assert "BC01" not in str(result)

    def test_prefer_newer_version_in_bc_over_older_fg(self, tmp_path):
        """Test that newer BC01 version is preferred over older FG01."""
        shot_name = "test_shot"
        workspace_base = tmp_path / "shows" / "test" / "shots" / "100" / shot_name

        # Create FG01 with v001
        fg_base = (
            workspace_base
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "FG01"
            / "nuke_lens_distortion"
        )
        fg_version_dir = fg_base / "v001"
        fg_shot_dir = fg_version_dir / f"{shot_name}_turnover-plate_FG01_aces_v001"
        fg_shot_dir.mkdir(parents=True)
        fg_nk_file = fg_shot_dir / f"{shot_name}_mm_default_LD_v001.nk"
        fg_nk_file.write_text("# Old FG01 v001")

        # Create BC01 with v050 (much newer)
        bc_base = (
            workspace_base
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "BC01"
            / "nuke_lens_distortion"
        )
        bc_version_dir = bc_base / "v050"
        bc_shot_dir = bc_version_dir / f"{shot_name}_turnover-plate_BC01_aces_v001"
        bc_shot_dir.mkdir(parents=True)
        bc_nk_file = bc_shot_dir / f"{shot_name}_mm_default_LD_v050.nk"
        bc_nk_file.write_text("# Newer BC01 v050")

        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_base), shot_name
        )

        # Should prefer BC01 v050 over FG01 v001 due to much newer version
        assert result == bc_nk_file
        assert "BC01" in str(result)
        assert "v050" in str(result)

    def test_handle_deeply_nested_structures(self, tmp_path):
        """Test handling of deeply nested directory structures."""
        shot_name = "deep_test"

        # Create a very deeply nested structure
        base = (
            tmp_path
            / "shows"
            / "project"
            / "shots"
            / "seq"
            / shot_name
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "FG01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v001"

        # Multiple levels of nesting
        deep_path = (
            version_dir
            / f"{shot_name}_turnover-plate_FG01_lin_v001"
            / "extra_dir"
            / "another_dir"
            / f"{shot_name}_LD_final"
        )
        deep_path.mkdir(parents=True)

        nk_file = deep_path / f"{shot_name}_mm_default_LD_v001.nk"
        nk_file.write_text("# Deeply nested undistortion")

        workspace_path = tmp_path / "shows" / "project" / "shots" / "seq" / shot_name
        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_path), shot_name
        )

        assert result == nk_file
        assert "extra_dir/another_dir" in str(result).replace("\\", "/")

    def test_handle_multiple_plates_and_versions(self, tmp_path):
        """Test complex scenario with multiple plates and versions."""
        shot_name = "complex_shot"
        workspace_base = tmp_path / "shows" / "test" / "shots" / "100" / shot_name

        # Create multiple plates with different versions
        plates_and_versions = [
            ("FG01", "v003"),
            ("FG02", "v007"),
            ("BG01", "v015"),
            ("BG02", "v002"),
            ("BC01", "v020"),
            ("BC02", "v001"),
        ]

        for plate_type, version in plates_and_versions:
            base = (
                workspace_base
                / "user"
                / "gabriel-h"
                / "mm"
                / "3de"
                / "mm-default"
                / "exports"
                / "scene"
                / plate_type
                / "nuke_lens_distortion"
            )
            version_dir = base / version
            shot_dir = (
                version_dir / f"{shot_name}_turnover-plate_{plate_type}_aces_v001"
            )
            shot_dir.mkdir(parents=True)

            nk_file = shot_dir / f"{shot_name}_mm_default_LD_{version}.nk"
            nk_file.write_text(f"# Undistortion for {plate_type} {version}")

        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_base), shot_name
        )

        # Should select BC01 v020 (highest version number)
        assert result is not None
        assert "BC01" in str(result)
        assert "v020" in str(result)

    def test_handle_lowercase_plate_names(self, tmp_path):
        """Test that lowercase plate names are handled correctly."""
        shot_name = "lowercase_test"

        # Create structure with lowercase plate names
        base = (
            tmp_path
            / "shows"
            / "project"
            / "shots"
            / "seq"
            / shot_name
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "fg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "v005"
        shot_dir = version_dir / f"{shot_name}_turnover-plate_fg01_lin_v001"
        shot_dir.mkdir(parents=True)

        nk_file = shot_dir / f"{shot_name}_mm_default_LD_v005.nk"
        nk_file.write_text("# Lowercase fg01 undistortion")

        workspace_path = tmp_path / "shows" / "project" / "shots" / "seq" / shot_name
        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_path), shot_name
        )

        assert result == nk_file
        assert "fg01" in str(result)

    def test_mixed_case_sensitivity(self, tmp_path):
        """Test handling of mixed case in paths and filenames."""
        shot_name = "MixedCase_Shot"

        base = (
            tmp_path
            / "shows"
            / "Project"
            / "shots"
            / "SEQ"
            / shot_name
            / "user"
            / "gabriel-h"
            / "mm"
            / "3de"
            / "mm-default"
            / "exports"
            / "scene"
            / "Fg01"
            / "nuke_lens_distortion"
        )
        version_dir = base / "V003"  # Note: uppercase V
        shot_dir = version_dir / f"{shot_name}_Turnover-Plate_Fg01_Lin_v001"
        shot_dir.mkdir(parents=True)

        # The finder should still find this file
        nk_file = shot_dir / f"{shot_name}_MM_Default_LD_V003.nk"
        nk_file.write_text("# Mixed case undistortion")

        workspace_path = tmp_path / "shows" / "Project" / "shots" / "SEQ" / shot_name
        result = UndistortionFinder.find_latest_undistortion(
            str(workspace_path), shot_name
        )

        # Should still find the file despite case differences
        assert result == nk_file
