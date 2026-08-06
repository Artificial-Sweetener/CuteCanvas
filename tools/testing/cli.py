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

"""Command-line interface for policy-owned test discovery and gates."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence

from tools.testing.changes import staged_paths, worktree_paths
from tools.testing.execution import run_selection
from tools.testing.inventory import validate_inventory
from tools.testing.model import TestPolicy, TestSelection
from tools.testing.policy import load_policies, repository_root
from tools.testing.selection import SelectionError, select_changed_paths


def main(arguments: Sequence[str] | None = None) -> int:
    """Run test discovery, explanation, focused proof, or commit gates."""
    parser = _parser()
    options = parser.parse_args(arguments)
    root = repository_root()
    try:
        policies = load_policies(root)
        if options.command == "list":
            _list_groups(policies, options.product)
            return 0
        if options.command == "validate":
            validate_inventory(root, policies)
            print("Test inventory and policy ownership are valid.")
            return 0
        if options.command == "explain":
            selection = select_changed_paths((options.path,), policies)
            _print_selection(selection, detailed_reasons=True)
            return 0
        if options.command == "run":
            validate_inventory(root, policies)
            selection = _explicit_selection(options, policies)
            _print_selection(selection)
            return run_selection(root, selection, policies)
        if options.command == "changed":
            validate_inventory(root, policies)
            selection = select_changed_paths(worktree_paths(root), policies)
            _print_selection(selection)
            return run_selection(root, selection, policies)
        if options.command == "staged":
            validate_inventory(root, policies)
            paths = staged_paths(root)
            if not paths:
                parser.error("staged gate requires at least one staged path")
            selection = select_changed_paths(paths, policies, commit=options.commit)
            _print_selection(selection)
            return run_selection(
                root,
                selection,
                policies,
                commit=options.commit,
            )
    except (KeyError, SelectionError, ValueError) as error:
        print(f"test selection failed: {error}", file=sys.stderr)
        return 2
    parser.error("a command is required")
    return 2


def _parser() -> argparse.ArgumentParser:
    """Build the supported user-facing command grammar."""
    parser = argparse.ArgumentParser(
        description="Run tests by product ownership instead of private node IDs."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("list", help="list supported test groups")
    list_parser.add_argument("product", nargs="?")
    explain = commands.add_parser("explain", help="explain proof for one path")
    explain.add_argument("path")
    run = commands.add_parser("run", help="run an owned product, area, or proof")
    run.add_argument("product")
    run.add_argument("area", nargs="?")
    run.add_argument("proof", nargs="?")
    commands.add_parser("changed", help="test staged, unstaged, and untracked work")
    staged = commands.add_parser("staged", help="test the staged diff")
    staged.add_argument(
        "--commit",
        action="store_true",
        help="run complete affected-product, packaging, and native commit gates",
    )
    commands.add_parser("validate", help="validate test policy and inventory")
    return parser


def _list_groups(
    policies: dict[str, TestPolicy],
    requested_product: str | None,
) -> None:
    """Print discoverable product, area, and proof targets."""
    active = policies
    if requested_product is not None:
        if requested_product not in active:
            raise KeyError(f"unknown product {requested_product!r}")
        active = {requested_product: active[requested_product]}
    for product, policy in active.items():
        print(product)
        for area in policy.areas:
            print(f"  {area.name}: {', '.join(area.proofs)}")


def _explicit_selection(
    options: argparse.Namespace,
    policies: dict[str, TestPolicy],
) -> TestSelection:
    """Resolve a supported product/area/proof target from policy facts."""
    if options.product not in policies:
        raise KeyError(f"unknown product {options.product!r}")
    policy = policies[options.product]
    groups = policy.groups()
    if options.area is not None:
        policy.area(options.area)
        groups = frozenset(group for group in groups if group.area == options.area)
    if options.proof is not None:
        groups = frozenset(group for group in groups if group.proof == options.proof)
        if not groups:
            raise KeyError(
                f"{options.product}.{options.area} has no proof "
                f"{options.proof!r}; use 'list' for supported targets"
            )
    return TestSelection(groups=groups, reasons=())


def _print_selection(
    selection: TestSelection,
    *,
    detailed_reasons: bool = False,
) -> None:
    """Print actionable, deterministic selection diagnostics."""
    if not selection.groups:
        if selection.validate_artifacts:
            print("Selected focused artifact validation; no runtime tests required.")
        else:
            print("No tests selected because no changed paths were supplied.")
        return
    print("Selected test groups:")
    for group in sorted(selection.groups):
        print(f"  {group.product}/{group.area}/{group.proof}")
    if selection.reasons and (detailed_reasons or len(selection.reasons) <= 24):
        print("Selection reasons:")
        for reason in selection.reasons:
            print(
                f"  {reason.changed_path} -> "
                f"{reason.group.product}/{reason.group.area}/{reason.group.proof}: "
                f"{reason.rule}"
            )
    elif selection.reasons:
        changed_paths = {reason.changed_path for reason in selection.reasons}
        print(
            f"Selection summary: {len(changed_paths)} changed paths produced "
            f"{len(selection.reasons)} proof requirements."
        )
        for rule, count in sorted(
            Counter(reason.rule for reason in selection.reasons).items()
        ):
            print(f"  {rule}: {count}")
        print("Representative reason for each selected group:")
        for group in sorted(selection.groups):
            group_reasons = tuple(
                reason for reason in selection.reasons if reason.group == group
            )
            reason = group_reasons[0]
            additional = len(group_reasons) - 1
            suffix = f" (+{additional} additional edges)" if additional else ""
            print(
                f"  {group.product}/{group.area}/{group.proof} <- "
                f"{reason.changed_path}: {reason.rule}{suffix}"
            )
