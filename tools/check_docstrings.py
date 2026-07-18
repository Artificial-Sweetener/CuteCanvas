#!/usr/bin/env python3
#    QPane - High-performance PySide6 image viewer
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

"""Check for missing docstrings and enforce whitespace standards.

Scans the qpane/ and examples/ directories to ensure every module, class,
and function has a docstring. Automatically fixes whitespace and formatting
issues to match the project's contribution guidelines.
"""

import ast
import inspect
import sys
from pathlib import Path

# Directories to scan
TARGET_DIRS = ["qpane", "examples"]

# Directories to exclude
EXCLUDE_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    "venv-core",
    "venv-full",
    "venv-mask",
    ".git",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "QPane.egg-info",
    "site-packages",
    "_version.py",
}

GUIDELINES_HEADER = "\n" + "=" * 60 + "\nFIXING GUIDELINES\n" + "=" * 60

GUIDELINES_TEXT = """
CORE RULES:
- Lead with a single-sentence, present-tense summary (instruction/description, not narrative).
- Add a blank line after the summary if including additional text.
- Use Google-style sections (Args:, Returns:, Raises:, Side effects:) for non-obvious behavior.
  - Prefer one-line entries; expand only when nuance matters.
  - Only document exceptions callers must handle.
  - Use 'Side effects:' for signaling, caching, async work, or thread hops.
- Do not restate types already in annotations. Focus on intent and contracts.
- Match Qt/PySide ergonomics (concise, camelCase-aware).

WHEN TO USE SECTIONS:
- Public/host-facing APIs, lifecycle hooks, and complex helpers.
- Skip sections for simple accessors and one-line delegates.

WORKFLOW INSTRUCTION:
- Do not guess based on the function name.
- Read the implementation code fully to understand the behavior before writing the docstring.
"""

EXAMPLES_GUIDELINES_TEXT = """
EXAMPLES DIRECTORY SPECIFIC:
- Tone: Inviting and explanatory (tutorial style).
- Narrative: Read the file's header and surrounding comments to understand the narrative arc.
  Your docstring must slot seamlessly into this story, acting as a guide for the reader.
"""


class DocstringChecker(ast.NodeVisitor):
    """AST visitor that collects missing docstring errors."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.errors: list[tuple[int, str]] = []

    def visit_Module(self, node: ast.Module) -> None:
        """Check for module-level docstring."""
        # Allow empty __init__.py files to skip docstrings
        if self.filepath.name == "__init__.py" and not node.body:
            return
        if not ast.get_docstring(node):
            self.errors.append((1, "Missing module docstring"))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check for class docstring."""
        print(".", end="", flush=True)
        if not ast.get_docstring(node):
            self.errors.append(
                (node.lineno, f"Missing docstring for class '{node.name}'")
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check for function docstring."""
        self._check_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check for async function docstring."""
        self._check_func(node)

    def _check_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Common check for function/method docstrings."""
        print(".", end="", flush=True)
        # Skip checking docstrings for property setters if they don't have one
        # (often the getter has the docstring)
        is_setter = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute) and decorator.attr == "setter":
                is_setter = True
                break
        if is_setter:
            pass
        elif not ast.get_docstring(node):
            self.errors.append(
                (node.lineno, f"Missing docstring for function/method '{node.name}'")
            )
        self.generic_visit(node)


def compact_google_sections(lines: list[str]) -> list[str]:
    """Remove blank lines inside Google-style sections."""
    headers = {"Args:", "Returns:", "Raises:", "Side effects:", "Yields:"}
    in_section = False
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped in headers:
            in_section = True
            # Ensure blank line before header if not at start
            if new_lines and new_lines[-1]:
                new_lines.append("")
            new_lines.append(line)
            i += 1
            # Remove blank lines immediately after header
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        if not stripped:
            # Handle blank lines
            if in_section:
                # Look ahead
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    next_stripped = lines[j].strip()
                    if next_stripped in headers:
                        # Keep one blank line before next header
                        new_lines.append("")
                    else:
                        # Remove blank lines between items in a section
                        pass
                i = j
                continue
            else:
                # Not in section (Summary/Description) -> Keep one blank line
                new_lines.append("")
                i += 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                continue
        new_lines.append(line)
        i += 1
    return new_lines


def format_docstring(content: str, indent: str) -> str:
    """Format a docstring content into a standard block.
    Args:
        content: The raw text of the docstring (no quotes).
        indent: The indentation string to apply to the body.
    Returns:
        The formatted docstring including quotes.
    """
    # Clean indentation and whitespace
    cleaned = inspect.cleandoc(content)
    lines = cleaned.splitlines()
    # Trim trailing whitespace from each line
    lines = [line.rstrip() for line in lines]
    # Remove leading/trailing blank lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return '""" """'
    # Apply Google-style section compaction
    lines = compact_google_sections(lines)
    # If it's a one-liner, keep it simple
    if len(lines) == 1:
        return f'"""{lines[0]}"""'
    # Multi-line: Ensure summary is separated if body exists
    # Heuristic: If line 1 is not empty, insert a blank line
    if len(lines) > 1 and lines[1].strip():
        lines.insert(1, "")
    # Reconstruct
    result = [f'"""{lines[0]}']
    for line in lines[1:]:
        if line:
            result.append(f"{indent}{line}")
        else:
            result.append("")
    result.append(f'{indent}"""')
    return "\n".join(result)


def fix_file(filepath: Path) -> bool:
    """Fix docstring whitespace in a file.
    Returns:
        True if the file was modified.
    """
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError):
        return False
    # Collect all docstrings with their locations
    docstrings = []  # List of (node, docstring_node)

    class Collector(ast.NodeVisitor):
        def visit_Module(self, node):
            if ast.get_docstring(node):
                docstrings.append((node, node.body[0]))
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            if ast.get_docstring(node):
                docstrings.append((node, node.body[0]))
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            if ast.get_docstring(node):
                docstrings.append((node, node.body[0]))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if ast.get_docstring(node):
                docstrings.append((node, node.body[0]))
            self.generic_visit(node)

    Collector().visit(tree)
    if not docstrings:
        return False
    lines = content.splitlines(keepends=True)
    modified = False
    # Process in reverse order to preserve line numbers
    for parent, ds_node in sorted(docstrings, key=lambda x: x[1].lineno, reverse=True):
        # Get the indentation of the parent definition
        # (approximate by looking at the line before the docstring?)
        # Actually, we want the indentation of the docstring itself.
        start_line = ds_node.lineno - 1
        end_line = ds_node.end_lineno
        # Extract raw lines
        raw_lines = lines[start_line:end_line]
        raw_text = "".join(raw_lines)
        # Determine indentation from the first line
        first_line = raw_lines[0]
        indent_match = len(first_line) - len(first_line.lstrip())
        indent = first_line[:indent_match]
        # Get the content value
        ds_value = ds_node.value.value  # Python 3.8+ Constant
        # Format it
        new_docstring = format_docstring(ds_value, indent)
        # Add the indentation to the first line (format_docstring doesn't add it to line 0)
        # Wait, format_docstring returns the block starting with """.
        # We need to prepend the indentation to the first line.
        new_text = f"{indent}{new_docstring}\n"
        # Check if it changed (ignoring the newline at the end which we just added)
        if new_text != raw_text:
            # Replace lines
            lines[start_line:end_line] = [new_text]
            modified = True
            print(f"Fixed docstring at {filepath}:{ds_node.lineno}")
    if modified:
        filepath.write_text("".join(lines), encoding="utf-8")
        return True
    return False


def check_file(filepath: Path) -> list[tuple[int, str]]:
    """Parse and check a single file for missing docstrings."""
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except SyntaxError as e:
        return [(e.lineno or 0, f"Syntax Error: {e.msg}")]
    except UnicodeDecodeError:
        return [(0, "Unicode Decode Error")]
    except RecursionError:
        return [(0, "Recursion Error during parsing")]
    checker = DocstringChecker(filepath)
    try:
        checker.visit(tree)
    except RecursionError:
        return [(0, "Recursion Error during visiting")]
    return checker.errors


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    qpane_errors = {}
    examples_errors = {}
    total_files = 0
    print(f"Scanning directories: {', '.join(TARGET_DIRS)}...")
    for dir_name in TARGET_DIRS:
        dir_path = root / dir_name
        if not dir_path.exists():
            print(f"Warning: Directory not found: {dir_path}")
            continue
        for filepath in dir_path.rglob("*.py"):
            # Check exclusions
            parts = filepath.parts
            if any(part in EXCLUDE_DIRS for part in parts):
                continue
            if "site-packages" in parts:
                continue
            rel_path = filepath.relative_to(root)
            print(f"{rel_path} ", end="", flush=True)
            total_files += 1
            fix_file(filepath)
            errors = check_file(filepath)
            print()
            if errors:
                if "examples" in parts:
                    examples_errors[filepath] = errors
                else:
                    qpane_errors[filepath] = errors
    if qpane_errors or examples_errors:
        print(
            f"\nFound missing docstrings in {len(qpane_errors) + len(examples_errors)} files:"
        )
        if qpane_errors:
            print("\n" + "=" * 60)
            print("ISSUES IN LIBRARY CODE (qpane/)")
            print("=" * 60)
            for filepath, errors in sorted(qpane_errors.items()):
                rel_path = filepath.relative_to(root)
                print(f"\n{rel_path}:")
                for lineno, msg in sorted(errors):
                    print(f"  Line {lineno}: {msg}")
            print("\n" + "-" * 20 + " GUIDELINES FOR QPANE " + "-" * 20)
            print(GUIDELINES_TEXT.strip())
            print()
        if examples_errors:
            print("\n" + "=" * 60)
            print("ISSUES IN EXAMPLES (examples/)")
            print("=" * 60)
            for filepath, errors in sorted(examples_errors.items()):
                rel_path = filepath.relative_to(root)
                print(f"\n{rel_path}:")
                for lineno, msg in sorted(errors):
                    print(f"  Line {lineno}: {msg}")
            print("\n" + "-" * 20 + " GUIDELINES FOR EXAMPLES " + "-" * 20)
            print(GUIDELINES_TEXT.strip())
            print(EXAMPLES_GUIDELINES_TEXT.strip())
            print()
        print(
            f"\nFAILED: Found issues in {len(qpane_errors) + len(examples_errors)} out of {total_files} files."
        )
        sys.exit(1)
    else:
        print(f"\nSUCCESS: Checked {total_files} files. No missing docstrings found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
