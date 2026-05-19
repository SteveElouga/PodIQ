"""
GraphQL register and login mutation tests.
gRPC clients are fully mocked; no database required.
"""

from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest
from graphql import GraphQLError

from app.api_codes import GRAPHQL_EXTENSION_CODE, ErrorCode
from tests.grpc_fake import FakeRpcError

_FAKE_PASS = "test-pass-123"

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_auth_response(token="tok-abc", user_id="uid-123", email="user@test.com"):
    return SimpleNamespace(token=token, user_id=user_id, email=email)


# ── email validation ──────────────────────────────────────────────────────────


class TestEmailValidation:
    @pytest.mark.parametrize(
        "bad_email",
        [
            "pas-un-email",
            "@nodomain.com",
            "no-at-sign",
            "missing@",
            "",
        ],
    )
    def test_invalid_emails_raise_graphql_error(self, bad_email):
        from app.graphql.mutations.auth import _validate_email

        with pytest.raises(GraphQLError) as exc_info:
            _validate_email(bad_email)

        assert exc_info.value.message == "Invalid email address"
        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE]
            == ErrorCode.VALIDATION.value
        )

    @pytest.mark.parametrize(
        "good_email",
        [
            "user@test.com",
            "alice.bob+tag@sub.domain.org",
            "x@y.io",
        ],
    )
    def test_valid_emails_pass(self, good_email):
        from app.graphql.mutations.auth import _validate_email

        _validate_email(good_email)  # must not raise

    def test_register_invalid_email_does_not_call_grpc(self):
        with patch("app.graphql.mutations.auth.auth_client.register") as mock_fn:
            from app.graphql.mutations.auth import _register as register

            with pytest.raises(GraphQLError):
                register(email="pas-un-email", password=_FAKE_PASS)

        mock_fn.assert_not_called()

    def test_login_invalid_email_does_not_call_grpc(self):
        with patch("app.graphql.mutations.auth.auth_client.login") as mock_fn:
            from app.graphql.mutations.auth import _login as login

            with pytest.raises(GraphQLError):
                login(email="pas-un-email", password=_FAKE_PASS)

        mock_fn.assert_not_called()


# ── register ──────────────────────────────────────────────────────────────────


class TestRegisterMutation:
    def test_register_returns_auth_payload(self):
        mock_resp = make_auth_response(
            token="jwt-token-xyz",
            user_id="uid-999",
            email="new@test.com",
        )
        with patch(
            "app.graphql.mutations.auth.auth_client.register", return_value=mock_resp
        ):
            from app.graphql.mutations.auth import _register as register

            result = register(email="new@test.com", password=_FAKE_PASS)

        assert result.token == "jwt-token-xyz"
        assert result.user_id == "uid-999"
        assert result.email == "new@test.com"

    def test_register_passes_email_and_password_to_client(self):
        mock_resp = make_auth_response()
        with patch(
            "app.graphql.mutations.auth.auth_client.register", return_value=mock_resp
        ) as mock_fn:
            from app.graphql.mutations.auth import _register as register

            register(email="alice@test.com", password=_FAKE_PASS)

        mock_fn.assert_called_once_with(email="alice@test.com", password=_FAKE_PASS)

    def test_register_maps_grpc_to_graphql_error(self):
        err = FakeRpcError(
            grpc.StatusCode.ALREADY_EXISTS, "This email is already registered"
        )
        with patch("app.graphql.mutations.auth.auth_client.register", side_effect=err):
            from app.graphql.mutations.auth import _register as register

            with pytest.raises(GraphQLError) as exc_info:
                register(email="dup@test.com", password=_FAKE_PASS)

        assert exc_info.value.message == "This email is already registered"
        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE]
            == ErrorCode.CONFLICT.value
        )


# ── login ─────────────────────────────────────────────────────────────────────


class TestLoginMutation:
    def test_login_returns_auth_payload(self):
        mock_resp = make_auth_response(
            token="login-token",
            user_id="uid-456",
            email="user@test.com",
        )
        with patch(
            "app.graphql.mutations.auth.auth_client.login", return_value=mock_resp
        ):
            from app.graphql.mutations.auth import _login as login

            result = login(email="user@test.com", password=_FAKE_PASS)

        assert result.token == "login-token"
        assert result.user_id == "uid-456"
        assert result.email == "user@test.com"

    def test_login_passes_credentials_to_client(self):
        mock_resp = make_auth_response()
        with patch(
            "app.graphql.mutations.auth.auth_client.login", return_value=mock_resp
        ) as mock_fn:
            from app.graphql.mutations.auth import _login as login

            login(email="bob@test.com", password=_FAKE_PASS)

        mock_fn.assert_called_once_with(email="bob@test.com", password=_FAKE_PASS)

    def test_login_maps_grpc_to_graphql_error(self):
        err = FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "Invalid email or password")
        with patch("app.graphql.mutations.auth.auth_client.login", side_effect=err):
            from app.graphql.mutations.auth import _login as login

            with pytest.raises(GraphQLError) as exc_info:
                login(email="x@test.com", password=_FAKE_PASS)

        assert exc_info.value.message == "Invalid email or password"
        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE]
            == ErrorCode.UNAUTHORIZED.value
        )
