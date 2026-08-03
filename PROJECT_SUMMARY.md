# 变更记录

## 0.2.0

### 修复的阻断性问题

- **服务无法启动**：`main()` 之前调用 `asyncio.run(stdio_server(server))`，会抛
  `ValueError: a coroutine was expected`。现在按 MCP SDK 的用法进入 `stdio_server()`
  异步上下文并调用 `server.run(...)`。新增端到端测试，真实启动子进程并完成 MCP 握手。
- **依赖无法解析**：`aws-az-failure-chaostoolkit>=1.0.0` 不存在（PyPI 最高 0.1.10），
  `uv sync` 直接失败。已改为 `>=0.1.10,<0.2.0` 并重建 `uv.lock`。
- **mcp 版本无上限**：`mcp` 2.x 移除了 lowlevel `Server` 的 `list_tools()` / `call_tool()`
  装饰器，装上 2.x 后 import 即失败。已约束 `mcp>=1.0,<2`。
- **开发依赖装不上**：README 写 `uv sync --all-groups`，但 dev 定义在
  `[project.optional-dependencies]`。已迁移到 `[dependency-groups]`。

### 修正的 API 映射

以下引用的函数在 `chaosaws` / `azchaosaws` 中并不存在，生成的实验必然失败，现已全部改为真实 API：

| 原实现 | 现在 |
| --- | --- |
| `chaosaws.ec2.actions.reboot_instances` | `restart_instances` |
| `chaosaws.ec2.actions.detach_volumes` | `detach_random_volume` |
| `chaosaws.ec2.actions.modify_security_groups` | `revoke_security_group_ingress` / `authorize_security_group_ingress` |
| `chaosaws.ec2.actions.simulate_network_latency` | SSM + `tc netem` |
| `chaosaws.ssm.actions.kill_process` | SSM + `pkill` |
| `chaosaws.elbv2.actions.deregister_targets` | `deregister_target`（参数是目标组名，不是 ARN） |
| `azchaosaws.ec2.actions.isolate_az_network` | `fail_az(failure_type="network")` + `vpc-id` 过滤 |
| `azchaosaws.ec2.actions.simulate_az_partition` | `fail_az(failure_type="network")` + 过滤器 |
| `chaoslib.provider.http.get` 探针 | HTTP provider（`{"type": "http", ...}`，tolerance 为状态码） |

同时修正了参数名：`send_command` 用 `targets` 而不是 `instance_ids`，`suspend_processes` 用
`process_names` 而不是 `scaling_processes`。原先的通用生成器把所有入参原样塞进 activity
arguments，现在每个工具按目标函数签名显式映射。

### 安全护栏

- 破坏性动作默认 `dry_run: true`；`chaos_run_experiment` 默认 `chaos run --dry activities`，
  真实执行需要同时 `dry_run=false` 且 `confirm_destructive=true`。
- 所有读写路径限制在 `$CHAOS_MCP_WORKDIR`（默认进程工作目录）内，拒绝 `..` 和目录外的绝对路径。
- SSM 命令中的路径、进程名、网卡名先做模式校验再 `shlex.quote`，消除命令注入。
- 能回滚的动作自动生成 rollback（`start_instances`、`resume_processes`、安全组反向操作、
  删除 `tc` qdisc、删除填充文件）；不能回滚的动作在响应里明确告知。
- AWS 标识符（实例、卷、安全组、VPC、AZ、端口、信号量）全部校验。
- `chaos_rollback_from_state` 改为读取 state 文件内容判断 ec2/asg，不再用文件名子串猜测；
  dry-run 产生的 state 会被跳过而不是执行后失败。

### 代码质量

- 删除约 200 行重复定义与 `return` 之后的不可达代码；`server.py` 拆分为
  `models.py` / `safety.py` / `builder.py` / `catalog.py` / `server.py`。
- `ruff check`（E/F/I/N/W/UP/B/SIM/RUF）与 `mypy --strict` 全部通过；新增 GitHub Actions CI
  在 Python 3.10-3.12 上跑 lint、类型检查与测试。
- 子进程改用 `asyncio.create_subprocess_exec`，不再阻塞事件循环；日志写 stderr，避免污染 stdout 上的 MCP 协议。
- 测试从 12 个增加到 143 个，覆盖率 36% → 89%；新增 stdio 端到端测试，以及"每个生成的
  activity 必须能在已安装的 chaosaws/azchaosaws 中解析到函数且参数名被接受"的回归测试。
- 补齐 `LICENSE`（Apache-2.0）与 `py.typed`；`.gitignore` 不再用 `*.json` 一刀切。

### 兼容性

`chaos_reboot_instances`、`chaos_detach_volumes`、`chaos_deregister_targets` 保留为别名，调用时会
提示应改用的新名称。生成函数由 async 改为同步并返回 `GeneratedExperiment`，直接导入这些函数的
代码需要调整（MCP 工具接口不变）。
