#!/usr/bin/env python3
"""
Example usage of Chaos Toolkit AWS MCP Server

This script demonstrates how to use the MCP server tools programmatically.
"""

import asyncio
import json
from pathlib import Path

from chaostoolkit_aws_mcp_server.server import (
    generate_az_failure_experiment,
    generate_asg_az_failure_experiment,
    generate_ec2_actions_experiment,
    validate_experiment,
)


async def main():
    """Main example function"""
    
    # Example 1: Generate AZ failure experiment
    print("=== Generating AZ Failure Experiment ===")
    az_args = {
        "title": "Production AZ Failure Test",
        "az": "cn-north-1a",
        "failure_type": "network",
        "dry_run": False,
        "health_check_url": "https://my-app.example.com/health",
        "state_path": "./fail_az.ec2.json",
        "output_file": "./examples/az-failure-experiment.json",
        "aws_region": "cn-north-1"
    }
    
    result = await generate_az_failure_experiment(az_args)
    print(result[0]["text"])
    
    # Example 2: Generate ASG AZ failure experiment
    print("\n=== Generating ASG AZ Failure Experiment ===")
    asg_args = {
        "title": "ASG Resilience Test",
        "az": "cn-north-1a", 
        "asg_tags": [
            {"Key": "Environment", "Value": "production"},
            {"Key": "AZ_FAILURE", "Value": "True"}
        ],
        "dry_run": False,
        "health_check_url": "https://my-app.example.com/health",
        "state_path": "./fail_az.asg.json",
        "output_file": "./examples/asg-az-failure-experiment.json",
        "aws_region": "cn-north-1"
    }
    
    result = await generate_asg_az_failure_experiment(asg_args)
    print(result[0]["text"])
    
    # Example 3: Generate EC2 actions experiment
    print("\n=== Generating EC2 Actions Experiment ===")
    ec2_args = {
        "title": "EC2 Instance Stop Test",
        "action_type": "stop_instances",
        "instance_ids": ["i-1234567890abcdef0", "i-0987654321fedcba0"],
        "filters": [
            {"Name": "tag:Environment", "Values": ["test"]},
            {"Name": "instance-state-name", "Values": ["running"]}
        ],
        "az": "cn-north-1a",
        "output_file": "./examples/ec2-stop-experiment.json",
        "aws_region": "cn-north-1"
    }
    
    result = await generate_ec2_actions_experiment(ec2_args)
    print(result[0]["text"])
    
    # Example 4: Validate experiments
    print("\n=== Validating Experiments ===")
    experiments = [
        "./examples/az-failure-experiment.json",
        "./examples/asg-az-failure-experiment.json", 
        "./examples/ec2-stop-experiment.json"
    ]
    
    for exp_file in experiments:
        if Path(exp_file).exists():
            result = await validate_experiment({"experiment_file": exp_file})
            print(f"Validation for {exp_file}:")
            print(result[0]["text"])
            print()


if __name__ == "__main__":
    # Create examples directory
    Path("./examples").mkdir(exist_ok=True)
    
    # Run examples
    asyncio.run(main())
