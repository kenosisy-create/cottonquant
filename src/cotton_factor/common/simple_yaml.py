"""Small YAML reader for repository config files.

This intentionally supports only the subset used by local product configs:
top-level key-value pairs, inline scalar lists, and indented scalar lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cotton_factor.common.exceptions import ConfigError


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Load a narrow, deterministic YAML subset from a local config file."""
    result: dict[str, Any] = {}
    current_list_key: str | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if current_list_key is None:
                raise ConfigError(f"list item without key at {path}:{line_number}")
            result[current_list_key].append(_parse_scalar(stripped[2:].strip()))
            continue

        if line.startswith((" ", "\t")):
            raise ConfigError(f"unsupported indentation at {path}:{line_number}")

        current_list_key = None
        if ":" not in line:
            raise ConfigError(f"expected key-value pair at {path}:{line_number}")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise ConfigError(f"empty key at {path}:{line_number}")
        if not value:
            result[key] = []
            current_list_key = key
        else:
            result[key] = _parse_value(value)

    return result


def _parse_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    return _parse_scalar(value)


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
