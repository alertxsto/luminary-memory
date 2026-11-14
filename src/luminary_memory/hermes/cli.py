"""Ordinary Hermes CLI commands; settings and inspector binding never activate a provider."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def bind_inspector(args) -> int:
    """Owner-approved exact record scope; does not activate a provider or UI."""
    from .inspector import native_session_context
    native = native_session_context(args.session)
    if args.agent != native["agent_id"]:
        raise PermissionError("Agent must equal the native provider's profile identity")
    if args.owner != args.user:
        raise PermissionError("One-owner inspector requires the exact record user to be its owner")
    if native.get("user_id") and (
        args.user != native["user_id"] or args.workspace != native["workspace_id"]
    ):
        raise PermissionError("Binding must match the complete native session provider scope")
    values = [args.owner, args.user, args.workspace, args.agent]
    if any(not value.strip() or len(value) > 4096 for value in values):
        raise ValueError("Nonempty exact owner and record scope are required")
    binding = {"owner_user_id": args.owner,
               "record_scope": {"user_id": args.user, "workspace_id": args.workspace, "agent_id": args.agent}}
    path = Path(native["profile_id"]) / "luminary" / "inspector.json"
    print("Native profile:", native["profile_id"])
    print("Native session workspace (location, not record scope):", native["workspace"])
    print(json.dumps(binding, indent=2))
    print("This binds existing exact record scope. No records are copied or reattributed; saving is unchanged.")
    if not sys.stdin.isatty() or input("Persist this owner-approved binding? [y/N] ").strip().lower() != "y":
        print("Cancelled; no binding changed.")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".inspector-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(binding, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Binding saved. Open Luminary Inspector in Hermes Desktop or dashboard; enable its backend separately.")
    return 0


def configure(args) -> int:
    """Consume the same real typed fields as Hermes's dashboard, in one profile."""
    from hermes_constants import get_hermes_home

    from .config import _typed_value, save_config
    from .config_schema import CONFIG_SCHEMA

    fields = {field.key: field for field in CONFIG_SCHEMA.fields}
    changes = {}
    for assignment in args.values:
        key, separator, value = assignment.partition("=")
        field = fields.get(key)
        if not separator or field is None or field.is_secret:
            raise ValueError("Use --set with a declared non-secret KEY=VALUE; secrets require --secret FIELD")
        if field.options and value not in field.allowed_values():
            raise ValueError(f"Invalid option for {key}")
        changes[key] = _typed_value(key, value)
    secret_fields = []
    for key in args.secrets:
        field = fields.get(key)
        if field is None or not field.is_secret or not field.env_key:
            raise ValueError("--secret requires a declared secret field")
        secret_fields.append(field)
    if secret_fields and not sys.stdin.isatty():
        raise PermissionError("Secret entry requires an interactive native owner terminal")
    if not changes and not secret_fields:
        print("Fields:", ", ".join(fields))
        print("Use configure --set KEY=VALUE or --secret FIELD; this never activates a provider.")
        return 0
    secret_values = []
    if secret_fields:
        from hermes_cli.secret_prompt import masked_secret_prompt
        for field in secret_fields:
            value = masked_secret_prompt(f"{field.label} (blank keeps the current secret): ")
            if value:
                secret_values.append((field.env_key, value))
    home = str(get_hermes_home())
    if changes:
        save_config(changes, home)
    if secret_values:
        from hermes_cli.config import save_env_value
        for env_key, value in secret_values:
            save_env_value(env_key, value)
    print("Profile settings saved; restart existing provider sessions. Provider activation is unchanged.")
    return 0


def register_cli(subparser) -> None:
    """Register only commands, never claim a custom rich terminal UI seam."""
    commands = subparser.add_subparsers(dest="luminary_command")
    bind = commands.add_parser("inspector-bind", help="Explicitly bind this native profile to an existing exact record scope")
    bind.add_argument("--session", required=True, help="Existing native session with a recorded cwd")
    bind.add_argument("--owner", required=True)
    bind.add_argument("--user", required=True, help="Exact existing provider record user_id, not a display name")
    bind.add_argument("--workspace", required=True, help="Exact existing provider record workspace_id, not inferred from cwd")
    bind.add_argument("--agent", required=True, help="Exact provider agent_identity (native profile name)")
    bind.set_defaults(func=bind_inspector)
    settings = commands.add_parser("configure", help="Persist typed profile settings without activating a provider")
    settings.add_argument("--set", dest="values", action="append", default=[], metavar="KEY=VALUE")
    settings.add_argument("--secret", dest="secrets", action="append", default=[], metavar="FIELD")
    settings.set_defaults(func=configure)
