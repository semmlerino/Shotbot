"""Generate Nuke scripts with proper Read nodes for plates and undistortion."""

import atexit
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Set, Tuple


class NukeScriptGenerator:
    """Generate temporary Nuke scripts with proper Read nodes.

    This class tracks temporary files and ensures they are cleaned up
    on program exit to prevent disk space leaks.
    """

    # Track all temporary files created for cleanup
    _temp_files: Set[str] = set()
    _cleanup_registered: bool = False

    @classmethod
    def _register_cleanup(cls) -> None:
        """Register cleanup function to run at program exit."""
        if not cls._cleanup_registered:
            atexit.register(cls._cleanup_temp_files)
            cls._cleanup_registered = True

    @classmethod
    def _cleanup_temp_files(cls) -> None:
        """Clean up all temporary files created during session."""
        for temp_file in cls._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
                    print(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                print(f"Warning: Could not delete temp file {temp_file}: {e}")
        cls._temp_files.clear()

    @classmethod
    def _track_temp_file(cls, filepath: str) -> str:
        """Track a temporary file for cleanup and return its path."""
        cls._register_cleanup()  # Ensure cleanup is registered
        cls._temp_files.add(filepath)
        return filepath

    @staticmethod
    def _escape_path(path: str) -> str:
        """Escape file path for Nuke script.

        Nuke uses forward slashes even on Windows.
        """
        if not path:
            return ""
        # Convert to forward slashes for Nuke
        return path.replace("\\", "/")

    @staticmethod
    def _detect_frame_range(plate_path: str) -> Tuple[int, int]:
        """Detect actual frame range from plate files.

        Returns:
            Tuple of (first_frame, last_frame)
        """
        if not plate_path:
            return 1001, 1100  # Default VFX range

        try:
            plate_dir = Path(plate_path).parent
            if not plate_dir.exists():
                return 1001, 1100

            # Build pattern for frame detection
            base_name = Path(plate_path).name
            # Replace #### or %04d with regex pattern
            pattern = base_name.replace("####", r"(\d{4})").replace("%04d", r"(\d{4})")
            frame_regex = re.compile(pattern)

            frame_numbers: List[int] = []
            for file in plate_dir.iterdir():
                match = frame_regex.match(file.name)
                if match:
                    frame_numbers.append(int(match.group(1)))

            if frame_numbers:
                return min(frame_numbers), max(frame_numbers)

        except Exception as e:
            print(f"Warning: Could not detect frame range: {e}")

        return 1001, 1100

    @staticmethod
    def _detect_colorspace(plate_path: str) -> Tuple[str, bool]:
        """Detect colorspace and raw flag from filename or path.

        Returns:
            Tuple of (colorspace, raw_flag)
            For linear plates: ("linear", True)
            For other plates: (colorspace_name, False)
        """
        if not plate_path:
            return "linear", True  # Default to linear raw

        path_lower = plate_path.lower()

        # Linear plates (use raw=true with colorspace="linear")
        if "lin_" in path_lower or "linear" in path_lower:
            return "linear", True

        # Log plates (use raw=false with appropriate colorspace)
        elif "logc" in path_lower or "alexa" in path_lower:
            return "logc3ei800", False
        elif "log" in path_lower:
            return "log", False

        # Display-referred colorspaces
        elif "rec709" in path_lower:
            return "rec709", False
        elif "srgb" in path_lower:
            return "sRGB", False

        # Default to linear raw (safest for VFX plates)
        else:
            return "linear", True

    @staticmethod
    def _detect_resolution(plate_path: str) -> Tuple[int, int]:
        """Detect resolution from path.

        Returns:
            Tuple of (width, height)
        """
        if not plate_path:
            return 4312, 2304  # Default production resolution

        # Look for patterns like 4312x2304 or 1920x1080
        resolution_pattern = re.compile(r"(\d{3,4})[x_](\d{3,4})")
        match = resolution_pattern.search(plate_path)

        if match:
            try:
                width = int(match.group(1))
                height = int(match.group(2))
                # Sanity check
                if 640 <= width <= 8192 and 480 <= height <= 4320:
                    return width, height
            except (ValueError, AttributeError):
                pass

        return 4312, 2304

    @staticmethod
    def create_plate_script(plate_path: str, shot_name: str) -> Optional[str]:
        """Create a Nuke script with a proper Read node for the plate.

        Args:
            plate_path: Path to the plate sequence (with #### or %04d pattern)
            shot_name: Name of the shot for the script

        Returns:
            Path to the temporary .nk script, or None if creation failed
        """
        try:
            # Sanitize shot_name to prevent path traversal
            safe_shot_name = re.sub(r"[^\w\-_]", "_", shot_name)

            # Convert path for Nuke
            nuke_path = NukeScriptGenerator._escape_path(plate_path)
            # Ensure we use %04d format for Nuke
            nuke_path = nuke_path.replace("####", "%04d")

            # Detect frame range
            first_frame, last_frame = NukeScriptGenerator._detect_frame_range(
                plate_path
            )

            # Detect colorspace and raw flag
            colorspace, use_raw = NukeScriptGenerator._detect_colorspace(plate_path)
            raw_str = "true" if use_raw else "false"

            # Detect resolution
            width, height = NukeScriptGenerator._detect_resolution(plate_path)

            # Create proper Nuke script content
            script_content = f"""#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
define_window_layout_xml {{<?xml version="1.0" encoding="UTF-8"?>
<layout version="1.0">
    <window x="0" y="0" w="1920" h="1080" fullscreen="0" screen="0">
        <splitter orientation="1">
            <split size="1214"/>
            <splitter orientation="2">
                <split size="570"/>
                <dock id="" activePageId="Viewer.1">
                    <page id="Viewer.1"/>
                </dock>
                <split size="460"/>
                <dock id="" activePageId="DAG.1">
                    <page id="DAG.1"/>
                </dock>
            </splitter>
            <split size="682"/>
            <dock id="" activePageId="Properties.1">
                <page id="Properties.1"/>
            </dock>
        </splitter>
    </window>
</layout>
}}
Root {{
 inputs 0
 name {safe_shot_name}_plate_comp
 first_frame {first_frame}
 last_frame {last_frame}
 fps 24
 format "{width} {height} 0 0 {width} {height} 1 {safe_shot_name}_format"
 proxy_type scale
 proxy_format "1920 1080 0 0 1920 1080 1 HD_1080"
 proxySetting "if \\[value root.proxy] {{ 960 540 }} else {{ {width} {height} }}"
 colorManagement OCIO
 OCIO_config aces_1.2
 defaultViewerLUT "OCIO LUTs"
 workingSpaceLUT "ACES - ACEScg"
 monitorLut "Rec.709 (ACES)"
 int8Lut "Rec.709 (ACES)"
 int16Lut "Rec.709 (ACES)"
 logLut "Log film emulation (ACES)"
 floatLut linear
}}
Read {{
 inputs 0
 file_type exr
 file "{nuke_path}"
 format "{width} {height} 0 0 {width} {height} 1 {safe_shot_name}_format"
 proxy "{nuke_path}"
 first {first_frame}
 last {last_frame}
 origfirst {first_frame}
 origlast {last_frame}
 origset true
 on_error black
 reload 0
 auto_alpha true
 premultiplied true
 raw {raw_str}
 colorspace "{colorspace}"
 name Read_Plate
 tile_color 0xcccccc01
 label "\\[value colorspace]\\nframes: {first_frame}-{last_frame}"
 selected true
 xpos 0
 ypos -150
}}
Grade {{
 inputs 1
 name Grade_CC
 label "Color Correction"
 xpos 0
 ypos -50
}}
Viewer {{
 frame_range {first_frame}-{last_frame}
 fps 24
 frame {first_frame}
 gain 1
 gamma 1
 name Viewer1
 selected true
 xpos 0
 ypos 50
}}
"""
            # Create temporary file (will be deleted when Nuke closes it)
            # Note: We need delete=False because Nuke needs to read the file
            # But we should track these files for cleanup elsewhere
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".nk",
                prefix=f"{safe_shot_name}_plate_",
                delete=False,  # Required for Nuke to read, but needs cleanup tracking
                encoding="utf-8",
            ) as tmp_file:
                tmp_file.write(script_content)
                temp_path = tmp_file.name

            # Track the file for cleanup at program exit
            return NukeScriptGenerator._track_temp_file(temp_path)

        except Exception as e:
            print(f"Error creating Nuke script: {e}")
            return None

    @staticmethod
    def _import_undistortion_nodes(
        undistortion_path: str, ypos_offset: int = -200
    ) -> str:
        """Import nodes from an undistortion .nk file.

        Args:
            undistortion_path: Path to the undistortion .nk file
            ypos_offset: Y position offset for imported nodes

        Returns:
            String containing the processed nodes to insert
        """
        try:
            with open(undistortion_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse nodes from the file
            imported_nodes: List[str] = []
            lines = content.split("\n")
            i = 0

            while i < len(lines):
                line = lines[i]

                # Skip comment lines, version, and window layout
                if (
                    line.startswith("#")
                    or line.startswith("version")
                    or line.startswith("define_window_layout")
                ):
                    i += 1
                    continue

                # Skip Root node and its contents
                if line.startswith("Root {") or line.strip() == "Root {":
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

                # Check if this line starts a node we want to import
                node_types = [
                    "LensDistortion",
                    "UVTile2",
                    "Crop",
                    "Switch",
                    "Expression",
                    "NoOp",
                    "Dot",
                    "Reformat",
                ]
                is_node_start = False
                for node_type in node_types:
                    if line.startswith(node_type + " {"):
                        is_node_start = True
                        break

                if is_node_start:
                    # Collect the entire node
                    node_lines = [line]
                    brace_count = line.count("{") - line.count("}")
                    i += 1

                    while i < len(lines) and brace_count > 0:
                        node_lines.append(lines[i])
                        brace_count += lines[i].count("{") - lines[i].count("}")
                        i += 1

                    # Process the node
                    node_text = "\n".join(node_lines)

                    # Adjust ypos values if present
                    if "ypos" in node_text:
                        ypos_match = re.search(r"ypos\s+(-?\d+)", node_text)
                        if ypos_match:
                            old_ypos = int(ypos_match.group(1))
                            new_ypos = old_ypos + ypos_offset
                            node_text = re.sub(
                                r"ypos\s+" + str(old_ypos),
                                f"ypos {new_ypos}",
                                node_text,
                            )

                    imported_nodes.append(node_text)
                else:
                    i += 1

            if imported_nodes:
                return (
                    "\n# Imported undistortion nodes from "
                    + undistortion_path
                    + "\n"
                    + "\n".join(imported_nodes)
                    + "\n"
                )
            else:
                return ""

        except Exception as e:
            print(
                f"Warning: Could not import undistortion nodes from {undistortion_path}: {e}"
            )
            return ""

    @staticmethod
    def create_plate_script_with_undistortion(
        plate_path: str, undistortion_path: Optional[str], shot_name: str
    ) -> Optional[str]:
        """Create a Nuke script with plate and optional undistortion.

        This version properly imports the undistortion nodes from the .nk file
        and integrates them into the compositing graph.

        Args:
            plate_path: Path to the plate sequence (can be empty)
            undistortion_path: Path to undistortion .nk file (optional)
            shot_name: Name of the shot

        Returns:
            Path to the temporary .nk script
        """
        try:
            # Sanitize shot_name to prevent path traversal
            safe_shot_name = re.sub(r"[^\w\-_]", "_", shot_name)

            # Handle empty or None paths
            plate_path = plate_path or ""
            undistortion_path = undistortion_path or ""

            # Convert paths for Nuke
            nuke_plate_path = NukeScriptGenerator._escape_path(plate_path)
            nuke_plate_path = nuke_plate_path.replace("####", "%04d")

            # Detect properties
            first_frame, last_frame = NukeScriptGenerator._detect_frame_range(
                plate_path
            )
            width, height = NukeScriptGenerator._detect_resolution(plate_path)
            colorspace, use_raw = NukeScriptGenerator._detect_colorspace(plate_path)
            raw_str = "true" if use_raw else "false"

            # Create enhanced Nuke script content
            script_content = f"""#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx
version 16.0 v4
define_window_layout_xml {{<?xml version="1.0" encoding="UTF-8"?>
<layout version="1.0">
    <window x="0" y="0" w="1920" h="1080" fullscreen="0" screen="0">
        <splitter orientation="1">
            <split size="1214"/>
            <splitter orientation="2">
                <split size="570"/>
                <dock id="" activePageId="Viewer.1">
                    <page id="Viewer.1"/>
                </dock>
                <split size="460"/>
                <dock id="" activePageId="DAG.1" focus="true">
                    <page id="DAG.1"/>
                </dock>
            </splitter>
            <split size="682"/>
            <dock id="" activePageId="Properties.1">
                <page id="Properties.1"/>
            </dock>
        </splitter>
    </window>
</layout>
}}
Root {{
 inputs 0
 name {safe_shot_name}_comp
 frame {first_frame}
 first_frame {first_frame}
 last_frame {last_frame}
 fps 24
 format "{width} {height} 0 0 {width} {height} 1 {safe_shot_name}_format"
 proxy_type scale
 proxy_format "1920 1080 0 0 1920 1080 1 HD_1080"
 colorManagement OCIO
 OCIO_config aces_1.2
 defaultViewerLUT "OCIO LUTs"
 workingSpaceLUT "ACES - ACEScg"
 monitorLut "Rec.709 (ACES)"
 int8Lut "Rec.709 (ACES)"
 int16Lut "Rec.709 (ACES)"
 logLut "Log film emulation (ACES)"
 floatLut linear
}}
"""

            # Add plate Read node if path provided
            if plate_path and nuke_plate_path:
                script_content += f"""
Read {{
 inputs 0
 file_type exr
 file "{nuke_plate_path}"
 format "{width} {height} 0 0 {width} {height} 1 {safe_shot_name}_format"
 proxy "{nuke_plate_path}"
 first {first_frame}
 last {last_frame}
 origfirst {first_frame}
 origlast {last_frame}
 origset true
 on_error black
 reload 0
 auto_alpha true
 premultiplied true
 raw {raw_str}
 colorspace "{colorspace}"
 name Read_Plate
 tile_color 0xcccccc01
 label "Raw Plate\\n\\[value colorspace]\\nframes: {first_frame}-{last_frame}"
 selected true
 xpos 0
 ypos -300
}}
"""

            # Import undistortion nodes if provided
            if undistortion_path and Path(undistortion_path).exists():
                # Import the actual undistortion nodes from the .nk file
                imported_nodes = NukeScriptGenerator._import_undistortion_nodes(
                    undistortion_path, ypos_offset=-200
                )
                if imported_nodes:
                    # Fix the first node to connect to Read_Plate (if it exists)
                    # and ensure proper chaining
                    if plate_path and nuke_plate_path:
                        # Connect first undistortion node to Read_Plate
                        imported_nodes = imported_nodes.replace(
                            "inputs 0", "inputs 1", 1
                        )

                    script_content += imported_nodes
                    script_content += f"""
# Reference to original undistortion file
StickyNote {{
 inputs 0
 name Note_Undistortion_Source
 label "Undistortion imported from:\\n{NukeScriptGenerator._escape_path(undistortion_path)}"
 note_font_size 14
 note_font_color 0x00aa00ff
 xpos 200
 ypos -300
}}
"""
                else:
                    # Fallback to reference if import failed
                    escaped_undist_path = NukeScriptGenerator._escape_path(
                        undistortion_path
                    )
                    script_content += f"""
# Undistortion available: {escaped_undist_path}
StickyNote {{
 inputs 0
 name Note_Undistortion
 label "UNDISTORTION AVAILABLE\\nFile > Import Script:\\n{escaped_undist_path}"
 note_font_size 16
 note_font_color 0xff8800ff
 xpos 200
 ypos -300
}}
"""

            # Add viewer and other nodes
            script_content += f"""
Viewer {{
 inputs 1
 frame {first_frame}
 frame_range {first_frame}-{last_frame}
 fps 24
 name Viewer1
 selected true
 xpos 0
 ypos 100
}}
"""

            # Create temporary file (will be deleted when Nuke closes it)
            # Note: We need delete=False because Nuke needs to read the file
            # But we should track these files for cleanup elsewhere
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".nk",
                prefix=f"{safe_shot_name}_comp_",
                delete=False,  # Required for Nuke to read, but needs cleanup tracking
                encoding="utf-8",
            ) as tmp_file:
                tmp_file.write(script_content)
                temp_path = tmp_file.name

            # Track the file for cleanup at program exit
            return NukeScriptGenerator._track_temp_file(temp_path)

        except Exception as e:
            print(f"Error creating Nuke script with undistortion: {e}")
            return None
