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
"""Validate built Python release artifacts at their public metadata boundary."""

from __future__ import annotations

import re
import tarfile
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import Parser
from pathlib import Path, PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from .candidate import read_product_requirements
from .products import ReleaseProduct

_REPOSITORY = "https://github.com/Artificial-Sweetener/CuteCanvas"
_RELATIVE_MARKDOWN_LINK = re.compile(r"\]\((?!https?://|mailto:|#)[^)]+\)")
_RELATIVE_HTML_SOURCE = re.compile(r"(?:src|href)=[\"'](?!https?://|mailto:|#)")
_WHEEL_PLATFORM_PATTERNS = {
    "linux-x64": re.compile(r"-(?:manylinux|musllinux)_[^.]*_x86_64\.whl$"),
    "windows-x64": re.compile(r"-win_amd64\.whl$"),
    "macos-arm64": re.compile(r"-macosx_[^.]*_arm64\.whl$"),
}


@dataclass(frozen=True)
class ArtifactMetadata:
    """Expose the release metadata required for package admission."""

    name: str
    version: str
    description_content_type: str
    project_urls: tuple[str, ...]
    requirements: tuple[str, ...]
    description: str


def validate_artifacts(
    product: ReleaseProduct,
    version: str,
    distribution: Path,
    expected_requirements: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Return every violation in a product's complete distribution set."""
    requirements = (
        _manifest_requirements(product)
        if expected_requirements is None
        else expected_requirements
    )
    errors: list[str] = []
    wheels = tuple(sorted(distribution.glob(f"{product.name}-*.whl")))
    source_distributions = tuple(sorted(distribution.glob(f"{product.name}-*.tar.gz")))
    expected_wheels = len(product.wheel_platforms) or 1
    if len(wheels) != expected_wheels:
        errors.append(
            f"expected {expected_wheels} {product.name} wheel(s), found {len(wheels)}"
        )
    if len(source_distributions) != 1:
        errors.append(
            f"expected one {product.name} source distribution, "
            f"found {len(source_distributions)}"
        )
    errors.extend(_validate_wheel_platforms(wheels, product))
    for wheel in wheels:
        errors.extend(
            _validate_metadata(
                read_wheel_metadata(wheel), product, version, requirements
            )
        )
        errors.extend(_validate_wheel_contents(wheel, product))
    if len(source_distributions) == 1:
        errors.extend(
            _validate_metadata(
                read_sdist_metadata(source_distributions[0]),
                product,
                version,
                requirements,
            )
        )
    return tuple(errors)


def _validate_wheel_platforms(
    wheels: tuple[Path, ...],
    product: ReleaseProduct,
) -> tuple[str, ...]:
    """Return missing or duplicated native platform wheel violations."""
    errors: list[str] = []
    for platform in product.wheel_platforms:
        pattern = _WHEEL_PLATFORM_PATTERNS[platform]
        matches = tuple(wheel for wheel in wheels if pattern.search(wheel.name))
        if len(matches) != 1:
            errors.append(
                f"expected one {product.name} {platform} wheel, found {len(matches)}"
            )
    return tuple(errors)


def read_wheel_metadata(path: Path) -> ArtifactMetadata:
    """Read the unique Core Metadata document from a wheel."""
    with zipfile.ZipFile(path) as archive:
        candidates = tuple(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        if len(candidates) != 1:
            raise ValueError(f"{path} contains {len(candidates)} METADATA files")
        content = archive.read(candidates[0]).decode("utf-8")
    return _metadata_from_text(content)


def read_sdist_metadata(path: Path) -> ArtifactMetadata:
    """Read the root Core Metadata document from a source distribution."""
    with tarfile.open(path, mode="r:gz") as archive:
        root = path.name.removesuffix(".tar.gz")
        candidates = tuple(
            member
            for member in archive.getmembers()
            if member.name == f"{root}/PKG-INFO"
        )
        if len(candidates) != 1:
            raise ValueError(f"{path} contains {len(candidates)} PKG-INFO files")
        extracted = archive.extractfile(candidates[0])
        if extracted is None:
            raise ValueError(f"could not read {candidates[0].name} from {path}")
        content = extracted.read().decode("utf-8")
    return _metadata_from_text(content)


def _metadata_from_text(content: str) -> ArtifactMetadata:
    """Translate serialized Core Metadata into the release validation model."""
    message = Parser().parsestr(content)
    return ArtifactMetadata(
        name=str(message.get("Name", "")),
        version=str(message.get("Version", "")),
        description_content_type=str(message.get("Description-Content-Type", "")),
        project_urls=tuple(message.get_all("Project-URL", [])),
        requirements=tuple(message.get_all("Requires-Dist", [])),
        description=_description(message),
    )


def _description(message: Message) -> str:
    """Return the Markdown long description from one metadata message."""
    payload = message.get_payload()
    return payload if isinstance(payload, str) else ""


def _validate_metadata(
    metadata: ArtifactMetadata,
    product: ReleaseProduct,
    version: str,
    expected_requirements: tuple[str, ...],
) -> tuple[str, ...]:
    """Return public contract violations in one artifact metadata document."""
    errors: list[str] = []
    if metadata.name.lower().replace("_", "-") != product.name:
        errors.append(
            f"artifact name {metadata.name!r} does not match {product.name!r}"
        )
    if metadata.version != version:
        errors.append(
            f"artifact version {metadata.version!r} does not match tag version {version!r}"
        )
    if not metadata.description_content_type.startswith("text/markdown"):
        errors.append("artifact description must declare text/markdown")
    if not any(value.endswith(f", {_REPOSITORY}") for value in metadata.project_urls):
        errors.append(f"artifact Repository URL must be {_REPOSITORY}")
    if _REPOSITORY not in metadata.description:
        errors.append("package README must link to the canonical CuteCanvas repository")
    if _RELATIVE_MARKDOWN_LINK.search(metadata.description):
        errors.append("package README contains a relative Markdown link")
    if _RELATIVE_HTML_SOURCE.search(metadata.description):
        errors.append("package README contains a relative HTML link or image source")
    errors.extend(_validate_dependencies(metadata, product, expected_requirements))
    return tuple(errors)


def _validate_dependencies(
    metadata: ArtifactMetadata,
    product: ReleaseProduct,
    expected_requirements: tuple[str, ...],
) -> tuple[str, ...]:
    """Return cross-product dependency contract violations."""
    parsed: list[Requirement] = []
    errors: list[str] = []
    for value in metadata.requirements:
        requirement = _parse_requirement(value)
        if requirement is None:
            errors.append(f"artifact contains invalid requirement {value!r}")
        else:
            parsed.append(requirement)

    product_names = {
        canonicalize_name(name) for name in ("ferrastra", "qpane", "cutecanvas")
    }
    actual_product_dependencies = tuple(
        requirement
        for requirement in parsed
        if canonicalize_name(requirement.name) in product_names
    )
    expected = tuple(Requirement(value) for value in expected_requirements)
    expected_names = {canonicalize_name(requirement.name) for requirement in expected}
    errors.extend(
        f"{product.display_name} must not depend on {requirement.name}"
        for requirement in actual_product_dependencies
        if canonicalize_name(requirement.name) not in expected_names
    )
    for expected_text, dependency in zip(expected_requirements, expected, strict=True):
        matching = tuple(
            requirement
            for requirement in actual_product_dependencies
            if canonicalize_name(requirement.name) == canonicalize_name(dependency.name)
        )
        if (
            len(matching) != 1
            or matching[0].extras
            or matching[0].marker is not None
            or matching[0].url is not None
            or matching[0].specifier != SpecifierSet(dependency.specifier)
        ):
            errors.append(
                f"{product.display_name} must require exactly {expected_text}"
            )
    return tuple(errors)


def _manifest_requirements(product: ReleaseProduct) -> tuple[str, ...]:
    """Return current source requirements for the product dependency edges."""
    values = read_product_requirements(product.package_path / "pyproject.toml")
    return tuple(
        f"{dependency.name}{values[dependency.name]}"
        for dependency in product.dependencies
    )


def _parse_requirement(value: str) -> Requirement | None:
    """Parse one requirement or return ``None`` when it is invalid."""
    try:
        return Requirement(value)
    except InvalidRequirement:
        return None


def _validate_wheel_contents(
    wheel: Path,
    product: ReleaseProduct,
) -> tuple[str, ...]:
    """Return wheel ownership violations outside the selected product package."""
    with zipfile.ZipFile(wheel) as archive:
        roots = {
            PurePosixPath(name).parts[0]
            for name in archive.namelist()
            if PurePosixPath(name).parts
        }
    unexpected = sorted(
        root
        for root in roots
        if root != product.name and not root.endswith(".dist-info")
    )
    if unexpected:
        return (f"wheel contains unexpected top-level paths: {unexpected}",)
    return ()
