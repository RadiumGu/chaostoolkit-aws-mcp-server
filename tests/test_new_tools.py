"""Tests for new chaos toolkit tools"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from chaostoolkit_aws_mcp_server.server import (
    generate_generic_experiment,
    generate_ssm_stress_experiment,
)


class TestNewTools:
    """Test new chaos toolkit tools"""

    @pytest.mark.asyncio
    async def test_generate_generic_experiment(self):
        """Test generic experiment generation"""
        args = {
            "title": "Test Generic Experiment",
            "instance_ids": ["i-123", "i-456"],
            "force": True,
            "output_file": "./test_generic_experiment.json",
            "aws_region": "us-east-1"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_generic_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_generic_experiment(args, "chaosaws.ec2.actions", "stop_instances")
            
            assert len(result) == 1
            assert "Generated stop_instances experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "Test Generic Experiment"
            assert experiment["configuration"]["aws_region"] == "us-east-1"
            assert len(experiment["method"]) == 1
            assert experiment["method"][0]["provider"]["module"] == "chaosaws.ec2.actions"
            assert experiment["method"][0]["provider"]["func"] == "stop_instances"
            assert experiment["method"][0]["provider"]["arguments"]["instance_ids"] == ["i-123", "i-456"]
            assert experiment["method"][0]["provider"]["arguments"]["force"] is True

    @pytest.mark.asyncio
    async def test_generate_ssm_cpu_stress_experiment(self):
        """Test SSM CPU stress experiment generation"""
        args = {
            "title": "SSM CPU Stress Test",
            "instance_ids": ["i-123"],
            "cpu_cores": 4,
            "duration_seconds": 600,
            "output_file": "./test_ssm_cpu_experiment.json",
            "aws_region": "us-west-2"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_ssm_cpu_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_ssm_stress_experiment(args, "cpu")
            
            assert len(result) == 1
            assert "Generated SSM cpu stress experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "SSM CPU Stress Test"
            assert experiment["configuration"]["aws_region"] == "us-west-2"
            assert len(experiment["method"]) == 1
            assert experiment["method"][0]["provider"]["module"] == "chaosaws.ssm.actions"
            assert experiment["method"][0]["provider"]["func"] == "send_command"
            
            # Check SSM command parameters
            args_dict = experiment["method"][0]["provider"]["arguments"]
            assert args_dict["instance_ids"] == ["i-123"]
            assert args_dict["document_name"] == "AWS-RunShellScript"
            assert "stress --cpu 4 --timeout 600s" in args_dict["parameters"]["commands"][0]

    @pytest.mark.asyncio
    async def test_generate_ssm_disk_stress_experiment(self):
        """Test SSM disk stress experiment generation"""
        args = {
            "title": "SSM Disk Stress Test",
            "instance_ids": ["i-789"],
            "size_mb": 2048,
            "duration_seconds": 300,
            "path": "/var/tmp",
            "output_file": "./test_ssm_disk_experiment.json",
            "aws_region": "eu-west-1"
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "test_ssm_disk_experiment.json"
            args["output_file"] = str(output_file)
            
            result = await generate_ssm_stress_experiment(args, "disk")
            
            assert len(result) == 1
            assert "Generated SSM disk stress experiment" in result[0]["text"]
            assert output_file.exists()
            
            # Verify the generated experiment file
            with open(output_file) as f:
                experiment = json.load(f)
            
            assert experiment["title"] == "SSM Disk Stress Test"
            assert experiment["configuration"]["aws_region"] == "eu-west-1"
            
            # Check SSM command parameters
            args_dict = experiment["method"][0]["provider"]["arguments"]
            commands = args_dict["parameters"]["commands"]
            assert "dd if=/dev/zero of=/var/tmp/chaos_fill bs=1M count=2048" in commands[0]
            assert "sleep 300" in commands[1]
            assert "rm -f /var/tmp/chaos_fill" in commands[2]
