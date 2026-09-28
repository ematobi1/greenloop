"""Admin CLI for principals and tokens. Run from services/orchestrator:

    python -m app.cli create-principal terry "Terry"
    python -m app.cli issue-token terry --label laptop
    python -m app.cli revoke-token tok-...

issue-token prints the token once on stdout. Only its SHA256 is stored.
"""

import argparse
import sys
from collections.abc import Callable, Sequence

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import tokens
from app.core.config import get_settings
from app.db.session import make_engine, make_session_factory
from greenloop_contracts.base import Identifier

_identifier = TypeAdapter(Identifier)


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
    issue = commands.add_parser("issue-token")
    issue.add_argument("principal_id", type=_identifier_arg)
    issue.add_argument("--label", type=_text_arg(100), default="default")
    revoke = commands.add_parser("revoke-token")
    revoke.add_argument("token_id", type=_identifier_arg)
    return parser


def run(argv: Sequence[str], session_factory: Callable[[], Session]) -> int:
    args = _parser().parse_args(argv)
    with session_factory() as session:
        try:
            if args.command == "create-principal":
                tokens.create_principal(session, args.principal_id, args.display_name)
                message = f"Created principal {args.principal_id}."
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


def main() -> int:
    return run(sys.argv[1:], make_session_factory(make_engine(get_settings())))


if __name__ == "__main__":
    raise SystemExit(main())
