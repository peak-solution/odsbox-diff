"""ods_diff_hierarchy"""

from __future__ import annotations

from .collect import collect, load_collect_results, save_collect_results
from .diff import diff_dictionaries, dump_diff_as_json

__version__ = "0.1.0"

__all__ = [
    "collect",
    "load_collect_results",
    "save_collect_results",
    "diff_dictionaries",
    "dump_diff_as_json",
]
