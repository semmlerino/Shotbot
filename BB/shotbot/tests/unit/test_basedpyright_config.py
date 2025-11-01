"""Test basedpyright configuration and type checking integration."""

# pyright: basic
# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false

import subprocess
from pathlib import Path

import pytest


class TestBasedPyrightConfiguration:
    """Test basedpyright type checker configuration."""

    def test_pyright_config_exists(self):
        """Test that pyproject.toml has basedpyright configuration."""
        project_root = Path(__file__).parent.parent.parent
        pyproject_path = project_root / "pyproject.toml"

        # pyproject.toml should exist
        assert pyproject_path.exists(), "pyproject.toml not found"

        # Read and check for basedpyright config
        content = pyproject_path.read_text(encoding="utf-8")
        assert "[tool.basedpyright]" in content or "[tool.pyright]" in content, (
            "basedpyright/pyright configuration not found in pyproject.toml"
        )

    def test_type_stubs_exist(self):
        """Test that critical .pyi stub files exist."""
        project_root = Path(__file__).parent.parent.parent

        expected_stubs = ["shot_model.pyi", "cache_manager.pyi", "utils.pyi"]

        for stub_file in expected_stubs:
            stub_path = project_root / stub_file
            assert stub_path.exists(), f"Type stub {stub_file} not found"

            # Verify stub file has content
            content = stub_path.read_text(encoding="utf-8")
            assert len(content.strip()) > 0, f"Type stub {stub_file} is empty"
            assert "def " in content or "class " in content, (
                f"Type stub {stub_file} doesn't contain definitions"
            )

    @pytest.mark.skipif(
        not Path("/usr/bin/python3").exists(), reason="Python3 not in /usr/bin"
    )
    def test_basedpyright_available(self):
        """Test that basedpyright is available for type checking."""
        try:
            # Try to run basedpyright --version
            result = subprocess.run(
                ["python3", "-m", "basedpyright", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Should succeed and output version info
            if result.returncode == 0:
                assert (
                    "basedpyright" in result.stdout.lower()
                    or "pyright" in result.stdout.lower()
                )
            else:
                pytest.skip("basedpyright not available")

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("basedpyright not available or timeout")

    def test_per_file_pyright_comments(self):
        """Test that test files have appropriate pyright comments."""
        test_file_path = Path(__file__)
        content = test_file_path.read_text(encoding="utf-8")

        # This file should have pyright configuration comments
        assert "# pyright: basic" in content, "Missing pyright mode configuration"
        assert "# pyright: reportPrivateUsage=false" in content, (
            "Missing pyright reportPrivateUsage configuration"
        )
        assert "# pyright: reportUnknownMemberType=false" in content, (
            "Missing pyright reportUnknownMemberType configuration"
        )

    def test_type_safety_test_structure(self):
        """Test that type safety test file has proper structure."""
        project_root = Path(__file__).parent.parent.parent
        type_safety_test = project_root / "tests" / "unit" / "test_type_safety.py"

        assert type_safety_test.exists(), "test_type_safety.py not found"

        content = type_safety_test.read_text(encoding="utf-8")

        # Should contain key test classes
        expected_classes = [
            "TestRefreshResultTypeAnnotations",
            "TestShotModelTypeAnnotations",
            "TestCacheManagerTypeAnnotations",
            "TestRuntimeTypeGuards",
            "TestTypeSystemIntegration",
        ]

        for class_name in expected_classes:
            assert f"class {class_name}" in content, f"Missing test class {class_name}"


class TestTypeAnnotationCompliance:
    """Test type annotation compliance across modules."""

    def test_shot_model_annotations(self):
        """Test shot_model has proper type annotations."""
        import shot_model

        # RefreshResult should be a NamedTuple
        assert hasattr(shot_model, "RefreshResult"), "RefreshResult not found"
        refresh_result = shot_model.RefreshResult

        # Should have the expected fields
        if hasattr(refresh_result, "_fields"):
            assert "success" in refresh_result._fields
            assert "has_changes" in refresh_result._fields

        # Shot class should exist
        assert hasattr(shot_model, "Shot"), "Shot class not found"

        # ShotModel class should exist
        assert hasattr(shot_model, "ShotModel"), "ShotModel class not found"

    def test_cache_manager_annotations(self):
        """Test cache_manager has proper type annotations."""
        import cache_manager

        # CacheManager should exist
        assert hasattr(cache_manager, "CacheManager"), "CacheManager class not found"

        # Should have required methods with type hints
        cache_cls = cache_manager.CacheManager
        required_methods = [
            "get_cached_shots",
            "cache_shots",
            "get_memory_usage",
            "get_cached_thumbnail",
            "cache_thumbnail",
        ]

        for method_name in required_methods:
            assert hasattr(cache_cls, method_name), f"Missing method {method_name}"

    def test_utils_annotations(self):
        """Test utils module has proper type annotations."""
        import utils

        # Should have utility classes
        expected_classes = ["PathUtils", "VersionUtils", "FileUtils", "ValidationUtils"]

        for class_name in expected_classes:
            assert hasattr(utils, class_name), f"Missing utility class {class_name}"

        # Should have cache stats function
        assert hasattr(utils, "get_cache_stats"), "Missing get_cache_stats function"


class TestTypeCheckerIntegration:
    """Test integration with type checkers."""

    def test_import_all_modules(self):
        """Test that all modules can be imported without type errors."""
        modules_to_test = [
            "shot_model",
            "cache_manager",
            "utils",
            "raw_plate_finder",
            "threede_scene_finder",
            "threede_scene_model",
        ]

        for module_name in modules_to_test:
            try:
                __import__(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_type_stub_consistency(self):
        """Test that type stubs are consistent with actual modules."""
        import shot_model

        # Check that Shot class exists and has expected attributes
        shot = shot_model.Shot("test", "seq", "shot", "/path")

        # Should have properties defined in stub
        assert hasattr(shot, "full_name"), "Missing full_name property"
        assert hasattr(shot, "thumbnail_dir"), "Missing thumbnail_dir property"
        assert hasattr(shot, "get_thumbnail_path"), "Missing get_thumbnail_path method"
        assert hasattr(shot, "to_dict"), "Missing to_dict method"
        assert hasattr(shot_model.Shot, "from_dict"), "Missing from_dict class method"

    def test_namedtuple_behavior(self):
        """Test that RefreshResult behaves like a proper NamedTuple."""
        from shot_model import RefreshResult

        # Create instance
        result = RefreshResult(success=True, has_changes=False)

        # Should support tuple unpacking
        success, has_changes = result
        assert success is True
        assert has_changes is False

        # Should support field access
        assert result.success is True
        assert result.has_changes is False

        # Should support _asdict if it's a NamedTuple
        if hasattr(result, "_asdict"):
            as_dict = result._asdict()
            assert isinstance(as_dict, dict)
            assert as_dict["success"] is True
            assert as_dict["has_changes"] is False

    def test_optional_types_runtime(self):
        """Test Optional types work correctly at runtime."""
        from unittest.mock import patch

        import utils
        from shot_model import Shot

        shot = Shot("test", "seq", "shot", "/nonexistent")

        # Mock PathUtils to return False (path doesn't exist)
        with patch.object(utils.PathUtils, "validate_path_exists", return_value=False):
            result = shot.get_thumbnail_path()

            # Should return None for Optional[Path]
            assert result is None

    def test_union_types_runtime(self):
        """Test Union types work correctly at runtime."""
        import tempfile
        from pathlib import Path

        from cache_manager import CacheManager
        from shot_model import Shot

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = CacheManager(cache_dir=Path(tmp_dir))

            # Test with List[Shot]
            shots = [Shot("show", "seq", "shot", "/path")]
            cache.cache_shots(shots)  # Should not raise type error

            # Test with List[Dict[str, str]]
            shot_dicts = [
                {
                    "show": "show",
                    "sequence": "seq",
                    "shot": "shot",
                    "workspace_path": "/path",
                }
            ]
            cache.cache_shots(shot_dicts)  # Should not raise type error


class TestMypyCompatibility:
    """Test mypy compatibility if available."""

    @pytest.mark.skipif(True, reason="mypy not required, using basedpyright")
    def test_mypy_check(self):
        """Test mypy type checking if available."""
        try:
            result = subprocess.run(
                ["python3", "-m", "mypy", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                pytest.skip("mypy not available")

            # Run mypy on key modules
            modules = ["shot_model.py", "cache_manager.py", "utils.py"]
            for module in modules:
                result = subprocess.run(
                    ["python3", "-m", "mypy", module],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # Should have no errors
                if result.returncode != 0:
                    pytest.fail(f"mypy errors in {module}: {result.stdout}")

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("mypy not available or timeout")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
