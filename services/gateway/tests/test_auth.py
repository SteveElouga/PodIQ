"""
Unit tests for app/auth.py (require_auth).
The gRPC auth_client is fully mocked — no database or network required.
"""

from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest
from graphql import GraphQLError

from app.api_codes import GRAPHQL_EXTENSION_CODE, ErrorCode
from tests.grpc_fake import FakeRpcError


def make_info(auth_header: str | None = None) -> SimpleNamespace:
    headers = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    return SimpleNamespace(
        context=SimpleNamespace(request=SimpleNamespace(headers=headers))
    )


def make_jwt_response(
    valid: bool, user_id: str = "", error: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(valid=valid, user_id=user_id, error=error)


class TestRequireAuth:
    def test_raises_when_info_is_none(self):
        from app.auth import require_auth

        with pytest.raises(PermissionError):
            require_auth(None)

    def test_raises_when_no_authorization_header(self):
        from app.auth import require_auth

        with pytest.raises(PermissionError):
            require_auth(make_info())

    def test_raises_when_scheme_is_not_bearer(self):
        from app.auth import require_auth

        with pytest.raises(PermissionError):
            require_auth(make_info("Basic dXNlcjpwYXNz"))

    def test_raises_when_token_is_empty_after_bearer(self):
        from app.auth import require_auth

        with pytest.raises(PermissionError):
            require_auth(make_info("Bearer "))

    def test_raises_when_jwt_is_invalid(self):
        response = make_jwt_response(valid=False, error="Token expired")
        with patch("app.auth.auth_client.validate_jwt", return_value=response):
            from app.auth import require_auth

            with pytest.raises(PermissionError, match="Token expired"):
                require_auth(make_info("Bearer expired-token"))

    def test_raises_with_fallback_message_when_error_is_empty(self):
        response = make_jwt_response(valid=False, error="")
        with patch("app.auth.auth_client.validate_jwt", return_value=response):
            from app.auth import require_auth

            with pytest.raises(PermissionError, match="Invalid or expired token"):
                require_auth(make_info("Bearer bad-token"))

    def test_returns_user_id_when_token_is_valid(self):
        response = make_jwt_response(valid=True, user_id="user-uuid-42")
        with patch("app.auth.auth_client.validate_jwt", return_value=response):
            from app.auth import require_auth

            result = require_auth(make_info("Bearer valid-token"))
        assert result == "user-uuid-42"

    def test_raises_graphql_when_validate_jwt_grpc_fails(self):
        err = FakeRpcError(grpc.StatusCode.UNAVAILABLE, "")
        with patch("app.auth.auth_client.validate_jwt", side_effect=err):
            from app.auth import require_auth

            with pytest.raises(GraphQLError) as exc_info:
                require_auth(make_info("Bearer valid-token"))

        assert (
            exc_info.value.extensions[GRAPHQL_EXTENSION_CODE]
            == ErrorCode.AUTH_GRPC.value
        )

    def test_validate_jwt_called_with_extracted_token(self):
        response = make_jwt_response(valid=True, user_id="uid")
        with patch(
            "app.auth.auth_client.validate_jwt", return_value=response
        ) as mock_fn:
            from app.auth import require_auth

            require_auth(make_info("Bearer my-secret-token"))
        mock_fn.assert_called_once_with("my-secret-token")

    def test_bearer_token_with_extra_spaces_is_stripped(self):
        response = make_jwt_response(valid=True, user_id="uid-x")
        with patch(
            "app.auth.auth_client.validate_jwt", return_value=response
        ) as mock_fn:
            from app.auth import require_auth

            require_auth(make_info("Bearer   trimmed-token  "))
        called_token = mock_fn.call_args[0][0]
        assert called_token == "trimmed-token"
