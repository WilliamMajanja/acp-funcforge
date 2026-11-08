"""ACP FuncForge: functional decomposition and software building via local OpenCode ACP servers."""

__all__ = [
    "ACPClient",
    "FunctionalDecomposer",
    "SoftwareBuilder",
    "read_text_file",
    "write_text_file",
    "scan_code_files",
    "format_code_context",
]
__version__ = "0.1.0"

from .acp_client import ACPClient
from .builder import SoftwareBuilder
from .decomposer import FunctionalDecomposer
from .filesystem import format_code_context, read_text_file, scan_code_files, write_text_file
