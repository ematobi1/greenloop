import pytest

from greenloop_contracts import ToolPermission, canonical_operation, operation_hash

HASH_OF_DEFAULT = "11bf1d7bb5c6f77f4126555c73c3c7947860d3a8d47fde20add6181a6c30c452"


@pytest.fixture
def permission():
    def factory(
        tool="github",
        operation="create_issue",
        consequence="write",
        principal_id="user-1",
        **arguments,
    ):
        return ToolPermission(
            principal_id=principal_id,
            tool=tool,
            operation=operation,
            consequence=consequence,
            arguments=arguments or {"repo": "greenloop", "title": "Bug"},
        )

    return factory


class TestCanonicalHash:
    def test_argument_order_does_not_change_hash(self, permission):
        first = permission(repo="greenloop", title="Bug")
        second = permission(title="Bug", repo="greenloop")
        assert operation_hash(first) == operation_hash(second)

    def test_canonical_form_is_compact_sorted_utf8(self, permission):
        canonical = canonical_operation(permission(title="café"))
        assert b" " not in canonical.replace(b"create_issue", b"")
        assert "café".encode() in canonical
        assert canonical.index(b'"arguments"') < canonical.index(b'"tool"')

    @pytest.mark.parametrize(
        "change",
        [
            {"title": "Bug!"},
            {"title": "Bug", "labels": ["x"]},
            {"repo": "other"},
        ],
    )
    def test_any_argument_change_changes_hash(self, permission, change):
        original = permission(repo="greenloop", title="Bug")
        changed = permission(**{"repo": "greenloop", "title": "Bug", **change})
        assert operation_hash(original) != operation_hash(changed)

    def test_principal_and_operation_are_bound(self, permission):
        base = operation_hash(permission())
        assert base != operation_hash(permission(principal_id="user-2"))
        assert base != operation_hash(permission(operation="create_pull_request"))
        assert base != operation_hash(permission(consequence="send"))

    def test_hash_is_lowercase_sha256_hex(self, permission):
        digest = operation_hash(permission())
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)

    def test_the_canonical_form_is_pinned(self, permission):
        """Every service must produce these exact bytes; changing them invalidates
        every stored approval."""
        assert canonical_operation(permission()) == (
            b'{"agent_id":null,"arguments":{"repo":"greenloop","title":"Bug"},'
            b'"consequence":"write","operation":"create_issue","principal_id":"user-1",'
            b'"tool":"github"}'
        )
        assert operation_hash(permission()) == HASH_OF_DEFAULT

    def test_values_are_hashed_as_written_not_normalized(self, permission):
        assert operation_hash(permission(n=1)) != operation_hash(permission(n=1.0))
        nfc, nfd = "café", "café"
        assert operation_hash(permission(title=nfc)) != operation_hash(permission(title=nfd))
