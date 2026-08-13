#    Ferrastra - CPU-first native graphics product engine
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

"""Verify Ferrastra's authoritative typed public Python surface."""

from __future__ import annotations

import ferrastra
from ferrastra_test_support.contracts import declared_names
from ferrastra_test_support.paths import package_root


def test_typed_contract_matches_runtime_exports() -> None:
    """Keep the authoritative Python contract aligned with the runtime facade."""
    contract = package_root() / "src/ferrastra/ferrastra.pyi"

    assert declared_names(contract) == set(ferrastra.__all__)


def test_public_surface_exposes_one_coherent_graph_workflow() -> None:
    """Expose typed construction and evaluation handles without private assembly types."""
    assert ferrastra.__all__ == [
        "BufferError",
        "CancellationToken",
        "CompiledGraph",
        "CoverageResult",
        "Engine",
        "EvaluationBudget",
        "EvaluationError",
        "EvaluationRequirements",
        "FerrastraError",
        "Graph",
        "GraphBuilder",
        "GraphError",
        "RasterReconstructionSpace",
        "RasterResult",
        "Region",
        "__version__",
    ]


def test_reconstruction_space_names_both_supported_srgb_contracts() -> None:
    """Expose the two sRGB reconstruction semantics as one typed contract."""
    assert ferrastra.RasterReconstructionSpace.SRGB_ENCODED == "srgb_encoded"
    assert ferrastra.RasterReconstructionSpace.SRGB_LINEAR == "srgb_linear"
