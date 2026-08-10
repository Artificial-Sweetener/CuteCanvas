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
"""Generate package-scoped release notes from user-meaningful commits."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .products import (
    ReleaseProduct,
    StableVersion,
    format_version,
    parse_stable_version,
)

_REPOSITORY = "https://github.com/Artificial-Sweetener/CuteCanvas"
_CONVENTIONAL_SUBJECT = re.compile(
    r"^(?P<kind>feat|fix|perf|revert)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<breaking>!)?:\s+(?P<title>.+)$"
)
_SECTION_NAMES = {
    "breaking": "Breaking changes",
    "feat": "Features",
    "fix": "Fixes",
    "perf": "Performance",
    "revert": "Reverts",
}


@dataclass(frozen=True)
class ReleaseChange:
    """Describe one user-facing commit admitted to package release notes."""

    commit: str
    kind: str
    title: str
    breaking: bool


def generate_release_notes(
    root: Path,
    product: ReleaseProduct,
    version: StableVersion,
    current_tag: str,
) -> str:
    """Return Markdown notes for one independently versioned product."""
    previous = previous_release_tag(root, product, current_tag)
    lines = [f"# {product.display_name} {format_version(version)}", ""]
    if previous is None:
        return "\n".join((*lines, "Initial release.", ""))
    changes = collect_release_changes(root, product, previous)
    lines.extend(
        [
            f"Changes since `{previous}`.",
            "",
        ]
    )
    for key in ("breaking", "feat", "fix", "perf", "revert"):
        section = tuple(
            change
            for change in changes
            if (key == "breaking" and change.breaking)
            or (key != "breaking" and change.kind == key and not change.breaking)
        )
        if not section:
            continue
        lines.extend([f"## {_SECTION_NAMES[key]}", ""])
        lines.extend(
            f"- {change.title} "
            f"([`{change.commit[:7]}`]({_REPOSITORY}/commit/{change.commit}))"
            for change in section
        )
        lines.append("")
    if not changes:
        lines.extend(["No user-facing changes were classified for this release.", ""])
    lines.extend(
        [
            f"**Full comparison:** [{previous}...{current_tag}]"
            f"({_REPOSITORY}/compare/{previous}...{current_tag})",
            "",
        ]
    )
    return "\n".join(lines)


def previous_release_tag(
    root: Path,
    product: ReleaseProduct,
    current_tag: str,
) -> str | None:
    """Return the newest prior tag in the selected product's version lineage."""
    tags = _git(root, "tag", "--merged", "HEAD", "--list").splitlines()
    candidates: list[tuple[StableVersion, str]] = []
    for tag in tags:
        if tag == current_tag:
            continue
        version_text: str | None = None
        if tag.startswith(product.tag_prefix):
            version_text = tag.removeprefix(product.tag_prefix)
        elif product.legacy_tag_fallback and tag.startswith("v"):
            version_text = tag.removeprefix("v")
        if version_text is None:
            continue
        try:
            candidates.append((parse_stable_version(version_text), tag))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def collect_release_changes(
    root: Path,
    product: ReleaseProduct,
    previous_tag: str | None,
) -> tuple[ReleaseChange, ...]:
    """Return conventional user-facing commits affecting one product."""
    revision = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    records = _git(root, "log", revision, "--format=%H%x1f%s%x1f%b%x1e")
    changes: list[ReleaseChange] = []
    for record in records.split("\x1e"):
        fields = record.strip("\r\n").split("\x1f", maxsplit=2)
        if len(fields) != 3:
            continue
        commit, subject, body = fields
        match = _CONVENTIONAL_SUBJECT.fullmatch(subject.strip())
        if match is None or not _commit_affects(
            root, commit, product, match.group("scope")
        ):
            continue
        changes.append(
            ReleaseChange(
                commit=commit,
                kind=match.group("kind"),
                title=match.group("title"),
                breaking=bool(match.group("breaking")) or "BREAKING CHANGE:" in body,
            )
        )
    return tuple(changes)


def _commit_affects(
    root: Path,
    commit: str,
    product: ReleaseProduct,
    scope: str | None,
) -> bool:
    """Return whether a commit belongs in one product's public history."""
    if scope is not None and product.name in {
        item.strip().lower() for item in re.split(r"[,/]", scope)
    }:
        return True
    paths = _git(
        root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit,
    ).splitlines()
    normalized_paths = tuple(path.replace("\\", "/") for path in paths)
    for owner in product.release_paths:
        owned = owner.as_posix()
        if any(
            path == owned or path.startswith(f"{owned}/") for path in normalized_paths
        ):
            return True
    return False


def _git(root: Path, *arguments: str) -> str:
    """Return UTF-8 output from one checked, non-interactive Git query."""
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout
