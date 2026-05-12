"""
Tests des mutations GraphQL register et login.
Les clients gRPC sont entièrement mockés — aucune base de données requise.
"""

from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest
from graphql import GraphQLError

from app.api_codes import GRAPHQL_EXTENSION_CODE, ErrorCode
from tests.grpc_fake import FakeRpcError

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_auth_response(token="tok-abc", user_id="uid-123", email="user@test.com"):
    return SimpleNamespace(token=token, user_id=user_id, email=email)


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

            result = register(info=None, email="new@test.com", password="pass1234")

        assert result.token == "jwt-token-xyz"
        assert result.user_id == "uid-999"
        assert result.email == "new@test.com"

    def test_register_passes_email_and_password_to_client(self):
        mock_resp = make_auth_response()
        with patch(
            "app.graphql.mutations.auth.auth_client.register", return_value=mock_resp
        ) as mock_fn:
            from app.graphql.mutations.auth import _register as register

            register(info=None, email="alice@test.com", password="secret")

        mock_fn.assert_called_once_with(email="alice@test.com", password="secret")

    def test_register_maps_grpc_to_graphql_error(self):
        err = FakeRpcError(
            grpc.StatusCode.ALREADY_EXISTS, "This email is already registered"
        )
        with patch("app.graphql.mutations.auth.auth_client.register", side_effect=err):
            from app.graphql.mutations.auth import _register as register

            with pytest.raises(GraphQLError) as exc_info:
                register(info=None, email="dup@test.com", password="pass")

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

            result = login(info=None, email="user@test.com", password="pass")

        assert result.token == "login-token"
        assert result.user_id == "uid-456"
        assert result.email == "user@test.com"

    def test_login_passes_credentials_to_client(self):
        mock_resp = make_auth_response()
        with patch(
            "app.graphql.mutations.auth.auth_client.login", return_value=mock_resp
        ) as mock_fn:
            from app.graphql.mutations.auth import _login as login

            login(info=None, email="bob@test.com", password="bobpass")

        mock_fn.assert_called_once_with(email="bob@test.com", password="bobpass")

    def test_login_maps_grpc_to_graphql_error(self):
        err = FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "Invalid email or password")
        with patch("app.graphql.mutations.auth.auth_client.login", side_effect=err):
            from app.graphql.mutations.auth import _login as login

            with pytest.raises(GraphQLError) as exc_info:
                login(info=None, email="x@test.com", password="wrong")

        assert exc_info.value.message == "Invalid email or password"
        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE]
            == ErrorCode.UNAUTHORIZED.value
        )
