"""DCC UI package for matchmove workflow.

Contains widgets for launching and managing DCC applications with integrated
file selection and configuration.
"""

from .dcc_accordion import DCCAccordion
from .dcc_config import DEFAULT_DCC_CONFIGS, DCCConfig
from .dcc_file_table import DCCFileTable
from .dcc_section_base import BaseDCCSection
from .dcc_section_file import FileDCCSection
from .dcc_section_rv import DCCSection, RVSection, create_dcc_section
from .dcc_sequence_table import DCCSequenceTable
from .scene_file import FILE_TYPE_COLORS, FileType, ImageSequence, SceneFile


__all__ = [
    "DEFAULT_DCC_CONFIGS",
    "FILE_TYPE_COLORS",
    "BaseDCCSection",
    "DCCAccordion",
    "DCCConfig",
    "DCCFileTable",
    "DCCSection",
    "DCCSequenceTable",
    "FileDCCSection",
    "FileType",
    "ImageSequence",
    "RVSection",
    "SceneFile",
    "create_dcc_section",
]
