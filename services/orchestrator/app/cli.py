"""Admin CLI for principals and tokens. Run from services/orchestrator:

    python -m app.cli create-principal terry "Terry"
    python -m app.cli create-principal verifier "Verifier" --role system
    python -m app.cli issue-token terry --label laptop
    python -m app.cli revoke-token tok-...

issue-token prints the token once on stdout. Only its SHA256 is stored.
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Sequence

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import accounts, tokens
from app.core.config import get_settings
from app.db.models import PrincipalRole, PrincipalRow
from app.db.session import make_engine, make_session_factory
from app.memory import indexing
from app.memory.embeddings import Embedder, build_embedder
from greenloop_contracts.base import Identifier

_identifier = TypeAdapter(Identifier)


NEW_PASSWORD_VARIABLE = "GREENLOOP_NEW_PASSWORD"  # noqa: S105 - variable name, not a value


def _identifier_arg(value: str) -> str:
    try:
        return _identifier.validate_python(value)
    except ValidationError:
        raise argparse.ArgumentTypeError(
            "must be 1-128 chars: letters, digits, . _ : - and start alphanumeric"
        ) from None


def _text_arg(max_chars: int) -> Callable[[str], str]:
    def parse(value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= max_chars:
            raise argparse.ArgumentTypeError(f"must be 1-{max_chars} characters")
        return value

    return parse


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-principal")
    create.add_argument("principal_id", type=_identifier_arg)
    create.add_argument("display_name", type=_text_arg(200))
    create.add_argument(
        "--role", type=PrincipalRole, choices=list(PrincipalRole), default=PrincipalRole.USER
    )
    issue = commands.add_parser("issue-token")
    issue.add_argument("principal_id", type=_identifier_arg)
    issue.add_argument("--label", type=_text_arg(100), default="default")
    revoke = commands.add_parser("revoke-token")
    revoke.add_argument("token_id", type=_identifier_arg)
    create_user = commands.add_parser(
        "create-user", help="Give a principal a web username and password (ADR 0012)."
    )
    create_user.add_argument("principal_id", type=_identifier_arg)
    create_user.add_argument("username")
    password = commands.add_parser(
        "set-password", help="Replace a user's password; signs out all their sessions."
    )
    password.add_argument("principal_id", type=_identifier_arg)
    sessions = commands.add_parser("revoke-sessions", help="Sign a user out everywhere.")
    sessions.add_argument("principal_id", type=_identifier_arg)
    unlock = commands.add_parser("unlock-user", help="Lift a sign-in lockout on a username.")
    unlock.add_argument("username")
    commands.add_parser(
        "embed-memory", help="Add embeddings to live memory records that have none (ADR 0011)."
    )
    return parser


def run(
    argv: Sequence[str],
    session_factory: Callable[[], Session],
    embedder: Embedder | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "embed-memory":
        return _embed_memory(session_factory, embedder)
    if args.command in {"create-user", "set-password", "revoke-sessions", "unlock-user"}:
        return _accounts(args, session_factory)
    with session_factory() as session:
        try:
            if args.command == "create-principal":
                tokens.create_principal(session, args.principal_id, args.display_name, args.role)
                message = f"Created {args.role.value} principal {args.principal_id}."
            elif args.command == "issue-token":
                token_id, token = tokens.issue_token(session, args.principal_id, args.label)
                message = f"Token id: {token_id}\nToken (shown once): {token}"
            else:
                tokens.revoke_token(session, args.token_id)
                message = f"Revoked {args.token_id}."
            session.commit()
        except IntegrityError:
            print("Error: that principal already exists.", file=sys.stderr)
            return 1
        except tokens.PrincipalNotFoundError:
            print("Error: no such principal.", file=sys.stderr)
            return 1
        except tokens.TokenNotFoundError:
            print("Error: no such token.", file=sys.stderr)
            return 1
    print(message)
    return 0


def read_new_password() -> str:
    """GREENLOOP_NEW_PASSWORD if set (scripts, tests), else a hidden prompt, asked twice."""
    from_env = os.environ.get(NEW_PASSWORD_VARIABLE)
    if from_env:
        return from_env
    first = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != first:
        raise accounts.AccountError("The passwords don't match.")
    return first


def _accounts(args: argparse.Namespace, session_factory: Callable[[], Session]) -> int:
    with session_factory() as session:
        try:
            if args.command == "create-user":
                accounts.create_user(session, args.principal_id, args.username, read_new_password())
                message = f"{args.principal_id} can now sign in as {args.username.strip().lower()}."
            elif args.command == "set-password":
                revoked = accounts.set_password(session, args.principal_id, read_new_password())
                message = f"Password changed; {revoked} sessions signed out."
            elif args.command == "unlock-user":
                unlocked = accounts.unlock_user(session, args.username)
                message = "Unlocked." if unlocked else "That username was not locked."
            else:
                if session.get(PrincipalRow, args.principal_id) is None:
                    raise accounts.AccountError("No such principal.")
                revoked = accounts.revoke_all_sessions(
                    session, args.principal_id, actor="admin-cli"
                )
                message = f"{revoked} sessions signed out."
            session.commit()
        except accounts.AccountError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
    print(message)
    return 0


def _embed_memory(session_factory: Callable[[], Session], embedder: Embedder | None) -> int:
    if embedder is None:
        print("Error: set EMBEDDING_PROVIDER first (see ADR 0011).", file=sys.stderr)
        return 1
    with session_factory() as session:
        added = asyncio.run(indexing.backfill(session, embedder))
        left = len(indexing.unembedded_live_records(session, embedder.model, 1))
    print(f"Embedded {added} memory records with {embedder.model}.")
    if left:
        print(
            "Error: some records are still missing embeddings; is the embedder up?", file=sys.stderr
        )
        return 1
    return 0


def main() -> int:
    settings = get_settings()
    return run(sys.argv[1:], make_session_factory(make_engine(settings)), build_embedder(settings))


if __name__ == "__main__":
    raise SystemExit(main())
