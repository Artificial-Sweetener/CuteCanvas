#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Own validated writes to GitHub Actions runner command files."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

_OUTPUT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class GitHubOutputError(RuntimeError):
    """Report an invalid GitHub Actions output-file boundary."""


def append_github_outputs(
    values: Mapping[str, str],
    *,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Append single-line values to the runner-owned GitHub output file."""
    process_environment = os.environ if environment is None else environment
    output_value = process_environment.get("GITHUB_OUTPUT", "").strip()
    if not output_value:
        return
    runner_temp_value = process_environment.get("RUNNER_TEMP", "").strip()
    if not runner_temp_value:
        raise GitHubOutputError("RUNNER_TEMP is required when GITHUB_OUTPUT is set")
    try:
        # lgtm[py/path-injection]
        output_path = Path(output_value).resolve()
        # lgtm[py/path-injection]
        runner_temp = Path(runner_temp_value).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise GitHubOutputError("GitHub runner output paths are invalid") from error
    if not output_path.is_relative_to(runner_temp):
        raise GitHubOutputError("GITHUB_OUTPUT is outside RUNNER_TEMP")

    lines: list[str] = []
    for name, value in values.items():
        if _OUTPUT_NAME.fullmatch(name) is None:
            raise GitHubOutputError(f"invalid GitHub output name {name!r}")
        if "\n" in value or "\r" in value:
            raise GitHubOutputError(f"GitHub output {name!r} contains line breaks")
        lines.append(f"{name}={value}\n")

    # The resolved command file is constrained to the runner-owned temp directory.
    # lgtm[py/path-injection]
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        output.writelines(lines)
