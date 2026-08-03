"""Tests for the experiment generators."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from chaostoolkit_aws_mcp_server import builder, catalog, safety
from chaostoolkit_aws_mcp_server.models import ActionConfig, ExperimentConfig, HttpProbeConfig

from .conftest import INSTANCE_ID, SAMPLE_ARGS


def _activities(experiment: dict[str, Any]) -> list[dict[str, Any]]:
    return list(experiment.get("method", [])) + list(experiment.get("rollbacks", []))


class TestExperimentAssembly:
    def test_generate_experiment_json(self) -> None:
        experiment = builder.generate_experiment_json(
            ExperimentConfig(title="t", description="d", aws_region="cn-north-1", tags=["x"]),
            [HttpProbeConfig(name="health", url="https://example.com/health")],
            [ActionConfig(name="a", module="m", func="f", arguments={"k": "v"})],
            [ActionConfig(name="r", module="m", func="g", arguments={})],
        )

        assert experiment["title"] == "t"
        assert experiment["configuration"] == {"aws_region": "cn-north-1"}
        assert experiment["tags"] == ["x"]
        assert len(experiment["method"]) == 1
        assert len(experiment["rollbacks"]) == 1

    def test_http_probe_uses_http_provider(self) -> None:
        probe = builder.build_probe(
            HttpProbeConfig(name="health", url="https://example.com/health", expected_status=204)
        )

        assert probe["provider"]["type"] == "http"
        assert probe["provider"]["url"] == "https://example.com/health"
        # chaoslib compares an int tolerance against the "status" key of the result.
        assert probe["tolerance"] == 204
        assert "chaoslib.provider.http" not in json.dumps(probe)

    def test_steady_state_hypothesis_is_omitted_without_probes(self) -> None:
        experiment = builder.generate_experiment_json(
            ExperimentConfig(title="t"), [], [ActionConfig(name="a", module="m", func="f")], []
        )
        assert "steady-state-hypothesis" not in experiment


class TestGeneratedApisExist:
    """Every generated activity must resolve to a real function."""

    @pytest.mark.parametrize("tool_name", sorted(SAMPLE_ARGS))
    def test_activity_functions_exist(self, tool_name: str, workdir: Path) -> None:
        pytest.importorskip("chaosaws")
        pytest.importorskip("azchaosaws")

        generated = catalog.GENERATORS[tool_name](dict(SAMPLE_ARGS[tool_name]))

        activities = _activities(generated.experiment)
        assert activities, f"{tool_name} generated no activities"
        for activity in activities:
            provider = activity["provider"]
            module = importlib.import_module(provider["module"])
            func = getattr(module, provider["func"], None)
            assert callable(func), f"{provider['module']}.{provider['func']} does not exist"

    @pytest.mark.parametrize("tool_name", sorted(SAMPLE_ARGS))
    def test_arguments_match_signatures(self, tool_name: str, workdir: Path) -> None:
        pytest.importorskip("chaosaws")
        import inspect

        generated = catalog.GENERATORS[tool_name](dict(SAMPLE_ARGS[tool_name]))
        for activity in _activities(generated.experiment):
            provider = activity["provider"]
            module = importlib.import_module(provider["module"])
            signature = inspect.signature(getattr(module, provider["func"]))
            unknown = set(provider["arguments"]) - set(signature.parameters)
            assert not unknown, f"{provider['func']} does not accept {sorted(unknown)}"

    @pytest.mark.parametrize("tool_name", sorted(SAMPLE_ARGS))
    def test_experiment_is_written(self, tool_name: str, workdir: Path) -> None:
        generated = catalog.GENERATORS[tool_name](dict(SAMPLE_ARGS[tool_name]))

        assert generated.path.is_file()
        assert json.loads(generated.path.read_text(encoding="utf-8")) == generated.experiment
        assert generated.path.is_relative_to(workdir)


class TestAzFailure:
    def test_dry_run_defaults_to_true(self, workdir: Path) -> None:
        generated = builder.generate_az_failure_experiment({"title": "t", "az": "us-east-1a"})

        arguments = generated.experiment["method"][0]["provider"]["arguments"]
        assert arguments["dry_run"] is True
        assert any("dry_run is enabled" in warning for warning in generated.warnings)

    def test_rollback_uses_same_state_path(self, workdir: Path) -> None:
        generated = builder.generate_az_failure_experiment(
            {"title": "t", "az": "us-east-1a", "state_path": "./state/fail.json"}
        )

        method = generated.experiment["method"][0]["provider"]
        rollback = generated.experiment["rollbacks"][0]["provider"]
        assert method["arguments"]["state_path"] == "./state/fail.json"
        assert rollback["func"] == "recover_az"
        assert rollback["arguments"]["state_path"] == "./state/fail.json"

    def test_destructive_tag_and_note(self, workdir: Path) -> None:
        generated = builder.generate_az_failure_experiment(
            {"title": "t", "az": "us-east-1a", "dry_run": False}
        )

        assert "destructive" in generated.experiment["tags"]
        assert any("changes live AWS resources" in warning for warning in generated.warnings)

    def test_invalid_az_is_rejected(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="az has an invalid value"):
            builder.generate_az_failure_experiment({"title": "t", "az": "us-east"})

    def test_partial_partition_requires_filters(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="filters"):
            builder.generate_az_partition_experiment(
                {"title": "t", "az": "us-east-1a", "partition_type": "partial"}
            )


class TestEc2AndAsg:
    def test_stop_instances_has_start_rollback(self, workdir: Path) -> None:
        generated = builder.generate_stop_instances_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID], "force": True}
        )

        method = generated.experiment["method"][0]["provider"]
        rollback = generated.experiment["rollbacks"][0]["provider"]
        assert method["func"] == "stop_instances"
        assert method["arguments"]["force"] is True
        assert rollback["func"] == "start_instances"
        # start_instances has no force parameter.
        assert "force" not in rollback["arguments"]

    def test_restart_uses_real_function_name(self, workdir: Path) -> None:
        generated = builder.generate_restart_instances_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID]}
        )
        assert generated.experiment["method"][0]["provider"]["func"] == "restart_instances"

    def test_targeting_is_required(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="at least one of"):
            builder.generate_stop_instances_experiment({"title": "t"})

    def test_suspend_processes_validates_names(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="unknown processes"):
            builder.generate_suspend_asg_processes_experiment(
                {"title": "t", "asg_names": ["a"], "process_names": ["Nope"]}
            )

    def test_suspend_processes_rollback_resumes(self, workdir: Path) -> None:
        generated = builder.generate_suspend_asg_processes_experiment(
            {"title": "t", "asg_names": ["a"], "process_names": ["Launch"]}
        )
        assert generated.experiment["rollbacks"][0]["provider"]["func"] == "resume_processes"

    def test_terminate_random_requires_exactly_one_size(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="exactly one of"):
            builder.generate_terminate_random_instances_experiment(
                {"title": "t", "asg_names": ["a"], "instance_count": 1, "instance_percent": 10}
            )


class TestSsm:
    def test_send_command_uses_targets(self, workdir: Path) -> None:
        generated = builder.generate_ssm_cpu_stress_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID], "cpu_cores": 4, "duration_seconds": 60}
        )

        arguments = generated.experiment["method"][0]["provider"]["arguments"]
        assert arguments["targets"] == [{"Key": "InstanceIds", "Values": [INSTANCE_ID]}]
        assert "instance_ids" not in arguments
        assert "--cpu 4 --timeout 60s" in arguments["parameters"]["commands"][0]

    def test_fill_disk_quotes_path_and_cleans_up(self, workdir: Path) -> None:
        generated = builder.generate_ssm_fill_disk_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID], "path": "/var/tmp", "size_mb": 8}
        )

        commands = generated.experiment["method"][0]["provider"]["arguments"]["parameters"][
            "commands"
        ]
        assert commands[0] == "dd if=/dev/zero of=/var/tmp/chaos_fill bs=1M count=8"
        assert commands[-1] == "rm -f /var/tmp/chaos_fill"
        rollback = generated.experiment["rollbacks"][0]["provider"]["arguments"]
        assert rollback["parameters"]["commands"] == ["rm -f /var/tmp/chaos_fill"]

    def test_fill_disk_rejects_shell_metacharacters(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError):
            builder.generate_ssm_fill_disk_experiment(
                {"title": "t", "instance_ids": [INSTANCE_ID], "path": "/tmp; rm -rf /"}
            )

    def test_kill_process_validates_name_and_signal(self, workdir: Path) -> None:
        generated = builder.generate_ssm_kill_process_experiment(
            {
                "title": "t",
                "instance_ids": [INSTANCE_ID],
                "process_name": "nginx",
                "signal": "SIGTERM",
            }
        )
        commands = generated.experiment["method"][0]["provider"]["arguments"]["parameters"][
            "commands"
        ]
        assert commands == ["pkill -TERM -x nginx"]

        with pytest.raises(safety.ValidationError):
            builder.generate_ssm_kill_process_experiment(
                {"title": "t", "instance_ids": [INSTANCE_ID], "process_name": "a; rm -rf /"}
            )
        with pytest.raises(safety.ValidationError, match="signal"):
            builder.generate_ssm_kill_process_experiment(
                {
                    "title": "t",
                    "instance_ids": [INSTANCE_ID],
                    "process_name": "nginx",
                    "signal": "SIGBOOM",
                }
            )

    def test_network_latency_removes_qdisc_on_rollback(self, workdir: Path) -> None:
        generated = builder.generate_network_latency_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID], "latency_ms": 250, "jitter_ms": 50}
        )

        commands = generated.experiment["method"][0]["provider"]["arguments"]["parameters"][
            "commands"
        ]
        assert commands[0] == "tc qdisc add dev eth0 root netem delay 250ms 50ms"
        rollback = generated.experiment["rollbacks"][0]["provider"]["arguments"]
        assert rollback["parameters"]["commands"] == ["tc qdisc del dev eth0 root netem || true"]

    def test_interface_is_validated(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="interface"):
            builder.generate_network_latency_experiment(
                {"title": "t", "instance_ids": [INSTANCE_ID], "interface": "eth0; reboot"}
            )


class TestSecurityGroupsAndManagedServices:
    def test_revoke_generates_authorize_rollback(self, workdir: Path) -> None:
        generated = builder.generate_modify_security_groups_experiment(
            {
                "title": "t",
                "security_group_ids": ["sg-0123456789abcdef0"],
                "action": "revoke",
                "ip_protocol": "tcp",
                "from_port": 443,
                "to_port": 443,
                "cidr_ip": "10.0.0.0/16",
            }
        )

        assert (
            generated.experiment["method"][0]["provider"]["func"]
            == "revoke_security_group_ingress"
        )
        assert (
            generated.experiment["rollbacks"][0]["provider"]["func"]
            == "authorize_security_group_ingress"
        )

    def test_source_is_exclusive(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="exactly one of cidr_ip"):
            builder.generate_modify_security_groups_experiment(
                {
                    "title": "t",
                    "security_group_ids": ["sg-0123456789abcdef0"],
                    "action": "revoke",
                    "ip_protocol": "tcp",
                    "from_port": 443,
                    "to_port": 443,
                    "cidr_ip": "10.0.0.0/16",
                    "ingress_security_group_id": "sg-0123456789abcdef1",
                }
            )

    def test_deregister_target_extracts_name_from_arn(self, workdir: Path) -> None:
        arn = "arn:aws-cn:elasticloadbalancing:cn-north-1:123456789012:targetgroup/web-tg/abc123"
        generated = builder.generate_deregister_target_experiment({"title": "t", "target_group_arn": arn})

        assert generated.experiment["method"][0]["provider"]["arguments"] == {"tg_name": "web-tg"}
        assert any("target group name" in warning for warning in generated.warnings)

    def test_failover_cluster_optional_target(self, workdir: Path) -> None:
        generated = builder.generate_failover_db_cluster_experiment(
            {"title": "t", "db_cluster_identifier": "c", "target_db_instance_identifier": "i"}
        )
        arguments = generated.experiment["method"][0]["provider"]["arguments"]
        assert arguments["target_db_instance_identifier"] == "i"


class TestRegionDefaulting:
    def test_region_comes_from_environment(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AWS_REGION", "cn-north-1")
        generated = builder.generate_restart_instances_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID]}
        )
        assert generated.experiment["configuration"]["aws_region"] == "cn-north-1"

    def test_explicit_region_wins(self, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AWS_REGION", "cn-north-1")
        generated = builder.generate_restart_instances_experiment(
            {"title": "t", "instance_ids": [INSTANCE_ID], "aws_region": "eu-west-1"}
        )
        assert generated.experiment["configuration"]["aws_region"] == "eu-west-1"
