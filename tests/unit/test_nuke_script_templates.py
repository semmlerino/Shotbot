"""Unit tests for nuke_script_templates module.

Tests template generation methods for Nuke script components including
Root nodes, Read nodes, Grade nodes, Viewer nodes, and utility functions.
"""

from nuke.script_templates import NukeScriptTemplates


class TestNukeScriptTemplates:
    """Test template generation methods."""

    def test_get_script_header(self) -> None:
        """Test script header generation."""
        header = NukeScriptTemplates.get_script_header()

        assert "#! /usr/local/Nuke16.0v4/nuke-16.0.4 -nx" in header
        assert "version 16.0 v4" in header
        assert header.count("\n") == 1  # Should have exactly one newline

    def test_get_root_node_basic(self) -> None:
        """Test basic Root node generation."""
        root = NukeScriptTemplates.get_root_node(
            shot_name="test_shot",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
        )

        assert "Root {" in root
        assert "name test_shot_comp" in root
        assert "frame 1001" in root
        assert "first_frame 1001" in root
        assert "last_frame 1100" in root
        assert "fps 24" in root  # default fps
        assert 'format "1920 1080 0 0 1920 1080 1 test_shot_format"' in root
        assert "colorManagement OCIO" in root
        assert "OCIO_config aces_1.2" in root

    def test_get_root_node_custom_fps(self) -> None:
        """Test Root node with custom FPS."""
        root = NukeScriptTemplates.get_root_node(
            shot_name="test_shot",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
            fps=30,
        )

        assert "fps 30" in root

    def test_get_root_node_aces_colorspace(self) -> None:
        """Test Root node includes ACES color management."""
        root = NukeScriptTemplates.get_root_node(
            shot_name="test_shot",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
        )

        # Check ACES-specific settings
        assert 'workingSpaceLUT "ACES - ACEScg"' in root
        assert 'monitorLut "Rec.709 (ACES)"' in root
        assert 'int8Lut "Rec.709 (ACES)"' in root
        assert 'int16Lut "Rec.709 (ACES)"' in root
        assert 'logLut "Log film emulation (ACES)"' in root
        assert 'floatLut "linear"' in root

    def test_get_read_node_basic(self) -> None:
        """Test basic Read node generation."""
        read_node = NukeScriptTemplates.get_read_node(
            file_path="/path/to/plates/shot_%04d.exr",
            shot_name="test_shot",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
            colorspace="linear",
            raw_flag=True,
        )

        assert "Read {" in read_node
        assert 'file "/path/to/plates/shot_%04d.exr"' in read_node
        assert "first 1001" in read_node
        assert "last 1100" in read_node
        assert "origfirst 1001" in read_node
        assert "origlast 1100" in read_node
        assert "raw true" in read_node
        assert 'colorspace "linear"' in read_node
        assert "name Read_Plate" in read_node
        assert "xpos 0" in read_node
        assert "ypos -300" in read_node

    def test_get_read_node_custom_params(self) -> None:
        """Test Read node with custom parameters."""
        read_node = NukeScriptTemplates.get_read_node(
            file_path="/custom/path_%04d.exr",
            shot_name="custom_shot",
            first_frame=2001,
            last_frame=2200,
            width=4096,
            height=2304,
            colorspace="logc3ei800",
            raw_flag=False,
            xpos=100,
            ypos=-500,
            node_name="Custom_Read",
        )

        assert 'file "/custom/path_%04d.exr"' in read_node
        assert "first 2001" in read_node
        assert "last 2200" in read_node
        assert "raw false" in read_node
        assert 'colorspace "logc3ei800"' in read_node
        assert "name Custom_Read" in read_node
        assert "xpos 100" in read_node
        assert "ypos -500" in read_node

    def test_get_read_node_format_and_proxy(self) -> None:
        """Test Read node format and proxy settings."""
        read_node = NukeScriptTemplates.get_read_node(
            file_path="/path/test_%04d.exr",
            shot_name="format_test",
            first_frame=1001,
            last_frame=1100,
            width=2048,
            height=1556,
            colorspace="linear",
            raw_flag=True,
        )

        assert 'format "2048 1556 0 0 2048 1556 1 format_test_format"' in read_node
        assert 'proxy "/path/test_%04d.exr"' in read_node
        assert "auto_alpha true" in read_node
        assert "premultiplied true" in read_node

    def test_get_grade_node_basic(self) -> None:
        """Test basic Grade node generation."""
        grade = NukeScriptTemplates.get_grade_node()

        assert "Grade {" in grade
        assert "inputs 1" in grade
        assert "name Grade_CC" in grade
        assert 'label "Color Correction"' in grade
        assert "xpos 0" in grade
        assert "ypos -50" in grade

    def test_get_grade_node_custom(self) -> None:
        """Test Grade node with custom parameters."""
        grade = NukeScriptTemplates.get_grade_node(
            xpos=200,
            ypos=-100,
            node_name="Custom_Grade",
            label="Custom Color Correction",
        )

        assert "name Custom_Grade" in grade
        assert 'label "Custom Color Correction"' in grade
        assert "xpos 200" in grade
        assert "ypos -100" in grade

    def test_get_viewer_node_basic(self) -> None:
        """Test basic Viewer node generation."""
        viewer = NukeScriptTemplates.get_viewer_node(first_frame=1001, last_frame=1100)

        assert "Viewer {" in viewer
        assert "frame_range 1001-1100" in viewer
        assert "fps 24" in viewer
        assert "frame 1001" in viewer
        assert "gain 1" in viewer
        assert "gamma 1" in viewer
        assert "name Viewer1" in viewer
        assert "xpos 0" in viewer
        assert "ypos 100" in viewer

    def test_get_viewer_node_custom(self) -> None:
        """Test Viewer node with custom parameters."""
        viewer = NukeScriptTemplates.get_viewer_node(
            first_frame=2001,
            last_frame=2200,
            xpos=150,
            ypos=200,
            node_name="Custom_Viewer",
            fps=30,
        )

        assert "frame_range 2001-2200" in viewer
        assert "fps 30" in viewer
        assert "frame 2001" in viewer
        assert "name Custom_Viewer" in viewer
        assert "xpos 150" in viewer
        assert "ypos 200" in viewer

    def test_get_sticky_note_basic(self) -> None:
        """Test basic StickyNote generation."""
        note = NukeScriptTemplates.get_sticky_note(
            label="Test Note", xpos=100, ypos=200
        )

        assert "StickyNote {" in note
        assert "inputs 0" in note
        assert "name Note" in note
        assert 'label "Test Note"' in note
        assert "note_font_size 14" in note
        assert "note_font_color 0x00aa00ff" in note
        assert "xpos 100" in note
        assert "ypos 200" in note

    def test_get_sticky_note_custom(self) -> None:
        """Test StickyNote with custom parameters."""
        note = NukeScriptTemplates.get_sticky_note(
            label="Custom Note",
            xpos=300,
            ypos=400,
            node_name="Custom_Note",
            font_size=18,
            color="0xff0000ff",
        )

        assert "name Custom_Note" in note
        assert 'label "Custom Note"' in note
        assert "note_font_size 18" in note
        assert "note_font_color 0xff0000ff" in note
        assert "xpos 300" in note
        assert "ypos 400" in note

    def test_get_noop_node_basic(self) -> None:
        """Test basic NoOp node generation."""
        noop = NukeScriptTemplates.get_noop_node(
            node_name="Test_NoOp", label="Test Label", xpos=50, ypos=75
        )

        assert "NoOp {" in noop
        assert "inputs 0" in noop
        assert "name Test_NoOp" in noop
        assert "tile_color 0xff000001" in noop
        assert 'label "Test Label"' in noop
        assert "xpos 50" in noop
        assert "ypos 75" in noop
        # Should not have onCreate when no script provided
        assert "onCreate" not in noop

    def test_get_noop_node_with_script(self) -> None:
        """Test NoOp node with Python script."""
        noop = NukeScriptTemplates.get_noop_node(
            node_name="Script_NoOp",
            label="With Script",
            xpos=100,
            ypos=150,
            tile_color="0x00ff00ff",
            oncreate_script="print('Hello from onCreate')",
        )

        assert "name Script_NoOp" in noop
        assert "tile_color 0x00ff00ff" in noop
        assert "onCreate \"print('Hello from onCreate')\"" in noop

    def test_escape_path_windows(self) -> None:
        """Test path escaping for Windows paths."""
        windows_path = "C:\\path\\to\\file.exr"
        escaped = NukeScriptTemplates.escape_path(windows_path)

        assert escaped == "C:/path/to/file.exr"

    def test_escape_path_unix(self) -> None:
        """Test path escaping for Unix paths (no change)."""
        unix_path = "/path/to/file.exr"
        escaped = NukeScriptTemplates.escape_path(unix_path)

        assert escaped == "/path/to/file.exr"

    def test_escape_path_empty(self) -> None:
        """Test path escaping with empty string."""
        escaped = NukeScriptTemplates.escape_path("")

        assert escaped == ""

    def test_format_frame_sequence_hash(self) -> None:
        """Test frame sequence formatting with #### pattern."""
        path_with_hash = "/path/to/sequence_####.exr"
        formatted = NukeScriptTemplates.format_frame_sequence(path_with_hash)

        assert formatted == "/path/to/sequence_%04d.exr"

    def test_format_frame_sequence_printf(self) -> None:
        """Test frame sequence formatting with %04d pattern (no change)."""
        path_with_printf = "/path/to/sequence_%04d.exr"
        formatted = NukeScriptTemplates.format_frame_sequence(path_with_printf)

        assert formatted == "/path/to/sequence_%04d.exr"

    def test_format_frame_sequence_windows_and_hash(self) -> None:
        """Test frame sequence formatting with Windows path and #### pattern."""
        path = "C:\\plates\\shot_####.exr"
        formatted = NukeScriptTemplates.format_frame_sequence(path)

        assert formatted == "C:/plates/shot_%04d.exr"

    def test_format_frame_sequence_empty(self) -> None:
        """Test frame sequence formatting with empty string."""
        formatted = NukeScriptTemplates.format_frame_sequence("")

        assert formatted == ""

    def test_window_layout_xml_constant(self) -> None:
        """Test that WINDOW_LAYOUT_XML constant is properly formatted."""
        xml = NukeScriptTemplates.WINDOW_LAYOUT_XML

        assert xml.startswith("define_window_layout_xml {")
        assert xml.endswith("}")
        assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
        assert '<layout version="1.0">' in xml
        assert 'activePageId="Viewer.1"' in xml
        assert 'activePageId="DAG.1"' in xml
        assert 'activePageId="Properties.1"' in xml

    def test_read_node_label_content(self) -> None:
        """Test Read node label contains colorspace and frame info."""
        read_node = NukeScriptTemplates.get_read_node(
            file_path="/test/path_%04d.exr",
            shot_name="test",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
            colorspace="logc3ei800",
            raw_flag=False,
        )

        # Check label contains colorspace reference and frame range
        assert 'label "\\[value colorspace]\\nframes: 1001-1100"' in read_node

    def test_read_node_file_type_and_settings(self) -> None:
        """Test Read node has correct file type and settings."""
        read_node = NukeScriptTemplates.get_read_node(
            file_path="/test/path_%04d.exr",
            shot_name="test",
            first_frame=1001,
            last_frame=1100,
            width=1920,
            height=1080,
            colorspace="linear",
            raw_flag=True,
        )

        assert "file_type exr" in read_node
        assert "on_error black" in read_node
        assert "reload 0" in read_node
        assert "origset true" in read_node
        assert "tile_color 0xcccccc01" in read_node
        assert "selected true" in read_node
