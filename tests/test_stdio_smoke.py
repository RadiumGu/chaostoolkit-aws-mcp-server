"""End-to-end test: start the server as a subprocess and talk MCP over stdio.

This is the regression test for the entry point: the previous implementation
raised ``ValueError: a coroutine was expected`` before serving anything.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.asyncio


def _server_parameters(workdir: Path) -> StdioServerParameters:
    source_root = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    env["CHAOS_MCP_WORKDIR"] = str(workdir)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    env["AWS_REGION"] = "cn-north-1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "chaostoolkit_aws_mcp_server.server"],
        env=env,
        cwd=str(workdir),
    )


async def test_server_starts_and_lists_tools(tmp_path: Path) -> None:
    async with (
        stdio_client(_server_parameters(tmp_path)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        listed = await session.list_tools()

    names = {tool.name for tool in listed.tools}
    assert "chaos_generate_az_failure_experiment" in names
    assert "chaos_restart_instances" in names
    assert len(names) >= 20


async def test_tool_call_generates_experiment(tmp_path: Path) -> None:
    async with (
        stdio_client(_server_parameters(tmp_path)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        response = await session.call_tool(
            "chaos_generate_az_failure_experiment",
            {
                "title": "Production AZ failure",
                "az": "cn-north-1a",
                "health_check_url": "https://example.com/health",
                "output_file": "./az.json",
            },
        )

    assert response.isError is False
    text = "\n".join(block.text for block in response.content if block.type == "text")
    assert "Generated experiment" in text

    written = tmp_path / "az.json"
    assert written.is_file()
    assert '"aws_region": "cn-north-1"' in written.read_text(encoding="utf-8")


async def test_invalid_arguments_return_an_error_message(tmp_path: Path) -> None:
    async with (
        stdio_client(_server_parameters(tmp_path)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        response = await session.call_tool(
            "chaos_generate_az_failure_experiment", {"title": "bad", "az": "not-an-az"}
        )

    text = "\n".join(block.text for block in response.content if block.type == "text")
    assert "Error:" in text
    assert "az has an invalid value" in text
