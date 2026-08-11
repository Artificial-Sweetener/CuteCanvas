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
"""Protect automatic independent product releases from the main branch."""

from __future__ import annotations

from tools.testing.policy import repository_root


def test_main_push_versions_the_complete_waterfall_before_publication() -> None:
    """Version every downstream product before publishing the first artifact."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    assert "branches: [main]" in workflow
    assert "uses: ./.github/workflows/verify.yml" in workflow

    ferrastra = workflow.index("  version-ferrastra:")
    qpane = workflow.index("  version-qpane:")
    cutecanvas = workflow.index("  version-cutecanvas:")
    publish_ferrastra = workflow.index("  publish-ferrastra:")
    publish_qpane = workflow.index("  publish-qpane:")
    publish_cutecanvas = workflow.index("  publish-cutecanvas:")
    assert ferrastra < qpane < cutecanvas < publish_ferrastra
    assert publish_ferrastra < publish_qpane < publish_cutecanvas
    assert workflow.count("uses: ./.github/workflows/version-product.yml") == 3
    assert workflow.count("uses: ./.github/workflows/publish.yml") == 3
    assert 'legacy_anchor: "v2.1.1"' in workflow
    assert 'first_bump: "minor"' in workflow
    assert workflow.count('first_bump: "major"') == 2


def test_release_waits_for_ferrastras_explicit_initial_publication() -> None:
    """Keep the native package private until its first release is admitted."""
    release = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    ferrastra = release[
        release.index("  version-ferrastra:") : release.index("  version-qpane:")
    ]
    qpane = release[
        release.index("  version-qpane:") : release.index("  version-cutecanvas:")
    ]
    cutecanvas = release[
        release.index("  version-cutecanvas:") : release.index("  publish-ferrastra:")
    ]
    version = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )

    assert "release_initial: false" in ferrastra
    assert "release_initial: true" in qpane
    assert "release_initial: true" in cutecanvas
    assert "release_initial:" in version
    assert "if: steps.lineage.outputs.enabled == 'true'" in version


def test_upstream_releases_force_downstream_patch_waterfalls() -> None:
    """Cascade Ferrastra through QPane and every QPane release through CuteCanvas."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    qpane = workflow[workflow.index("  version-qpane:") :]
    cutecanvas = workflow[workflow.index("  version-cutecanvas:") :]
    assert "cascade_patch:" in qpane
    assert "needs.version-ferrastra.outputs.released == 'true'" in qpane
    assert "cascade_patch:" in cutecanvas
    assert "needs.version-qpane.outputs.released == 'true'" in cutecanvas


def test_waterfall_versions_only_the_verified_release_lineage() -> None:
    """Pass each release commit to the next product instead of rereading moving main."""
    workflow = (repository_root() / ".github/workflows/release.yml").read_text("utf-8")
    assert "expected_head: ${{ github.sha }}" in workflow
    assert "expected_head: ${{ needs.version-ferrastra.outputs.head_sha }}" in workflow
    assert "expected_head: ${{ needs.version-qpane.outputs.head_sha }}" in workflow


def test_version_workflow_uses_python_semantic_release_to_push_product_tags() -> None:
    """Keep semantic version calculation, release commits, and tags in PSR."""
    workflow = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )
    assert 'PYTHON_SEMANTIC_RELEASE_VERSION: "10.6.1"' in workflow
    assert "working-directory: packages/${{ inputs.product }}" in workflow
    assert "python -m semantic_release -v version" in workflow
    assert "--no-vcs-release" in workflow
    assert 'remote_tags="$(git ls-remote --tags origin' in workflow
    assert "released=" in workflow
    assert "release_tag=" in workflow
    assert "EXPECTED_HEAD" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"' in workflow
    assert "head_sha=" in workflow


def test_cascade_patch_never_downgrades_a_larger_product_release() -> None:
    """Force a patch only when semantic-release finds no direct product release."""
    workflow = (repository_root() / ".github/workflows/version-product.yml").read_text(
        "utf-8"
    )
    assert "cascade_patch:" in workflow
    assert "DIRECT_VERSION" in workflow
    assert "LAST_RELEASED_VERSION" in workflow
    assert 'if [ "$DIRECT_VERSION" = "$LAST_RELEASED_VERSION" ]' in workflow
    assert 'arguments+=("--patch")' in workflow


def test_release_verification_installs_the_exact_workspace_python_stack() -> None:
    """Prove CuteCanvas against the QPane wheel from the release source tree."""
    workflow = (repository_root() / ".github/workflows/verify.yml").read_text("utf-8")
    wheel_job = workflow.index("  python-wheels:")
    gate = workflow.index("  gate:")
    assert wheel_job < gate
    assert "python tools/verify_python_wheels.py" in workflow[wheel_job:gate]
    assert "- python-wheels" in workflow[gate:]
    assert "PYTHON_WHEELS_RESULT" in workflow[gate:]


def test_publish_workflow_validates_before_trusted_publication() -> None:
    """Require tag, index, artifact, and Markdown proof before PyPI upload."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    admission = workflow.index("python tools/check_python_release.py")
    build = workflow.index(
        'python -m build "packages/${{ needs.select.outputs.package }}"'
    )
    artifact = workflow.index("python tools/verify_python_release_artifacts.py")
    publish = workflow.index("pypa/gh-action-pypi-publish@release/v1")
    assert admission < build < artifact < publish
    assert '"readme-renderer[md]==${{ env.README_RENDERER_VERSION }}"' in workflow
    assert "python -m twine check --strict" in workflow
    assert "skip-existing: false" in workflow


def test_publish_workflow_is_called_directly_after_automated_tagging() -> None:
    """Publish PSR tags without depending on suppressed GITHUB_TOKEN events."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "release_tag:" in workflow
    assert "RELEASE_TAG: ${{ inputs.release_tag || github.ref_name }}" in workflow
    assert "if: inputs.verified != true" in workflow
    assert "ref: ${{ env.RELEASE_TAG }}" in workflow
    assert "tags:" in workflow


def test_publish_workflow_creates_package_scoped_release_notes_after_pypi() -> None:
    """Create one product release only after its immutable upload succeeds."""
    workflow = (repository_root() / ".github/workflows/publish.yml").read_text("utf-8")
    release_job = workflow.index("  release-product:")
    assert workflow.index("      - publish", release_job) > release_job
    assert "python tools/generate_release_notes.py" in workflow[release_job:]
    assert 'gh release create "$RELEASE_TAG" --verify-tag' in workflow
    assert "needs.select.outputs.package != 'ferrastra'" not in workflow[release_job:]
