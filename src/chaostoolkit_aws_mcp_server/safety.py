"""Safety helpers for the MCP server.

Three concerns live here:

* **Path confinement** - every file the server reads or writes must stay inside a
  base directory (``CHAOS_MCP_WORKDIR``, defaulting to the process working
  directory) so a tool call cannot read or clobber arbitrary files.
* **Shell safety** - values interpolated into shell commands that end up running
  on EC2 instances through SSM are validated *and* quoted.
* **Input validation** - AWS identifiers are checked against conservative
  patterns so malformed input fails fast with a readable message instead of
  producing a broken experiment.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

WORKDIR_ENV = "CHAOS_MCP_WORKDIR"

INSTANCE_ID = re.compile(r"^i-[0-9a-f]{8,17}$")
VOLUME_ID = re.compile(r"^vol-[0-9a-f]{8,17}$")
SECURITY_GROUP_ID = re.compile(r"^sg-[0-9a-f]{8,17}$")
VPC_ID = re.compile(r"^vpc-[0-9a-f]{8,17}$")
SUBNET_ID = re.compile(r"^subnet-[0-9a-f]{8,17}$")
AVAILABILITY_ZONE = re.compile(r"^[a-z]{2}(?:-[a-z]+)+-\d[a-z]$")
# ASG names, RDS identifiers, target group names, SSM document names.
AWS_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+@-]{0,254}$")
PROCESS_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
NETWORK_INTERFACE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
POSIX_PATH = re.compile(r"^/[A-Za-z0-9._/-]{0,255}$")
CIDR = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$")

SIGNALS = frozenset(
    {
        "SIGHUP",
        "SIGINT",
        "SIGQUIT",
        "SIGKILL",
        "SIGTERM",
        "SIGSTOP",
        "SIGCONT",
        "SIGUSR1",
        "SIGUSR2",
    }
)
IP_PROTOCOLS = frozenset({"tcp", "udp", "icmp", "-1"})

# Actions that change or destroy live infrastructure. Used to tag generated
# experiments and to decide whether a run needs an explicit confirmation.
DESTRUCTIVE_MARKERS = frozenset(
    {
        "fail_az",
        "terminate_instances",
        "terminate_random_instances",
        "stop_instances",
        "stop_random_instances",
        "restart_instances",
        "detach_random_volume",
        "detach_random_instances",
        "revoke_security_group_ingress",
        "authorize_security_group_ingress",
        "suspend_processes",
        "reboot_db_instance",
        "failover_db_cluster",
        "deregister_target",
        "send_command",
    }
)


class ValidationError(ValueError):
    """Raised when a tool argument fails validation."""


def workdir() -> Path:
    """Return the directory every path handled by the server is confined to."""
    raw = os.environ.get(WORKDIR_ENV)
    base = Path(raw).expanduser() if raw else Path.cwd()
    return base.resolve()


def _confine(candidate: str, field: str) -> Path:
    base = workdir()
    raw = Path(candidate).expanduser()
    path = (raw if raw.is_absolute() else base / raw).resolve()
    if path != base and not path.is_relative_to(base):
        raise ValidationError(
            f"{field} must stay inside {base} (got {path}). "
            f"Set the {WORKDIR_ENV} environment variable to allow another directory."
        )
    return path


def resolve_output_path(candidate: str | None, default: str) -> Path:
    """Resolve a writable ``.json`` path inside the workdir, creating parents."""
    value = (candidate or default).strip()
    if not value:
        raise ValidationError("output_file must not be empty")
    path = _confine(value, "output_file")
    if path.suffix.lower() != ".json":
        raise ValidationError(f"output_file must end with .json (got {path.name})")
    if path.is_dir():
        raise ValidationError(f"output_file points at a directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_existing_file(candidate: str, field: str) -> Path:
    """Resolve an existing file inside the workdir."""
    value = candidate.strip()
    if not value:
        raise ValidationError(f"{field} must not be empty")
    path = _confine(value, field)
    if not path.is_file():
        raise ValidationError(f"{field} not found: {path}")
    return path


def resolve_directory(candidate: str | None) -> Path:
    """Resolve an existing directory inside the workdir (defaults to workdir)."""
    if not candidate or not candidate.strip():
        return workdir()
    path = _confine(candidate.strip(), "working_directory")
    if not path.is_dir():
        raise ValidationError(f"working_directory not found: {path}")
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as pretty JSON."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def require(value: object, field: str) -> Any:
    """Reject ``None`` and empty containers for a required argument."""
    if value is None or (isinstance(value, str | list | dict) and len(value) == 0):
        raise ValidationError(f"{field} is required")
    return value


def match(pattern: re.Pattern[str], value: object, field: str) -> str:
    """Validate a single string against ``pattern``."""
    if not isinstance(value, str) or not pattern.match(value):
        raise ValidationError(f"{field} has an invalid value: {value!r}")
    return value


def match_all(pattern: re.Pattern[str], values: object, field: str) -> list[str]:
    """Validate every item of a list against ``pattern``."""
    if not isinstance(values, list) or not values:
        raise ValidationError(f"{field} must be a non-empty list")
    return [match(pattern, item, f"{field}[{index}]") for index, item in enumerate(values)]


def choice(value: object, allowed: Iterable[str], field: str, default: str | None = None) -> str:
    """Validate a value against a fixed set of choices."""
    if value is None and default is not None:
        return default
    options = sorted(allowed)
    if not isinstance(value, str) or value not in options:
        raise ValidationError(f"{field} must be one of {options} (got {value!r})")
    return value


def integer(value: object, field: str, *, minimum: int, maximum: int, default: int) -> int:
    """Validate an integer argument and clamp it to a sane range."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer (got {value!r})")
    if not minimum <= value <= maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum} (got {value})")
    return value


def boolean(value: object, field: str, *, default: bool) -> bool:
    """Validate a boolean argument."""
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean (got {value!r})")
    return value


def tag_filters(value: object, field: str) -> list[dict[str, Any]]:
    """Validate a list of EC2 style ``{"Name": ..., "Values": [...]}`` filters."""
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list of filters")
    filters: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or "Name" not in item or "Values" not in item:
            raise ValidationError(f"{field}[{index}] must have 'Name' and 'Values' keys")
        name = match(AWS_NAME, item["Name"], f"{field}[{index}].Name")
        values = item["Values"]
        if not isinstance(values, list) or not values:
            raise ValidationError(f"{field}[{index}].Values must be a non-empty list")
        filters.append({"Name": name, "Values": [str(entry) for entry in values]})
    return filters


def key_value_tags(value: object, field: str) -> list[dict[str, str]]:
    """Validate a list of ``{"Key": ..., "Value": ...}`` tags."""
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty list of Key/Value objects")
    tags: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or "Key" not in item or "Value" not in item:
            raise ValidationError(f"{field}[{index}] must have 'Key' and 'Value' keys")
        tags.append({"Key": str(item["Key"]), "Value": str(item["Value"])})
    return tags


def shell_path(value: object, field: str) -> str:
    """Validate an absolute POSIX path destined for a remote shell command."""
    path = match(POSIX_PATH, value, field)
    if ".." in path.split("/"):
        raise ValidationError(f"{field} must not contain '..' (got {path!r})")
    return path


def quote(value: str) -> str:
    """Shell-quote a value that is interpolated into a remote command."""
    return shlex.quote(value)


def is_destructive(funcs: Sequence[str]) -> bool:
    """Return whether any of the given activity functions changes live state."""
    return any(func in DESTRUCTIVE_MARKERS for func in funcs)
