"""
Unit tests for app/parsers/log_cleaner.py.
Pure functions — no external dependencies.
"""
from app.parsers.log_cleaner import truncate, mask_secrets, clean, MAX_LOG_LINES


class TestTruncate:
    def test_short_log_is_unchanged(self):
        logs = "line1\nline2\nline3"
        assert truncate(logs) == logs

    def test_exact_max_lines_is_unchanged(self):
        logs = "\n".join(f"line{i}" for i in range(MAX_LOG_LINES))
        result = truncate(logs)
        assert result == logs

    def test_over_limit_adds_header(self):
        lines = [f"line{i}" for i in range(MAX_LOG_LINES + 10)]
        result = truncate("\n".join(lines))
        assert result.startswith("[... truncated")

    def test_over_limit_keeps_last_n_lines(self):
        lines = [f"line{i}" for i in range(MAX_LOG_LINES + 5)]
        result = truncate("\n".join(lines))
        result_lines = result.splitlines()[1:]
        assert result_lines == lines[-MAX_LOG_LINES:]

    def test_custom_max_lines(self):
        logs = "a\nb\nc\nd\ne"
        result = truncate(logs, max_lines=3)
        assert result.startswith("[... truncated")
        assert "c\nd\ne" in result

    def test_empty_string_is_unchanged(self):
        assert truncate("") == ""

    def test_single_line_is_unchanged(self):
        assert truncate("one line") == "one line"


class TestMaskSecrets:
    def test_masks_password_equals(self):
        result = mask_secrets("password=supersecret")
        assert "supersecret" not in result
        assert "***" in result

    def test_masks_password_colon(self):
        result = mask_secrets("password: mysecret")
        assert "mysecret" not in result

    def test_masks_secret_equals(self):
        result = mask_secrets("secret=abc123")
        assert "abc123" not in result

    def test_masks_token_equals(self):
        result = mask_secrets("token=eyJhbGciOiJIUzI1")
        assert "eyJhbGciOiJIUzI1" not in result

    def test_masks_api_key_equals(self):
        result = mask_secrets("api_key=sk-1234abcd")
        assert "sk-1234abcd" not in result

    def test_masks_bearer_token(self):
        result = mask_secrets("Authorization: Bearer eyJ.abc.def")
        assert "eyJ.abc.def" not in result

    def test_masks_private_key(self):
        result = mask_secrets("private_key=-----BEGIN RSA")
        assert "-----BEGIN RSA" not in result

    def test_masks_case_insensitive(self):
        result = mask_secrets("PASSWORD=topsecret")
        assert "topsecret" not in result

    def test_non_secret_text_unchanged(self):
        text = "pod crashloopbackoff in namespace default"
        assert mask_secrets(text) == text

    def test_multiple_secrets_in_one_string(self):
        text = "password=abc token=xyz"
        result = mask_secrets(text)
        assert "abc" not in result
        assert "xyz" not in result


class TestClean:
    def test_clean_combines_truncate_and_mask(self):
        lines = [f"line{i}" for i in range(MAX_LOG_LINES + 5)]
        lines.append("password=secret")
        result = clean("\n".join(lines))
        assert result.startswith("[... truncated")
        assert "secret" not in result

    def test_clean_on_short_safe_log_is_passthrough(self):
        log = "INFO: server started on port 8080"
        assert clean(log) == log
