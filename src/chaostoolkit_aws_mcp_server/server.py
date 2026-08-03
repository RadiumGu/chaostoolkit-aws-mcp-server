#!/usr/bin/env python3
"""Chaos Toolkit AWS MCP server.

Generates Chaos Toolkit experiments for AWS and drives the ``chaos`` CLI to
validate, run and roll them back. All generated activities map onto functions
that exist in ``chaosaws`` / ``azchaosaws``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import catalog, safety
from .builder import AZ_ASG_ACTIONS, AZ_EC2_ACTIONS
from .models import default_region

logger = logging.getLogger("chaostoolkit_aws_mcp_server")

server: Server[Any, Any] = Server("chaostoolkit-aws-mcp-server")

MAX_TIMEOUT = 86400


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a ``chaos`` CLI invocation."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def render(self, header: str) -> str:
        status = "TIMED OUT" if self.timed_out else ("SUCCESS" if self.ok else "FAILED")
        parts = [f"{header}: {status} (exit code {self.exit_code})"]
        if self.stdout.strip():
            parts.append(f"\nSTDOUT:\n{self.stdout.strip()}")
        if self.stderr.strip():
            parts.append(f"\nSTDERR:\n{self.stderr.strip()}")
        return "\n".join(parts)


def _text(message: str) -> TextContent:
    return TextContent(type="text", text=message)


def _chaos_executable() -> str:
    executable = shutil.which("chaos")
    if not executable:
        raise safety.ValidationError(
            "the 'chaos' CLI was not found on PATH; install chaostoolkit in the "
            "environment running this server"
        )
    return executable


async def _run_command(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
    """Run a command without blocking the event loop."""
    logger.info("running %s in %s", " ".join(command), cwd)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        process.kill()
        await process.wait()
        return CommandResult(
            exit_code=-1,
            stdout="",
            stderr=f"command timed out after {timeout} seconds",
            timed_out=True,
        )
    return CommandResult(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


# --------------------------------------------------------------------------- #
# Lifecycle tools
# --------------------------------------------------------------------------- #
async def run_experiment(args: dict[str, Any]) -> list[TextContent]:
    """Run an experiment through the ``chaos`` CLI.

    Runs in dry mode unless the caller both disables ``dry_run`` and sets
    ``confirm_destructive``.
    """
    experiment_file = safety.resolve_existing_file(
        str(safety.require(args.get("experiment_file"), "experiment_file")), "experiment_file"
    )
    dry_run = safety.boolean(args.get("dry_run"), "dry_run", default=True)
    confirmed = safety.boolean(
        args.get("confirm_destructive"), "confirm_destructive", default=False
    )
    if not dry_run and not confirmed:
        return [
            _text(
                "Refusing to run the experiment for real: dry_run=false requires "
                "confirm_destructive=true. Run it with dry_run=true first and review "
                "the output."
            )
        ]
    timeout = safety.integer(
        args.get("timeout_seconds"), "timeout_seconds", minimum=1, maximum=MAX_TIMEOUT, default=3600
    )
    rollback_strategy = safety.choice(
        args.get("rollback_strategy"),
        {"default", "always", "never", "deviated"},
        "rollback_strategy",
        default="default",
    )
    cwd = safety.resolve_directory(args.get("working_directory"))

    command = [_chaos_executable(), "run", str(experiment_file)]
    if dry_run:
        command += ["--dry", "activities"]
    if args.get("journal_path"):
        journal = safety.resolve_output_path(str(args["journal_path"]), "./journal.json")
        command += ["--journal-path", str(journal)]
    command += ["--rollback-strategy", rollback_strategy]

    result = await _run_command(command, cwd, timeout)
    header = f"Experiment {'dry ' if dry_run else ''}run of {experiment_file.name}"
    return [_text(result.render(header))]


async def validate_experiment(args: dict[str, Any]) -> list[TextContent]:
    """Validate an experiment file locally and through ``chaos validate``."""
    experiment_file = safety.resolve_existing_file(
        str(safety.require(args.get("experiment_file"), "experiment_file")), "experiment_file"
    )
    timeout = safety.integer(
        args.get("timeout_seconds"), "timeout_seconds", minimum=1, maximum=MAX_TIMEOUT, default=120
    )
    cwd = safety.resolve_directory(args.get("working_directory"))

    if experiment_file.suffix.lower() == ".json":
        try:
            json.loads(experiment_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return [_text(f"Validation of {experiment_file.name}: FAILED\n\nInvalid JSON: {exc}")]

    result = await _run_command(
        [_chaos_executable(), "validate", str(experiment_file)], cwd, timeout
    )
    return [_text(result.render(f"Validation of {experiment_file.name}"))]


def _rollback_module(state: dict[str, Any], override: str | None) -> str:
    resource_type = override
    if resource_type is None:
        if "AutoScalingGroups" in state:
            resource_type = "asg"
        elif "Subnets" in state or "Instances" in state:
            resource_type = "ec2"
        else:
            raise safety.ValidationError(
                "cannot tell whether this state file belongs to ec2 or asg; "
                "pass resource_type explicitly"
            )
    return AZ_ASG_ACTIONS if resource_type == "asg" else AZ_EC2_ACTIONS


async def rollback_from_state(args: dict[str, Any]) -> list[TextContent]:
    """Run ``recover_az`` for each state file produced by ``fail_az``."""
    raw_files = safety.require(args.get("state_files"), "state_files")
    if not isinstance(raw_files, list):
        raise safety.ValidationError("state_files must be a list of paths")
    override = args.get("resource_type")
    if override is not None:
        override = safety.choice(override, {"ec2", "asg"}, "resource_type")
    timeout = safety.integer(
        args.get("timeout_seconds"), "timeout_seconds", minimum=1, maximum=MAX_TIMEOUT, default=600
    )
    cwd = safety.resolve_directory(args.get("working_directory"))

    report: list[str] = []
    for raw in raw_files:
        try:
            state_file = safety.resolve_existing_file(str(raw), "state_files")
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise safety.ValidationError(f"{state_file} does not contain a state object")
            if state.get("DryRun"):
                report.append(
                    f"Skipped {state_file.name}: it was produced by a dry run, so "
                    "recover_az has nothing to restore."
                )
                continue
            module = _rollback_module(state, override)
        except (safety.ValidationError, json.JSONDecodeError) as exc:
            report.append(f"Skipped {raw}: {exc}")
            continue

        experiment = {
            "version": "1.0.0",
            "title": f"Rollback from {state_file.name}",
            "description": "Automated AZ failure rollback",
            "tags": ["rollback"],
            "configuration": {"aws_region": args.get("aws_region") or default_region()},
            "method": [
                {
                    "type": "action",
                    "name": "recover-az",
                    "provider": {
                        "type": "python",
                        "module": module,
                        "func": "recover_az",
                        "arguments": {"state_path": str(state_file)},
                    },
                }
            ],
        }
        descriptor, raw_temp = tempfile.mkstemp(
            suffix=".json", prefix="chaos-rollback-", dir=cwd
        )
        temp_path = Path(raw_temp)
        try:
            with open(descriptor, "w", encoding="utf-8") as handle:
                json.dump(experiment, handle, indent=2)
            result = await _run_command(
                [_chaos_executable(), "run", str(temp_path)], cwd, timeout
            )
            report.append(result.render(f"Rollback from {state_file.name} using {module}"))
        finally:
            temp_path.unlink(missing_ok=True)

    if not report:
        report.append("Nothing to roll back.")
    return [_text("\n\n".join(report))]


LIFECYCLE_HANDLERS = {
    "chaos_run_experiment": run_experiment,
    "chaos_validate_experiment": validate_experiment,
    "chaos_rollback_from_state": rollback_from_state,
}


# --------------------------------------------------------------------------- #
# MCP wiring
# --------------------------------------------------------------------------- #
async def dispatch(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route a tool call to its handler."""
    resolved = catalog.resolve(name)
    notes: list[str] = []
    if resolved != name:
        notes.append(f"'{name}' is deprecated, use '{resolved}' instead.")

    if resolved in catalog.GENERATORS:
        generator = catalog.GENERATORS[resolved]
        generated = await asyncio.to_thread(generator, arguments)
        body = generated.to_text()
        return [_text("\n".join([*(f"NOTE: {note}" for note in notes), body]))]

    handler = LIFECYCLE_HANDLERS.get(resolved)
    if handler is not None:
        return await handler(arguments)

    raise safety.ValidationError(
        f"unknown tool: {name}. Available tools: {sorted(catalog.tool_names())}"
    )


@server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
async def list_tools() -> list[Tool]:
    """Advertise the tool catalog."""
    return list(catalog.TOOLS)


@server.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    """Handle a tool call, turning validation problems into readable errors."""
    try:
        return await dispatch(name, arguments or {})
    except safety.ValidationError as exc:
        return [_text(f"Error: {exc}")]
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("tool %s failed", name)
        return [_text(f"Error: {type(exc).__name__}: {exc}")]


async def serve() -> None:
    """Serve the MCP protocol over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Entry point for the ``chaostoolkit-aws-mcp-server`` script."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,  # stdout carries the MCP protocol
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("workdir confined to %s", safety.workdir())
    asyncio.run(serve())


if __name__ == "__main__":
    main()
