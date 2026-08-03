#!/usr/bin/env python3
"""Example usage of the Chaos Toolkit AWS MCP server.

Runs the generators directly, without going through MCP, and writes the
experiments next to this file. Set CHAOS_MCP_WORKDIR to the examples directory
so the generated paths stay inside it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent
os.environ.setdefault("CHAOS_MCP_WORKDIR", str(EXAMPLES_DIR))
os.environ.setdefault("AWS_REGION", "cn-north-1")

from chaostoolkit_aws_mcp_server import builder  # noqa: E402
from chaostoolkit_aws_mcp_server.server import dispatch  # noqa: E402


def show(generated: builder.GeneratedExperiment) -> None:
    print(f"\n=== {generated.experiment['title']} -> {generated.path.name} ===")
    for warning in generated.warnings:
        print(f"  warning: {warning}")


def generate_examples() -> None:
    """Generate one experiment per family of chaos actions."""
    show(
        builder.generate_az_failure_experiment(
            {
                "title": "Production AZ failure",
                "az": "cn-north-1a",
                "failure_type": "network",
                # dry_run defaults to true; flip it once the experiment is reviewed.
                "dry_run": True,
                "health_check_url": "https://my-app.example.com/health",
                "state_path": "./fail_az.ec2.json",
                "output_file": "./az-failure-experiment.json",
            }
        )
    )
    show(
        builder.generate_asg_az_failure_experiment(
            {
                "title": "ASG resilience test",
                "az": "cn-north-1a",
                "asg_tags": [{"Key": "Environment", "Value": "production"}],
                "health_check_url": "https://my-app.example.com/health",
                "output_file": "./asg-az-failure-experiment.json",
            }
        )
    )
    show(
        builder.generate_stop_instances_experiment(
            {
                "title": "Stop two web instances",
                "instance_ids": ["i-1234567890abcdef0", "i-0987654321fedcba0"],
                "output_file": "./stop-instances-experiment.json",
            }
        )
    )
    show(
        builder.generate_ssm_cpu_stress_experiment(
            {
                "title": "CPU stress",
                "instance_ids": ["i-1234567890abcdef0"],
                "cpu_cores": 4,
                "duration_seconds": 300,
                "output_file": "./ssm-cpu-stress-experiment.json",
            }
        )
    )


async def validate_examples() -> None:
    """Validate the generated files through the MCP lifecycle tool."""
    for name in sorted(path.name for path in EXAMPLES_DIR.glob("*-experiment.json")):
        result = await dispatch("chaos_validate_experiment", {"experiment_file": f"./{name}"})
        print(f"\n{result[0].text}")


if __name__ == "__main__":
    generate_examples()
    asyncio.run(validate_examples())
