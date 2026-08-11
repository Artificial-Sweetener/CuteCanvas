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
"""Own automatic publication dispatch and release-verification admission."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tools.release.products import PRODUCTS, release_from_tag

_PUBLISH_WORKFLOW = "publish.yml"
_RELEASE_WORKFLOW_PATH = ".github/workflows/release.yml"
_VERIFICATION_GATE = "verify / Gate"
_POLL_SECONDS = 15.0
_PUBLICATION_TIMEOUT_SECONDS = 21_000.0


class PublicationError(RuntimeError):
    """Report a publication-orchestration contract failure."""


@dataclass(frozen=True)
class PublicationRun:
    """Describe the observable state of one publication workflow run."""

    run_id: int
    display_title: str
    status: str
    conclusion: str | None
    url: str


class ActionsGateway(Protocol):
    """Provide the GitHub Actions operations required by release orchestration."""

    def dispatch_publication(self, tag: str, orchestrator_run_id: str) -> None:
        """Dispatch the trusted publication workflow for ``tag``."""
        ...

    def publication_runs(self, tag: str) -> Sequence[PublicationRun]:
        """Return recent independently dispatched publication runs for ``tag``."""
        ...

    def workflow_run(self, run_id: int) -> Mapping[str, Any]:
        """Return metadata for one workflow run."""
        ...

    def workflow_jobs(self, run_id: int) -> Sequence[Mapping[str, Any]]:
        """Return jobs belonging to one workflow run."""
        ...


class GitHubActionsGateway:
    """Access GitHub Actions through its authenticated REST API."""

    def __init__(self, repository: str, token: str, api_url: str) -> None:
        """Create a gateway for one GitHub repository."""
        self._repository = repository
        self._token = token
        self._api_url = api_url.rstrip("/")

    def dispatch_publication(self, tag: str, orchestrator_run_id: str) -> None:
        """Dispatch ``publish.yml`` as a top-level workflow at ``tag``."""
        self._request(
            "POST",
            f"/repos/{self._repository}/actions/workflows/"
            f"{_PUBLISH_WORKFLOW}/dispatches",
            {
                "ref": tag,
                "inputs": {
                    "release_tag": tag,
                    "orchestrator_run_id": orchestrator_run_id,
                },
            },
        )

    def publication_runs(self, tag: str) -> tuple[PublicationRun, ...]:
        """Return recent workflow-dispatch runs of ``publish.yml`` for ``tag``."""
        query = urlencode(
            {"event": "workflow_dispatch", "branch": tag, "per_page": "30"}
        )
        payload = self._request(
            "GET",
            f"/repos/{self._repository}/actions/workflows/"
            f"{_PUBLISH_WORKFLOW}/runs?{query}",
        )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise PublicationError(
                "GitHub publication-run response omitted workflow_runs"
            )
        return tuple(_publication_run(item) for item in runs)

    def workflow_run(self, run_id: int) -> Mapping[str, Any]:
        """Return metadata for one workflow run."""
        return self._request("GET", f"/repos/{self._repository}/actions/runs/{run_id}")

    def workflow_jobs(self, run_id: int) -> tuple[Mapping[str, Any], ...]:
        """Return every job reported for one workflow run."""
        payload = self._request(
            "GET", f"/repos/{self._repository}/actions/runs/{run_id}/jobs?per_page=100"
        )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise PublicationError("GitHub workflow-job response omitted jobs")
        return tuple(_mapping(job, "workflow job") for job in jobs)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Send one authenticated JSON request and return its object response."""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
        except OSError as error:
            raise PublicationError(
                f"GitHub Actions request failed: {method} {path}: {error}"
            ) from error
        if not body:
            return {}
        decoded = json.loads(body)
        return _mapping(decoded, "GitHub API response")


def release_tags_from_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Return versioned product tags in dependency publication order."""
    tags: list[str] = []
    for product_name in PRODUCTS:
        prefix = product_name.upper()
        released = environment.get(f"{prefix}_RELEASED", "").strip().lower()
        tag = environment.get(f"{prefix}_RELEASE_TAG", "").strip()
        if released not in {"true", "false"}:
            raise PublicationError(
                f"{prefix}_RELEASED must be true or false, received {released!r}"
            )
        if released == "false":
            if tag:
                raise PublicationError(
                    f"{prefix}_RELEASE_TAG must be empty when no release was created"
                )
            continue
        if not tag:
            raise PublicationError(
                f"{prefix}_RELEASE_TAG is required when the product was released"
            )
        product, _version = release_from_tag(tag)
        if product.name != product_name:
            raise PublicationError(
                f"{prefix}_RELEASE_TAG selected {product.name}, expected {product_name}"
            )
        tags.append(tag)
    return tuple(tags)


def confirm_verified_orchestrator(
    gateway: ActionsGateway,
    *,
    run_id: int,
    repository: str,
) -> None:
    """Admit only an active ``release.yml`` run whose verification gate passed."""
    run = gateway.workflow_run(run_id)
    path = run.get("path")
    status = run.get("status")
    run_repository = _nested_value(run, "repository", "full_name")
    if path != _RELEASE_WORKFLOW_PATH:
        raise PublicationError(
            f"orchestrator run {run_id} uses {path!r}, expected {_RELEASE_WORKFLOW_PATH!r}"
        )
    if run_repository != repository:
        raise PublicationError(
            f"orchestrator run {run_id} belongs to {run_repository!r}, "
            f"expected {repository!r}"
        )
    if status != "in_progress":
        raise PublicationError(
            f"orchestrator run {run_id} must be in_progress, received {status!r}"
        )
    gate = next(
        (
            job
            for job in gateway.workflow_jobs(run_id)
            if job.get("name") == _VERIFICATION_GATE
        ),
        None,
    )
    if gate is None:
        raise PublicationError(
            f"orchestrator run {run_id} has no {_VERIFICATION_GATE!r} job"
        )
    if gate.get("status") != "completed" or gate.get("conclusion") != "success":
        raise PublicationError(
            f"orchestrator run {run_id} verification gate is "
            f"{gate.get('status')}/{gate.get('conclusion')}, expected completed/success"
        )


def dispatch_publication_waterfall(
    gateway: ActionsGateway,
    tags: Sequence[str],
    *,
    orchestrator_run_id: str,
    monotonic: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    timeout_seconds: float = _PUBLICATION_TIMEOUT_SECONDS,
) -> None:
    """Dispatch each product publication and stop unless it succeeds."""
    if not tags:
        raise PublicationError("the versioning workflow produced no release tags")
    _validate_tag_order(tags)
    for tag in tags:
        expected_title = _publication_title(tag, orchestrator_run_id)
        existing_ids = {
            run.run_id
            for run in gateway.publication_runs(tag)
            if run.display_title == expected_title
        }
        gateway.dispatch_publication(tag, orchestrator_run_id)
        print(f"Dispatched trusted publication for {tag}.")
        deadline = monotonic() + timeout_seconds
        last_state: tuple[str, str | None] | None = None
        while monotonic() < deadline:
            candidates = [
                run
                for run in gateway.publication_runs(tag)
                if run.display_title == expected_title
                and run.run_id not in existing_ids
            ]
            if candidates:
                publication = max(candidates, key=lambda run: run.run_id)
                state = (publication.status, publication.conclusion)
                if state != last_state:
                    print(
                        f"Publication {publication.run_id} for {tag}: "
                        f"{publication.status}/{publication.conclusion or '-'} "
                        f"{publication.url}"
                    )
                    last_state = state
                if publication.status == "completed":
                    if publication.conclusion != "success":
                        raise PublicationError(
                            f"publication {publication.run_id} for {tag} completed "
                            f"with {publication.conclusion!r}: {publication.url}"
                        )
                    break
            pause(_POLL_SECONDS)
        else:
            raise PublicationError(
                f"timed out waiting for the trusted publication of {tag}"
            )
        print(f"SUCCESS: published {tag} through {_PUBLISH_WORKFLOW}.")


def _validate_tag_order(tags: Sequence[str]) -> None:
    """Reject duplicate, unknown, or dependency-inverted publication plans."""
    product_order = {name: index for index, name in enumerate(PRODUCTS)}
    names = [release_from_tag(tag)[0].name for tag in tags]
    if len(set(names)) != len(names):
        raise PublicationError("the publication waterfall contains duplicate products")
    if names != sorted(names, key=product_order.__getitem__):
        raise PublicationError(
            "publication tags must be ordered Ferrastra, QPane, then CuteCanvas"
        )


def _publication_title(tag: str, orchestrator_run_id: str) -> str:
    """Return the exact run title used to correlate one workflow dispatch."""
    return f"Publish {tag} from release {orchestrator_run_id}"


def _publication_run(value: object) -> PublicationRun:
    """Validate and convert one GitHub workflow-run response."""
    run = _mapping(value, "publication workflow run")
    try:
        return PublicationRun(
            run_id=int(run["id"]),
            display_title=str(run["display_title"]),
            status=str(run["status"]),
            conclusion=(
                None if run.get("conclusion") is None else str(run["conclusion"])
            ),
            url=str(run["html_url"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PublicationError(
            f"invalid publication workflow-run response: {run!r}"
        ) from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """Require an object-shaped GitHub API value."""
    if not isinstance(value, dict):
        raise PublicationError(f"{label} must be a JSON object")
    return value


def _nested_value(value: Mapping[str, Any], owner: str, field: str) -> object:
    """Return a value nested under one object-shaped response field."""
    nested = value.get(owner)
    return nested.get(field) if isinstance(nested, dict) else None
