"""Fixtures specifically for type safety tests."""

# pyright: basic
# pyright: reportPrivateUsage=false

from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager
from shot_model import Shot, ShotModel


@pytest.fixture
def type_safe_shot() -> Shot:
    """Create a type-safe Shot instance for testing."""
    return Shot(
        show="test_show",
        sequence="test_seq",
        shot="test_shot",
        workspace_path="/shows/test_show/shots/test_seq/test_seq_test_shot",
    )


@pytest.fixture
def type_safe_shot_list() -> List[Shot]:
    """Create a list of type-safe Shot instances."""
    return [
        Shot("show1", "seq1", "shot1", "/path1"),
        Shot("show2", "seq2", "shot2", "/path2"),
        Shot("show3", "seq3", "shot3", "/path3"),
    ]


@pytest.fixture
def temp_cache_manager(tmp_path) -> Generator[CacheManager, None, None]:
    """Create a CacheManager with temporary directory."""
    cache = CacheManager(cache_dir=tmp_path)
    yield cache
    # Cleanup is handled by tmp_path fixture


@pytest.fixture
def type_safe_shot_model(temp_cache_manager) -> ShotModel:
    """Create a ShotModel with type-safe cache manager."""
    return ShotModel(cache_manager=temp_cache_manager, load_cache=False)


@pytest.fixture
def mock_ws_output_typed() -> str:
    """Mock ws command output with proper typing."""
    return """
    workspace /shows/test_show1/shots/seq_001/seq_001_shot_001
    workspace /shows/test_show1/shots/seq_001/seq_001_shot_002  
    workspace /shows/test_show2/shots/seq_100/seq_100_shot_010
    workspace /shows/test_show2/shots/seq_200/seq_200_shot_020
    """


@pytest.fixture
def mock_successful_subprocess():
    """Mock subprocess.run for successful ws command with type safety."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = """
    workspace /shows/ygsk/shots/108_BQS/108_BQS_0005
    workspace /shows/ygsk/shots/108_CHV/108_CHV_0010
    """
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        yield mock_result


@pytest.fixture
def mock_failed_subprocess():
    """Mock subprocess.run for failed ws command."""
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error: ws command failed"

    with patch("subprocess.run", return_value=mock_result):
        yield mock_result


@pytest.fixture
def sample_shot_dict() -> Dict[str, str]:
    """Sample shot dictionary with proper string typing."""
    return {
        "show": "sample_show",
        "sequence": "sample_seq",
        "shot": "sample_shot",
        "workspace_path": "/shows/sample_show/shots/sample_seq/sample_seq_sample_shot",
    }


@pytest.fixture
def sample_shot_dict_list() -> List[Dict[str, str]]:
    """Sample list of shot dictionaries."""
    return [
        {
            "show": "show1",
            "sequence": "seq1",
            "shot": "shot1",
            "workspace_path": "/path1",
        },
        {
            "show": "show2",
            "sequence": "seq2",
            "shot": "shot2",
            "workspace_path": "/path2",
        },
    ]


@pytest.fixture
def temp_directory_with_images(tmp_path) -> Path:
    """Create temporary directory with sample image files."""
    # Create sample image files
    (tmp_path / "image1.jpg").touch()
    (tmp_path / "image2.jpeg").touch()
    (tmp_path / "image3.png").touch()
    (tmp_path / "not_image.txt").touch()

    return tmp_path


@pytest.fixture
def temp_versioned_directory(tmp_path) -> Path:
    """Create temporary directory with version directories."""
    # Create version directories
    (tmp_path / "v001").mkdir()
    (tmp_path / "v002").mkdir()
    (tmp_path / "v003").mkdir()
    (tmp_path / "not_version").mkdir()

    return tmp_path


@pytest.fixture
def mock_path_utils():
    """Mock PathUtils methods with type-safe returns."""
    with patch("utils.PathUtils") as mock_utils:
        # Configure methods to return proper types
        mock_utils.build_path.return_value = Path("/mock/path")
        mock_utils.validate_path_exists.return_value = True
        mock_utils.batch_validate_paths.return_value = {"/path1": True, "/path2": False}
        mock_utils.discover_plate_directories.return_value = [("BG01", 1), ("FG01", 2)]

        yield mock_utils


@pytest.fixture
def mock_version_utils():
    """Mock VersionUtils methods with type-safe returns."""
    with patch("utils.VersionUtils") as mock_utils:
        # Configure methods to return proper types
        mock_utils.find_version_directories.return_value = [(1, "v001"), (2, "v002")]
        mock_utils.get_latest_version.return_value = "v002"
        mock_utils.extract_version_from_path.return_value = "v001"

        yield mock_utils


@pytest.fixture
def mock_file_utils():
    """Mock FileUtils methods with type-safe returns."""
    with patch("utils.FileUtils") as mock_utils:
        # Configure methods to return proper types
        mock_utils.find_files_by_extension.return_value = [
            Path("/file1.jpg"),
            Path("/file2.png"),
        ]
        mock_utils.get_first_image_file.return_value = Path("/first_image.jpg")
        mock_utils.validate_file_size.return_value = True

        yield mock_utils


@pytest.fixture
def mock_validation_utils():
    """Mock ValidationUtils methods with type-safe returns."""
    with patch("utils.ValidationUtils") as mock_utils:
        # Configure methods to return proper types
        mock_utils.validate_not_empty.return_value = True
        mock_utils.validate_shot_components.return_value = True
        mock_utils.get_current_username.return_value = "test_user"
        mock_utils.get_excluded_users.return_value = {"test_user", "other_user"}

        yield mock_utils


class TypeAssertionHelper:
    """Helper class for type assertions in tests."""

    @staticmethod
    def assert_shot_type(shot: Any) -> None:
        """Assert that object is a properly typed Shot."""
        assert isinstance(shot, Shot)
        assert isinstance(shot.show, str)
        assert isinstance(shot.sequence, str)
        assert isinstance(shot.shot, str)
        assert isinstance(shot.workspace_path, str)

    @staticmethod
    def assert_shot_list_type(shots: Any) -> None:
        """Assert that object is a properly typed List[Shot]."""
        assert isinstance(shots, list)
        for shot in shots:
            TypeAssertionHelper.assert_shot_type(shot)

    @staticmethod
    def assert_dict_str_str(data: Any) -> None:
        """Assert that object is a properly typed Dict[str, str]."""
        assert isinstance(data, dict)
        for key, value in data.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    @staticmethod
    def assert_optional_type(
        value: Any, expected_type: type, allow_none: bool = True
    ) -> None:
        """Assert Optional type handling."""
        if value is None:
            if not allow_none:
                raise AssertionError(
                    f"None not allowed, expected {expected_type.__name__}"
                )
        else:
            assert isinstance(value, expected_type)


@pytest.fixture
def type_helper() -> TypeAssertionHelper:
    """Provide type assertion helper."""
    return TypeAssertionHelper()
