"""Admin CLI for broker service tokens. Run from services/broker:

    python -m app.cli issue-service-token --name orchestrator
    python -m app.cli list-service-tokens
    python -m app.cli revoke-service-token svc-...

issue-service-token writes the token, and nothing else, to stdout once, so it can be
piped straight into the clipboard without appearing on screen:

    python -m app.cli issue-service-token --name orchestrator | Set-Clipboard

Everything else (token id, hints, errors) goes to stderr. Only the token's SHA256
is stored.
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app import service_tokens
from app.config import get_settings
from app.db.session import DatabaseNotConfiguredError, database_url, make_engine
from greenloop_contracts.base import Identifier

_identifier = TypeAdapter(Identifier)


def _identifier_arg(value: str) -> str:
    try:
        return _identifier.validate_python(value)
    except ValidationError:
        raise argparse.ArgumentTypeError(
            "must be 1-128 chars: letters, digits, . _ : - and start alphanumeric"
        ) from None


def _name_arg(value: str) -> str:
    value = _identifier_arg(value)
    if len(value) > 100:
        raise argparse.ArgumentTypeError("must be at most 100 characters")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue-service-token")
    issue.add_argument("--name", type=_name_arg, required=True)
    commands.add_parser("list-service-tokens")
    revoke = commands.add_parser("revoke-service-token")
    revoke.add_argument("token_id", type=_identifier_arg)
    return parser


def run(argv: Sequence[str], engine: Engine) -> int:
    args = _parser().parse_args(argv)
    if args.command == "issue-service-token":
        token_id, token = service_tokens.issue(engine, args.name)
        print(token)
        print(
            f"Issued {token_id} for {args.name}. The token was written to stdout once and"
            " is not stored; put it in BROKER_SERVICE_TOKEN for the orchestrator.",
            file=sys.stderr,
        )
        return 0
    if args.command == "list-service-tokens":
        for info in service_tokens.list_all(engine):
            state = f"revoked {info.revoked_at.isoformat()}" if info.revoked_at else "active"
            print(f"{info.token_id}  {info.name}  created {info.created_at.isoformat()}  {state}")
        return 0
    if service_tokens.revoke(engine, args.token_id):
        print(f"Revoked {args.token_id}.", file=sys.stderr)
        return 0
    print(f"Error: no active service token {args.token_id}.", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        engine = make_engine(database_url(get_settings()))
    except DatabaseNotConfiguredError:
        print("Error: BROKER_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    try:
        return run(sys.argv[1:] if argv is None else argv, engine)
    except OperationalError:
        print("Error: could not reach the broker database.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
