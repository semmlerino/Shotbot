"""Template strings and builders for Nuke script components.

This module provides template-based generation of Nuke script elements,
replacing string concatenation with structured template methods.
"""

from __future__ import annotations


class NukeScriptTemplates:
    """Template builders for Nuke script components."""

    # Window layout XML template
    WINDOW_LAYOUT_XML: str = """define_window_layout_xml {<?xml version="1.0" encoding="UTF-8"?>
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
}"""

    @staticmethod
    def get_script_header() -> str:
        """Get the standard Nuke script header."""
        return "#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx\nversion 16.0 v4"

    @staticmethod
    def get_root_node(
        shot_name: str,
        first_frame: int,
        last_frame: int,
        width: int,
        height: int,
        fps: int = 24,
    ) -> str:
        """Generate Root node with ACES color management.

        Args:
            shot_name: Name of the shot for format naming
            first_frame: First frame of the sequence
            last_frame: Last frame of the sequence
            width: Image width in pixels
            height: Image height in pixels
            fps: Frames per second (default: 24)

        Returns:
            Formatted Root node string

        """
        return f"""Root {{
 inputs 0
 name {shot_name}_comp
 frame {first_frame}
 first_frame {first_frame}
 last_frame {last_frame}
 fps {fps}
 format "{width} {height} 0 0 {width} {height} 1 {shot_name}_format"
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
 floatLut "linear"
}}"""

    @staticmethod
    def get_read_node(
        file_path: str,
        shot_name: str,
        first_frame: int,
        last_frame: int,
        width: int,
        height: int,
        colorspace: str,
        raw_flag: bool,
        xpos: int = 0,
        ypos: int = -300,
        node_name: str = "Read_Plate",
    ) -> str:
        """Generate Read node for plate or media.

        Args:
            file_path: Path to the media file (with %04d pattern)
            shot_name: Shot name for format reference
            first_frame: First frame number
            last_frame: Last frame number
            width: Image width
            height: Image height
            colorspace: Colorspace name
            raw_flag: Whether to use raw flag
            xpos: X position in node graph
            ypos: Y position in node graph
            node_name: Name for the Read node

        Returns:
            Formatted Read node string

        """
        raw_str = "true" if raw_flag else "false"

        return f"""Read {{
 inputs 0
 file_type exr
 file "{file_path}"
 format "{width} {height} 0 0 {width} {height} 1 {shot_name}_format"
 proxy "{file_path}"
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
 name {node_name}
 tile_color 0xcccccc01
 label "\\[value colorspace]\\nframes: {first_frame}-{last_frame}"
 selected true
 xpos {xpos}
 ypos {ypos}
}}"""

    @staticmethod
    def get_grade_node(
        xpos: int = 0,
        ypos: int = -50,
        node_name: str = "Grade_CC",
        label: str = "Color Correction",
    ) -> str:
        """Generate Grade node for color correction.

        Args:
            xpos: X position in node graph
            ypos: Y position in node graph
            node_name: Name for the Grade node
            label: Label text for the node

        Returns:
            Formatted Grade node string

        """
        return f"""Grade {{
 inputs 1
 name {node_name}
 label "{label}"
 xpos {xpos}
 ypos {ypos}
}}"""

    @staticmethod
    def get_viewer_node(
        first_frame: int,
        last_frame: int,
        xpos: int = 0,
        ypos: int = 100,
        node_name: str = "Viewer1",
        fps: int = 24,
    ) -> str:
        """Generate Viewer node.

        Args:
            first_frame: First frame of the sequence
            last_frame: Last frame of the sequence
            xpos: X position in node graph
            ypos: Y position in node graph
            node_name: Name for the Viewer node
            fps: Frames per second

        Returns:
            Formatted Viewer node string

        """
        return f"""Viewer {{
 frame_range {first_frame}-{last_frame}
 fps {fps}
 frame {first_frame}
 gain 1
 gamma 1
 name {node_name}
 selected true
 xpos {xpos}
 ypos {ypos}
}}"""

    @staticmethod
    def get_sticky_note(
        label: str,
        xpos: int,
        ypos: int,
        node_name: str = "Note",
        font_size: int = 14,
        color: str = "0x00aa00ff",
    ) -> str:
        """Generate StickyNote node.

        Args:
            label: Text content for the note
            xpos: X position in node graph
            ypos: Y position in node graph
            node_name: Name for the StickyNote node
            font_size: Font size for the text
            color: Color in hex format (RGBA)

        Returns:
            Formatted StickyNote node string

        """
        return f"""StickyNote {{
 inputs 0
 name {node_name}
 label "{label}"
 note_font_size {font_size}
 note_font_color {color}
 xpos {xpos}
 ypos {ypos}
}}"""

    @staticmethod
    def get_noop_node(
        node_name: str,
        label: str,
        xpos: int,
        ypos: int,
        tile_color: str = "0xff000001",
        oncreate_script: str = "",
    ) -> str:
        """Generate NoOp node with optional Python script.

        Args:
            node_name: Name for the NoOp node
            label: Label text for the node
            xpos: X position in node graph
            ypos: Y position in node graph
            tile_color: Color in hex format
            oncreate_script: Python script to execute onCreate

        Returns:
            Formatted NoOp node string

        """
        oncreate_attr = f' onCreate "{oncreate_script}"' if oncreate_script else ""

        return f"""NoOp {{
 inputs 0
 name {node_name}
 tile_color {tile_color}
 label "{label}"{oncreate_attr}
 xpos {xpos}
 ypos {ypos}
}}"""

    @staticmethod
    def escape_path(path: str) -> str:
        """Escape file path for Nuke script.

        Nuke uses forward slashes even on Windows.

        Args:
            path: File path to escape

        Returns:
            Escaped path with forward slashes

        """
        if not path:
            return ""
        return path.replace("\\", "/")

    @staticmethod
    def format_frame_sequence(path: str) -> str:
        """Convert frame sequence path to Nuke format.

        Args:
            path: Path with #### or %04d pattern

        Returns:
            Path with %04d format for Nuke

        """
        if not path:
            return ""
        escaped = NukeScriptTemplates.escape_path(path)
        return escaped.replace("####", "%04d")
