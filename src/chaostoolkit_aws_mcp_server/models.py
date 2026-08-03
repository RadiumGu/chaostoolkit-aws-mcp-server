"""Pydantic models describing the pieces of a Chaos Toolkit experiment."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_REGION = "us-east-1"


def default_region() -> str:
    """Resolve the AWS region from the environment, falling back to us-east-1."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION


class ExperimentConfig(BaseModel):
    """Top level experiment metadata."""

    title: str = Field(min_length=1)
    description: str = ""
    aws_region: str = Field(default_factory=default_region)
    tags: list[str] = Field(default_factory=list)


class ProbeConfig(BaseModel):
    """A steady state probe backed by a Python function."""

    name: str
    type: Literal["probe"] = "probe"
    module: str
    func: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tolerance: Any = True


class HttpProbeConfig(BaseModel):
    """A steady state probe backed by the Chaos Toolkit HTTP provider.

    The HTTP provider returns a dict with a ``status`` key, and chaoslib compares
    an integer tolerance against that status, so ``expected_status`` maps onto
    the activity ``tolerance``.
    """

    name: str
    type: Literal["probe"] = "probe"
    url: str
    method: str = "GET"
    timeout: float = 3.0
    expected_status: int = 200
    verify_tls: bool = True


class ActionConfig(BaseModel):
    """A method or rollback activity backed by a Python function."""

    name: str
    type: Literal["action"] = "action"
    module: str
    func: str
    arguments: dict[str, Any] = Field(default_factory=dict)
