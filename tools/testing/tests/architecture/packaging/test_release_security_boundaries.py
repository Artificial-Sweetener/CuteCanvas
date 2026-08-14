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
"""Prove release credentials and runner command files retain trusted owners."""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request

import pytest
from typing_extensions import Self

from tools.release import orchestration
from tools.release.github_outputs import GitHubOutputError, append_github_outputs
from tools.release.orchestration import GitHubActionsGateway


class _Response:
    """Provide one empty successful GitHub REST response."""

    def __enter__(self) -> Self:
        """Enter the fake response context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Leave the fake response context."""
        del exc_type, exc_value, traceback

    def read(self) -> bytes:
        """Return one valid empty response object."""
        return b"{}"


def test_github_gateway_sends_tokens_only_to_the_public_api_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the release token off caller-selected or environment-selected hosts."""
    requests: list[Request] = []

    def open_request(request: Request, timeout: int) -> _Response:
        """Capture one GitHub request without using the network."""
        assert timeout == 30
        requests.append(request)
        return _Response()

    monkeypatch.setattr(orchestration, "urlopen", open_request)
    gateway = GitHubActionsGateway(
        repository="Artificial-Sweetener/CuteCanvas",
        token="secret",
    )

    assert gateway.workflow_run(42) == {}
    assert requests[0].full_url == (
        "https://api.github.com/repos/Artificial-Sweetener/CuteCanvas/actions/runs/42"
    )


def test_github_gateway_rejects_a_different_repository() -> None:
    """Reject release-token use for any repository outside this project."""
    with pytest.raises(orchestration.PublicationError, match="release repository"):
        GitHubActionsGateway(repository="attacker/example", token="secret")


def test_github_outputs_are_appended_inside_runner_temp(tmp_path: Path) -> None:
    """Preserve ordinary GitHub output publication inside the runner boundary."""
    runner_temp = tmp_path / "runner-temp"
    output = runner_temp / "_runner_file_commands" / "set_output"
    output.parent.mkdir(parents=True)

    append_github_outputs(
        {"released": "true", "plan_id": "plan-123"},
        environment={
            "GITHUB_OUTPUT": str(output),
            "RUNNER_TEMP": str(runner_temp),
        },
    )

    assert output.read_text("utf-8") == "released=true\nplan_id=plan-123\n"


def test_github_outputs_reject_paths_outside_runner_temp(tmp_path: Path) -> None:
    """Reject an output-file path that could overwrite caller-selected data."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    with pytest.raises(GitHubOutputError, match="outside RUNNER_TEMP"):
        append_github_outputs(
            {"released": "true"},
            environment={
                "GITHUB_OUTPUT": str(tmp_path / "outside"),
                "RUNNER_TEMP": str(runner_temp),
            },
        )


def test_github_outputs_reject_command_file_injection(tmp_path: Path) -> None:
    """Reject output values that could create additional runner commands."""
    runner_temp = tmp_path / "runner-temp"
    output = runner_temp / "set_output"
    runner_temp.mkdir()

    with pytest.raises(GitHubOutputError, match="line breaks"):
        append_github_outputs(
            {"released": "true\nforged=value"},
            environment={
                "GITHUB_OUTPUT": str(output),
                "RUNNER_TEMP": str(runner_temp),
            },
        )
