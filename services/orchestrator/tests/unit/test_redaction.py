import pytest

from app.core.redaction import HOLD_BACK_CHARS, REDACTED, Redactor, redact_event_dict

SECRETS = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-abcdefghijklmnopqrstuvwxyz0123456789",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_abcdefghijklmnopqrstuvwxyz0123",
    "AKIAABCDEFGHIJKLMNOP",
    "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
]
KEY_BODY = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy"
PEM = f"-----BEGIN RSA PRIVATE KEY-----\n{KEY_BODY}\n-----END RSA PRIVATE KEY-----"


def stream_in_chunks(redactor: Redactor, text: str, size: int) -> str:
    stream = redactor.stream()
    output = "".join(stream.feed(text[i : i + size]) for i in range(0, len(text), size))
    return output + stream.flush()


class TestBatch:
    @pytest.mark.parametrize("secret", SECRETS)
    def test_known_secret_formats_are_redacted(self, secret):
        redacted = Redactor().redact(f"here is my key {secret} please keep it")
        assert secret not in redacted
        assert REDACTED in redacted

    def test_bearer_and_authorization_values_are_redacted(self):
        text = (
            "curl -H 'Authorization: Bearer abc123def456ghi789' and Authorization: rawsecretvalue99"
        )
        redacted = Redactor().redact(text)
        assert "abc123def456ghi789" not in redacted
        assert "rawsecretvalue99" not in redacted
        assert "Bearer" in redacted

    def test_key_value_secrets_keep_the_label_and_hide_the_value(self):
        redacted = Redactor().redact("password: hunter2hunter2 and API_KEY=zzzzzzzzzzzz")
        assert "hunter2hunter2" not in redacted
        assert "zzzzzzzzzzzz" not in redacted
        assert "password" in redacted and "API_KEY" in redacted

    def test_private_key_block_is_redacted(self):
        assert KEY_BODY not in Redactor().redact(f"my key:\n{PEM}\nthanks")

    def test_unterminated_private_key_is_redacted_to_the_end(self):
        redacted = Redactor().redact(f"x -----BEGIN PRIVATE KEY-----\n{KEY_BODY}")
        assert KEY_BODY not in redacted

    def test_exact_known_secret_is_redacted_without_a_known_format(self):
        redacted = Redactor(known_secrets=["plain-credential-value"]).redact(
            "x plain-credential-value y"
        )
        assert redacted == f"x {REDACTED} y"

    def test_longer_known_secret_wins_over_its_prefix(self):
        redactor = Redactor(known_secrets=["abcdefgh", "abcdefgh-longer"])
        assert redactor.redact("abcdefgh-longer") == REDACTED

    def test_short_known_secrets_are_ignored_to_avoid_mangling_text(self):
        assert Redactor(known_secrets=["abc"]).redact("abc def") == "abc def"

    def test_plain_text_is_untouched(self):
        text = "Meet at 5pm. The password policy is strong. Token ring networks are old."
        assert Redactor().redact(text) == text

    def test_redact_counted_reports_every_hit(self):
        text = f"{SECRETS[0]} and {SECRETS[2]} and password=hunter2hunter2"
        redacted, count = Redactor().redact_counted(text)
        assert count == 3
        assert redacted.count(REDACTED) == 3

    def test_clean_text_counts_zero(self):
        assert Redactor().redact_counted("nothing to see")[1] == 0


class TestStream:
    @pytest.mark.parametrize("chunk_size", [1, 3, 7, 50])
    def test_catches_secrets_split_across_chunks(self, chunk_size):
        filler = "word " * 200
        text = f"{filler}my key is {SECRETS[0]} and then more text {filler}"
        output = stream_in_chunks(Redactor(), text, chunk_size)
        assert SECRETS[0] not in output
        assert "and then more text" in output

    @pytest.mark.parametrize("chunk_size", [1, 5, 40])
    def test_handles_label_then_value_split(self, chunk_size):
        filler = "lorem ipsum " * 60
        text = f"{filler}Authorization: Bearer supersecrettokenvalue123 {filler}"
        assert "supersecrettokenvalue123" not in stream_in_chunks(Redactor(), text, chunk_size)

    @pytest.mark.parametrize("chunk_size", [1, 4, 16, 64])
    def test_private_key_body_split_across_chunks_never_leaks(self, chunk_size):
        filler = "text " * 100
        text = f"{filler}\n{PEM}\n{filler}after the key"
        output = stream_in_chunks(Redactor(), text, chunk_size)
        assert KEY_BODY not in output
        for piece in ("MIIBOg", "AKj34G", "InFEX6"):
            assert piece not in output
        assert "after the key" in output

    def test_unterminated_key_in_a_long_stream_is_suppressed(self):
        body = "A" * 9000
        output = stream_in_chunks(
            Redactor(), f"start -----BEGIN PRIVATE KEY-----\n{body} tail", 100
        )
        assert "AAAAAAAAAA" not in output
        assert output.startswith("start")

    def test_matches_batch_redaction_for_clean_text(self):
        text = "The quick brown fox. " * 100
        assert stream_in_chunks(Redactor(), text, 13) == Redactor().redact(text)

    def test_holds_back_only_a_bounded_tail(self):
        stream = Redactor().stream()
        total = HOLD_BACK_CHARS * 4
        early = stream.feed("a " * (total // 2))
        assert total - 2 * HOLD_BACK_CHARS < len(early) <= total - HOLD_BACK_CHARS
        assert len(early) + len(stream.flush()) == total

    def test_known_secrets_apply_to_streams(self):
        output = stream_in_chunks(
            Redactor(known_secrets=["my-db-password-123"]), "x " * 50 + "my-db-password-123 end", 3
        )
        assert "my-db-password-123" not in output


def test_structlog_processor_redacts_nested_values():
    processor = redact_event_dict(Redactor())
    result = processor(None, "info", {"event": "x", "detail": {"key": ["Bearer abcdefghijk12345"]}})
    assert "abcdefghijk12345" not in str(result)
    assert result["event"] == "x"


def test_structlog_processor_leaves_non_strings_alone():
    processor = redact_event_dict(Redactor())
    assert processor(None, "info", {"status": 200, "ok": True}) == {"status": 200, "ok": True}


class TestCurrentBehaviorPinned:
    """Exact outputs that must not change when new redaction rules are added."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("password=hunter2abc", "password=[REDACTED]"),
            ("api_key: abcdef123456", "api_key: [REDACTED]"),
            ('password="hunter2abc"', 'password="[REDACTED]"'),
            ("client_secret = s3cr3tvalue", "client_secret = [REDACTED]"),
            ("Authorization: Bearer abc123def456ghi789", "Authorization: Bearer [REDACTED]"),
            ("password=abc", "password=abc"),
            ("the token is valid", "the token is valid"),
        ],
    )
    def test_labelled_values(self, text, expected):
        assert Redactor().redact(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            '{"name": "Terry", "token_count": 12}',
            '{"max_tokens": 16000, "model": "claude-opus-5-5"}',
            '{"secret_santa": true}',
            "Tokens: 1200 input, 300 output.",
        ],
    )
    def test_harmless_text_and_json_are_unchanged(self, text):
        assert Redactor().redact(text) == text

    def test_a_known_secret_without_a_recognized_shape_is_redacted(self):
        secret = "plain-known-value-42"
        redacted, count = Redactor([secret]).redact_counted(f"a {secret} b {secret}")
        assert (redacted, count) == (f"a {REDACTED} b {REDACTED}", 2)

    def test_redaction_counts_each_hit(self):
        text = "password=hunter2abc and api_key: abcdef123456"
        assert Redactor().redact_counted(text)[1] == 2


JSON_SECRETS = [
    ('{"password": "hunter2-synthetic"}', '{"password": "[REDACTED]"}'),
    ('{"api_key": "abcdef123456"}', '{"api_key": "[REDACTED]"}'),
    ('{"apiKey":"abcdef123456"}', '{"apiKey":"[REDACTED]"}'),
    ('{"db_password": "pa ss word 1"}', '{"db_password": "[REDACTED]"}'),
    ('{"access_token": "tok-1234567"}', '{"access_token": "[REDACTED]"}'),
    ("{'client_secret': 'cs-1234567'}", "{'client_secret': '[REDACTED]'}"),
    ('{"Authorization": "Basic dXNlcjpwYXNz"}', '{"Authorization": "[REDACTED]"}'),
]


class TestJsonForm:
    @pytest.mark.parametrize(("text", "expected"), JSON_SECRETS)
    def test_json_and_dict_secrets_keep_the_key_and_hide_the_value(self, text, expected):
        assert Redactor().redact(text) == expected

    @pytest.mark.parametrize(("text", "expected"), JSON_SECRETS)
    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13])
    def test_json_secrets_split_across_chunks_are_redacted(self, text, expected, chunk_size):
        padded = f"Here is the config: {text} done."
        assert stream_in_chunks(Redactor(), padded, chunk_size) == (
            f"Here is the config: {expected} done."
        )

    def test_short_json_values_stay_visible(self):
        assert Redactor().redact('{"password": "abc"}') == '{"password": "abc"}'
