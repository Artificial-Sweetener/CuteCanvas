#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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
"""Validate the versioned Ferrastra benchmark and conformance manifest."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "benchmarks/ferrastra_manifest.toml"
_METRICS = {
    "allocated_bytes",
    "cancellation_latency_ms",
    "latency_ms",
    "peak_resident_bytes",
    "throughput_per_second",
}
_CONTRACT_FIELDS = {
    "cancellation",
    "conformance",
    "damage",
    "demand",
    "input_products",
    "memory_budget",
    "output_product",
    "quality",
    "semantic_id",
    "semantic_version",
}


def validate_manifest(path: Path = _MANIFEST) -> list[str]:
    """Return deterministic validation errors for one benchmark manifest."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    measurement = _table(data, "measurement", errors)
    registration = _table(data, "registration", errors)
    if set(_strings(measurement, "required_metrics", errors)) != _METRICS:
        errors.append("measurement.required_metrics must contain every Stage 0 metric")
    if _integers(measurement, "percentiles", errors) != (50, 95, 99):
        errors.append("measurement.percentiles must be [50, 95, 99]")
    if (
        set(_strings(registration, "required_operation_fields", errors))
        != _CONTRACT_FIELDS
    ):
        errors.append("registration.required_operation_fields is incomplete")
    required_flags = (
        "require_reference_result",
        "require_memory_ceiling",
        "require_latency_thresholds",
        "require_adversarial_inputs",
    )
    errors.extend(
        f"registration.{key} must be true"
        for key in required_flags
        if registration.get(key) is not True
    )
    operations = registration.get("operations")
    if not isinstance(operations, list):
        errors.append("registration.operations must be an array")
    return errors


def _table(data: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    """Return one table or record a schema error."""
    value = data.get(key)
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    errors.append(f"{key} must be a table")
    return {}


def _strings(data: dict[str, Any], key: str, errors: list[str]) -> tuple[str, ...]:
    """Return one string array or record a schema error."""
    value = data.get(key)
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, str) for item in items):
            return tuple(cast(list[str], items))
    errors.append(f"{key} must be a string array")
    return ()


def _integers(data: dict[str, Any], key: str, errors: list[str]) -> tuple[int, ...]:
    """Return one integer array or record a schema error."""
    value = data.get(key)
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, int) and not isinstance(item, bool) for item in items):
            return tuple(cast(list[int], items))
    errors.append(f"{key} must be an integer array")
    return ()


def run() -> None:
    """Print benchmark schema diagnostics and fail on incomplete policy."""
    errors = validate_manifest()
    for error in errors:
        print(f"{_MANIFEST.name}: {error}")
    if errors:
        raise SystemExit(f"FAILED: Found {len(errors)} benchmark manifest errors.")
    print("SUCCESS: Ferrastra benchmark and conformance policy is complete.")


if __name__ == "__main__":
    run()
