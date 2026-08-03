# Chaos Toolkit AWS MCP Server

An MCP server that generates [Chaos Toolkit](https://chaostoolkit.org/) experiments for AWS and
drives the `chaos` CLI to validate, run and roll them back.

Every generated activity maps onto a function that really exists in
[`chaosaws`](https://github.com/chaostoolkit-incubator/chaostoolkit-aws) (chaostoolkit-aws) or
[`azchaosaws`](https://github.com/awslabs/aws-az-failure-chaostoolkit) (aws-az-failure-chaostoolkit),
and the arguments follow those function signatures. The test suite imports both packages and asserts
this for every tool, so an experiment that this server generates will not fail with
`ActivityFailed: module 'chaosaws...' has no attribute ...`.

## Safety model

Chaos experiments break production on purpose, so the server is deliberately conservative:

- **Dry run by default.** `fail_az` is generated with `dry_run: true`, and `chaos_run_experiment`
  runs `chaos run --dry activities` unless you pass both `dry_run: false` and
  `confirm_destructive: true`.
- **Confined file access.** Every path the server reads or writes must stay inside a base directory:
  `$CHAOS_MCP_WORKDIR`, defaulting to the process working directory. `../escape.json` and
  `/etc/anything` are rejected.
- **Validated shell input.** Values interpolated into SSM shell commands (paths, process names,
  interfaces) are pattern-checked and `shlex`-quoted, so `path="/tmp; rm -rf /"` is refused instead
  of ending up in `AWS-RunShellScript`.
- **Rollbacks where they exist.** Stopping instances generates `start_instances`, suspending ASG
  processes generates `resume_processes`, revoking a security group rule generates the matching
  authorise, `tc netem` and disk-fill experiments clean up after themselves. When no rollback is
  possible (termination, `pkill`) the response says so explicitly.
- **Validated AWS identifiers.** Instance, volume, security group, VPC ids, AZ names and ports are
  checked before an experiment is written.

## Installation

```bash
git clone https://github.com/RadiumGu/chaostoolkit-aws-mcp-server.git
# or the China mirror: https://gitee.com/radiumgu/chaostoolkit-aws-mcp-server.git
cd chaostoolkit-aws-mcp-server

uv sync --all-groups          # runtime + dev dependencies
```

`uv sync` installs `chaostoolkit`, `chaostoolkit-aws` and `aws-az-failure-chaostoolkit`; no extra
`pip install` step is needed. Python 3.10+ is required, and the MCP SDK is pinned to `>=1.0,<2`
because the low level decorator API used here was removed in `mcp` 2.x.

Configure AWS credentials as usual, for example for AWS China:

```bash
aws configure --profile awscn   # region cn-north-1
```

## MCP client configuration

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
      "AWS_REGION": "cn-north-1",
      "AWS_PROFILE": "awscn",
      "CHAOS_MCP_WORKDIR": "/path/to/experiments"
    }
  }
}
```

`AWS_REGION` (or `AWS_DEFAULT_REGION`) becomes the default `configuration.aws_region` of generated
experiments. `CHAOS_MCP_WORKDIR` is where experiments, journals and state files are written and the
only directory the server may touch.

## Tools

All generation tools accept `title` (required), `tags`, `health_check_url`, `health_check_status`,
`health_check_timeout`, `output_file` and `aws_region`. A `health_check_url` becomes a steady state
hypothesis using the Chaos Toolkit HTTP provider with the status code as tolerance.

### Availability zone failure — `azchaosaws`

| Tool | Generated activity |
| --- | --- |
| `chaos_generate_az_failure_experiment` | `azchaosaws.ec2.actions.fail_az` + `recover_az` rollback |
| `chaos_generate_asg_az_failure_experiment` | `azchaosaws.asg.actions.fail_az` + `recover_az` rollback |
| `chaos_isolate_az_network` | `fail_az(failure_type="network")` scoped by a `vpc-id` filter |
| `chaos_simulate_az_partition` | `fail_az(failure_type="network")`; a partial partition requires `filters` |

`fail_az` only touches resources tagged `AZ_FAILURE=True` unless you pass your own `filters`.

### EC2 — `chaosaws.ec2.actions`

| Tool | Generated activity |
| --- | --- |
| `chaos_stop_instances` | `stop_instances` + `start_instances` rollback |
| `chaos_terminate_instances` | `terminate_instances` (irreversible) |
| `chaos_restart_instances` | `restart_instances` |
| `chaos_detach_random_volume` | `detach_random_volume` |
| `chaos_generate_ec2_actions_experiment` | one of the three instance actions above |
| `chaos_modify_security_groups` | `revoke_security_group_ingress` / `authorize_security_group_ingress`, with the inverse as rollback |

### Auto Scaling groups — `chaosaws.asg.actions`

| Tool | Generated activity |
| --- | --- |
| `chaos_suspend_asg_processes` | `suspend_processes` + `resume_processes` rollback |
| `chaos_terminate_random_instances` | `terminate_random_instances` (`instance_count` or `instance_percent`) |

### SSM — `chaosaws.ssm.actions.send_command`

| Tool | Command sent to the instances |
| --- | --- |
| `chaos_ssm_send_command` | your own commands, verbatim |
| `chaos_ssm_stress_cpu` | `stress-ng --cpu N --timeout Ns` (falls back to `stress`) |
| `chaos_ssm_fill_disk` | `dd` a fill file, then remove it (also on rollback) |
| `chaos_ssm_kill_process` | `pkill -SIGNAL -x <process>` |
| `chaos_simulate_network_latency` | `tc qdisc add ... netem delay`, removed on rollback |

`send_command` targets instances through `targets=[{"Key": "InstanceIds", "Values": [...]}]`, which is
what the real signature takes. SSM commands run as root and require the SSM agent, an instance
profile with `AmazonSSMManagedInstanceCore`, and `stress-ng`/`iproute2` for the stress tools.

### RDS and load balancing

| Tool | Generated activity |
| --- | --- |
| `chaos_reboot_db_instance` | `chaosaws.rds.actions.reboot_db_instance` |
| `chaos_failover_db_cluster` | `chaosaws.rds.actions.failover_db_cluster` |
| `chaos_deregister_target` | `chaosaws.elbv2.actions.deregister_target` (target group **name**) |

### Lifecycle

| Tool | Behaviour |
| --- | --- |
| `chaos_run_experiment` | `chaos run`; dry by default, `--journal-path` and `--rollback-strategy` supported |
| `chaos_validate_experiment` | JSON parse check, then `chaos validate` |
| `chaos_rollback_from_state` | `recover_az` per state file; the resource type is read from the file contents, not guessed from its name |

### Deprecated aliases

| Old name | Use instead |
| --- | --- |
| `chaos_reboot_instances` | `chaos_restart_instances` |
| `chaos_detach_volumes` | `chaos_detach_random_volume` |
| `chaos_deregister_targets` | `chaos_deregister_target` |

They still work and the response says which tool to use instead.

### Not implemented

There is no upstream primitive for these, so the server does not pretend to offer them: packet loss
and corruption, memory and IO stress, detaching an internet gateway, modifying target group health
checks, DB connection limits and DB latency injection. `chaos_ssm_send_command` is the escape hatch
for anything that can be expressed as a shell command.

## Example session

```
1. chaos_generate_az_failure_experiment
   title="Production AZ failure", az="cn-north-1a",
   health_check_url="https://my-app.example.com/health"

2. chaos_validate_experiment
   experiment_file="./az-failure-experiment.json"

3. chaos_run_experiment                      # dry run, nothing is touched
   experiment_file="./az-failure-experiment.json"

4. chaos_generate_az_failure_experiment      # regenerate for a real run
   title="Production AZ failure", az="cn-north-1a", dry_run=false

5. chaos_run_experiment
   experiment_file="./az-failure-experiment.json",
   dry_run=false, confirm_destructive=true, journal_path="./journal.json"

6. chaos_rollback_from_state                 # if the rollback did not run
   state_files=["./fail_az.ec2.json"]
```

`examples/example_usage.py` does the same thing in Python.

## Development

```bash
uv sync --all-groups
uv run pytest --cov --cov-branch --cov-report=term-missing
uv run ruff check .
uv run mypy src/ tests/
```

143 tests, 89% statement/branch coverage. The suite includes an end-to-end test that starts the
server as a subprocess and speaks MCP over stdio, and a test that asserts every generated activity
resolves to an existing `chaosaws`/`azchaosaws` function with accepted argument names. CI runs lint,
types and tests on Python 3.10-3.12.

## License

Apache-2.0
