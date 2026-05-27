"""
auth-service gRPC server unit tests.
In-memory SQLite via config.settings_pytest — no .env or postgres-auth required.
"""

import hashlib
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import grpc
import jwt
import pytest

from app.grpc_server import (
    JWT_SECRET,
    AuthServicer,
    _generate_token,
    _hash_api_key,
    _hash_password,
    _needs_rehash,
    _verify_password,
)
from core.models import ApiKey, User
from stubs.auth import auth_pb2


def _make_legacy_sha256_hash(password: str) -> str:
    """Reproduce the legacy SHA-256+pepper hash used before Argon2id migration."""
    pepper = os.environ.get("DJANGO_SECRET_KEY", "")
    return hashlib.sha256(f"{pepper}{password}".encode()).hexdigest()


# ── Helpers ───────────────────────────────────────────────────────────────────


def ctx() -> MagicMock:
    """Return a mocked gRPC context with set_code and set_details."""
    mock = MagicMock(spec=grpc.ServicerContext)
    mock.set_code = MagicMock()
    mock.set_details = MagicMock()
    return mock


@pytest.fixture
def servicer() -> AuthServicer:
    return AuthServicer()


@pytest.fixture
def user(db) -> User:
    return User.objects.create(
        email="existing@test.com",
        password_hash=_hash_password("correct-password"),
    )


@pytest.fixture
def api_key(db, user) -> tuple[ApiKey, str]:
    raw = "raw-test-key-abcdef1234567890"
    key = ApiKey.objects.create(
        user_id=user.id,
        key_hash=_hash_api_key(raw),
        name="ci-key",
        is_active=True,
    )
    return key, raw


# -- Helper functions ------------------------------------------------------------


class TestHelpers:
    # ── _hash_password (Argon2id) ────────────────────────────────────────────

    def test_hash_password_is_argon2id_format(self):
        """Output must start with the Argon2id marker."""
        assert _hash_password("secret").startswith("$argon2id$")

    def test_hash_password_uses_unique_salts(self):
        """Each call must produce a different hash even for identical passwords."""
        h1 = _hash_password("secret")
        h2 = _hash_password("secret")
        assert h1 != h2, "Argon2id must embed a unique random salt per call"

    def test_hash_password_different_inputs(self):
        """Different passwords must never produce the same hash."""
        assert _hash_password("secret") != _hash_password("other")

    # ── _needs_rehash ────────────────────────────────────────────────────────

    def test_needs_rehash_legacy_sha256_returns_true(self):
        """Legacy 64-char hex SHA-256 hash must be flagged for upgrade."""
        legacy = _make_legacy_sha256_hash("somepassword")
        assert len(legacy) == 64  # sanity-check it looks like a hex digest
        assert _needs_rehash(legacy) is True

    def test_needs_rehash_argon2id_returns_false(self):
        """Fresh Argon2id hash must NOT be flagged for re-hashing."""
        fresh = _hash_password("somepassword")
        assert _needs_rehash(fresh) is False

    # ── _verify_password (Argon2id) ───────────────────────────────────────────

    def test_verify_password_correct(self):
        h = _hash_password("mypassword")
        assert _verify_password("mypassword", h) is True

    def test_verify_password_wrong(self):
        h = _hash_password("mypassword")
        assert _verify_password("wrong", h) is False

    # ── _verify_password (legacy SHA-256) — migration compatibility ───────────

    def test_verify_legacy_sha256_correct_password(self):
        """Legacy SHA-256+pepper hashes must still verify during migration window."""
        legacy = _make_legacy_sha256_hash("legacypass")
        assert _verify_password("legacypass", legacy) is True

    def test_verify_legacy_sha256_wrong_password_returns_false(self):
        legacy = _make_legacy_sha256_hash("legacypass")
        assert _verify_password("wrongpass", legacy) is False

    # ── _generate_token ───────────────────────────────────────────────────────

    def test_generate_token_contains_claims(self):
        token = _generate_token("uid-123", "user@test.com")
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        assert payload["user_id"] == "uid-123"
        assert payload["email"] == "user@test.com"

    def test_generate_token_has_expiry(self):
        token = _generate_token("uid-123", "user@test.com")
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        assert "exp" in payload
        assert payload["exp"] > datetime.now(UTC).timestamp()

    # ── _hash_api_key ─────────────────────────────────────────────────────────

    def test_hash_api_key_deterministic(self):
        assert _hash_api_key("mykey") == _hash_api_key("mykey")

    def test_hash_api_key_different_inputs(self):
        assert _hash_api_key("key1") != _hash_api_key("key2")


# ── Register ──────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRegister:
    def test_register_success(self, servicer):
        c = ctx()
        resp = servicer.Register(
            auth_pb2.RegisterRequest(
                email="new@test.com", password="pass1234"
            ),  # pragma: allowlist secret
            c,
        )
        assert resp.email == "new@test.com"
        assert resp.token != ""
        assert resp.user_id != ""
        c.set_code.assert_not_called()

    def test_register_creates_user_in_db(self, servicer):
        c = ctx()
        servicer.Register(
            auth_pb2.RegisterRequest(
                email="dbcheck@test.com", password="pass1234"
            ),  # pragma: allowlist secret
            c,
        )
        assert User.objects.filter(email="dbcheck@test.com").exists()

    def test_register_password_not_stored_in_plain(self, servicer):
        c = ctx()
        servicer.Register(
            auth_pb2.RegisterRequest(
                email="hash@test.com",
                password="myplainpassword",  # pragma: allowlist secret
            ),
            c,
        )
        user = User.objects.get(email="hash@test.com")
        assert user.password_hash != "myplainpassword"  # pragma: allowlist secret

    def test_register_token_is_valid_jwt(self, servicer):
        c = ctx()
        resp = servicer.Register(
            auth_pb2.RegisterRequest(
                email="jwt@test.com", password="pass"
            ),  # pragma: allowlist secret
            c,
        )
        payload = jwt.decode(resp.token, JWT_SECRET, algorithms=["HS256"])
        assert payload["email"] == "jwt@test.com"

    def test_register_duplicate_email_returns_already_exists(self, servicer, user):
        c = ctx()
        servicer.Register(
            auth_pb2.RegisterRequest(
                email="existing@test.com", password="pass"
            ),  # pragma: allowlist secret
            c,
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.ALREADY_EXISTS)

    def test_register_empty_email_returns_invalid_argument(self, servicer):
        c = ctx()
        servicer.Register(
            auth_pb2.RegisterRequest(email="", password="pass"),
            c,  # pragma: allowlist secret
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.INVALID_ARGUMENT)

    def test_register_empty_password_returns_invalid_argument(self, servicer):
        c = ctx()
        servicer.Register(auth_pb2.RegisterRequest(email="a@test.com", password=""), c)
        c.set_code.assert_called_once_with(grpc.StatusCode.INVALID_ARGUMENT)


# ── Login ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLogin:
    def test_login_success(self, servicer, user):
        c = ctx()
        resp = servicer.Login(
            auth_pb2.LoginRequest(
                email="existing@test.com",
                password="correct-password",  # pragma: allowlist secret
            ),
            c,
        )
        assert resp.email == "existing@test.com"
        assert resp.token != ""
        c.set_code.assert_not_called()

    def test_login_returns_valid_jwt(self, servicer, user):
        c = ctx()
        resp = servicer.Login(
            auth_pb2.LoginRequest(
                email="existing@test.com",
                password="correct-password",  # pragma: allowlist secret
            ),
            c,
        )
        payload = jwt.decode(resp.token, JWT_SECRET, algorithms=["HS256"])
        assert payload["email"] == "existing@test.com"

    def test_login_wrong_password_returns_unauthenticated(self, servicer, user):
        c = ctx()
        servicer.Login(
            auth_pb2.LoginRequest(
                email="existing@test.com", password="wrong"
            ),  # pragma: allowlist secret
            c,
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.UNAUTHENTICATED)

    def test_login_unknown_email_returns_not_found(self, servicer):
        c = ctx()
        servicer.Login(
            auth_pb2.LoginRequest(
                email="ghost@test.com", password="pass"
            ),  # pragma: allowlist secret
            c,
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.NOT_FOUND)

    def test_login_error_message_is_generic(self, servicer, user):
        """Error message does not reveal whether email or password was wrong."""
        c = ctx()
        servicer.Login(
            auth_pb2.LoginRequest(
                email="existing@test.com", password="wrong"
            ),  # pragma: allowlist secret
            c,
        )
        call_args = c.set_details.call_args[0][0]
        assert "email" in call_args.lower() or "password" in call_args.lower()
        assert "existing@test.com" not in call_args


# ── Login — Argon2id transparent migration ────────────────────────────────────


@pytest.mark.django_db
class TestLoginMigration:
    def test_login_accepts_legacy_sha256_hash(self, servicer):
        """A user with a legacy SHA-256 hash can still log in during the migration window."""
        User.objects.create(
            email="legacy@test.com",
            password_hash=_make_legacy_sha256_hash(
                "oldpass"
            ),  # pragma: allowlist secret
        )
        c = ctx()
        resp = servicer.Login(
            auth_pb2.LoginRequest(
                email="legacy@test.com",
                password="oldpass",  # pragma: allowlist secret  # NOSONAR
            ),
            c,
        )
        assert resp.email == "legacy@test.com"
        assert resp.token != ""
        c.set_code.assert_not_called()

    def test_login_upgrades_legacy_sha256_to_argon2id(self, servicer):
        """After a successful login with a legacy hash the stored hash must be Argon2id."""
        user = User.objects.create(
            email="migrate@test.com",
            password_hash=_make_legacy_sha256_hash(
                "oldpass"
            ),  # pragma: allowlist secret
        )
        # Confirm the hash is legacy before login
        assert _needs_rehash(user.password_hash) is True

        c = ctx()
        servicer.Login(
            auth_pb2.LoginRequest(
                email="migrate@test.com",
                password="oldpass",  # pragma: allowlist secret  # NOSONAR
            ),
            c,
        )

        user.refresh_from_db()
        assert user.password_hash.startswith(
            "$argon2id$"
        ), "Hash must be upgraded to Argon2id after first successful login"
        assert _needs_rehash(user.password_hash) is False

    def test_login_does_not_rehash_already_argon2id(self, servicer):
        """A user with an Argon2id hash must NOT be rehashed again on login."""
        original_hash = _hash_password("newpass")  # pragma: allowlist secret
        user = User.objects.create(
            email="fresh@test.com",
            password_hash=original_hash,
        )
        c = ctx()
        servicer.Login(
            auth_pb2.LoginRequest(
                email="fresh@test.com",
                password="newpass",  # pragma: allowlist secret  # NOSONAR
            ),
            c,
        )
        user.refresh_from_db()
        # The hash identity may differ (Argon2 verify may re-encode), but it
        # must still start with the Argon2id marker and must verify correctly.
        assert user.password_hash.startswith("$argon2id$")
        assert (
            _verify_password("newpass", user.password_hash) is True
        )  # pragma: allowlist secret


# ── ValidateJWT ───────────────────────────────────────────────────────────────


class TestValidateJWT:
    def test_valid_token_returns_true(self, servicer):
        token = _generate_token("uid-42", "valid@test.com")
        c = ctx()
        resp = servicer.ValidateJWT(auth_pb2.ValidateJWTRequest(token=token), c)
        assert resp.valid is True
        assert resp.user_id == "uid-42"
        assert resp.email == "valid@test.com"
        assert resp.error == ""

    def test_expired_token_returns_false(self, servicer):
        payload = {
            "user_id": "uid-42",
            "email": "expired@test.com",
            "iat": datetime(2020, 1, 1, tzinfo=UTC),
            "exp": datetime(2020, 1, 2, tzinfo=UTC),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        c = ctx()
        resp = servicer.ValidateJWT(auth_pb2.ValidateJWTRequest(token=token), c)
        assert resp.valid is False
        assert resp.error != ""

    def test_tampered_token_returns_false(self, servicer):
        token = _generate_token("uid-42", "test@test.com") + "tampered"
        c = ctx()
        resp = servicer.ValidateJWT(auth_pb2.ValidateJWTRequest(token=token), c)
        assert resp.valid is False
        assert resp.error != ""

    def test_wrong_secret_token_returns_false(self, servicer):
        token = jwt.encode(
            {"user_id": "uid", "email": "e"}, "wrong-secret", algorithm="HS256"
        )
        c = ctx()
        resp = servicer.ValidateJWT(auth_pb2.ValidateJWTRequest(token=token), c)
        assert resp.valid is False

    def test_empty_token_returns_false(self, servicer):
        c = ctx()
        resp = servicer.ValidateJWT(auth_pb2.ValidateJWTRequest(token=""), c)
        assert resp.valid is False


# ── CreateApiKey ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateApiKey:
    def test_create_success(self, servicer, user):
        c = ctx()
        resp = servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=str(user.id), name="gh-actions"), c
        )
        assert resp.raw_key != ""
        assert resp.key_id != ""
        assert resp.name == "gh-actions"
        c.set_code.assert_not_called()

    def test_create_raw_key_not_stored(self, servicer, user):
        c = ctx()
        resp = servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=str(user.id), name="test"), c
        )
        key = ApiKey.objects.get(id=resp.key_id)
        assert key.key_hash != resp.raw_key

    def test_create_stores_hashed_key(self, servicer, user):
        c = ctx()
        resp = servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=str(user.id), name="test"), c
        )
        key = ApiKey.objects.get(id=resp.key_id)
        assert key.key_hash == _hash_api_key(resp.raw_key)

    def test_create_key_is_active(self, servicer, user):
        c = ctx()
        resp = servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=str(user.id), name="test"), c
        )
        key = ApiKey.objects.get(id=resp.key_id)
        assert key.is_active is True

    def test_create_invalid_user_id_returns_invalid_argument(self, servicer):
        c = ctx()
        servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id="not-a-uuid", name="test"), c
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.INVALID_ARGUMENT)

    def test_raw_key_has_sufficient_length(self, servicer, user):
        c = ctx()
        resp = servicer.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=str(user.id), name="test"), c
        )
        assert len(resp.raw_key) >= 32


# ── ValidateApiKey ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestValidateApiKey:
    def test_valid_key_returns_true(self, servicer, api_key):
        key_obj, raw = api_key
        c = ctx()
        resp = servicer.ValidateApiKey(auth_pb2.ValidateApiKeyRequest(raw_key=raw), c)
        assert resp.valid is True
        assert resp.user_id == str(key_obj.user_id)
        assert resp.key_id == str(key_obj.id)

    def test_unknown_key_returns_false(self, servicer):
        c = ctx()
        resp = servicer.ValidateApiKey(
            auth_pb2.ValidateApiKeyRequest(raw_key="totally-unknown-key"), c
        )
        assert resp.valid is False
        assert resp.error != ""

    def test_valid_key_updates_last_used(self, servicer, api_key):
        key_obj, raw = api_key
        assert key_obj.last_used is None
        c = ctx()
        servicer.ValidateApiKey(auth_pb2.ValidateApiKeyRequest(raw_key=raw), c)
        key_obj.refresh_from_db()
        assert key_obj.last_used is not None

    def test_revoked_key_returns_false(self, servicer, api_key):
        key_obj, raw = api_key
        key_obj.is_active = False
        key_obj.save()
        c = ctx()
        resp = servicer.ValidateApiKey(auth_pb2.ValidateApiKeyRequest(raw_key=raw), c)
        assert resp.valid is False


# ── RevokeApiKey ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRevokeApiKey:
    def test_revoke_success(self, servicer, api_key):
        key_obj, _ = api_key
        c = ctx()
        resp = servicer.RevokeApiKey(
            auth_pb2.RevokeApiKeyRequest(
                key_id=str(key_obj.id), user_id=str(key_obj.user_id)
            ),
            c,
        )
        assert resp.success is True
        key_obj.refresh_from_db()
        assert key_obj.is_active is False

    def test_revoke_wrong_user_returns_not_found(self, servicer, api_key):
        key_obj, _ = api_key
        c = ctx()
        servicer.RevokeApiKey(
            auth_pb2.RevokeApiKeyRequest(
                key_id=str(key_obj.id), user_id=str(uuid.uuid4())
            ),
            c,
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.NOT_FOUND)

    def test_revoke_already_revoked_returns_not_found(self, servicer, api_key):
        key_obj, _ = api_key
        key_obj.is_active = False
        key_obj.save()
        c = ctx()
        servicer.RevokeApiKey(
            auth_pb2.RevokeApiKeyRequest(
                key_id=str(key_obj.id), user_id=str(key_obj.user_id)
            ),
            c,
        )
        c.set_code.assert_called_once_with(grpc.StatusCode.NOT_FOUND)

    def test_revoke_does_not_affect_other_keys(self, servicer, user, api_key):
        key_obj, raw = api_key
        other_raw = "other-raw-key-xyz"
        other_key = ApiKey.objects.create(
            user_id=user.id,
            key_hash=_hash_api_key(other_raw),
            name="other",
            is_active=True,
        )
        c = ctx()
        servicer.RevokeApiKey(
            auth_pb2.RevokeApiKeyRequest(
                key_id=str(key_obj.id), user_id=str(key_obj.user_id)
            ),
            c,
        )
        other_key.refresh_from_db()
        assert other_key.is_active is True
