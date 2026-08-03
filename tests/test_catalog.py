"""Tests for the tool catalog."""

from __future__ import annotations

from chaostoolkit_aws_mcp_server import catalog

from .conftest import SAMPLE_ARGS


class TestCatalog:
    def test_every_tool_has_a_handler(self) -> None:
        lifecycle = catalog.MANAGEMENT_TOOLS
        for tool in catalog.TOOLS:
            assert tool.name in catalog.GENERATORS or tool.name in lifecycle

    def test_every_generator_is_advertised(self) -> None:
        advertised = {tool.name for tool in catalog.TOOLS}
        assert set(catalog.GENERATORS) <= advertised

    def test_every_generator_has_sample_arguments(self) -> None:
        assert set(catalog.GENERATORS) == set(SAMPLE_ARGS)

    def test_tool_names_are_unique(self) -> None:
        names = [tool.name for tool in catalog.TOOLS]
        assert len(names) == len(set(names))

    def test_aliases_point_at_existing_tools(self) -> None:
        advertised = {tool.name for tool in catalog.TOOLS}
        for deprecated, current in catalog.ALIASES.items():
            assert deprecated not in advertised
            assert current in advertised
            assert catalog.resolve(deprecated) == current

    def test_resolve_passes_through_unknown_names(self) -> None:
        assert catalog.resolve("chaos_stop_instances") == "chaos_stop_instances"

    def test_schemas_declare_title_and_required(self) -> None:
        for tool in catalog.TOOLS:
            schema = tool.inputSchema
            assert schema["type"] == "object"
            assert "properties" in schema
            for required in schema.get("required", []):
                assert required in schema["properties"], f"{tool.name}: {required}"
            if tool.name in catalog.GENERATORS:
                assert "title" in schema["required"]
                assert "output_file" in schema["properties"]

    def test_descriptions_reference_real_modules(self) -> None:
        # Function names that do not exist in chaosaws must never be advertised.
        forbidden = (
            "chaosaws.ec2.actions.reboot_instances",
            "chaosaws.ec2.actions.detach_volumes",
            "chaosaws.ec2.actions.modify_security_groups",
            "chaosaws.ec2.actions.simulate_network_latency",
            "chaosaws.ssm.actions.kill_process",
            "chaosaws.elbv2.actions.deregister_targets",
            "azchaosaws.ec2.actions.isolate_az_network",
            "azchaosaws.ec2.actions.simulate_az_partition",
            "chaoslib.provider.http",
        )
        for tool in catalog.TOOLS:
            assert tool.description
            for name in forbidden:
                assert name not in tool.description, f"{tool.name} advertises {name}"
