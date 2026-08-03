"""Shared fixtures and sample tool arguments."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

INSTANCE_ID = "i-0123456789abcdef0"
SECURITY_GROUP_ID = "sg-0123456789abcdef0"
VPC_ID = "vpc-0123456789abcdef0"

# One realistic argument set per generation tool, used to assert that every
# generated activity points at a function that really exists.
SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "chaos_generate_az_failure_experiment": {"title": "az", "az": "us-east-1a"},
    "chaos_generate_asg_az_failure_experiment": {"title": "asg az", "az": "us-east-1a"},
    "chaos_isolate_az_network": {"title": "isolate", "az": "us-east-1a", "vpc_id": VPC_ID},
    "chaos_simulate_az_partition": {
        "title": "partition",
        "az": "us-east-1a",
        "filters": [{"Name": "tag:App", "Values": ["web"]}],
    },
    "chaos_generate_ec2_actions_experiment": {
        "title": "ec2",
        "action_type": "stop_instances",
        "instance_ids": [INSTANCE_ID],
    },
    "chaos_stop_instances": {"title": "stop", "instance_ids": [INSTANCE_ID]},
    "chaos_terminate_instances": {"title": "terminate", "instance_ids": [INSTANCE_ID]},
    "chaos_restart_instances": {"title": "restart", "instance_ids": [INSTANCE_ID]},
    "chaos_detach_random_volume": {"title": "detach", "instance_ids": [INSTANCE_ID]},
    "chaos_suspend_asg_processes": {
        "title": "suspend",
        "asg_names": ["my-asg"],
        "process_names": ["AZRebalance"],
    },
    "chaos_terminate_random_instances": {
        "title": "terminate random",
        "asg_names": ["my-asg"],
        "instance_count": 1,
    },
    "chaos_ssm_send_command": {
        "title": "ssm",
        "instance_ids": [INSTANCE_ID],
        "commands": ["echo chaos"],
    },
    "chaos_ssm_stress_cpu": {"title": "cpu", "instance_ids": [INSTANCE_ID]},
    "chaos_ssm_fill_disk": {"title": "disk", "instance_ids": [INSTANCE_ID]},
    "chaos_ssm_kill_process": {
        "title": "kill",
        "instance_ids": [INSTANCE_ID],
        "process_name": "nginx",
    },
    "chaos_simulate_network_latency": {"title": "latency", "instance_ids": [INSTANCE_ID]},
    "chaos_modify_security_groups": {
        "title": "sg",
        "security_group_ids": [SECURITY_GROUP_ID],
        "action": "revoke",
        "ip_protocol": "tcp",
        "from_port": 443,
        "to_port": 443,
        "cidr_ip": "0.0.0.0/0",
    },
    "chaos_reboot_db_instance": {"title": "rds", "db_instance_identifier": "my-db"},
    "chaos_failover_db_cluster": {"title": "cluster", "db_cluster_identifier": "my-cluster"},
    "chaos_deregister_target": {"title": "tg", "target_group_name": "my-tg"},
}


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Confine the server to a temporary directory for the duration of a test."""
    monkeypatch.setenv("CHAOS_MCP_WORKDIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    os.environ.pop("CHAOS_MCP_WORKDIR", None)
