"""OpenCode integration contracts and JSONL sidecar."""

from .protocol import (
    OPERATIONS,
    PROTOCOL_VERSION,
    OpenCodeRequest,
    OpenCodeResponse,
    OpenCodeScope,
    ProtocolValidationError,
    Request,
    Response,
    Scope,
)
from .sidecar import Sidecar, main, run_jsonl

__all__ = [
    "OPERATIONS",
    "PROTOCOL_VERSION",
    "OpenCodeRequest",
    "OpenCodeResponse",
    "OpenCodeScope",
    "ProtocolValidationError",
    "Request",
    "Response",
    "Scope",
    "Sidecar",
    "main",
    "run_jsonl",
]
