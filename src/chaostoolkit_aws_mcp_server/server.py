#!/usr/bin/env python3
"""
Chaos Toolkit AWS MCP Server

This server provides tools for generating and managing Chaos Toolkit experiments
for AWS infrastructure, including AZ failure simulation, EC2 chaos, ASG scaling,
and other AWS chaos engineering scenarios.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool
from pydantic import BaseModel


class ExperimentConfig(BaseModel):
    """Configuration for chaos experiments"""
    title: str
    description: str = ""
    aws_region: str = "us-east-1"
    tags: List[str] = []


class ProbeConfig(BaseModel):
    """Configuration for steady state probes"""
    name: str
    type: str = "probe"
    module: str
    func: str
    arguments: Dict[str, Any]
    tolerance: Any = True


class ActionConfig(BaseModel):
    """Configuration for chaos actions"""
    name: str
    type: str = "action"
    module: str
    func: str
    arguments: Dict[str, Any]


# Initialize the MCP server
server = Server("chaostoolkit-aws-mcp-server")


def generate_experiment_json(
    config: ExperimentConfig,
    probes: List[ProbeConfig],
    actions: List[ActionConfig],
    rollbacks: List[ActionConfig]
) -> Dict[str, Any]:
    """Generate a complete Chaos Toolkit experiment JSON"""
    
    experiment = {
        "version": "1.0.0",
        "title": config.title,
        "description": config.description,
        "tags": config.tags,
        "configuration": {
            "aws_region": config.aws_region
        },
        "steady-state-hypothesis": {
            "title": "System is in steady state",
            "probes": [
                {
                    "type": probe.type,
                    "name": probe.name,
                    "provider": {
                        "type": "python",
                        "module": probe.module,
                        "func": probe.func,
                        "arguments": probe.arguments
                    },
                    "tolerance": probe.tolerance
                }
                for probe in probes
            ]
        },
        "method": [
            {
                "type": action.type,
                "name": action.name,
                "provider": {
                    "type": "python",
                    "module": action.module,
                    "func": action.func,
                    "arguments": action.arguments
                }
            }
            for action in actions
        ],
        "rollbacks": [
            {
                "type": rollback.type,
                "name": rollback.name,
                "provider": {
                    "type": "python",
                    "module": rollback.module,
                    "func": rollback.func,
                    "arguments": rollback.arguments
                }
            }
            for rollback in rollbacks
        ]
    }
    
    return experiment


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available chaos toolkit tools"""
    return [
        # AZ Failure Tools
        Tool(
            name="chaos_generate_az_failure_experiment",
            description="Generate AZ failure experiment using azchaosaws.ec2.actions.fail_az",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "failure_type": {
                        "type": "string", 
                        "enum": ["network", "instance"],
                        "default": "network",
                        "description": "Type of failure to simulate"
                    },
                    "dry_run": {"type": "boolean", "default": False},
                    "health_check_url": {"type": "string", "description": "URL for health checks"},
                    "state_path": {"type": "string", "default": "./fail_az.ec2.json"},
                    "output_file": {"type": "string", "default": "./az-failure-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "az"]
            }
        ),
        Tool(
            name="chaos_isolate_az_network",
            description="Generate experiment to isolate AZ network connections",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "vpc_id": {"type": "string", "description": "VPC ID"},
                    "dry_run": {"type": "boolean", "default": False},
                    "output_file": {"type": "string", "default": "./isolate-az-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "az", "vpc_id"]
            }
        ),
        Tool(
            name="chaos_simulate_az_partition",
            description="Generate experiment to simulate AZ network partition",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "partition_type": {"type": "string", "enum": ["partial", "complete"], "default": "partial"},
                    "dry_run": {"type": "boolean", "default": False},
                    "output_file": {"type": "string", "default": "./az-partition-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "az"]
            }
        ),
        Tool(
            name="chaos_generate_asg_az_failure_experiment",
            description="Generate ASG AZ failure experiment using azchaosaws.asg.actions.fail_az",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "asg_tags": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "Key": {"type": "string"},
                                "Value": {"type": "string"}
                            }
                        },
                        "default": [{"Key": "AZ_FAILURE", "Value": "True"}]
                    },
                    "dry_run": {"type": "boolean", "default": False},
                    "health_check_url": {"type": "string", "description": "URL for health checks"},
                    "state_path": {"type": "string", "default": "./fail_az.asg.json"},
                    "output_file": {"type": "string", "default": "./asg-az-failure-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "az"]
            }
        ),
        Tool(
            name="chaos_generate_ec2_actions_experiment",
            description="Generate EC2 chaos experiment using standard chaosaws actions",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "action_type": {
                        "type": "string",
                        "enum": ["stop_instances", "terminate_instances", "reboot_instances"],
                        "description": "Type of EC2 action"
                    },
                    "instance_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of instance IDs"
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "Name": {"type": "string"},
                                "Values": {"type": "array", "items": {"type": "string"}}
                            }
                        },
                        "description": "EC2 filters"
                    },
                    "az": {"type": "string", "description": "Target availability zone"},
                    "output_file": {"type": "string", "default": "./ec2-chaos-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "action_type"]
            }
        ),
        Tool(
            name="chaos_run_experiment",
            description="Execute Chaos Toolkit experiment from JSON file",
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_file": {"type": "string", "description": "Path to experiment JSON file"},
                    "dry_run": {"type": "boolean", "default": False},
                    "journal_path": {"type": "string", "description": "Path to save journal"},
                    "working_directory": {"type": "string", "description": "Working directory for execution"}
                },
                "required": ["experiment_file"]
            }
        ),
        Tool(
            name="chaos_validate_experiment",
            description="Validate Chaos Toolkit experiment JSON syntax",
            inputSchema={
                "type": "object",
                "properties": {
                    "experiment_file": {"type": "string", "description": "Path to experiment JSON file"}
                },
                "required": ["experiment_file"]
            }
        ),
        Tool(
            name="chaos_rollback_from_state",
            description="Execute rollback using state files",
            inputSchema={
                "type": "object",
                "properties": {
                    "state_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of state file paths"
                    },
                    "working_directory": {"type": "string", "description": "Working directory"}
                },
                "required": ["state_files"]
            }
        ),
        # EC2 Chaos Tools
        Tool(
            name="chaos_stop_instances",
            description="Generate experiment to stop EC2 instances",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "filters": {"type": "array", "items": {"type": "object"}, "description": "EC2 filters"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "force": {"type": "boolean", "default": False},
                    "output_file": {"type": "string", "default": "./stop-instances-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="chaos_terminate_instances",
            description="Generate experiment to terminate EC2 instances",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "filters": {"type": "array", "items": {"type": "object"}, "description": "EC2 filters"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "output_file": {"type": "string", "default": "./terminate-instances-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="chaos_reboot_instances",
            description="Generate experiment to reboot EC2 instances",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "filters": {"type": "array", "items": {"type": "object"}, "description": "EC2 filters"},
                    "az": {"type": "string", "description": "Target availability zone"},
                    "output_file": {"type": "string", "default": "./reboot-instances-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="chaos_detach_volumes",
            description="Generate experiment to detach EBS volumes",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "volume_ids": {"type": "array", "items": {"type": "string"}, "description": "Volume IDs"},
                    "device_names": {"type": "array", "items": {"type": "string"}, "description": "Device names"},
                    "force": {"type": "boolean", "default": False},
                    "output_file": {"type": "string", "default": "./detach-volumes-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title"]
            }
        ),
        # ASG Chaos Tools
        Tool(
            name="chaos_suspend_asg_processes",
            description="Generate experiment to suspend ASG processes",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "asg_names": {"type": "array", "items": {"type": "string"}, "description": "ASG names"},
                    "scaling_processes": {"type": "array", "items": {"type": "string"}, "description": "Processes to suspend"},
                    "output_file": {"type": "string", "default": "./suspend-asg-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "asg_names"]
            }
        ),
        Tool(
            name="chaos_terminate_random_instances",
            description="Generate experiment to terminate random ASG instances",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "asg_names": {"type": "array", "items": {"type": "string"}, "description": "ASG names"},
                    "instance_count": {"type": "integer", "description": "Number of instances to terminate"},
                    "az_name": {"type": "string", "description": "Target availability zone"},
                    "output_file": {"type": "string", "default": "./terminate-random-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "asg_names"]
            }
        ),
        # SSM Chaos Tools
        Tool(
            name="chaos_ssm_send_command",
            description="Generate experiment to send SSM commands",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "document_name": {"type": "string", "default": "AWS-RunShellScript"},
                    "commands": {"type": "array", "items": {"type": "string"}, "description": "Commands to execute"},
                    "output_file": {"type": "string", "default": "./ssm-command-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "instance_ids", "commands"]
            }
        ),
        Tool(
            name="chaos_ssm_stress_cpu",
            description="Generate experiment for CPU stress via SSM",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "cpu_cores": {"type": "integer", "default": 2},
                    "duration_seconds": {"type": "integer", "default": 300},
                    "output_file": {"type": "string", "default": "./ssm-cpu-stress-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "instance_ids"]
            }
        ),
        Tool(
            name="chaos_ssm_fill_disk",
            description="Generate experiment to fill disk via SSM",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "path": {"type": "string", "default": "/tmp"},
                    "size_mb": {"type": "integer", "default": 1024},
                    "duration_seconds": {"type": "integer", "default": 600},
                    "output_file": {"type": "string", "default": "./ssm-fill-disk-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "instance_ids"]
            }
        ),
        Tool(
            name="chaos_ssm_kill_process",
            description="Generate experiment to kill process via SSM",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "process_name": {"type": "string", "description": "Process name to kill"},
                    "signal": {"type": "string", "default": "SIGKILL"},
                    "output_file": {"type": "string", "default": "./ssm-kill-process-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "instance_ids", "process_name"]
            }
        ),
        # Network Chaos Tools
        Tool(
            name="chaos_modify_security_groups",
            description="Generate experiment to modify security group rules",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "group_ids": {"type": "array", "items": {"type": "string"}, "description": "Security group IDs"},
                    "action": {"type": "string", "enum": ["revoke", "authorize"], "description": "Action to perform"},
                    "rules": {"type": "array", "items": {"type": "object"}, "description": "Security group rules"},
                    "output_file": {"type": "string", "default": "./modify-sg-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "group_ids", "action"]
            }
        ),
        Tool(
            name="chaos_simulate_network_latency",
            description="Generate experiment to simulate network latency",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "instance_ids": {"type": "array", "items": {"type": "string"}, "description": "Instance IDs"},
                    "latency_ms": {"type": "integer", "default": 100},
                    "duration_seconds": {"type": "integer", "default": 300},
                    "output_file": {"type": "string", "default": "./network-latency-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "instance_ids"]
            }
        ),
        # RDS Chaos Tools
        Tool(
            name="chaos_reboot_db_instance",
            description="Generate experiment to reboot RDS instance",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "db_instance_identifier": {"type": "string", "description": "RDS instance identifier"},
                    "force_failover": {"type": "boolean", "default": False},
                    "output_file": {"type": "string", "default": "./reboot-db-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "db_instance_identifier"]
            }
        ),
        Tool(
            name="chaos_failover_db_cluster",
            description="Generate experiment to failover RDS cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "db_cluster_identifier": {"type": "string", "description": "RDS cluster identifier"},
                    "target_db_instance_identifier": {"type": "string", "description": "Target instance for failover"},
                    "output_file": {"type": "string", "default": "./failover-cluster-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "db_cluster_identifier"]
            }
        ),
        # Load Balancer Chaos Tools
        Tool(
            name="chaos_deregister_targets",
            description="Generate experiment to deregister ALB/NLB targets",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Experiment title"},
                    "target_group_arn": {"type": "string", "description": "Target group ARN"},
                    "target_ids": {"type": "array", "items": {"type": "string"}, "description": "Target IDs"},
                    "output_file": {"type": "string", "default": "./deregister-targets-experiment.json"},
                    "aws_region": {"type": "string", "default": "us-east-1"}
                },
                "required": ["title", "target_group_arn"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Handle tool calls"""
    
    # AZ Failure Tools
    if name == "chaos_generate_az_failure_experiment":
        return await generate_az_failure_experiment(arguments)
    elif name == "chaos_generate_asg_az_failure_experiment":
        return await generate_asg_az_failure_experiment(arguments)
    elif name == "chaos_isolate_az_network":
        return await generate_generic_experiment(arguments, "azchaosaws.ec2.actions", "isolate_az_network")
    elif name == "chaos_simulate_az_partition":
        return await generate_generic_experiment(arguments, "azchaosaws.ec2.actions", "simulate_az_partition")
    
    # EC2 Chaos Tools
    elif name == "chaos_stop_instances":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "stop_instances")
    elif name == "chaos_terminate_instances":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "terminate_instances")
    elif name == "chaos_reboot_instances":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "reboot_instances")
    elif name == "chaos_detach_volumes":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "detach_volumes")
    
    # ASG Chaos Tools
    elif name == "chaos_suspend_asg_processes":
        return await generate_generic_experiment(arguments, "chaosaws.asg.actions", "suspend_processes")
    elif name == "chaos_terminate_random_instances":
        return await generate_generic_experiment(arguments, "chaosaws.asg.actions", "terminate_random_instances")
    
    # SSM Chaos Tools
    elif name == "chaos_ssm_send_command":
        return await generate_generic_experiment(arguments, "chaosaws.ssm.actions", "send_command")
    elif name == "chaos_ssm_stress_cpu":
        return await generate_ssm_stress_experiment(arguments, "cpu")
    elif name == "chaos_ssm_fill_disk":
        return await generate_ssm_stress_experiment(arguments, "disk")
    elif name == "chaos_ssm_kill_process":
        return await generate_generic_experiment(arguments, "chaosaws.ssm.actions", "kill_process")
    
    # Network Chaos Tools
    elif name == "chaos_modify_security_groups":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "modify_security_groups")
    elif name == "chaos_simulate_network_latency":
        return await generate_generic_experiment(arguments, "chaosaws.ec2.actions", "simulate_network_latency")
    
    # RDS Chaos Tools
    elif name == "chaos_reboot_db_instance":
        return await generate_generic_experiment(arguments, "chaosaws.rds.actions", "reboot_db_instance")
    elif name == "chaos_failover_db_cluster":
        return await generate_generic_experiment(arguments, "chaosaws.rds.actions", "failover_db_cluster")
    
    # Load Balancer Chaos Tools
    elif name == "chaos_deregister_targets":
        return await generate_generic_experiment(arguments, "chaosaws.elbv2.actions", "deregister_targets")
    
    # Original Tools
    elif name == "chaos_generate_ec2_actions_experiment":
        return await generate_ec2_actions_experiment(arguments)
    elif name == "chaos_run_experiment":
        return await run_experiment(arguments)
    elif name == "chaos_validate_experiment":
        return await validate_experiment(arguments)
    elif name == "chaos_rollback_from_state":
        return await rollback_from_state(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def generate_az_failure_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate AZ failure experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"AZ failure test for {args['az']}",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Health check probe
    probes = []
    if args.get("health_check_url"):
        probes.append(ProbeConfig(
            name="health_check",
            module="chaoslib.provider.http",
            func="get",
            arguments={
                "url": args["health_check_url"],
                "expected_status": 200
            }
        ))
    
    # AZ failure action
    actions = [ActionConfig(
        name="fail_az",
        module="azchaosaws.ec2.actions",
        func="fail_az",
        arguments={
            "az": args["az"],
            "dry_run": args.get("dry_run", False),
            "failure_type": args.get("failure_type", "network"),
            "state_path": args.get("state_path", "./fail_az.ec2.json")
        }
    )]
    
    # Rollback action
    rollbacks = [ActionConfig(
        name="recover_az",
        module="azchaosaws.ec2.actions",
        func="recover_az",
        arguments={
            "state_path": args.get("state_path", "./fail_az.ec2.json")
        }
    )]
    
    experiment = generate_experiment_json(config, probes, actions, rollbacks)
    
    # Write to file
    output_file = args.get("output_file", "./az-failure-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated AZ failure experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_asg_az_failure_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate ASG AZ failure experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"ASG AZ failure test for {args['az']}",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Health check probe
    probes = []
    if args.get("health_check_url"):
        probes.append(ProbeConfig(
            name="health_check",
            module="chaoslib.provider.http",
            func="get",
            arguments={
                "url": args["health_check_url"],
                "expected_status": 200
            }
        ))
    
    # ASG AZ failure action
    actions = [ActionConfig(
        name="fail_asg_az",
        module="azchaosaws.asg.actions",
        func="fail_az",
        arguments={
            "az": args["az"],
            "dry_run": args.get("dry_run", False),
            "tags": args.get("asg_tags", [{"Key": "AZ_FAILURE", "Value": "True"}]),
            "state_path": args.get("state_path", "./fail_az.asg.json")
        }
    )]
    
    # Rollback action
    rollbacks = [ActionConfig(
        name="recover_asg_az",
        module="azchaosaws.asg.actions",
        func="recover_az",
        arguments={
            "state_path": args.get("state_path", "./fail_az.asg.json")
        }
    )]
    
    experiment = generate_experiment_json(config, probes, actions, rollbacks)
    
    # Write to file
    output_file = args.get("output_file", "./asg-az-failure-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated ASG AZ failure experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_ec2_actions_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate EC2 actions experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"EC2 {args['action_type']} experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build action arguments
    action_args = {}
    if args.get("instance_ids"):
        action_args["instance_ids"] = args["instance_ids"]
    if args.get("filters"):
        action_args["filters"] = args["filters"]
    if args.get("az"):
        action_args["az"] = args["az"]
    
    # EC2 action
    actions = [ActionConfig(
        name=args["action_type"],
        module="chaosaws.ec2.actions",
        func=args["action_type"],
        arguments=action_args
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", "./ec2-chaos-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated EC2 {args['action_type']} experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]

    """Generate a generic chaos experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"{func} experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build action arguments by excluding meta fields
    action_args = {k: v for k, v in args.items() 
                   if k not in ["title", "output_file", "aws_region"]}
    
    # Create action
    actions = [ActionConfig(
        name=func,
        module=module,
        func=func,
        arguments=action_args
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", f"./{func}-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated {func} experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_ssm_stress_experiment(args: Dict[str, Any], stress_type: str) -> List[Dict[str, Any]]:
    """Generate SSM stress experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"SSM {stress_type} stress experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build stress command based on type
    if stress_type == "cpu":
        commands = [f"stress --cpu {args.get('cpu_cores', 2)} --timeout {args.get('duration_seconds', 300)}s"]
    elif stress_type == "disk":
        size_mb = args.get('size_mb', 1024)
        duration = args.get('duration_seconds', 600)
        path = args.get('path', '/tmp')
        commands = [
            f"dd if=/dev/zero of={path}/chaos_fill bs=1M count={size_mb}",
            f"sleep {duration}",
            f"rm -f {path}/chaos_fill"
        ]
    else:
        commands = ["echo 'Unknown stress type'"]
    
    # Create SSM action
    actions = [ActionConfig(
        name=f"ssm_{stress_type}_stress",
        module="chaosaws.ssm.actions",
        func="send_command",
        arguments={
            "instance_ids": args["instance_ids"],
            "document_name": "AWS-RunShellScript",
            "parameters": {
                "commands": commands
            }
        }
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", f"./ssm-{stress_type}-stress-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated SSM {stress_type} stress experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


    """Generate AZ failure experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"AZ failure test for {args['az']}",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Health check probe
    probes = []
    if args.get("health_check_url"):
        probes.append(ProbeConfig(
            name="health_check",
            module="chaoslib.provider.http",
            func="get",
            arguments={
                "url": args["health_check_url"],
                "expected_status": 200
            }
        ))
    
    # AZ failure action
    actions = [ActionConfig(
        name="fail_az",
        module="azchaosaws.ec2.actions",
        func="fail_az",
        arguments={
            "az": args["az"],
            "dry_run": args.get("dry_run", False),
            "failure_type": args.get("failure_type", "network"),
            "state_path": args.get("state_path", "./fail_az.ec2.json")
        }
    )]
    
    # Rollback action
    rollbacks = [ActionConfig(
        name="recover_az",
        module="azchaosaws.ec2.actions",
        func="recover_az",
        arguments={
            "state_path": args.get("state_path", "./fail_az.ec2.json")
        }
    )]
    
    experiment = generate_experiment_json(config, probes, actions, rollbacks)
    
    # Write to file
    output_file = args.get("output_file", "./az-failure-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated AZ failure experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_asg_az_failure_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate ASG AZ failure experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"ASG AZ failure test for {args['az']}",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Health check probe
    probes = []
    if args.get("health_check_url"):
        probes.append(ProbeConfig(
            name="health_check",
            module="chaoslib.provider.http",
            func="get",
            arguments={
                "url": args["health_check_url"],
                "expected_status": 200
            }
        ))
    
    # ASG AZ failure action
    actions = [ActionConfig(
        name="fail_asg_az",
        module="azchaosaws.asg.actions",
        func="fail_az",
        arguments={
            "az": args["az"],
            "dry_run": args.get("dry_run", False),
            "tags": args.get("asg_tags", [{"Key": "AZ_FAILURE", "Value": "True"}]),
            "state_path": args.get("state_path", "./fail_az.asg.json")
        }
    )]
    
    # Rollback action
    rollbacks = [ActionConfig(
        name="recover_asg_az",
        module="azchaosaws.asg.actions",
        func="recover_az",
        arguments={
            "state_path": args.get("state_path", "./fail_az.asg.json")
        }
    )]
    
    experiment = generate_experiment_json(config, probes, actions, rollbacks)
    
    # Write to file
    output_file = args.get("output_file", "./asg-az-failure-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated ASG AZ failure experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_ec2_actions_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate EC2 actions experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"EC2 {args['action_type']} experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build action arguments
    action_args = {}
    if args.get("instance_ids"):
        action_args["instance_ids"] = args["instance_ids"]
    if args.get("filters"):
        action_args["filters"] = args["filters"]
    if args.get("az"):
        action_args["az"] = args["az"]
    
    # EC2 action
    actions = [ActionConfig(
        name=args["action_type"],
        module="chaosaws.ec2.actions",
        func=args["action_type"],
        arguments=action_args
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", "./ec2-chaos-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated EC2 {args['action_type']} experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def run_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run Chaos Toolkit experiment"""
    
    experiment_file = args["experiment_file"]
    if not os.path.exists(experiment_file):
        return [{"type": "text", "text": f"Error: Experiment file not found: {experiment_file}"}]
    
    # Build chaos command
    cmd = ["chaos", "run", experiment_file]
    
    if args.get("journal_path"):
        cmd.extend(["--journal-path", args["journal_path"]])
    
    # Set working directory
    cwd = args.get("working_directory", os.getcwd())
    
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        output = f"Exit code: {result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        
        return [{"type": "text", "text": output}]
        
    except subprocess.TimeoutExpired:
        return [{"type": "text", "text": "Error: Experiment execution timed out after 1 hour"}]
    except Exception as e:
        return [{"type": "text", "text": f"Error running experiment: {str(e)}"}]


async def validate_experiment(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Validate Chaos Toolkit experiment"""
    
    experiment_file = args["experiment_file"]
    if not os.path.exists(experiment_file):
        return [{"type": "text", "text": f"Error: Experiment file not found: {experiment_file}"}]
    
    try:
        result = subprocess.run(
            ["chaos", "validate", experiment_file],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        output = f"Validation result: {'PASSED' if result.returncode == 0 else 'FAILED'}\n\n{result.stdout}\n{result.stderr}"
        
        return [{"type": "text", "text": output}]
        
    except Exception as e:
        return [{"type": "text", "text": f"Error validating experiment: {str(e)}"}]


async def rollback_from_state(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute rollback using state files"""
    
    state_files = args["state_files"]
    cwd = args.get("working_directory", os.getcwd())
    
    results = []
    
    for state_file in state_files:
        if not os.path.exists(state_file):
            results.append(f"Warning: State file not found: {state_file}")
            continue
        
        try:
            # Determine rollback action based on state file name
            if "ec2" in state_file:
                module = "azchaosaws.ec2.actions"
            elif "asg" in state_file:
                module = "azchaosaws.asg.actions"
            else:
                results.append(f"Warning: Unknown state file type: {state_file}")
                continue
            
            # Create temporary rollback experiment
            rollback_experiment = {
                "version": "1.0.0",
                "title": f"Rollback from {state_file}",
                "description": "Automated rollback",
                "method": [
                    {
                        "type": "action",
                        "name": "recover_az",
                        "provider": {
                            "type": "python",
                            "module": module,
                            "func": "recover_az",
                            "arguments": {
                                "state_path": state_file
                            }
                        }
                    }
                ]
            }
            
            # Write temporary experiment file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(rollback_experiment, f, indent=2)
                temp_file = f.name
            
            try:
                result = subprocess.run(
                    ["chaos", "run", temp_file],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minutes timeout
                )
                
                results.append(f"Rollback from {state_file}: {'SUCCESS' if result.returncode == 0 else 'FAILED'}")
                if result.stdout:
                    results.append(f"Output: {result.stdout}")
                if result.stderr:
                    results.append(f"Errors: {result.stderr}")
                    
            finally:
                os.unlink(temp_file)
                
        except Exception as e:
            results.append(f"Error rolling back {state_file}: {str(e)}")
    
    return [{"type": "text", "text": "\n".join(results)}]



async def generate_generic_experiment(args: Dict[str, Any], module: str, func: str) -> List[Dict[str, Any]]:
    """Generate a generic chaos experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"{func} experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build action arguments by excluding meta fields
    action_args = {k: v for k, v in args.items() 
                   if k not in ["title", "output_file", "aws_region"]}
    
    # Create action
    actions = [ActionConfig(
        name=func,
        module=module,
        func=func,
        arguments=action_args
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", f"./{func}-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated {func} experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


async def generate_ssm_stress_experiment(args: Dict[str, Any], stress_type: str) -> List[Dict[str, Any]]:
    """Generate SSM stress experiment"""
    
    config = ExperimentConfig(
        title=args["title"],
        description=f"SSM {stress_type} stress experiment",
        aws_region=args.get("aws_region", "us-east-1")
    )
    
    # Build stress command based on type
    if stress_type == "cpu":
        commands = [f"stress --cpu {args.get('cpu_cores', 2)} --timeout {args.get('duration_seconds', 300)}s"]
    elif stress_type == "disk":
        size_mb = args.get('size_mb', 1024)
        duration = args.get('duration_seconds', 600)
        path = args.get('path', '/tmp')
        commands = [
            f"dd if=/dev/zero of={path}/chaos_fill bs=1M count={size_mb}",
            f"sleep {duration}",
            f"rm -f {path}/chaos_fill"
        ]
    else:
        commands = ["echo 'Unknown stress type'"]
    
    # Create SSM action
    actions = [ActionConfig(
        name=f"ssm_{stress_type}_stress",
        module="chaosaws.ssm.actions",
        func="send_command",
        arguments={
            "instance_ids": args["instance_ids"],
            "document_name": "AWS-RunShellScript",
            "parameters": {
                "commands": commands
            }
        }
    )]
    
    experiment = generate_experiment_json(config, [], actions, [])
    
    # Write to file
    output_file = args.get("output_file", f"./ssm-{stress_type}-stress-experiment.json")
    with open(output_file, "w") as f:
        json.dump(experiment, f, indent=2)
    
    return [{
        "type": "text",
        "text": f"Generated SSM {stress_type} stress experiment: {output_file}\n\nExperiment preview:\n{json.dumps(experiment, indent=2)}"
    }]


def main():
    """Main entry point"""
    import asyncio
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
