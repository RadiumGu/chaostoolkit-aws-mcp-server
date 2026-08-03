"""Tests for the MCP server layer: dispatch, run, validate and rollback."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from chaostoolkit_aws_mcp_server import safety
from chaostoolkit_aws_mcp_server import server as server_module
from chaostoolkit_aws_mcp_server.server import CommandResult

from .conftest import INSTANCE_ID


@pytest.fixture
def recorded_commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture chaos CLI invocations instead of running them."""
    commands: list[list[str]] = []

    async def fake_run(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        commands.append(list(command))
        return CommandResult(exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(server_module, "_run_command", fake_run)
    monkeypatch.setattr(server_module, "_chaos_executable", lambda: "chaos")
    return commands


def _experiment_file(workdir: Path, name: str = "experiment.json") -> Path:
    path = workdir / name
    path.write_text(json.dumps({"version": "1.0.0", "title": "t", "method": []}), encoding="utf-8")
    return path


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_tools_returns_catalog(self) -> None:
        from chaostoolkit_aws_mcp_server import catalog

        tools = await server_module.list_tools()

        assert [tool.name for tool in tools] == [tool.name for tool in catalog.TOOLS]
        assert all(tool.description for tool in tools)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_generation_tool_writes_file(self, workdir: Path) -> None:
        result = await server_module.dispatch(
            "chaos_stop_instances", {"title": "t", "instance_ids": [INSTANCE_ID]}
        )

        assert len(result) == 1
        assert "Generated experiment" in result[0].text
        assert (workdir / "stop-instances-experiment.json").is_file()

    @pytest.mark.asyncio
    async def test_deprecated_alias_is_reported(self, workdir: Path) -> None:
        result = await server_module.dispatch(
            "chaos_reboot_instances", {"title": "t", "instance_ids": [INSTANCE_ID]}
        )

        assert "is deprecated, use 'chaos_restart_instances'" in result[0].text
        assert "restart_instances" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool_is_an_error(self, workdir: Path) -> None:
        result = await server_module.call_tool("chaos_nope", {})

        assert result[0].text.startswith("Error: unknown tool: chaos_nope")

    @pytest.mark.asyncio
    async def test_validation_error_is_returned_as_text(self, workdir: Path) -> None:
        result = await server_module.call_tool("chaos_stop_instances", {"title": "t"})

        assert result[0].text.startswith("Error:")
        assert "at least one of" in result[0].text

    @pytest.mark.asyncio
    async def test_missing_arguments_are_tolerated(self, workdir: Path) -> None:
        result = await server_module.call_tool("chaos_stop_instances", None)

        assert result[0].text.startswith("Error:")


class TestRunExperiment:
    @pytest.mark.asyncio
    async def test_dry_run_is_the_default(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        path = _experiment_file(workdir)

        result = await server_module.run_experiment({"experiment_file": str(path)})

        assert recorded_commands == [
            ["chaos", "run", str(path), "--dry", "activities", "--rollback-strategy", "default"]
        ]
        assert "dry run" in result[0].text
        assert "SUCCESS" in result[0].text

    @pytest.mark.asyncio
    async def test_real_run_requires_confirmation(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        path = _experiment_file(workdir)

        result = await server_module.run_experiment(
            {"experiment_file": str(path), "dry_run": False}
        )

        assert recorded_commands == []
        assert "confirm_destructive=true" in result[0].text

    @pytest.mark.asyncio
    async def test_confirmed_run_executes_without_dry_flag(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        path = _experiment_file(workdir)

        await server_module.run_experiment(
            {
                "experiment_file": str(path),
                "dry_run": False,
                "confirm_destructive": True,
                "journal_path": "./journal.json",
                "rollback_strategy": "always",
            }
        )

        command = recorded_commands[0]
        assert "--dry" not in command
        assert command[-2:] == ["--rollback-strategy", "always"]
        assert str(workdir / "journal.json") in command

    @pytest.mark.asyncio
    async def test_missing_experiment_file(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        with pytest.raises(safety.ValidationError, match="not found"):
            await server_module.run_experiment({"experiment_file": "./missing.json"})

    @pytest.mark.asyncio
    async def test_experiment_file_outside_workdir_is_rejected(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        with pytest.raises(safety.ValidationError, match="must stay inside"):
            await server_module.run_experiment({"experiment_file": "/etc/hosts"})

    @pytest.mark.asyncio
    async def test_timeout_is_reported(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _experiment_file(workdir)

        async def timing_out(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
            return CommandResult(-1, "", "command timed out after 1 seconds", timed_out=True)

        monkeypatch.setattr(server_module, "_run_command", timing_out)
        monkeypatch.setattr(server_module, "_chaos_executable", lambda: "chaos")

        result = await server_module.run_experiment(
            {"experiment_file": str(path), "timeout_seconds": 1}
        )

        assert "TIMED OUT" in result[0].text

    @pytest.mark.asyncio
    async def test_missing_chaos_cli(self, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _experiment_file(workdir)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        result = await server_module.call_tool(
            "chaos_run_experiment", {"experiment_file": str(path)}
        )

        assert "'chaos' CLI was not found" in result[0].text


class TestValidateExperiment:
    @pytest.mark.asyncio
    async def test_valid_file_runs_chaos_validate(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        path = _experiment_file(workdir)

        result = await server_module.validate_experiment({"experiment_file": str(path)})

        assert recorded_commands == [["chaos", "validate", str(path)]]
        assert "SUCCESS" in result[0].text

    @pytest.mark.asyncio
    async def test_broken_json_fails_before_calling_chaos(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        path = workdir / "broken.json"
        path.write_text("{not json", encoding="utf-8")

        result = await server_module.validate_experiment({"experiment_file": str(path)})

        assert recorded_commands == []
        assert "Invalid JSON" in result[0].text

    @pytest.mark.asyncio
    async def test_working_directory_is_honoured(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nested = workdir / "nested"
        nested.mkdir()
        path = _experiment_file(nested)
        seen: dict[str, Path] = {}

        async def fake_run(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
            seen["cwd"] = cwd
            return CommandResult(0, "", "")

        monkeypatch.setattr(server_module, "_run_command", fake_run)
        monkeypatch.setattr(server_module, "_chaos_executable", lambda: "chaos")

        await server_module.validate_experiment(
            {"experiment_file": str(path), "working_directory": "nested"}
        )

        assert seen["cwd"] == nested


class TestRollbackFromState:
    def _state(self, workdir: Path, name: str, payload: dict[str, Any]) -> Path:
        path = workdir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @pytest.mark.asyncio
    async def test_ec2_state_uses_ec2_module(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(
            workdir, "fail_az.ec2.json", {"DryRun": False, "Subnets": [], "Instances": []}
        )

        result = await server_module.rollback_from_state({"state_files": [str(state)]})

        assert len(recorded_commands) == 1
        assert "azchaosaws.ec2.actions" in result[0].text
        assert "SUCCESS" in result[0].text

    @pytest.mark.asyncio
    async def test_asg_state_uses_asg_module(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(
            workdir, "state.json", {"DryRun": False, "AutoScalingGroups": [{"Name": "a"}]}
        )

        result = await server_module.rollback_from_state({"state_files": [str(state)]})

        assert "azchaosaws.asg.actions" in result[0].text

    @pytest.mark.asyncio
    async def test_module_is_not_guessed_from_the_file_name(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        # A path mentioning ec2 but holding ASG state must still roll back the ASG.
        state = self._state(
            workdir, "ec2-like-name.json", {"DryRun": False, "AutoScalingGroups": []}
        )

        result = await server_module.rollback_from_state({"state_files": [str(state)]})

        assert "azchaosaws.asg.actions" in result[0].text

    @pytest.mark.asyncio
    async def test_dry_run_state_is_skipped(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(workdir, "dry.json", {"DryRun": True, "Subnets": []})

        result = await server_module.rollback_from_state({"state_files": [str(state)]})

        assert recorded_commands == []
        assert "produced by a dry run" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_state_shape_is_reported(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(workdir, "weird.json", {"DryRun": False, "Something": 1})

        result = await server_module.rollback_from_state({"state_files": [str(state)]})

        assert recorded_commands == []
        assert "pass resource_type explicitly" in result[0].text

    @pytest.mark.asyncio
    async def test_resource_type_override(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(workdir, "weird.json", {"DryRun": False, "Something": 1})

        result = await server_module.rollback_from_state(
            {"state_files": [str(state)], "resource_type": "asg"}
        )

        assert "azchaosaws.asg.actions" in result[0].text

    @pytest.mark.asyncio
    async def test_missing_state_file_is_reported(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        result = await server_module.rollback_from_state({"state_files": ["./nope.json"]})

        assert recorded_commands == []
        assert "Skipped" in result[0].text

    @pytest.mark.asyncio
    async def test_temporary_experiment_is_cleaned_up(
        self, workdir: Path, recorded_commands: list[list[str]]
    ) -> None:
        state = self._state(workdir, "fail_az.ec2.json", {"DryRun": False, "Subnets": []})

        await server_module.rollback_from_state({"state_files": [str(state)]})

        assert not list(workdir.glob("chaos-rollback-*.json"))


class TestCommandResult:
    def test_render_includes_streams(self) -> None:
        rendered = CommandResult(1, "out", "err").render("Run")

        assert "FAILED" in rendered
        assert "out" in rendered
        assert "err" in rendered
