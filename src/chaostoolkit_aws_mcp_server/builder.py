"""Experiment generators.

Every generator maps a tool call onto activities that really exist in
``chaosaws`` (chaostoolkit-aws) or ``azchaosaws``
(aws-az-failure-chaostoolkit). Argument names follow the signatures of those
functions, and anything not accepted by the target function is rejected instead
of being forwarded blindly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import safety
from .models import ActionConfig, ExperimentConfig, HttpProbeConfig, ProbeConfig

Probe = ProbeConfig | HttpProbeConfig

EC2_ACTIONS = "chaosaws.ec2.actions"
ASG_ACTIONS = "chaosaws.asg.actions"
SSM_ACTIONS = "chaosaws.ssm.actions"
RDS_ACTIONS = "chaosaws.rds.actions"
ELBV2_ACTIONS = "chaosaws.elbv2.actions"
AZ_EC2_ACTIONS = "azchaosaws.ec2.actions"
AZ_ASG_ACTIONS = "azchaosaws.asg.actions"

SHELL_DOCUMENT = "AWS-RunShellScript"

ASG_PROCESSES = frozenset(
    {
        "Launch",
        "Terminate",
        "HealthCheck",
        "ReplaceUnhealthy",
        "AZRebalance",
        "AlarmNotification",
        "ScheduledActions",
        "AddToLoadBalancer",
        "InstanceRefresh",
    }
)

SIGNALS_ALLOWED = safety.SIGNALS

HTTP_URL = re.compile(r"^https?://[^\s\"']+$")
TARGET_GROUP_ARN = re.compile(
    r"^arn:aws[a-z-]*:elasticloadbalancing:[^:]+:\d+:targetgroup/([^/]+)/"
)

DESTRUCTIVE_NOTE = (
    "This experiment changes live AWS resources. Review it, then run it with "
    "chaos_run_experiment using dry_run=true first."
)


@dataclass(frozen=True)
class GeneratedExperiment:
    """The result of a generation tool: where it was written and what it contains."""

    path: Path
    experiment: dict[str, Any]
    warnings: tuple[str, ...] = field(default=())

    def to_text(self) -> str:
        """Render the human readable payload returned to the MCP client."""
        lines = [f"Generated experiment: {self.path}"]
        lines.extend(f"WARNING: {warning}" for warning in self.warnings)
        lines.append("")
        lines.append(json.dumps(self.experiment, indent=2))
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Experiment assembly
# --------------------------------------------------------------------------- #
def build_probe(probe: Probe) -> dict[str, Any]:
    """Serialise a probe into Chaos Toolkit activity form."""
    if isinstance(probe, HttpProbeConfig):
        return {
            "type": probe.type,
            "name": probe.name,
            "tolerance": probe.expected_status,
            "provider": {
                "type": "http",
                "url": probe.url,
                "method": probe.method,
                "timeout": probe.timeout,
                "verify_tls": probe.verify_tls,
            },
        }
    return {
        "type": probe.type,
        "name": probe.name,
        "provider": {
            "type": "python",
            "module": probe.module,
            "func": probe.func,
            "arguments": probe.arguments,
        },
        "tolerance": probe.tolerance,
    }


def build_activity(action: ActionConfig) -> dict[str, Any]:
    """Serialise an action into Chaos Toolkit activity form."""
    return {
        "type": action.type,
        "name": action.name,
        "provider": {
            "type": "python",
            "module": action.module,
            "func": action.func,
            "arguments": action.arguments,
        },
    }


def generate_experiment_json(
    config: ExperimentConfig,
    probes: Sequence[Probe],
    actions: Sequence[ActionConfig],
    rollbacks: Sequence[ActionConfig],
) -> dict[str, Any]:
    """Assemble a complete Chaos Toolkit experiment document."""
    experiment: dict[str, Any] = {
        "version": "1.0.0",
        "title": config.title,
        "description": config.description,
        "tags": list(config.tags),
        "configuration": {"aws_region": config.aws_region},
        "method": [build_activity(action) for action in actions],
        "rollbacks": [build_activity(rollback) for rollback in rollbacks],
    }
    if probes:
        experiment["steady-state-hypothesis"] = {
            "title": "System is in steady state",
            "probes": [build_probe(probe) for probe in probes],
        }
    return experiment


# --------------------------------------------------------------------------- #
# Shared argument handling
# --------------------------------------------------------------------------- #
def _experiment_config(args: dict[str, Any], description: str) -> ExperimentConfig:
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise safety.ValidationError("title is required")
    region = args.get("aws_region")
    tags = args.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise safety.ValidationError("tags must be a list of strings")
    kwargs: dict[str, Any] = {"title": title.strip(), "description": description, "tags": tags}
    if region is not None:
        kwargs["aws_region"] = safety.match(safety.AWS_NAME, region, "aws_region")
    return ExperimentConfig(**kwargs)


def _health_probes(args: dict[str, Any]) -> list[Probe]:
    url = args.get("health_check_url")
    if not url:
        return []
    validated = safety.match(HTTP_URL, url, "health_check_url")
    status = safety.integer(
        args.get("health_check_status"),
        "health_check_status",
        minimum=100,
        maximum=599,
        default=200,
    )
    timeout = safety.integer(
        args.get("health_check_timeout"),
        "health_check_timeout",
        minimum=1,
        maximum=300,
        default=3,
    )
    method = safety.choice(
        args.get("health_check_method"),
        {"GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"},
        "health_check_method",
        default="GET",
    )
    # Endpoints behind a load balancer often redirect to HTTPS with a certificate
    # that does not match the load balancer hostname, which fails verification.
    verify_tls = safety.boolean(
        args.get("health_check_verify_tls"), "health_check_verify_tls", default=True
    )
    return [
        HttpProbeConfig(
            name="health-check",
            url=validated,
            method=method,
            expected_status=status,
            timeout=float(timeout),
            verify_tls=verify_tls,
        )
    ]


def _state_path(args: dict[str, Any], default: str) -> tuple[str, Path]:
    """Resolve the fail_az state file.

    The reference embedded in the experiment is absolute on purpose: ``chaos run``
    resolves relative paths against its own working directory, which is not
    necessarily the workdir, and a state file that ``recover_az`` cannot find
    means the rollback silently does nothing.
    """
    path = safety.resolve_output_path(args.get("state_path"), default)
    return str(path), path


def _finalise(
    args: dict[str, Any],
    default_output: str,
    config: ExperimentConfig,
    probes: Sequence[Probe],
    actions: Sequence[ActionConfig],
    rollbacks: Sequence[ActionConfig] = (),
    warnings: Sequence[str] = (),
) -> GeneratedExperiment:
    """Validate the output path, tag the experiment and write it to disk."""
    collected = list(warnings)
    funcs = [action.func for action in actions]
    if safety.is_destructive(funcs):
        if "destructive" not in config.tags:
            config.tags.append("destructive")
        collected.append(DESTRUCTIVE_NOTE)
    if not rollbacks:
        collected.append(
            "No rollback activity could be generated for this action; "
            "recovery has to be handled manually."
        )
    experiment = generate_experiment_json(config, probes, actions, rollbacks)
    path = safety.resolve_output_path(args.get("output_file"), default_output)
    safety.write_json(path, experiment)
    return GeneratedExperiment(path=path, experiment=experiment, warnings=tuple(collected))


def _ssm_send_command(
    name: str,
    instance_ids: list[str],
    commands: list[str],
    timeout_seconds: int | None = None,
) -> ActionConfig:
    """Build a ``chaosaws.ssm.actions.send_command`` activity.

    ``send_command`` takes ``targets``, not ``instance_ids``.
    """
    arguments: dict[str, Any] = {
        "document_name": SHELL_DOCUMENT,
        "targets": [{"Key": "InstanceIds", "Values": instance_ids}],
        "parameters": {"commands": commands},
    }
    if timeout_seconds is not None:
        arguments["timeout_seconds"] = timeout_seconds
    return ActionConfig(name=name, module=SSM_ACTIONS, func="send_command", arguments=arguments)


def _instance_ids(args: dict[str, Any]) -> list[str]:
    return safety.match_all(
        safety.INSTANCE_ID,
        safety.require(args.get("instance_ids"), "instance_ids"),
        "instance_ids",
    )


# --------------------------------------------------------------------------- #
# AZ failure (aws-az-failure-chaostoolkit)
# --------------------------------------------------------------------------- #
def generate_az_failure_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``azchaosaws.ec2.actions.fail_az`` with a matching ``recover_az`` rollback."""
    az = safety.match(safety.AVAILABILITY_ZONE, safety.require(args.get("az"), "az"), "az")
    failure_type = safety.choice(
        args.get("failure_type"), {"network", "instance"}, "failure_type", default="network"
    )
    dry_run = safety.boolean(args.get("dry_run"), "dry_run", default=True)
    state_ref, _ = _state_path(args, "./fail_az.ec2.json")
    arguments: dict[str, Any] = {
        "az": az,
        "dry_run": dry_run,
        "failure_type": failure_type,
        "state_path": state_ref,
    }
    if args.get("filters"):
        arguments["filters"] = safety.tag_filters(args["filters"], "filters")

    warnings: list[str] = []
    if dry_run:
        warnings.append(
            "dry_run is enabled: fail_az only performs read-only calls, and "
            "recover_az refuses to roll back a state file produced by a dry run. "
            "Pass dry_run=false once the experiment has been reviewed."
        )
    # fail_az applies the filters to different resources depending on the failure
    # type, so a tag that only exists on instances silently matches no subnets.
    filtered = "subnets (describe_subnets)" if failure_type == "network" else "instances"
    if args.get("filters"):
        warnings.append(
            f"With failure_type='{failure_type}' the filters are applied to {filtered}; "
            "tag filters must match tags on those resources or fail_az reports "
            "'No subnets found!' / no instances."
        )
    else:
        warnings.append(
            f"fail_az adds the default filter tag:AZ_FAILURE=True and applies it to "
            f"{filtered}; tag those resources or pass your own filters."
        )

    return _finalise(
        args,
        "./az-failure-experiment.json",
        _experiment_config(args, f"EC2 availability zone failure in {az}"),
        _health_probes(args),
        [
            ActionConfig(
                name="fail-az", module=AZ_EC2_ACTIONS, func="fail_az", arguments=arguments
            )
        ],
        [
            ActionConfig(
                name="recover-az",
                module=AZ_EC2_ACTIONS,
                func="recover_az",
                arguments={"state_path": state_ref},
            )
        ],
        warnings,
    )


def generate_asg_az_failure_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``azchaosaws.asg.actions.fail_az`` with a matching ``recover_az`` rollback."""
    az = safety.match(safety.AVAILABILITY_ZONE, safety.require(args.get("az"), "az"), "az")
    dry_run = safety.boolean(args.get("dry_run"), "dry_run", default=True)
    tags = safety.key_value_tags(
        args.get("asg_tags") or [{"Key": "AZ_FAILURE", "Value": "True"}], "asg_tags"
    )
    state_ref, _ = _state_path(args, "./fail_az.asg.json")

    warnings: list[str] = []
    if dry_run:
        warnings.append(
            "dry_run is enabled: fail_az only performs read-only calls, and "
            "recover_az refuses to roll back a state file produced by a dry run. "
            "Pass dry_run=false once the experiment has been reviewed."
        )

    return _finalise(
        args,
        "./asg-az-failure-experiment.json",
        _experiment_config(args, f"Auto Scaling group availability zone failure in {az}"),
        _health_probes(args),
        [
            ActionConfig(
                name="fail-asg-az",
                module=AZ_ASG_ACTIONS,
                func="fail_az",
                arguments={
                    "az": az,
                    "dry_run": dry_run,
                    "tags": tags,
                    "state_path": state_ref,
                },
            )
        ],
        [
            ActionConfig(
                name="recover-asg-az",
                module=AZ_ASG_ACTIONS,
                func="recover_az",
                arguments={"state_path": state_ref},
            )
        ],
        warnings,
    )


def generate_isolate_az_network_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Network isolation of an AZ, scoped to a VPC.

    ``azchaosaws`` has no ``isolate_az_network`` function; network isolation is
    ``fail_az(failure_type="network")`` with a ``vpc-id`` filter.
    """
    az = safety.match(safety.AVAILABILITY_ZONE, safety.require(args.get("az"), "az"), "az")
    vpc_id = safety.match(safety.VPC_ID, safety.require(args.get("vpc_id"), "vpc_id"), "vpc_id")
    dry_run = safety.boolean(args.get("dry_run"), "dry_run", default=True)
    state_ref, _ = _state_path(args, "./isolate_az.ec2.json")

    filters: list[dict[str, Any]] = [{"Name": "vpc-id", "Values": [vpc_id]}]
    if args.get("filters"):
        filters.extend(safety.tag_filters(args["filters"], "filters"))

    return _finalise(
        args,
        "./isolate-az-experiment.json",
        _experiment_config(args, f"Isolate network of {az} in {vpc_id}"),
        _health_probes(args),
        [
            ActionConfig(
                name="isolate-az-network",
                module=AZ_EC2_ACTIONS,
                func="fail_az",
                arguments={
                    "az": az,
                    "dry_run": dry_run,
                    "failure_type": "network",
                    "filters": filters,
                    "state_path": state_ref,
                },
            )
        ],
        [
            ActionConfig(
                name="recover-az",
                module=AZ_EC2_ACTIONS,
                func="recover_az",
                arguments={"state_path": state_ref},
            )
        ],
        [
            "Implemented as fail_az(failure_type='network'); subnets in the AZ are "
            "associated with a deny-all network ACL.",
        ],
    )


def generate_az_partition_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Approximate an AZ network partition with ``fail_az(failure_type='network')``."""
    az = safety.match(safety.AVAILABILITY_ZONE, safety.require(args.get("az"), "az"), "az")
    partition_type = safety.choice(
        args.get("partition_type"), {"partial", "complete"}, "partition_type", default="partial"
    )
    dry_run = safety.boolean(args.get("dry_run"), "dry_run", default=True)
    state_ref, _ = _state_path(args, "./az_partition.ec2.json")

    arguments: dict[str, Any] = {
        "az": az,
        "dry_run": dry_run,
        "failure_type": "network",
        "state_path": state_ref,
    }
    if partition_type == "partial":
        filters = safety.tag_filters(
            safety.require(args.get("filters"), "filters (required for a partial partition)"),
            "filters",
        )
        arguments["filters"] = filters

    return _finalise(
        args,
        "./az-partition-experiment.json",
        _experiment_config(args, f"{partition_type.capitalize()} network partition of {az}"),
        _health_probes(args),
        [
            ActionConfig(
                name="partition-az",
                module=AZ_EC2_ACTIONS,
                func="fail_az",
                arguments=arguments,
            )
        ],
        [
            ActionConfig(
                name="recover-az",
                module=AZ_EC2_ACTIONS,
                func="recover_az",
                arguments={"state_path": state_ref},
            )
        ],
        [
            "A partition is approximated by denying traffic on the subnets selected "
            "by the filters; AWS offers no true intra-AZ partition primitive.",
        ],
    )


# --------------------------------------------------------------------------- #
# EC2
# --------------------------------------------------------------------------- #
def _ec2_targeting(args: dict[str, Any], *, allow_az: bool = True) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if args.get("instance_ids"):
        arguments["instance_ids"] = safety.match_all(
            safety.INSTANCE_ID, args["instance_ids"], "instance_ids"
        )
    if args.get("filters"):
        arguments["filters"] = safety.tag_filters(args["filters"], "filters")
    if allow_az and args.get("az"):
        arguments["az"] = safety.match(safety.AVAILABILITY_ZONE, args["az"], "az")
    if not arguments:
        raise safety.ValidationError("provide at least one of instance_ids, filters or az")
    return arguments


def generate_stop_instances_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.ec2.actions.stop_instances``, rolled back by ``start_instances``."""
    arguments = _ec2_targeting(args)
    arguments["force"] = safety.boolean(args.get("force"), "force", default=False)
    rollback_arguments = {k: v for k, v in arguments.items() if k != "force"}
    return _finalise(
        args,
        "./stop-instances-experiment.json",
        _experiment_config(args, "Stop EC2 instances"),
        _health_probes(args),
        [
            ActionConfig(
                name="stop-instances",
                module=EC2_ACTIONS,
                func="stop_instances",
                arguments=arguments,
            )
        ],
        [
            ActionConfig(
                name="start-instances",
                module=EC2_ACTIONS,
                func="start_instances",
                arguments=rollback_arguments,
            )
        ],
    )


def generate_terminate_instances_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.ec2.actions.terminate_instances`` (irreversible)."""
    return _finalise(
        args,
        "./terminate-instances-experiment.json",
        _experiment_config(args, "Terminate EC2 instances"),
        _health_probes(args),
        [
            ActionConfig(
                name="terminate-instances",
                module=EC2_ACTIONS,
                func="terminate_instances",
                arguments=_ec2_targeting(args),
            )
        ],
        warnings=[
            "Termination cannot be rolled back. Only target instances managed by an "
            "Auto Scaling group or another replacement mechanism."
        ],
    )


def generate_restart_instances_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.ec2.actions.restart_instances`` (the real name of ``reboot``)."""
    return _finalise(
        args,
        "./restart-instances-experiment.json",
        _experiment_config(args, "Restart EC2 instances"),
        _health_probes(args),
        [
            ActionConfig(
                name="restart-instances",
                module=EC2_ACTIONS,
                func="restart_instances",
                arguments=_ec2_targeting(args),
            )
        ],
        warnings=["Instances come back on their own; no rollback activity is needed."],
    )


def generate_detach_volume_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.ec2.actions.detach_random_volume``.

    ``chaosaws`` has no ``detach_volumes``; volumes are picked at random from the
    selected instances, so explicit volume ids are not supported.
    """
    arguments = _ec2_targeting(args, allow_az=False)
    arguments["force"] = safety.boolean(args.get("force"), "force", default=True)
    return _finalise(
        args,
        "./detach-volume-experiment.json",
        _experiment_config(args, "Detach a random EBS volume"),
        _health_probes(args),
        [
            ActionConfig(
                name="detach-random-volume",
                module=EC2_ACTIONS,
                func="detach_random_volume",
                arguments=arguments,
            )
        ],
        warnings=[
            "detach_random_volume picks the volume itself; reattaching is a manual "
            "step (chaosaws.ec2.actions.attach_volume).",
        ],
    )


def generate_ec2_actions_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Generic EC2 instance action, restricted to functions that exist."""
    action_type = safety.choice(
        args.get("action_type"),
        {"stop_instances", "terminate_instances", "restart_instances"},
        "action_type",
    )
    generators = {
        "stop_instances": generate_stop_instances_experiment,
        "terminate_instances": generate_terminate_instances_experiment,
        "restart_instances": generate_restart_instances_experiment,
    }
    payload = dict(args)
    payload.setdefault("output_file", "./ec2-chaos-experiment.json")
    return generators[action_type](payload)


# --------------------------------------------------------------------------- #
# Auto Scaling groups
# --------------------------------------------------------------------------- #
def _asg_targeting(args: dict[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if args.get("asg_names"):
        arguments["asg_names"] = safety.match_all(safety.AWS_NAME, args["asg_names"], "asg_names")
    if args.get("tags"):
        arguments["tags"] = safety.key_value_tags(args["tags"], "tags")
    if not arguments:
        raise safety.ValidationError("provide either asg_names or tags")
    return arguments


def generate_suspend_asg_processes_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.asg.actions.suspend_processes`` with a ``resume_processes`` rollback."""
    arguments = _asg_targeting(args)
    process_names = args.get("process_names") or args.get("scaling_processes")
    if process_names:
        validated = safety.match_all(safety.AWS_NAME, process_names, "process_names")
        unknown = sorted(set(validated) - ASG_PROCESSES)
        if unknown:
            raise safety.ValidationError(
                f"process_names contains unknown processes {unknown}; "
                f"valid values are {sorted(ASG_PROCESSES)}"
            )
        arguments["process_names"] = validated
    return _finalise(
        args,
        "./suspend-asg-experiment.json",
        _experiment_config(args, "Suspend Auto Scaling group processes"),
        _health_probes(args),
        [
            ActionConfig(
                name="suspend-processes",
                module=ASG_ACTIONS,
                func="suspend_processes",
                arguments=arguments,
            )
        ],
        [
            ActionConfig(
                name="resume-processes",
                module=ASG_ACTIONS,
                func="resume_processes",
                arguments=dict(arguments),
            )
        ],
    )


def generate_terminate_random_instances_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.asg.actions.terminate_random_instances``."""
    arguments = _asg_targeting(args)
    count = args.get("instance_count")
    percent = args.get("instance_percent")
    if (count is None) == (percent is None):
        raise safety.ValidationError("provide exactly one of instance_count or instance_percent")
    if count is not None:
        arguments["instance_count"] = safety.integer(
            count, "instance_count", minimum=1, maximum=100, default=1
        )
    else:
        arguments["instance_percent"] = safety.integer(
            percent, "instance_percent", minimum=1, maximum=100, default=10
        )
    if args.get("az") or args.get("az_name"):
        arguments["az"] = safety.match(
            safety.AVAILABILITY_ZONE, args.get("az") or args.get("az_name"), "az"
        )
    return _finalise(
        args,
        "./terminate-random-instances-experiment.json",
        _experiment_config(args, "Terminate random Auto Scaling group instances"),
        _health_probes(args),
        [
            ActionConfig(
                name="terminate-random-instances",
                module=ASG_ACTIONS,
                func="terminate_random_instances",
                arguments=arguments,
            )
        ],
        warnings=["The Auto Scaling group is expected to replace the terminated instances."],
    )


# --------------------------------------------------------------------------- #
# SSM
# --------------------------------------------------------------------------- #
def generate_ssm_send_command_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.ssm.actions.send_command`` with caller supplied commands."""
    instance_ids = _instance_ids(args)
    commands = safety.require(args.get("commands"), "commands")
    if not isinstance(commands, list) or any(not isinstance(item, str) for item in commands):
        raise safety.ValidationError("commands must be a list of strings")
    document_name = safety.match(
        safety.AWS_NAME, args.get("document_name") or SHELL_DOCUMENT, "document_name"
    )
    timeout_seconds = safety.integer(
        args.get("timeout_seconds"), "timeout_seconds", minimum=30, maximum=2592000, default=600
    )
    action = _ssm_send_command("ssm-send-command", instance_ids, list(commands), timeout_seconds)
    action.arguments["document_name"] = document_name
    return _finalise(
        args,
        "./ssm-command-experiment.json",
        _experiment_config(args, "Run commands through SSM"),
        _health_probes(args),
        [action],
        warnings=[
            "Commands are passed through verbatim and run with root privileges on "
            "the target instances; review them before running the experiment.",
        ],
    )


def generate_ssm_cpu_stress_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """CPU pressure through SSM, using stress-ng when available."""
    instance_ids = _instance_ids(args)
    cores = safety.integer(args.get("cpu_cores"), "cpu_cores", minimum=1, maximum=256, default=2)
    duration = safety.integer(
        args.get("duration_seconds"), "duration_seconds", minimum=1, maximum=86400, default=300
    )
    command = (
        f"if command -v stress-ng >/dev/null 2>&1; then "
        f"stress-ng --cpu {cores} --timeout {duration}s; "
        f"elif command -v stress >/dev/null 2>&1; then "
        f"stress --cpu {cores} --timeout {duration}s; "
        f"else echo 'neither stress-ng nor stress is installed' >&2; exit 1; fi"
    )
    return _finalise(
        args,
        "./ssm-cpu-stress-experiment.json",
        _experiment_config(args, f"CPU stress on {cores} core(s) for {duration}s"),
        _health_probes(args),
        [_ssm_send_command("ssm-cpu-stress", instance_ids, [command], duration + 120)],
        [
            _ssm_send_command(
                "stop-cpu-stress",
                instance_ids,
                ["pkill -f stress-ng || pkill -f stress || true"],
            )
        ],
    )


def generate_ssm_fill_disk_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Disk pressure through SSM, with the fill file removed on rollback."""
    instance_ids = _instance_ids(args)
    target_dir = safety.shell_path(args.get("path") or "/tmp", "path")
    size_mb = safety.integer(
        args.get("size_mb"), "size_mb", minimum=1, maximum=1048576, default=1024
    )
    duration = safety.integer(
        args.get("duration_seconds"), "duration_seconds", minimum=1, maximum=86400, default=600
    )
    fill_file = safety.quote(f"{target_dir.rstrip('/')}/chaos_fill")
    commands = [
        f"dd if=/dev/zero of={fill_file} bs=1M count={size_mb}",
        f"sleep {duration}",
        f"rm -f {fill_file}",
    ]
    return _finalise(
        args,
        "./ssm-fill-disk-experiment.json",
        _experiment_config(args, f"Fill {size_mb}MB of disk under {target_dir}"),
        _health_probes(args),
        [_ssm_send_command("ssm-fill-disk", instance_ids, commands, duration + 300)],
        [_ssm_send_command("remove-fill-file", instance_ids, [f"rm -f {fill_file}"])],
    )


def generate_ssm_kill_process_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Kill a process through SSM."""
    instance_ids = _instance_ids(args)
    process_name = safety.match(
        safety.PROCESS_NAME,
        safety.require(args.get("process_name"), "process_name"),
        "process_name",
    )
    signal_name = safety.choice(args.get("signal"), SIGNALS_ALLOWED, "signal", default="SIGKILL")
    command = f"pkill -{signal_name[3:]} -x {safety.quote(process_name)}"
    return _finalise(
        args,
        "./ssm-kill-process-experiment.json",
        _experiment_config(args, f"Send {signal_name} to {process_name}"),
        _health_probes(args),
        [_ssm_send_command("ssm-kill-process", instance_ids, [command])],
        warnings=[
            f"Restarting {process_name} is not automated; make sure a supervisor "
            "(systemd, container runtime, ...) brings it back.",
        ],
    )


def generate_network_latency_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Network latency through SSM and ``tc netem``.

    ``chaosaws`` has no network latency action, so latency is injected with
    ``tc`` on the instance itself.
    """
    instance_ids = _instance_ids(args)
    latency_ms = safety.integer(
        args.get("latency_ms"), "latency_ms", minimum=1, maximum=60000, default=100
    )
    jitter_ms = safety.integer(
        args.get("jitter_ms"), "jitter_ms", minimum=0, maximum=60000, default=0
    )
    duration = safety.integer(
        args.get("duration_seconds"), "duration_seconds", minimum=1, maximum=86400, default=300
    )
    interface = safety.match(
        safety.NETWORK_INTERFACE, args.get("interface") or "eth0", "interface"
    )
    device = safety.quote(interface)
    jitter = f" {jitter_ms}ms" if jitter_ms else ""
    remove = f"tc qdisc del dev {device} root netem || true"
    commands = [
        f"tc qdisc add dev {device} root netem delay {latency_ms}ms{jitter}",
        f"sleep {duration}",
        remove,
    ]
    return _finalise(
        args,
        "./network-latency-experiment.json",
        _experiment_config(args, f"Add {latency_ms}ms latency on {interface}"),
        _health_probes(args),
        [_ssm_send_command("inject-latency", instance_ids, commands, duration + 300)],
        [_ssm_send_command("remove-latency", instance_ids, [remove])],
        warnings=[
            "Requires the iproute2 package (tc) and root privileges on the instances. "
            "Latency applies to all traffic on the interface, including SSM itself.",
        ],
    )


# --------------------------------------------------------------------------- #
# Security groups
# --------------------------------------------------------------------------- #
def generate_modify_security_groups_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """Revoke or authorise a security group ingress rule, with the inverse as rollback."""
    group_ids = safety.match_all(
        safety.SECURITY_GROUP_ID,
        safety.require(
            args.get("security_group_ids") or args.get("group_ids"), "security_group_ids"
        ),
        "security_group_ids",
    )
    action = safety.choice(args.get("action"), {"revoke", "authorize"}, "action")
    ip_protocol = safety.choice(args.get("ip_protocol"), safety.IP_PROTOCOLS, "ip_protocol")
    from_port = safety.integer(
        args.get("from_port"), "from_port", minimum=-1, maximum=65535, default=-1
    )
    to_port = safety.integer(args.get("to_port"), "to_port", minimum=-1, maximum=65535, default=-1)
    cidr_ip = args.get("cidr_ip")
    ingress_sg = args.get("ingress_security_group_id")
    if bool(cidr_ip) == bool(ingress_sg):
        raise safety.ValidationError(
            "provide exactly one of cidr_ip or ingress_security_group_id"
        )

    shared: dict[str, Any] = {
        "ip_protocol": ip_protocol,
        "from_port": from_port,
        "to_port": to_port,
    }
    if cidr_ip:
        shared["cidr_ip"] = safety.match(safety.CIDR, cidr_ip, "cidr_ip")
    else:
        shared["ingress_security_group_id"] = safety.match(
            safety.SECURITY_GROUP_ID, ingress_sg, "ingress_security_group_id"
        )

    func = f"{action}_security_group_ingress"
    inverse = (
        "authorize_security_group_ingress"
        if action == "revoke"
        else "revoke_security_group_ingress"
    )
    actions = [
        ActionConfig(
            name=f"{action}-ingress-{group_id}",
            module=EC2_ACTIONS,
            func=func,
            arguments={"requested_security_group_id": group_id, **shared},
        )
        for group_id in group_ids
    ]
    rollbacks = [
        ActionConfig(
            name=f"restore-ingress-{group_id}",
            module=EC2_ACTIONS,
            func=inverse,
            arguments={"requested_security_group_id": group_id, **shared},
        )
        for group_id in group_ids
    ]
    return _finalise(
        args,
        "./modify-security-groups-experiment.json",
        _experiment_config(args, f"{action.capitalize()} security group ingress"),
        _health_probes(args),
        actions,
        rollbacks,
    )


# --------------------------------------------------------------------------- #
# RDS
# --------------------------------------------------------------------------- #
def generate_reboot_db_instance_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.rds.actions.reboot_db_instance``."""
    identifier = safety.match(
        safety.AWS_NAME,
        safety.require(args.get("db_instance_identifier"), "db_instance_identifier"),
        "db_instance_identifier",
    )
    force_failover = safety.boolean(args.get("force_failover"), "force_failover", default=False)
    return _finalise(
        args,
        "./reboot-db-instance-experiment.json",
        _experiment_config(args, f"Reboot RDS instance {identifier}"),
        _health_probes(args),
        [
            ActionConfig(
                name="reboot-db-instance",
                module=RDS_ACTIONS,
                func="reboot_db_instance",
                arguments={
                    "db_instance_identifier": identifier,
                    "force_failover": force_failover,
                },
            )
        ],
        warnings=["The instance recovers by itself once the reboot completes."],
    )


def generate_failover_db_cluster_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.rds.actions.failover_db_cluster``."""
    cluster = safety.match(
        safety.AWS_NAME,
        safety.require(args.get("db_cluster_identifier"), "db_cluster_identifier"),
        "db_cluster_identifier",
    )
    arguments: dict[str, Any] = {"db_cluster_identifier": cluster}
    if args.get("target_db_instance_identifier"):
        arguments["target_db_instance_identifier"] = safety.match(
            safety.AWS_NAME,
            args["target_db_instance_identifier"],
            "target_db_instance_identifier",
        )
    return _finalise(
        args,
        "./failover-db-cluster-experiment.json",
        _experiment_config(args, f"Fail over RDS cluster {cluster}"),
        _health_probes(args),
        [
            ActionConfig(
                name="failover-db-cluster",
                module=RDS_ACTIONS,
                func="failover_db_cluster",
                arguments=arguments,
            )
        ],
        warnings=[
            "Failing back means running another failover targeting the original writer.",
        ],
    )


# --------------------------------------------------------------------------- #
# Load balancing
# --------------------------------------------------------------------------- #
def generate_deregister_target_experiment(args: dict[str, Any]) -> GeneratedExperiment:
    """``chaosaws.elbv2.actions.deregister_target``.

    The real signature takes a target group *name*, not an ARN, and deregisters
    a random healthy target from it.
    """
    warnings: list[str] = []
    name = args.get("target_group_name")
    if not name and args.get("target_group_arn"):
        arn_match = TARGET_GROUP_ARN.match(str(args["target_group_arn"]))
        if not arn_match:
            raise safety.ValidationError("target_group_arn is not a valid target group ARN")
        name = arn_match.group(1)
        warnings.append(
            f"deregister_target takes a target group name; using '{name}' from the ARN."
        )
    tg_name = safety.match(
        safety.AWS_NAME,
        safety.require(name, "target_group_name"),
        "target_group_name",
    )
    if args.get("target_ids"):
        warnings.append(
            "target_ids is not supported: deregister_target picks a random healthy "
            "target from the group."
        )
    return _finalise(
        args,
        "./deregister-target-experiment.json",
        _experiment_config(args, f"Deregister a target from {tg_name}"),
        _health_probes(args),
        [
            ActionConfig(
                name="deregister-target",
                module=ELBV2_ACTIONS,
                func="deregister_target",
                arguments={"tg_name": tg_name},
            )
        ],
        warnings=[
            *warnings,
            "Re-register the target manually or let the Auto Scaling group do it.",
        ],
    )
