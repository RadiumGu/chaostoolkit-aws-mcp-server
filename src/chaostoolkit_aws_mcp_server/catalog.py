"""Tool catalog: JSON schemas exposed over MCP and the handler for each tool."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from . import builder
from .builder import GeneratedExperiment

Generator = Callable[[dict[str, Any]], GeneratedExperiment]

# Tools kept for backwards compatibility, pointing at the renamed tool that maps
# onto the function that actually exists in chaosaws.
ALIASES: dict[str, str] = {
    "chaos_reboot_instances": "chaos_restart_instances",
    "chaos_detach_volumes": "chaos_detach_random_volume",
    "chaos_deregister_targets": "chaos_deregister_target",
}

MANAGEMENT_TOOLS = frozenset(
    {"chaos_run_experiment", "chaos_validate_experiment", "chaos_rollback_from_state"}
)

_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}
_FILTERS = {
    "type": "array",
    "description": "EC2 filters, e.g. [{\"Name\": \"tag:Env\", \"Values\": [\"prod\"]}]",
    "items": {
        "type": "object",
        "properties": {"Name": _STRING, "Values": _STRING_LIST},
        "required": ["Name", "Values"],
    },
}
_KEY_VALUE_TAGS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"Key": _STRING, "Value": _STRING},
        "required": ["Key", "Value"],
    },
}

_COMMON = {
    "title": {"type": "string", "description": "Experiment title"},
    "tags": {**_STRING_LIST, "description": "Experiment tags"},
    "health_check_url": {
        "type": "string",
        "description": (
            "Optional URL probed as steady state hypothesis (HTTP provider). It is "
            "checked before and after the method, so a failing probe aborts the run "
            "before any chaos is injected."
        ),
    },
    "health_check_status": {"type": "integer", "default": 200},
    "health_check_timeout": {"type": "integer", "default": 3},
    "health_check_method": {
        "type": "string",
        "enum": ["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"],
        "default": "GET",
    },
    "health_check_verify_tls": {
        "type": "boolean",
        "default": True,
        "description": (
            "Set to false when the endpoint redirects to HTTPS with a certificate that "
            "does not match the host, which is common for raw load balancer DNS names"
        ),
    },
    "output_file": {"type": "string", "description": "Where to write the experiment JSON"},
    "aws_region": {
        "type": "string",
        "description": "AWS region; defaults to $AWS_REGION, then $AWS_DEFAULT_REGION",
    },
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {**_COMMON, **properties},
        "required": required,
        "additionalProperties": False,
    }


GENERATORS: dict[str, Generator] = {
    "chaos_generate_az_failure_experiment": builder.generate_az_failure_experiment,
    "chaos_generate_asg_az_failure_experiment": builder.generate_asg_az_failure_experiment,
    "chaos_isolate_az_network": builder.generate_isolate_az_network_experiment,
    "chaos_simulate_az_partition": builder.generate_az_partition_experiment,
    "chaos_generate_ec2_actions_experiment": builder.generate_ec2_actions_experiment,
    "chaos_stop_instances": builder.generate_stop_instances_experiment,
    "chaos_terminate_instances": builder.generate_terminate_instances_experiment,
    "chaos_restart_instances": builder.generate_restart_instances_experiment,
    "chaos_detach_random_volume": builder.generate_detach_volume_experiment,
    "chaos_suspend_asg_processes": builder.generate_suspend_asg_processes_experiment,
    "chaos_terminate_random_instances": builder.generate_terminate_random_instances_experiment,
    "chaos_ssm_send_command": builder.generate_ssm_send_command_experiment,
    "chaos_ssm_stress_cpu": builder.generate_ssm_cpu_stress_experiment,
    "chaos_ssm_fill_disk": builder.generate_ssm_fill_disk_experiment,
    "chaos_ssm_kill_process": builder.generate_ssm_kill_process_experiment,
    "chaos_simulate_network_latency": builder.generate_network_latency_experiment,
    "chaos_modify_security_groups": builder.generate_modify_security_groups_experiment,
    "chaos_reboot_db_instance": builder.generate_reboot_db_instance_experiment,
    "chaos_failover_db_cluster": builder.generate_failover_db_cluster_experiment,
    "chaos_deregister_target": builder.generate_deregister_target_experiment,
}


TOOLS: list[Tool] = [
    # ---------------------------------------------------------------- AZ failure
    Tool(
        name="chaos_generate_az_failure_experiment",
        description=(
            "Generate an availability zone failure experiment "
            "(azchaosaws.ec2.actions.fail_az) with a recover_az rollback. "
            "dry_run defaults to true."
        ),
        inputSchema=_schema(
            {
                "az": {
                    "type": "string",
                    "description": "Target availability zone, e.g. cn-north-1a",
                },
                "failure_type": {
                    "type": "string",
                    "enum": ["network", "instance"],
                    "default": "network",
                },
                "dry_run": {"type": "boolean", "default": True},
                "filters": _FILTERS,
                "state_path": {"type": "string", "default": "./fail_az.ec2.json"},
            },
            ["title", "az"],
        ),
    ),
    Tool(
        name="chaos_generate_asg_az_failure_experiment",
        description=(
            "Generate an Auto Scaling group AZ failure experiment "
            "(azchaosaws.asg.actions.fail_az) with a recover_az rollback. "
            "dry_run defaults to true."
        ),
        inputSchema=_schema(
            {
                "az": {"type": "string", "description": "Target availability zone"},
                "asg_tags": {
                    **_KEY_VALUE_TAGS,
                    "description": "Tags selecting the Auto Scaling groups",
                    "default": [{"Key": "AZ_FAILURE", "Value": "True"}],
                },
                "dry_run": {"type": "boolean", "default": True},
                "state_path": {"type": "string", "default": "./fail_az.asg.json"},
            },
            ["title", "az"],
        ),
    ),
    Tool(
        name="chaos_isolate_az_network",
        description=(
            "Isolate the network of an AZ inside a VPC. Implemented as "
            "azchaosaws.ec2.actions.fail_az(failure_type='network') with a vpc-id filter."
        ),
        inputSchema=_schema(
            {
                "az": {"type": "string", "description": "Target availability zone"},
                "vpc_id": {"type": "string", "description": "VPC id, e.g. vpc-0123456789abcdef0"},
                "dry_run": {"type": "boolean", "default": True},
                "filters": _FILTERS,
                "state_path": {"type": "string", "default": "./isolate_az.ec2.json"},
            },
            ["title", "az", "vpc_id"],
        ),
    ),
    Tool(
        name="chaos_simulate_az_partition",
        description=(
            "Approximate an AZ network partition with "
            "azchaosaws.ec2.actions.fail_az(failure_type='network'). "
            "A partial partition requires filters selecting the affected resources."
        ),
        inputSchema=_schema(
            {
                "az": {"type": "string", "description": "Target availability zone"},
                "partition_type": {
                    "type": "string",
                    "enum": ["partial", "complete"],
                    "default": "partial",
                },
                "dry_run": {"type": "boolean", "default": True},
                "filters": _FILTERS,
                "state_path": {"type": "string", "default": "./az_partition.ec2.json"},
            },
            ["title", "az"],
        ),
    ),
    # ---------------------------------------------------------------------- EC2
    Tool(
        name="chaos_generate_ec2_actions_experiment",
        description="Generate an EC2 instance experiment (stop, terminate or restart).",
        inputSchema=_schema(
            {
                "action_type": {
                    "type": "string",
                    "enum": ["stop_instances", "terminate_instances", "restart_instances"],
                },
                "instance_ids": _STRING_LIST,
                "filters": _FILTERS,
                "az": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            ["title", "action_type"],
        ),
    ),
    Tool(
        name="chaos_stop_instances",
        description=(
            "Generate an experiment stopping EC2 instances "
            "(chaosaws.ec2.actions.stop_instances) with a start_instances rollback."
        ),
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "filters": _FILTERS,
                "az": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            ["title"],
        ),
    ),
    Tool(
        name="chaos_terminate_instances",
        description=(
            "Generate an experiment terminating EC2 instances "
            "(chaosaws.ec2.actions.terminate_instances). Irreversible."
        ),
        inputSchema=_schema(
            {"instance_ids": _STRING_LIST, "filters": _FILTERS, "az": {"type": "string"}},
            ["title"],
        ),
    ),
    Tool(
        name="chaos_restart_instances",
        description=(
            "Generate an experiment restarting EC2 instances "
            "(chaosaws.ec2.actions.restart_instances). Replaces chaos_reboot_instances."
        ),
        inputSchema=_schema(
            {"instance_ids": _STRING_LIST, "filters": _FILTERS, "az": {"type": "string"}},
            ["title"],
        ),
    ),
    Tool(
        name="chaos_detach_random_volume",
        description=(
            "Generate an experiment detaching a random EBS volume "
            "(chaosaws.ec2.actions.detach_random_volume). Replaces chaos_detach_volumes."
        ),
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "filters": _FILTERS,
                "force": {"type": "boolean", "default": True},
            },
            ["title"],
        ),
    ),
    # ---------------------------------------------------------------------- ASG
    Tool(
        name="chaos_suspend_asg_processes",
        description=(
            "Generate an experiment suspending Auto Scaling group processes "
            "(chaosaws.asg.actions.suspend_processes) with a resume_processes rollback."
        ),
        inputSchema=_schema(
            {
                "asg_names": _STRING_LIST,
                "tags": {**_KEY_VALUE_TAGS, "description": "Tags selecting the ASGs"},
                "process_names": {
                    **_STRING_LIST,
                    "description": (
                        "Launch, Terminate, HealthCheck, ReplaceUnhealthy, AZRebalance, "
                        "AlarmNotification, ScheduledActions, AddToLoadBalancer, InstanceRefresh"
                    ),
                },
            },
            ["title"],
        ),
    ),
    Tool(
        name="chaos_terminate_random_instances",
        description=(
            "Generate an experiment terminating random Auto Scaling group instances "
            "(chaosaws.asg.actions.terminate_random_instances). Provide exactly one of "
            "instance_count or instance_percent."
        ),
        inputSchema=_schema(
            {
                "asg_names": _STRING_LIST,
                "tags": _KEY_VALUE_TAGS,
                "instance_count": {"type": "integer", "minimum": 1},
                "instance_percent": {"type": "integer", "minimum": 1, "maximum": 100},
                "az": {"type": "string"},
            },
            ["title"],
        ),
    ),
    # ---------------------------------------------------------------------- SSM
    Tool(
        name="chaos_ssm_send_command",
        description=(
            "Generate an experiment running commands through SSM "
            "(chaosaws.ssm.actions.send_command). Commands run as root."
        ),
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "document_name": {"type": "string", "default": "AWS-RunShellScript"},
                "commands": _STRING_LIST,
                "timeout_seconds": {"type": "integer", "default": 600},
            },
            ["title", "instance_ids", "commands"],
        ),
    ),
    Tool(
        name="chaos_ssm_stress_cpu",
        description="Generate a CPU stress experiment through SSM (stress-ng or stress).",
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "cpu_cores": {"type": "integer", "default": 2, "minimum": 1},
                "duration_seconds": {"type": "integer", "default": 300, "minimum": 1},
            },
            ["title", "instance_ids"],
        ),
    ),
    Tool(
        name="chaos_ssm_fill_disk",
        description="Generate a disk fill experiment through SSM, with cleanup on rollback.",
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "path": {"type": "string", "default": "/tmp"},
                "size_mb": {"type": "integer", "default": 1024, "minimum": 1},
                "duration_seconds": {"type": "integer", "default": 600, "minimum": 1},
            },
            ["title", "instance_ids"],
        ),
    ),
    Tool(
        name="chaos_ssm_kill_process",
        description="Generate an experiment killing a process through SSM (pkill).",
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "process_name": {"type": "string"},
                "signal": {
                    "type": "string",
                    "enum": sorted(builder.SIGNALS_ALLOWED),
                    "default": "SIGKILL",
                },
            },
            ["title", "instance_ids", "process_name"],
        ),
    ),
    Tool(
        name="chaos_simulate_network_latency",
        description=(
            "Generate a network latency experiment through SSM using tc netem, "
            "with the qdisc removed on rollback. Requires iproute2 on the instances."
        ),
        inputSchema=_schema(
            {
                "instance_ids": _STRING_LIST,
                "latency_ms": {"type": "integer", "default": 100, "minimum": 1},
                "jitter_ms": {"type": "integer", "default": 0, "minimum": 0},
                "duration_seconds": {"type": "integer", "default": 300, "minimum": 1},
                "interface": {"type": "string", "default": "eth0"},
            },
            ["title", "instance_ids"],
        ),
    ),
    # ------------------------------------------------------------ Security groups
    Tool(
        name="chaos_modify_security_groups",
        description=(
            "Generate an experiment revoking or authorising a security group ingress rule "
            "(chaosaws.ec2.actions.{revoke,authorize}_security_group_ingress). "
            "The inverse action is generated as rollback."
        ),
        inputSchema=_schema(
            {
                "security_group_ids": _STRING_LIST,
                "action": {"type": "string", "enum": ["revoke", "authorize"]},
                "ip_protocol": {"type": "string", "enum": ["tcp", "udp", "icmp", "-1"]},
                "from_port": {"type": "integer", "minimum": -1, "maximum": 65535},
                "to_port": {"type": "integer", "minimum": -1, "maximum": 65535},
                "cidr_ip": {"type": "string", "description": "e.g. 10.0.0.0/16"},
                "ingress_security_group_id": {"type": "string"},
            },
            ["title", "security_group_ids", "action", "ip_protocol", "from_port", "to_port"],
        ),
    ),
    # ---------------------------------------------------------------------- RDS
    Tool(
        name="chaos_reboot_db_instance",
        description="Generate an experiment rebooting an RDS instance.",
        inputSchema=_schema(
            {
                "db_instance_identifier": {"type": "string"},
                "force_failover": {"type": "boolean", "default": False},
            },
            ["title", "db_instance_identifier"],
        ),
    ),
    Tool(
        name="chaos_failover_db_cluster",
        description="Generate an experiment failing over an RDS cluster.",
        inputSchema=_schema(
            {
                "db_cluster_identifier": {"type": "string"},
                "target_db_instance_identifier": {"type": "string"},
            },
            ["title", "db_cluster_identifier"],
        ),
    ),
    # ------------------------------------------------------------- Load balancing
    Tool(
        name="chaos_deregister_target",
        description=(
            "Generate an experiment deregistering a random healthy target from a target "
            "group (chaosaws.elbv2.actions.deregister_target). Takes a target group name."
        ),
        inputSchema=_schema(
            {
                "target_group_name": {"type": "string"},
                "target_group_arn": {
                    "type": "string",
                    "description": "Accepted for convenience; the name is extracted from it",
                },
                "target_ids": {**_STRING_LIST, "description": "Ignored, kept for compatibility"},
            },
            ["title"],
        ),
    ),
    # ------------------------------------------------------------------ Lifecycle
    Tool(
        name="chaos_run_experiment",
        description=(
            "Run a Chaos Toolkit experiment. dry_run defaults to true (chaos run --dry "
            "activities); a real run additionally requires confirm_destructive=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "experiment_file": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "confirm_destructive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Must be true to really execute (dry_run=false)",
                },
                "journal_path": {"type": "string"},
                "rollback_strategy": {
                    "type": "string",
                    "enum": ["default", "always", "never", "deviated"],
                    "default": "default",
                },
                "working_directory": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 3600, "minimum": 1},
            },
            "required": ["experiment_file"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="chaos_validate_experiment",
        description="Validate a Chaos Toolkit experiment file (JSON parse plus chaos validate).",
        inputSchema={
            "type": "object",
            "properties": {
                "experiment_file": {"type": "string"},
                "working_directory": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 120, "minimum": 1},
            },
            "required": ["experiment_file"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="chaos_rollback_from_state",
        description=(
            "Roll back an AZ failure using the state files written by fail_az. The "
            "resource type is detected from the state file contents."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "state_files": _STRING_LIST,
                "resource_type": {
                    "type": "string",
                    "enum": ["ec2", "asg"],
                    "description": "Override the detected resource type",
                },
                "working_directory": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 600, "minimum": 1},
            },
            "required": ["state_files"],
            "additionalProperties": False,
        },
    ),
]


def tool_names() -> set[str]:
    """Every tool name accepted by the server, including deprecated aliases."""
    return {tool.name for tool in TOOLS} | set(ALIASES)


def resolve(name: str) -> str:
    """Map a possibly deprecated tool name onto its current name."""
    return ALIASES.get(name, name)
