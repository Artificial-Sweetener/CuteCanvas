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

from .products import ReleaseProduct

_REPOSITORY = "https://github.com/Artificial-Sweetener/CuteCanvas"
_RELATIVE_MARKDOWN_LINK = re.compile(r"\]\((?!https?://|mailto:|#)[^)]+\)")
_RELATIVE_HTML_SOURCE = re.compile(r"(?:src|href)=[\"'](?!https?://|mailto:|#)")


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
) -> tuple[str, ...]:
    """Return every violation in one wheel and source distribution set."""
    errors: list[str] = []
    wheels = tuple(distribution.glob(f"{product.name}-*.whl"))
    source_distributions = tuple(distribution.glob(f"{product.name}-*.tar.gz"))
    if len(wheels) != 1:
        errors.append(f"expected one {product.name} wheel, found {len(wheels)}")
    if len(source_distributions) != 1:
        errors.append(
            f"expected one {product.name} source distribution, "
            f"found {len(source_distributions)}"
        )
    if len(wheels) == 1:
        wheel = wheels[0]
        errors.extend(_validate_metadata(read_wheel_metadata(wheel), product, version))
        errors.extend(_validate_wheel_contents(wheel, product))
    if len(source_distributions) == 1:
        errors.extend(
            _validate_metadata(
                read_sdist_metadata(source_distributions[0]), product, version
            )
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
    errors.extend(_validate_dependencies(metadata, product))
    return tuple(errors)


def _validate_dependencies(
    metadata: ArtifactMetadata,
    product: ReleaseProduct,
) -> tuple[str, ...]:
    """Return cross-product dependency contract violations."""
    qpane = tuple(
        requirement.replace(" ", "")
        for requirement in metadata.requirements
        if requirement.lower().startswith("qpane")
    )
    if product.name == "cutecanvas":
        if len(qpane) != 1 or ">=3.0.0" not in qpane[0] or "<4.0.0" not in qpane[0]:
            return ("CuteCanvas must require exactly qpane>=3.0.0,<4.0.0",)
    elif any(
        requirement.lower().startswith("cutecanvas")
        for requirement in metadata.requirements
    ):
        return ("QPane must not depend on CuteCanvas",)
    return ()


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
