"""Tests for the bundle encode/decode pipeline (decode_app.py, transfer_config.json)."""

from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

import pytest

from decode_app import _cleanup_partial_extraction, decode_bundle
from transfer_cli import FolderEncoder


class TestCleanupPartialExtraction:
    """Tests for _cleanup_partial_extraction helper."""

    def test_cleanup_removes_partial_directory(self, tmp_path: Path) -> None:
        """Cleanup removes partial extraction directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create a "partial extraction"
        partial = output_dir / "bundle_root"
        partial.mkdir()
        (partial / "file.txt").write_text("partial")

        _cleanup_partial_extraction(str(output_dir), "bundle_root")

        assert not partial.exists()

    def test_cleanup_does_nothing_if_no_root_name(self, tmp_path: Path) -> None:
        """Cleanup is a no-op when root_name is None."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Should not raise
        _cleanup_partial_extraction(str(output_dir), None)

    def test_cleanup_handles_missing_directory(self, tmp_path: Path) -> None:
        """Cleanup handles case where partial dir doesn't exist."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Should not raise even if directory doesn't exist
        _cleanup_partial_extraction(str(output_dir), "nonexistent")


class TestDecodeBundleCleanup:
    """Tests for decode_bundle cleanup on failure."""

    def _create_valid_bundle(self, tmp_path: Path) -> Path:
        """Create a valid base64-encoded tar.gz bundle."""
        # Create a folder to encode
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.txt").write_text("content")

        # Create tar.gz in memory
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            tar.add(str(source), arcname="source")

        # Encode to base64
        tar_buffer.seek(0)
        encoded = base64.b64encode(tar_buffer.read()).decode("utf-8")

        # Write to file
        bundle_file = tmp_path / "bundle.txt"
        bundle_file.write_text(encoded)

        return bundle_file

    def test_decode_bundle_success(self, tmp_path: Path) -> None:
        """Successful decode extracts files."""
        bundle = self._create_valid_bundle(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = decode_bundle(str(bundle), str(output_dir))

        assert result is True
        assert (output_dir / "source" / "file.txt").exists()

    def test_decode_bundle_invalid_base64_returns_false(
        self, tmp_path: Path
    ) -> None:
        """Invalid base64 returns False."""
        bundle_file = tmp_path / "invalid.txt"
        bundle_file.write_text("not valid base64!!!")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = decode_bundle(str(bundle_file), str(output_dir))

        assert result is False

    def test_decode_bundle_missing_file_returns_false(self) -> None:
        """Missing bundle file returns False."""
        result = decode_bundle("/nonexistent/bundle.txt", "/tmp")
        assert result is False

    def test_decode_bundle_list_only_does_not_extract(
        self, tmp_path: Path
    ) -> None:
        """list_only=True lists contents without extracting."""
        bundle = self._create_valid_bundle(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = decode_bundle(str(bundle), str(output_dir), list_only=True)

        assert result is True
        # Should NOT have extracted
        assert not (output_dir / "source").exists()


class TestFolderEncoderSizeLimit:
    """Tests for folder size limit enforcement."""

    def test_encode_folder_under_limit_succeeds(self, tmp_path: Path) -> None:
        """Encoding a small folder succeeds."""
        # Create a small test folder
        test_folder = tmp_path / "small_folder"
        test_folder.mkdir()
        (test_folder / "file.txt").write_text("small content")

        encoder = FolderEncoder()
        encoded, _chunks = encoder.encode_folder(str(test_folder))

        assert encoded is not None
        assert len(encoded) > 0

    def test_encode_folder_over_limit_raises_value_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Encoding a folder over size limit raises ValueError."""
        # Create a test folder
        test_folder = tmp_path / "large_folder"
        test_folder.mkdir()
        (test_folder / "file.txt").write_text("content")

        # Set a very low limit for testing (1 byte)
        monkeypatch.setattr(FolderEncoder, "MAX_FOLDER_SIZE_MB", 0.000001)

        encoder = FolderEncoder()

        with pytest.raises(ValueError, match="Folder too large to encode"):
            encoder.encode_folder(str(test_folder))

    def test_get_folder_size_calculates_correctly(self, tmp_path: Path) -> None:
        """_get_folder_size returns correct total size."""
        test_folder = tmp_path / "sized_folder"
        test_folder.mkdir()

        # Create files with known sizes
        (test_folder / "file1.txt").write_bytes(b"a" * 100)  # 100 bytes
        (test_folder / "file2.txt").write_bytes(b"b" * 200)  # 200 bytes

        subfolder = test_folder / "sub"
        subfolder.mkdir()
        (subfolder / "file3.txt").write_bytes(b"c" * 50)  # 50 bytes

        encoder = FolderEncoder()
        size = encoder._get_folder_size(test_folder)

        # Total: 100 + 200 + 50 = 350 bytes
        assert size == 350

    def test_get_folder_size_handles_permission_errors(
        self, tmp_path: Path
    ) -> None:
        """_get_folder_size skips files it can't access."""
        test_folder = tmp_path / "mixed_folder"
        test_folder.mkdir()
        (test_folder / "accessible.txt").write_bytes(b"a" * 100)

        encoder = FolderEncoder()
        # Should not raise, even if some files can't be accessed
        size = encoder._get_folder_size(test_folder)

        assert size >= 100

    def test_encode_nonexistent_folder_raises_file_not_found(self) -> None:
        """Encoding nonexistent folder raises FileNotFoundError."""
        encoder = FolderEncoder()

        with pytest.raises(FileNotFoundError, match="Folder not found"):
            encoder.encode_folder("/nonexistent/path/that/does/not/exist")

    def test_encode_file_instead_of_folder_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        """Encoding a file (not folder) raises ValueError."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        encoder = FolderEncoder()

        with pytest.raises(ValueError, match="not a directory"):
            encoder.encode_folder(str(test_file))

    def test_verbose_mode_reports_size(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verbose mode reports folder size in output."""
        test_folder = tmp_path / "verbose_folder"
        test_folder.mkdir()
        (test_folder / "file.txt").write_text("content")

        encoder = FolderEncoder(verbose=True)
        encoder.encode_folder(str(test_folder))

        captured = capsys.readouterr()
        # Verbose output includes size in MB
        assert "MB" in captured.err or "Encoding folder" in captured.err
