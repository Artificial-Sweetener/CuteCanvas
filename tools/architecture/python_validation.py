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
"""Validate Python product dependencies and protected adapter structure."""

from __future__ import annotations

import ast
import fnmatch
from collections.abc import Iterable
from pathlib import Path

from .model import (
    ArchitecturePolicy,
    Diagnostic,
    PythonDependencyPolicy,
    PythonProductPolicy,
    PythonProtectedRootPolicy,
)

_DYNAMIC_IMPORTS = {"__import__", "importlib.import_module"}
_GLOBAL_RESOURCE_CALLS = {
    "ProcessPoolExecutor",
    "QThreadPool.globalInstance",
    "ThreadPoolExecutor",
    "functools.cache",
    "functools.lru_cache",
}


def validate_python(root: Path, policy: ArchitecturePolicy) -> list[Diagnostic]:
    """Return Python dependency, layer, and structural diagnostics."""
    parsed = _parse_product_sources(root, policy.python_products)
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(_validate_product_dependencies(root, parsed, policy))
    for protected in policy.python_protected_roots:
        diagnostics.extend(_validate_protected_root(root, protected, policy))
    return diagnostics


def _parse_product_sources(
    root: Path,
    products: tuple[PythonProductPolicy, ...],
) -> dict[Path, tuple[PythonProductPolicy, str, ast.Module]]:
    """Parse every Python product source once."""
    parsed: dict[Path, tuple[PythonProductPolicy, str, ast.Module]] = {}
    for product in products:
        source_root = root / product.root
        if not source_root.is_dir():
            continue
        for path in _python_files(source_root):
            relative = path.relative_to(source_root)
            module = _module_name(product.name, relative)
            parsed[path] = (
                product,
                module,
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            )
    return parsed


def _validate_product_dependencies(
    root: Path,
    parsed: dict[Path, tuple[PythonProductPolicy, str, ast.Module]],
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate every import between independently owned Python products."""
    diagnostics: list[Diagnostic] = []
    product_names = {product.name for product in policy.python_products}
    dependencies = {
        (dependency.source, dependency.target): dependency
        for dependency in policy.python_dependencies
    }
    for path, (product, importer, tree) in parsed.items():
        relative_path = path.relative_to(root).as_posix()
        for imported, line in _imports(tree, importer):
            target = imported.partition(".")[0]
            if target not in product_names or target == product.name:
                continue
            dependency = dependencies.get((product.name, target))
            if dependency is None:
                diagnostics.append(
                    Diagnostic(
                        "PY001",
                        relative_path,
                        f"{product.name} may not depend on {target}",
                        line,
                    )
                )
                continue
            diagnostics.extend(
                _validate_dependency_use(relative_path, imported, line, dependency)
            )
        diagnostics.extend(
            _validate_layer_imports(relative_path, importer, tree, policy)
        )
    return diagnostics


def _validate_dependency_use(
    path: str,
    imported: str,
    line: int,
    dependency: PythonDependencyPolicy,
) -> list[Diagnostic]:
    """Validate the path and public module constraints of one dependency use."""
    diagnostics: list[Diagnostic] = []
    if not any(
        fnmatch.fnmatchcase(path, pattern) for pattern in dependency.allowed_paths
    ):
        diagnostics.append(
            Diagnostic(
                "PY002",
                path,
                f"{dependency.target} imports are restricted to its declared adapter",
                line,
            )
        )
    if not any(
        _module_matches(imported, pattern) for pattern in dependency.allowed_modules
    ):
        diagnostics.append(
            Diagnostic(
                "PY003",
                path,
                f"{imported} bypasses the supported {dependency.target} facade or SDK",
                line,
            )
        )
    return diagnostics


def _validate_layer_imports(
    path: str,
    importer: str,
    tree: ast.Module,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate internal dependency directions for declared Python layers."""
    diagnostics: list[Diagnostic] = []
    for layer in policy.python_layers:
        if not _is_module_or_child(importer, layer.module_prefix):
            continue
        product = layer.module_prefix.partition(".")[0]
        for imported, line in _imports(tree, importer):
            if imported.partition(".")[0] != product or imported == product:
                continue
            if any(
                _is_module_or_child(imported, allowed)
                for allowed in layer.allowed_internal
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    "PY004",
                    path,
                    f"layer {layer.name} may not import internal module {imported}",
                    line,
                )
            )
    return diagnostics


def _validate_protected_root(
    root: Path,
    protected: PythonProtectedRootPolicy,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate strict rules within one Ferrastra or package-adapter root."""
    source_root = root / protected.path
    if not source_root.exists():
        return []
    diagnostics: list[Diagnostic] = []
    module_trees: dict[str, tuple[Path, ast.Module]] = {}
    for path in _python_files(source_root):
        relative = path.relative_to(source_root)
        module = _module_name(protected.product, relative)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_trees[module] = (path, tree)
        diagnostics.extend(
            _validate_protected_file(root, path, tree, protected, policy)
        )
    if protected.detect_cycles:
        diagnostics.extend(_cycle_diagnostics(root, module_trees))
    return diagnostics


def _validate_protected_file(
    root: Path,
    path: Path,
    tree: ast.Module,
    protected: PythonProtectedRootPolicy,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Validate one protected Python source or stub."""
    relative_path = path.relative_to(root).as_posix()
    diagnostics = _protected_name_diagnostics(root, path, policy)
    module = _module_name(protected.product, path.relative_to(root / protected.path))
    if (
        path.suffix == ".py"
        and protected.require_responsibility
        and not ast.get_docstring(tree)
    ):
        diagnostics.append(
            Diagnostic(
                "PY005",
                relative_path,
                "production module has no responsibility docstring",
            )
        )
    for imported, line in _imports(tree, module):
        if any(
            _is_module_or_child(imported, name) for name in protected.forbidden_imports
        ):
            diagnostics.append(
                Diagnostic(
                    "PY006", relative_path, f"protected source imports {imported}", line
                )
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) in _DYNAMIC_IMPORTS:
            diagnostics.append(
                Diagnostic(
                    "PY007",
                    relative_path,
                    "dynamic imports require an explicitly owned loader module",
                    node.lineno,
                )
            )
    diagnostics.extend(_global_resource_diagnostics(relative_path, tree))
    return diagnostics


def _protected_name_diagnostics(
    root: Path,
    path: Path,
    policy: ArchitecturePolicy,
) -> list[Diagnostic]:
    """Reject generic ownership names within explicitly protected roots."""
    relative_path = path.relative_to(root).as_posix()
    diagnostics: list[Diagnostic] = []
    protected_parts = {part.lower() for part in path.with_suffix("").parts}
    forbidden = protected_parts & policy.structure.forbidden_names
    if forbidden:
        diagnostics.append(
            Diagnostic(
                "STRUCT001",
                relative_path,
                f"generic ownership name is forbidden: {min(forbidden)}",
            )
        )
    return diagnostics


def _global_resource_diagnostics(path: str, tree: ast.Module) -> list[Diagnostic]:
    """Reject hidden module-level schedulers and unbounded caches."""
    diagnostics: list[Diagnostic] = []
    for statement in tree.body:
        candidates: Iterable[ast.AST]
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr)):
            candidates = ast.walk(statement)
        elif isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            candidates = statement.decorator_list
        else:
            continue
        for node in candidates:
            if not isinstance(node, ast.Call):
                continue
            call = _call_name(node.func)
            if call in _GLOBAL_RESOURCE_CALLS or call.rpartition(".")[2] in {
                "ThreadPoolExecutor",
                "ProcessPoolExecutor",
            }:
                diagnostics.append(
                    Diagnostic(
                        "PY008",
                        path,
                        f"module-level global resource is forbidden: {call}",
                        node.lineno,
                    )
                )
    return diagnostics


def _cycle_diagnostics(
    root: Path,
    modules: dict[str, tuple[Path, ast.Module]],
) -> list[Diagnostic]:
    """Return one deterministic diagnostic for every internal import cycle."""
    graph = {
        module: {
            imported
            for imported, _line in _imports(tree, module)
            if imported in modules
        }
        for module, (_path, tree) in modules.items()
    }
    diagnostics: list[Diagnostic] = []
    for cycle in _find_cycles(graph):
        first = cycle[0]
        path = modules[first][0].relative_to(root).as_posix()
        diagnostics.append(
            Diagnostic(
                "PY009", path, f"internal import cycle: {' -> '.join((*cycle, first))}"
            )
        )
    return diagnostics


def _find_cycles(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    """Return canonical simple cycles from a directed graph."""
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str, stack: tuple[str, ...]) -> None:
        """Walk one dependency path and record its canonical simple cycles."""
        if node in stack:
            cycle = stack[stack.index(node) :]
            rotations = tuple(
                cycle[index:] + cycle[:index] for index in range(len(cycle))
            )
            cycles.add(min(rotations))
            return
        for target in sorted(graph.get(node, set())):
            visit(target, (*stack, node))

    for module in sorted(graph):
        visit(module, ())
    return tuple(sorted(cycles))


def _imports(tree: ast.Module, importer: str) -> tuple[tuple[str, int], ...]:
    """Return normalized imports and source lines from one syntax tree."""
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from_import(importer, node.module, node.level)
            if module:
                imports.append((module, node.lineno))
    return tuple(imports)


def _resolve_from_import(importer: str, module: str | None, level: int) -> str:
    """Resolve one absolute or relative from-import to a module name."""
    if level == 0:
        return module or ""
    package_parts = importer.split(".")
    if package_parts[-1] != "__init__" and len(package_parts) > 1:
        package_parts.pop()
    remove = max(level - 1, 0)
    if remove:
        package_parts = package_parts[:-remove]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(package_parts)


def _module_name(product: str, relative: Path) -> str:
    """Return an import name for one source-root-relative path."""
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join((product, *parts)) if parts else product


def _python_files(root: Path) -> tuple[Path, ...]:
    """Return deterministic Python implementation and stub files."""
    return tuple(sorted((*root.rglob("*.py"), *root.rglob("*.pyi"))))


def _module_matches(module: str, pattern: str) -> bool:
    """Return whether a module matches an exact or glob policy value."""
    return fnmatch.fnmatchcase(module, pattern) or module == pattern


def _is_module_or_child(module: str, prefix: str) -> bool:
    """Return whether a module is a prefix or descendant match."""
    return module == prefix or module.startswith(f"{prefix}.")


def _call_name(node: ast.expr) -> str:
    """Return a dotted name for a direct call expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    return ""
