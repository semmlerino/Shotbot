"""DCC UI package for matchmove workflow.

Contains widgets for launching and managing DCC applications with integrated
file selection and configuration.
"""

from .dcc_accordion import DCCAccordion
from .dcc_file_table import DCCFileTable
from .dcc_section import DEFAULT_DCC_CONFIGS, DCCConfig, DCCSection
from .dcc_sequence_table import DCCSequenceTable
from .scene_file import FILE_TYPE_COLORS, FileType, ImageSequence, SceneFile


__all__ = [
    "DEFAULT_DCC_CONFIGS",
    "FILE_TYPE_COLORS",
    "DCCAccordion",
    "DCCConfig",
    "DCCFileTable",
    "DCCSection",
    "DCCSequenceTable",
    "FileType",
    "ImageSequence",
    "SceneFile",
]
