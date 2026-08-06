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
"""Keep tutorial environment tiers aligned with published package extras."""

from __future__ import annotations

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


def validate_demo_provisioning(root: Path) -> list[str]:
    """Return errors when demo tiers request absent or unnecessary extras."""
    tier_path = (
        root / "packages" / "cutecanvas" / "examples" / "cutecanvas_demo_environment.py"
    )
    metadata_path = root / "packages" / "cutecanvas" / "pyproject.toml"
    if not tier_path.exists():
        return [f"demo provisioning source is missing: {tier_path}"]
    if not metadata_path.exists():
        return [f"CuteCanvas package metadata is missing: {metadata_path}"]
    tier_extras = _parse_tier_extras(tier_path)
    if isinstance(tier_extras, str):
        return [tier_extras]
    metadata = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
    optional_extras = set(metadata.get("project", {}).get("optional-dependencies", {}))
    return _compare_tier_extras(tier_extras, optional_extras)


def _parse_tier_extras(path: Path) -> dict[str, str | None] | str:
    """Read literal ``DEMO_TIERS`` names and extras without importing the demo."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "DEMO_TIERS"
                for target in node.targets
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "DEMO_TIERS"
            )
        ):
            value = node.value
        if value is None:
            continue
        mapping = _mapping_argument(value)
        if mapping is None:
            return "demo provisioning DEMO_TIERS is not a literal mapping"
        tiers: dict[str, str | None] = {}
        for key, value in zip(mapping.keys, mapping.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                return "demo provisioning has a non-literal tier name"
            extra = _demo_tier_extra(value)
            if extra is ...:
                return f"demo tier {key.value!r} has a non-literal extra"
            tiers[key.value] = extra
        return tiers
    return "demo provisioning has no DEMO_TIERS mapping"


def _mapping_argument(value: ast.expr) -> ast.Dict | None:
    """Return the dictionary wrapped by ``MappingProxyType`` when present."""
    if isinstance(value, ast.Call) and len(value.args) == 1:
        value = value.args[0]
    return value if isinstance(value, ast.Dict) else None


def _demo_tier_extra(value: ast.expr) -> str | None | type[...]:
    """Return one literal ``DemoTier`` extra or an invalid-value sentinel."""
    if not isinstance(value, ast.Call):
        return ...
    for keyword in value.keywords:
        if keyword.arg == "extra":
            try:
                extra = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                return ...
            return extra if extra is None or isinstance(extra, str) else ...
    return ...


def _compare_tier_extras(
    tier_extras: dict[str, str | None],
    optional_extras: set[str],
) -> list[str]:
    """Return invalid-extra and CuteCanvas ownership errors for demo tiers."""
    errors = [
        f"demo tier {tier!r} requests unknown CuteCanvas extra {extra!r}"
        for tier, extra in tier_extras.items()
        if extra is not None and extra not in optional_extras
    ]
    if tier_extras.get("cutecanvas") is not None:
        errors.append("the standard CuteCanvas demo must use the normal install")
    if "cutecanvas-sam" in tier_extras and tier_extras["cutecanvas-sam"] != "sam":
        errors.append("the SAM-enabled CuteCanvas demo must request the 'sam' extra")
    return errors
