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
_OPERATION_FIELDS = _CONTRACT_FIELDS | {
    "adversarial_inputs",
    "benchmark_cases",
    "cancellation_latency_ms",
    "controlled_case",
    "latency_thresholds_ms",
    "memory_ceiling_bytes",
    "reference_result",
    "thread_budget",
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
    else:
        for index, operation in enumerate(cast(list[object], operations)):
            errors.extend(_operation_errors(operation, index))
    return errors


def _operation_errors(operation: object, index: int) -> list[str]:
    """Return completeness errors for one registered operation contract."""
    prefix = f"registration.operations[{index}]"
    if not isinstance(operation, dict):
        return [f"{prefix} must be a table"]
    record = cast(dict[str, Any], operation)
    errors = [
        f"{prefix} is missing required field {key}"
        for key in sorted(_OPERATION_FIELDS - set(record))
    ]
    text_fields = (
        "semantic_id",
        "output_product",
        "demand",
        "damage",
        "memory_budget",
        "cancellation",
        "quality",
        "conformance",
        "reference_result",
    )
    errors.extend(
        f"{prefix}.{key} must be a nonempty string"
        for key in text_fields
        if not isinstance(record.get(key), str) or not cast(str, record[key]).strip()
    )
    for key in ("input_products", "benchmark_cases", "adversarial_inputs"):
        value = record.get(key)
        items = cast(list[object], value) if isinstance(value, list) else []
        if not items or not all(isinstance(item, str) and item for item in items):
            errors.append(f"{prefix}.{key} must be a nonempty string array")
    for key in ("semantic_version", "memory_ceiling_bytes", "thread_budget"):
        value = record.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"{prefix}.{key} must be a positive integer")
    cancellation_latency = record.get("cancellation_latency_ms")
    if (
        not isinstance(cancellation_latency, (int, float))
        or isinstance(cancellation_latency, bool)
        or cancellation_latency <= 0
    ):
        errors.append(f"{prefix}.cancellation_latency_ms must be positive")
    thresholds = record.get("latency_thresholds_ms")
    if not isinstance(thresholds, dict):
        errors.append(f"{prefix}.latency_thresholds_ms must be a table")
    else:
        threshold_values = cast(dict[str, object], thresholds)
        if set(threshold_values) != {"p50", "p95", "p99"}:
            errors.append(
                f"{prefix}.latency_thresholds_ms must contain p50, p95, and p99"
            )
        elif not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
            for value in threshold_values.values()
        ):
            errors.append(f"{prefix}.latency_thresholds_ms values must be positive")
    errors.extend(_controlled_case_errors(record.get("controlled_case"), prefix))
    return errors


def _controlled_case_errors(value: object, prefix: str) -> list[str]:
    """Return schema errors for one executable controlled benchmark case."""
    case_prefix = f"{prefix}.controlled_case"
    if not isinstance(value, dict):
        return [f"{case_prefix} must be a table"]
    case = cast(dict[str, object], value)
    expected = {
        "destination_height",
        "destination_width",
        "edge_mode",
        "id",
        "memory_budget_bytes",
        "scratch_budget_bytes",
        "source_height",
        "source_width",
        "working_space",
    }
    errors = (
        [f"{case_prefix} must contain exactly {sorted(expected)}"]
        if set(case) != expected
        else []
    )
    errors.extend(
        f"{case_prefix}.{key} must be a nonempty string"
        for key in ("id", "edge_mode", "working_space")
        if not isinstance(case.get(key), str) or not cast(str, case[key]).strip()
    )
    for key in (
        "source_width",
        "source_height",
        "destination_width",
        "destination_height",
        "memory_budget_bytes",
        "scratch_budget_bytes",
    ):
        item = case.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            errors.append(f"{case_prefix}.{key} must be a positive integer")
    if case.get("edge_mode") not in {"clamp", "reflect", "transparent", "wrap"}:
        errors.append(f"{case_prefix}.edge_mode is unsupported")
    if case.get("working_space") not in {"srgb_encoded", "srgb_linear"}:
        errors.append(f"{case_prefix}.working_space is unsupported")
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
