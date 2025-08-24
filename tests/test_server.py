"""Tests for the Chaos Toolkit AWS MCP Server"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chaostoolkit_aws_mcp_server.server import (
    ActionConfig,
    ExperimentConfig,
    ProbeConfig,
    generate_experiment_json,
    generate_az_failure_experiment,
    generate_asg_az_failure_experiment,
    generate_ec2_actions_experiment,
    validate_experiment,
)


class TestExperimentGeneration:
    """Test experiment generation functions"""

    def test_generate_experiment_json(self):
        """Test basic experiment JSON generation"""
        config = ExperimentConfig(
            title="Test Experiment",
            description="Test description",
            aws_region="us-east-1"
        )
        
        probes = [ProbeConfig(
            name="test_probe",
            module="test.module",
            func="test_func",
            arguments={"arg1": "value1"}
        )]
        
        actions = [ActionConfig(
            name="test_action",
            module="test.module",
            func="test_action_func",
            arguments={"arg2": "value2"}
        )]
        
        rollbacks = [ActionConfig(
            name="test_rollback",
            module="test.module", 
            func="test_rollback_func",
            arguments={"arg3": "value3"}
        )]
        
        result = generate_experiment_json(config, probes, actions, rollbacks)
        
        assert result["title"] == "Test Experiment"
        assert result["description"] == "Test description"
        assert result["configuration"]["aws_region"] == "us-east-1"
        assert len(result["steady-state-hypothesis"]["probes"]) == 1
        assert len(result["method"]) == 1
        assert len(result["rollbacks"]) == 1

    @pytest.mark.asyncio
    async def test_generate_az_failure_experiment(self):
        """Test AZ failure experiment generation"""
        args = {
            "title": "AZ Failure Test",
            "az": "us-east-1a",
            "failure_type": "network",
            "dry_run": False,
            "health_check_url": "http://test.com/health",
            "state_path": "./test_fail_az.ec2.json",
            "output_file": "./test_az_experiment.json",
            "aws_region": "us-east-1"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_az_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_az_failure_experiment(args)
            
            assert len(result) == 1
            assert "Generated AZ failure experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "AZ Failure Test"
            assert experiment["configuration"]["aws_region"] == "us-east-1"
            assert len(experiment["method"]) == 1
            assert experiment["method"][0]["provider"]["module"] == "azchaosaws.ec2.actions"
            assert experiment["method"][0]["provider"]["func"] == "fail_az"

    @pytest.mark.asyncio
    async def test_generate_asg_az_failure_experiment(self):
        """Test ASG AZ failure experiment generation"""
        args = {
            "title": "ASG AZ Failure Test",
            "az": "us-east-1a",
            "asg_tags": [{"Key": "Environment", "Value": "test"}],
            "dry_run": True,
            "output_file": "./test_asg_experiment.json",
            "aws_region": "us-west-2"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_asg_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_asg_az_failure_experiment(args)
            
            assert len(result) == 1
            assert "Generated ASG AZ failure experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "ASG AZ Failure Test"
            assert experiment["configuration"]["aws_region"] == "us-west-2"
            assert experiment["method"][0]["provider"]["module"] == "azchaosaws.asg.actions"

    @pytest.mark.asyncio
    async def test_generate_ec2_actions_experiment(self):
        """Test EC2 actions experiment generation"""
        args = {
            "title": "EC2 Stop Test",
            "action_type": "stop_instances",
            "instance_ids": ["i-1234567890abcdef0"],
            "az": "us-east-1a",
            "output_file": "./test_ec2_experiment.json",
            "aws_region": "us-east-1"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_ec2_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_ec2_actions_experiment(args)
            
            assert len(result) == 1
            assert "Generated EC2 stop_instances experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "EC2 Stop Test"
            assert experiment["method"][0]["provider"]["module"] == "chaosaws.ec2.actions"
            assert experiment["method"][0]["provider"]["func"] == "stop_instances"

    @pytest.mark.asyncio
    async def test_validate_experiment_success(self):
        """Test successful experiment validation"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"title": "Test", "method": []}, f)
            experiment_file = f.name
        
        try:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="Valid", stderr="")
                
                result = await validate_experiment({"experiment_file": experiment_file})
                
                assert len(result) == 1
                assert "PASSED" in result[0]["text"]
                mock_run.assert_called_once()
        finally:
            Path(experiment_file).unlink()

    @pytest.mark.asyncio
    async def test_validate_experiment_file_not_found(self):
        """Test validation with non-existent file"""
        result = await validate_experiment({"experiment_file": "./nonexistent.json"})
        
        assert len(result) == 1
        assert "Error: Experiment file not found" in result[0]["text"]


class TestConfigModels:
    """Test configuration models"""

    def test_experiment_config_defaults(self):
        """Test ExperimentConfig with defaults"""
        config = ExperimentConfig(title="Test")
        
        assert config.title == "Test"
        assert config.description == ""
        assert config.aws_region == "us-east-1"
        assert config.tags == []

    def test_probe_config(self):
        """Test ProbeConfig"""
        probe = ProbeConfig(
            name="test_probe",
            module="test.module",
            func="test_func",
            arguments={"key": "value"}
        )
        
        assert probe.name == "test_probe"
        assert probe.type == "probe"
        assert probe.module == "test.module"
        assert probe.func == "test_func"
        assert probe.arguments == {"key": "value"}
        assert probe.tolerance is True

    def test_action_config(self):
        """Test ActionConfig"""
        action = ActionConfig(
            name="test_action",
            module="test.module",
            func="test_func",
            arguments={"key": "value"}
        )
        
        assert action.name == "test_action"
        assert action.type == "action"
        assert action.module == "test.module"
        assert action.func == "test_func"
        assert action.arguments == {"key": "value"}
