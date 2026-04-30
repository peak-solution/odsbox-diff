import logging
import re
from typing import Any

from deepdiff import DeepDiff


def diff_dictionaries(
    result1: dict[Any, Any],
    result2: dict[Any, Any],
    custom_exclude_regex_paths: list[str],
    custom_exclude_paths: list[str],
) -> DeepDiff:
    log = logging.getLogger(__name__)
    exclude_regex_paths_str = [r"\.(Id|DateCreated|Version)'\]$"] + custom_exclude_regex_paths
    log.debug("Compile exclude_regex_paths_str %s", exclude_regex_paths_str)
    exclude_regex_paths = [re.compile(item) for item in exclude_regex_paths_str]
    exclude_paths: list[str] = [] + custom_exclude_paths
    log.info("Start DeepDiff.")
    log.debug("  exclude_regex_paths: %s", exclude_regex_paths_str)
    log.debug("  exclude_paths: %s", exclude_paths)
    diff_result = DeepDiff(
        result1,
        result2,
        exclude_paths=exclude_paths,
        exclude_regex_paths=exclude_regex_paths,
        ignore_nan_inequality=True,
    )
    log.info("Finished DeepDiff.")
    return diff_result


def dump_diff_as_json(file_path: str, diff_result: DeepDiff) -> None:
    with open(file_path, "w", encoding="utf-8") as json_file:
        json_file.write(diff_result.to_json(indent=2))
