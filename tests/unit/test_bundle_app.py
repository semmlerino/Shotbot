"""Smoke tests for bundle_app.py to catch packaging regressions.

These tests cover:
- GitIgnoreParser pattern matching
- ApplicationBundler file collection
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deploy.bundle_app import ApplicationBundler, GitIgnoreParser


class TestGitIgnoreParser:
    """Tests for GitIgnoreParser pattern matching."""

    def test_always_exclude_pycache(self) -> None:
        """Parser always excludes __pycache__ directories."""
        parser = GitIgnoreParser()
        assert parser.should_exclude("__pycache__", is_dir=True)
        assert parser.should_exclude("some/path/__pycache__", is_dir=True)

    def test_always_exclude_pyc_files(self) -> None:
        """Parser always excludes .pyc files."""
        parser = GitIgnoreParser()
        assert parser.should_exclude("module.pyc")
        assert parser.should_exclude("path/to/module.pyc")

    def test_always_exclude_git_directory(self) -> None:
        """Parser always excludes .git directory."""
        parser = GitIgnoreParser()
        assert parser.should_exclude(".git", is_dir=True)

    def test_always_exclude_venv(self) -> None:
        """Parser always excludes venv directories."""
        parser = GitIgnoreParser()
        assert parser.should_exclude("venv", is_dir=True)
        assert parser.should_exclude(".venv", is_dir=True)

    def test_does_not_exclude_normal_python_files(self) -> None:
        """Parser does not exclude normal Python files."""
        parser = GitIgnoreParser()
        assert not parser.should_exclude("module.py")
        assert not parser.should_exclude("src/utils.py")

    def test_parses_gitignore_file(self, tmp_path: Path) -> None:
        """Parser reads patterns from .gitignore file."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/\n*.log\n# comment\n\n")

        parser = GitIgnoreParser(str(gitignore))

        assert parser.should_exclude("build", is_dir=True)
        assert parser.should_exclude("debug.log")
        # Normal files still allowed
        assert not parser.should_exclude("src", is_dir=True)

    def test_handles_missing_gitignore(self) -> None:
        """Parser works when .gitignore doesn't exist."""
        parser = GitIgnoreParser("/nonexistent/.gitignore")
        # Should use always_exclude patterns only
        assert parser.should_exclude("__pycache__", is_dir=True)
        assert not parser.should_exclude("normal_file.py")


class TestApplicationBundler:
    """Tests for ApplicationBundler file collection."""

    @pytest.fixture
    def sample_project(self, tmp_path: Path) -> Path:
        """Create a sample project structure for testing."""
        # Create source files
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "config.json").write_text('{"key": "value"}')
        (tmp_path / "README.md").write_text("# README")

        # Create subdirectory with files
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "utils.py").write_text("# utils")

        # Create excluded content
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"compiled")

        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("# git config")

        # Create test directory (typically excluded)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("# test")

        return tmp_path

    def test_bundler_initialization(self) -> None:
        """ApplicationBundler initializes with defaults."""
        bundler = ApplicationBundler(verbose=False)
        assert bundler.config is not None
        assert "include_patterns" in bundler.config
        assert "exclude_patterns" in bundler.config

    def test_bundler_with_config_file(self, tmp_path: Path) -> None:
        """ApplicationBundler loads config from file."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"include_patterns": ["*.py", "*.txt"]}')

        bundler = ApplicationBundler(config_path=str(config_file), verbose=False)
        assert "*.py" in bundler.config["include_patterns"]
        assert "*.txt" in bundler.config["include_patterns"]

    def test_collects_python_files(self, sample_project: Path) -> None:
        """Bundler collects .py files."""
        bundler = ApplicationBundler(verbose=False)
        files = bundler.collect_files(str(sample_project))

        relative_paths = [rel for _, rel in files]
        assert "main.py" in relative_paths
        assert "lib/utils.py" in relative_paths

    def test_collects_json_files(self, sample_project: Path) -> None:
        """Bundler collects .json files."""
        bundler = ApplicationBundler(verbose=False)
        files = bundler.collect_files(str(sample_project))

        relative_paths = [rel for _, rel in files]
        assert "config.json" in relative_paths

    def test_excludes_pycache(self, sample_project: Path) -> None:
        """Bundler excludes __pycache__ directories."""
        bundler = ApplicationBundler(verbose=False)
        files = bundler.collect_files(str(sample_project))

        relative_paths = [rel for _, rel in files]
        assert not any("__pycache__" in p for p in relative_paths)
        assert not any(".pyc" in p for p in relative_paths)

    def test_excludes_git_directory(self, sample_project: Path) -> None:
        """Bundler excludes .git directory."""
        bundler = ApplicationBundler(verbose=False)
        files = bundler.collect_files(str(sample_project))

        relative_paths = [rel for _, rel in files]
        assert not any(".git" in p for p in relative_paths)
