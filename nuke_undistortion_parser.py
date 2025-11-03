"""Parser for Nuke undistortion files.

This module handles parsing and importing undistortion .nk files,
supporting both standard format and copy/paste format files.
"""

from __future__ import annotations

import re
from pathlib import Path

from logging_mixin import get_module_logger


# Module-level logger for static methods
logger = get_module_logger(__name__)


class NukeUndistortionParser:
    """Parser for Nuke undistortion files."""

    @staticmethod
    def parse_undistortion_file(
        undistortion_path: str,
        ypos_offset: int = -200,
    ) -> str:
        """Parse and import content from an undistortion .nk file.

        This method tries copy/paste format first (most common for undistortion files),
        then falls back to standard format parsing.

        Args:
            undistortion_path: Path to the undistortion .nk file
            ypos_offset: Y position offset for imported nodes

        Returns:
            String containing the processed content to insert, or empty string
        """
        if not undistortion_path or not Path(undistortion_path).exists():
            logger.error(f"Undistortion file not found: {undistortion_path}")
            return ""

        logger.info(f"Attempting to parse undistortion file: {undistortion_path}")

        # Try copy/paste format first (most common for undistortion files)
        imported_nodes = NukeUndistortionParser._parse_copy_paste_format(
            undistortion_path, ypos_offset
        )

        # If copy/paste format failed, try the standard parser
        if not imported_nodes:
            logger.info(
                "Copy/paste format parser returned empty result, trying standard parser as fallback"
            )
            imported_nodes = NukeUndistortionParser._parse_standard_format(
                undistortion_path, ypos_offset
            )

        if imported_nodes:
            logger.info("Successfully parsed undistortion nodes")
            return imported_nodes

        logger.warning(f"Failed to parse undistortion file: {undistortion_path}")
        return ""

    @staticmethod
    def _parse_copy_paste_format(
        undistortion_path: str,
        ypos_offset: int = -200,
    ) -> str:
        """Import content from a copy/paste format undistortion .nk file.

        This handles files that start with 'set cut_paste_input [stack 0]'
        which is Nuke's standard copy/paste format.

        Args:
            undistortion_path: Path to the undistortion .nk file
            ypos_offset: Y position offset for imported nodes

        Returns:
            String containing the processed content to insert
        """
        try:
            logger.debug(
                f"Attempting copy/paste format import from: {undistortion_path}"
            )

            if not Path(undistortion_path).exists():
                logger.error(f"Undistortion file not found: {undistortion_path}")
                return ""

            with Path(undistortion_path).open(encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                logger.error(f"Undistortion file is empty: {undistortion_path}")
                return ""

            lines = content.split("\n")

            # Check if this is copy/paste format
            is_copy_paste_format = False
            for line in lines[:10]:  # Check first 10 lines
                if "set cut_paste_input" in line:
                    is_copy_paste_format = True
                    logger.info("Detected copy/paste format undistortion file")
                    break

            if not is_copy_paste_format:
                logger.debug(
                    "Not copy/paste format, returning empty (main method will handle fallback)"
                )
                return ""

            # Process copy/paste format - import everything except boilerplate
            imported_lines: list[str] = []
            i = 0
            inside_root = False
            root_brace_count = 0
            inside_python = False
            python_brace_count = 0

            while i < len(lines):
                line = lines[i]
                stripped = line.strip()

                # Skip standard boilerplate lines
                if NukeUndistortionParser._should_skip_boilerplate_line(line, stripped):
                    logger.debug(f"Skipping boilerplate line: {line[:50]}")
                    i += 1
                    continue

                # Skip Root node and its contents (would conflict)
                if not inside_root and (
                    stripped.startswith("Root {") or stripped == "Root {"
                ):
                    logger.debug("Found Root node, skipping its contents")
                    inside_root = True
                    root_brace_count = 1
                    i += 1
                    continue

                # If inside Root node, track braces and skip content
                if inside_root:
                    if "{" in line:
                        root_brace_count += line.count("{")
                    if "}" in line:
                        root_brace_count -= line.count("}")

                    if root_brace_count <= 0:
                        inside_root = False
                        logger.debug("Finished skipping Root node")
                    i += 1
                    continue

                # Apply ypos offset if this line contains ypos
                adjusted_line = NukeUndistortionParser._adjust_ypos_in_line(
                    line, ypos_offset
                )
                if adjusted_line != line:
                    logger.debug(f"Adjusted ypos in line: {stripped[:50]}...")
                    line = adjusted_line

                # Sanitize node names - replace illegal characters (like hyphens)
                line = NukeUndistortionParser._sanitize_node_names_in_line(line)

                # Handle Python blocks - strip indentation from Python code
                if not inside_python and stripped.startswith("python {"):
                    inside_python = True
                    python_brace_count = 1
                    imported_lines.append("python {")
                    logger.debug("Entering Python block in copy/paste format")
                    i += 1
                    continue

                # If inside Python block, handle Python code properly
                if inside_python:
                    if "{" in line:
                        python_brace_count += line.count("{")
                    if "}" in line:
                        python_brace_count -= line.count("}")

                    if python_brace_count <= 0:
                        inside_python = False
                        logger.debug("Exiting Python block in copy/paste format")
                        imported_lines.append("}")
                    # For Python code, use same logic as standard format
                    elif stripped:  # Non-empty line
                        indent_count = len(line) - len(line.lstrip())

                        # Top-level Python statements should have NO indentation
                        if stripped.startswith(
                            ("import ", "from ", "def ", "class ")
                        ):
                            imported_lines.append(stripped)
                        else:
                            # Preserve relative indentation for nested blocks
                            if indent_count >= 5:
                                dedented = (
                                    line[5:] if len(line) > 5 else line.lstrip()
                                )
                            elif indent_count == 4:
                                dedented = line[4:]
                            else:
                                dedented = line.lstrip()
                            imported_lines.append(dedented)

                        if imported_lines[-1] != line:
                            logger.debug(
                                f"Dedented Python line in copy/paste: {imported_lines[-1][:50]}..."
                            )
                    else:
                        # Empty line in Python block
                        imported_lines.append("")
                    i += 1
                    continue

                # Import this line normally (not in Python block)
                imported_lines.append(line)
                i += 1

            # Join the imported content
            imported_content = "\n".join(imported_lines).strip()

            if imported_content:
                result = (
                    (
                        "\n# Imported undistortion content from copy/paste format\n"
                        "# "
                    )
                    + undistortion_path
                    + "\n"
                    + imported_content
                    + "\n"
                )
                logger.info(
                    f"Successfully imported copy/paste content ({len(result)} characters)"
                )
                return result

            logger.warning("No content found to import")
            return ""

        except Exception as e:
            logger.error(f"Error importing copy/paste format: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return ""

    @staticmethod
    def _parse_standard_format(
        undistortion_path: str,
        ypos_offset: int = -200,
    ) -> str:
        """Import ALL content from a standard format undistortion .nk file.

        This method imports the entire content of the .nk file, excluding only
        the parts that would conflict with the main script (Root node, version, etc).

        Args:
            undistortion_path: Path to the undistortion .nk file
            ypos_offset: Y position offset for imported nodes

        Returns:
            String containing the processed content to insert
        """
        try:
            logger.debug(f"Starting standard format import from: {undistortion_path}")

            # Check if file exists
            undistortion_file = Path(undistortion_path)
            if not undistortion_file.exists():
                logger.error(f"Undistortion file not found: {undistortion_path}")
                return ""

            logger.debug(f"File exists, size: {undistortion_file.stat().st_size} bytes")

            with undistortion_file.open(encoding="utf-8") as f:
                content = f.read()

            logger.debug(
                f"Successfully read file, content length: {len(content)} characters"
            )

            if not content.strip():
                logger.error(f"Undistortion file is empty: {undistortion_path}")
                return ""

            logger.debug(f"File content preview (first 200 chars): {content[:200]}")

            # Process the file content - we'll import everything except conflicting sections
            lines = content.split("\n")
            imported_lines: list[str] = []
            i = 0
            inside_root = False
            root_brace_count = 0
            inside_python = False
            python_brace_count = 0

            logger.debug(f"Processing {len(lines)} lines")

            while i < len(lines):
                line = lines[i]
                stripped = line.strip()

                # Skip standard boilerplate lines
                if NukeUndistortionParser._should_skip_boilerplate_line(line, stripped):
                    logger.debug(f"Skipping boilerplate line: {line[:50]}")
                    i += 1
                    continue

                # Skip window layout definition (conflicts with main script)
                if stripped.startswith("define_window_layout"):
                    logger.debug("Skipping window layout definition")
                    # Skip until we find the closing brace
                    brace_count = 1
                    i += 1
                    while i < len(lines) and brace_count > 0:
                        if "{" in lines[i]:
                            brace_count += lines[i].count("{")
                        if "}" in lines[i]:
                            brace_count -= lines[i].count("}")
                        i += 1
                    continue

                # Handle Root node - skip it and its contents
                if not inside_root and (
                    stripped.startswith("Root {") or stripped == "Root {"
                ):
                    logger.debug("Found Root node, skipping its contents")
                    inside_root = True
                    root_brace_count = 1
                    i += 1
                    continue

                # If inside Root node, track braces and skip content
                if inside_root:
                    if "{" in line:
                        root_brace_count += line.count("{")
                    if "}" in line:
                        root_brace_count -= line.count("}")

                    if root_brace_count <= 0:
                        inside_root = False
                        logger.debug("Finished skipping Root node")
                    i += 1
                    continue

                # Apply ypos offset if this line contains ypos
                adjusted_line = NukeUndistortionParser._adjust_ypos_in_line(
                    line, ypos_offset
                )
                if adjusted_line != line:
                    logger.debug(f"Adjusted ypos in line: {stripped[:50]}...")
                    line = adjusted_line

                # Sanitize node names - replace illegal characters (like hyphens)
                line = NukeUndistortionParser._sanitize_node_names_in_line(line)

                # Handle Python blocks - strip indentation from Python code
                if not inside_python and stripped.startswith("python {"):
                    inside_python = True
                    python_brace_count = 1
                    imported_lines.append("python {")
                    logger.debug("Entering Python block")
                    i += 1
                    continue

                # If inside Python block, handle Python code properly
                if inside_python:
                    if "{" in line:
                        python_brace_count += line.count("{")
                    if "}" in line:
                        python_brace_count -= line.count("}")

                    if python_brace_count <= 0:
                        inside_python = False
                        logger.debug("Exiting Python block")
                        imported_lines.append("}")
                    # For Python code, we need to intelligently strip base indentation
                    elif stripped:  # Non-empty line
                        # Find how much the line is indented
                        indent_count = len(line) - len(line.lstrip())

                        # For top-level Python statements, remove ALL indentation
                        if stripped.startswith(
                            ("import ", "from ", "def ", "class ")
                        ):
                            imported_lines.append(stripped)
                        else:
                            # For other lines, try to preserve relative indentation
                            if indent_count >= 5:
                                dedented = (
                                    line[5:] if len(line) > 5 else line.lstrip()
                                )
                            elif indent_count == 4:
                                dedented = line[4:]
                            else:
                                dedented = line.lstrip()
                            imported_lines.append(dedented)

                        logger.debug(
                            f"Processed Python line: {imported_lines[-1][:50]}..."
                        )
                    else:
                        # Empty line in Python block
                        imported_lines.append("")
                    i += 1
                    continue

                # Import this line normally (not in Python block)
                imported_lines.append(line)
                i += 1

            # Join the imported lines
            imported_content = "\n".join(imported_lines).strip()

            if imported_content:
                result = (
                    "\n# Imported undistortion content from "
                    + undistortion_path
                    + "\n"
                    + imported_content
                    + "\n"
                )
                logger.info(
                    f"Successfully imported standard format content ({len(result)} characters)"
                )
                return result

            logger.warning("No content to import after filtering")
            return ""

        except FileNotFoundError:
            logger.error(f"Undistortion file not found: {undistortion_path}")
            return ""
        except UnicodeDecodeError as e:
            logger.error(f"Could not decode undistortion file {undistortion_path}: {e}")
            return ""
        except Exception as e:
            logger.error(
                f"Unexpected error importing undistortion from {undistortion_path}: {e}"
            )
            import traceback

            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return ""

    @staticmethod
    def _adjust_ypos_in_line(line: str, ypos_offset: int) -> str:
        """Adjust ypos values in a line by the given offset.

        Args:
            line: The line to process
            ypos_offset: Amount to add to ypos values

        Returns:
            Line with adjusted ypos values
        """
        if "ypos" not in line or ypos_offset == 0:
            return line

        def adjust_ypos(match: re.Match[str]) -> str:
            old_ypos = int(match.group(1))
            new_ypos = old_ypos + ypos_offset
            return f"ypos {new_ypos}"

        ypos_pattern = re.compile(r"ypos\s+(-?\d+)")
        return ypos_pattern.sub(adjust_ypos, line)

    @staticmethod
    def _sanitize_node_names_in_line(line: str) -> str:
        """Sanitize node names in a line to be Nuke-compatible.

        Args:
            line: The line to process

        Returns:
            Line with sanitized node names
        """
        if " name " not in line:
            return line

        def sanitize_name(match: re.Match[str]) -> str:
            prefix = match.group(1)
            name = match.group(2)
            # Replace any character that's not alphanumeric or underscore
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
            if sanitized != name:
                logger.debug(f"Sanitized node name: {name} -> {sanitized}")
            return prefix + sanitized

        name_pattern = re.compile(r"(\s+name\s+)([^\s]+)")
        return name_pattern.sub(sanitize_name, line)

    @staticmethod
    def _should_skip_boilerplate_line(line: str, stripped: str) -> bool:
        """Check if a line should be skipped as boilerplate.

        Args:
            line: The full line
            stripped: The stripped line

        Returns:
            True if this line should be skipped
        """
        # Skip version line (will be in main script already)
        if stripped.startswith("version "):
            return True

        # Skip shebang line
        if stripped.startswith("#!"):
            return True

        # Skip copy/paste specific lines
        if "set cut_paste_input" in line:
            return True

        return bool(
            stripped.startswith("push")
            and ("push $cut_paste_input" in line or "push 0" in stripped)
        )
