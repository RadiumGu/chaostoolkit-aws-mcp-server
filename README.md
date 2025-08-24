# Chaos Toolkit AWS MCP Server

A Model Context Protocol (MCP) server that provides tools for generating and managing Chaos Toolkit experiments for AWS infrastructure. This server implements all chaos actions from the actions.md specification.

## Features

- **AZ Failure Simulation**: Generate experiments to simulate entire availability zone failures
- **EC2 Chaos Testing**: Stop, terminate, reboot instances and detach volumes
- **ASG Chaos Testing**: Create Auto Scaling Group failure scenarios  
- **SSM Chaos Operations**: Execute chaos commands via Systems Manager
- **Network Chaos**: Modify security groups and simulate network issues
- **RDS Chaos**: Database instance and cluster failure scenarios
- **Load Balancer Chaos**: Target deregistration and health check modifications
- **Experiment Management**: Run, validate, and rollback chaos experiments
- **State Management**: Automatic state file handling for safe rollbacks

## Installation

### 1. Install the MCP Server
```bash
cd chaostoolkit-aws-mcp-server
uv venv && uv sync --all-groups
```

### 2. Install Required Chaos Toolkit Extensions
```bash
# Install Chaos Toolkit core
pip install chaostoolkit

# Install AWS extension
pip install chaostoolkit-aws

# Install AWS AZ Failure extension (required for AZ failure experiments)
pip install aws-az-failure-chaostoolkit
```

### 3. Configure AWS Credentials
```bash
# For AWS China regions
aws configure --profile awscn
AWS Access Key ID [None]: your-access-key
AWS Secret Access Key [None]: your-secret-key
Default region name [None]: cn-north-1
Default output format [None]: json
```

## Usage

### With MCP Client

Add to your MCP client configuration:

```json
{
  "chaostoolkit-aws-mcp-server": {
    "command": "uv",
    "args": [
      "--directory",
      "/path/to/chaostoolkit-aws-mcp-server",
      "run",
      "chaostoolkit-aws-mcp-server"
    ],
    "env": {
      "AWS_REGION": "cn-north-1"
    }
  }
}
```

## Available Tools

### AZ Failure Tools
- `chaos_generate_az_failure_experiment` - Generate AZ failure experiments using `azchaosaws.ec2.actions.fail_az`
- `chaos_isolate_az_network` - Generate experiments to isolate AZ network connections
- `chaos_simulate_az_partition` - Generate experiments to simulate AZ network partition
- `chaos_generate_asg_az_failure_experiment` - Generate ASG AZ failure using `azchaosaws.asg.actions.fail_az`

### EC2 Chaos Tools
- `chaos_stop_instances` - Generate experiments to stop EC2 instances
- `chaos_terminate_instances` - Generate experiments to terminate EC2 instances  
- `chaos_reboot_instances` - Generate experiments to reboot EC2 instances
- `chaos_detach_volumes` - Generate experiments to detach EBS volumes

### ASG Chaos Tools
- `chaos_suspend_asg_processes` - Generate experiments to suspend ASG processes
- `chaos_terminate_random_instances` - Generate experiments to terminate random ASG instances

### SSM Chaos Tools
- `chaos_ssm_send_command` - Generate experiments to send SSM commands
- `chaos_ssm_stress_cpu` - Generate CPU stress experiments via SSM
- `chaos_ssm_fill_disk` - Generate disk fill experiments via SSM
- `chaos_ssm_kill_process` - Generate process termination experiments via SSM

### Network Chaos Tools
- `chaos_modify_security_groups` - Generate experiments to modify security group rules
- `chaos_simulate_network_latency` - Generate network latency simulation experiments

### RDS Chaos Tools
- `chaos_reboot_db_instance` - Generate experiments to reboot RDS instances
- `chaos_failover_db_cluster` - Generate experiments to failover RDS clusters

### Load Balancer Chaos Tools
- `chaos_deregister_targets` - Generate experiments to deregister ALB/NLB targets

### Experiment Management Tools
- `chaos_run_experiment` - Execute Chaos Toolkit experiments from JSON files
- `chaos_validate_experiment` - Validate Chaos Toolkit experiment JSON syntax
- `chaos_rollback_from_state` - Execute rollback operations using state files

## Example Usage

### 1. Generate an AZ failure experiment:
```
Use the chaos_generate_az_failure_experiment tool with:
- title: "Production AZ Failure Test"
- az: "cn-north-1a"
- failure_type: "network"
- health_check_url: "https://my-app.com/health"
```

### 2. Generate SSM CPU stress experiment:
```
Use chaos_ssm_stress_cpu with:
- title: "CPU Stress Test"
- instance_ids: ["i-1234567890abcdef0"]
- cpu_cores: 4
- duration_seconds: 300
```

### 3. Generate EC2 instance termination experiment:
```
Use chaos_terminate_instances with:
- title: "Instance Termination Test"
- instance_ids: ["i-1234567890abcdef0", "i-0987654321fedcba0"]
- az: "cn-north-1a"
```

### 4. Run the experiment:
```
Use chaos_run_experiment with:
- experiment_file: "./experiment.json"
- journal_path: "./experiment-journal.json"
```

### 5. Rollback if needed:
```
Use chaos_rollback_from_state with:
- state_files: ["./fail_az.ec2.json"]
```

## Supported Chaos Actions

This server implements all chaos actions from the specification:

### 1. AZ Failure Simulation
- **simulate_az_failure** - Simulate entire availability zone failure
- **isolate_az_network** - Isolate AZ network connections
- **block_az_traffic** - Block specific AZ traffic
- **drain_az_instances** - Drain AZ instances
- **simulate_az_partition** - Simulate AZ network partition

### 2. EC2 Chaos Experiments
- **stop_instances** - Stop EC2 instances
- **terminate_instances** - Terminate instances
- **reboot_instances** - Restart instances
- **detach_volumes** - Detach EBS volumes
- **stress_cpu** - CPU pressure testing
- **fill_disk** - Disk fill testing

### 3. ASG Chaos Experiments
- **suspend_asg_processes** - Suspend ASG processes (Launch, Terminate, HealthCheck, etc.)
- **resume_asg_processes** - Resume ASG processes
- **change_asg_subnets** - Modify ASG subnet configuration
- **detach_random_instances** - Randomly detach ASG instances
- **terminate_random_instances** - Randomly terminate ASG instances
- **set_asg_capacity** - Modify ASG capacity (min/max/desired)
- **stop_random_instances** - Randomly stop ASG instances

### 4. SSM Chaos Experiments
- **send_command** - Send chaos commands via SSM
- **run_shell_command** - Execute shell commands for fault injection
- **stress_cpu_via_ssm** - CPU pressure testing via SSM
- **fill_disk_via_ssm** - Disk fill via SSM
- **kill_process** - Terminate specified processes
- **network_corruption** - Network packet corruption
- **memory_stress** - Memory pressure testing
- **io_stress** - IO pressure testing

### 5. Network Layer Chaos Experiments
- **blackhole_traffic** - Network blackhole
- **modify_security_groups** - Modify security group rules
- **detach_internet_gateway** - Detach internet gateway
- **simulate_network_latency** - Network latency injection
- **packet_loss_simulation** - Packet loss simulation

### 6. Load Balancer Chaos Experiments
- **deregister_targets** - Deregister ALB/NLB targets
- **modify_health_checks** - Modify health checks
- **simulate_lb_failure** - Simulate load balancer failure

### 7. RDS/Database Chaos Experiments
- **reboot_db_instance** - Restart database instances
- **failover_db_cluster** - Database cluster failover
- **simulate_db_connection_limit** - Simulate connection limits
- **inject_db_latency** - Database latency injection

## Prerequisites

- Python 3.10+
- Chaos Toolkit installed (`pip install chaostoolkit`)
- Chaos Toolkit AWS extension (`pip install chaostoolkit-aws`)
- AWS AZ Failure Chaos Toolkit extension (`pip install aws-az-failure-chaostoolkit`)
- AWS credentials configured
- Required AWS permissions for the chaos actions

## Development

```bash
# Install development dependencies
uv sync --all-groups

# Run tests
uv run pytest --cov --cov-branch --cov-report=term-missing

# Run linting
uv run ruff check
uv run mypy src/
```

## Test Coverage

Current test coverage: **36%** with 12 passing tests
- Core functionality covered
- Unit tests for experiment generation
- Async test support

## License

Apache-2.0
