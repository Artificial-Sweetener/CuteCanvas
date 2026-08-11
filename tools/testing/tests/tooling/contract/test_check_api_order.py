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
"""Contract tests for public-facade implementation discovery."""

from pathlib import Path

from tools.check_api_order import FacadeContract, implemented_methods


def _write(path: Path, source: str) -> Path:
    """Write one isolated facade source fixture."""
    path.write_text(source, encoding="utf-8")
    return path


def test_focused_facade_mixin_inheritance_contributes_public_methods(
    tmp_path: Path,
) -> None:
    """Methods owned by a focused base mixin satisfy the facade contract."""
    facade = _write(
        tmp_path / "facade.py",
        "class SessionApiMixin:\n"
        "    def activeSession(self):\n"
        "        return None\n\n"
        "class InteractionApiMixin(SessionApiMixin):\n"
        "    def activateTool(self):\n"
        "        return None\n",
    )
    contract = FacadeContract(
        name="Example",
        stub=tmp_path / "unused.pyi",
        sources=(facade,),
        implementation_classes=frozenset({"InteractionApiMixin"}),
    )

    assert implemented_methods(contract) == {"activeSession", "activateTool"}


def test_unrelated_source_class_does_not_satisfy_facade_contract(
    tmp_path: Path,
) -> None:
    """A method outside the selected facade hierarchy remains unimplemented."""
    facade = _write(
        tmp_path / "facade.py",
        "class InteractionApiMixin:\n"
        "    def activateTool(self):\n"
        "        return None\n\n"
        "class UnrelatedApiMixin:\n"
        "    def activeSession(self):\n"
        "        return None\n",
    )
    contract = FacadeContract(
        name="Example",
        stub=tmp_path / "unused.pyi",
        sources=(facade,),
        implementation_classes=frozenset({"InteractionApiMixin"}),
    )

    assert implemented_methods(contract) == {"activateTool"}
