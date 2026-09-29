import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.auth import get_current_principal
from app.core.errors import ApiError
from app.db.models import PrincipalRole


def _bearer(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_authentication_leaves_no_open_transaction(session_factory, issue_token):
    token = issue_token("user-1", PrincipalRole.SYSTEM)
    with session_factory() as session:
        principal = get_current_principal(_bearer(token), session)
        assert not session.in_transaction()
    assert (principal.principal_id, principal.role) == ("user-1", PrincipalRole.SYSTEM)


def test_a_rejected_token_also_leaves_no_open_transaction(session_factory):
    with session_factory() as session:
        with pytest.raises(ApiError) as err:
            get_current_principal(_bearer("not-a-token"), session)
        assert not session.in_transaction()
    assert err.value.status_code == 401
