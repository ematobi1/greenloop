import re

import pytest

from app.cli import run
from app.core import tokens
from app.db.models import PrincipalRow


def _token_from(output: str) -> str:
    return re.search(r"Token \(shown once\): (\S+)", output).group(1)


def test_create_issue_and_revoke_round_trip(session_factory, capsys):
    assert run(["create-principal", "terry", "Terry"], session_factory) == 0
    assert run(["issue-token", "terry", "--label", "laptop"], session_factory) == 0
    output = capsys.readouterr().out
    token = _token_from(output)
    token_id = re.search(r"Token id: (\S+)", output).group(1)
    with session_factory() as session:
        assert tokens.find_active_principal(session, token).principal_id == "terry"

    assert run(["revoke-token", token_id], session_factory) == 0
    with session_factory() as session:
        assert tokens.find_active_principal(session, token) is None


def test_duplicate_principal_fails_cleanly(session_factory, capsys):
    run(["create-principal", "terry", "Terry"], session_factory)
    assert run(["create-principal", "terry", "Terry again"], session_factory) == 1
    assert "already exists" in capsys.readouterr().err


def test_issue_token_for_unknown_principal_fails_cleanly(session_factory, capsys):
    assert run(["issue-token", "ghost"], session_factory) == 1
    assert "no such principal" in capsys.readouterr().err


def test_revoke_unknown_token_fails_cleanly(session_factory, capsys):
    assert run(["revoke-token", "tok-missing"], session_factory) == 1
    assert "no such token" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["create-principal", "bad id", "Name"],
        ["create-principal", "-leading-dash", "Name"],
        ["create-principal", "ok", "   "],
        ["issue-token", "ok", "--label", "x" * 101],
    ],
)
def test_invalid_arguments_exit_with_usage_error(session_factory, argv):
    with pytest.raises(SystemExit) as exit_info:
        run(argv, session_factory)
    assert exit_info.value.code == 2


def test_create_principal_with_system_role(session_factory, capsys):
    argv = ["create-principal", "verifier", "Verifier", "--role", "system"]
    assert run(argv, session_factory) == 0
    assert "Created system principal verifier." in capsys.readouterr().out
    with session_factory() as session:
        assert session.get(PrincipalRow, "verifier").role == "system"


def test_principals_default_to_the_user_role(session_factory):
    run(["create-principal", "terry", "Terry"], session_factory)
    with session_factory() as session:
        assert session.get(PrincipalRow, "terry").role == "user"


def test_unknown_role_is_a_usage_error(session_factory):
    with pytest.raises(SystemExit) as exit_info:
        run(["create-principal", "x", "X", "--role", "admin"], session_factory)
    assert exit_info.value.code == 2
