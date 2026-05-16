import hashlib
import hmac
import os
import secrets
import uuid
from concurrent import futures
from datetime import datetime, timezone, timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import grpc
import jwt
import structlog
from django.utils import timezone as tz

from stubs.auth import auth_pb2, auth_pb2_grpc
from core.models import User, ApiKey

logger = structlog.get_logger()

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "1440"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    pepper = os.environ.get("DJANGO_SECRET_KEY", "")
    return hashlib.sha256(f"{pepper}{password}".encode()).hexdigest()


def _verify_password(password: str, stored_hash: str) -> bool:
    return hmac.compare_digest(_hash_password(password), stored_hash)


def _generate_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ── Servicer ──────────────────────────────────────────────────────────────────

class AuthServicer(auth_pb2_grpc.AuthServiceServicer):

    def Register(
        self,
        request: auth_pb2.RegisterRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.AuthResponse:
        logger.info("auth_register", email=request.email)

        if not request.email or not request.password:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Email and password are required")
            return auth_pb2.AuthResponse()

        if User.objects.filter(email=request.email).exists():
            context.set_code(grpc.StatusCode.ALREADY_EXISTS)
            context.set_details("This email is already registered")
            return auth_pb2.AuthResponse()

        user = User.objects.create(
            email=request.email,
            password_hash=_hash_password(request.password),
        )
        token = _generate_token(str(user.id), user.email)
        logger.info("auth_register_ok", user_id=str(user.id))
        return auth_pb2.AuthResponse(user_id=str(user.id), token=token, email=user.email)

    def Login(
        self,
        request: auth_pb2.LoginRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.AuthResponse:
        logger.info("auth_login", email=request.email)

        try:
            user = User.objects.get(email=request.email)
        except User.DoesNotExist:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Invalid email or password")
            return auth_pb2.AuthResponse()

        if not _verify_password(request.password, user.password_hash):
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Invalid email or password")
            return auth_pb2.AuthResponse()

        token = _generate_token(str(user.id), user.email)
        logger.info("auth_login_ok", user_id=str(user.id))
        return auth_pb2.AuthResponse(user_id=str(user.id), token=token, email=user.email)

    def ValidateJWT(
        self,
        request: auth_pb2.ValidateJWTRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.ValidateJWTResponse:
        try:
            payload = jwt.decode(request.token, JWT_SECRET, algorithms=["HS256"])
            return auth_pb2.ValidateJWTResponse(
                valid=True,
                user_id=payload["user_id"],
                email=payload.get("email", ""),
            )
        except jwt.ExpiredSignatureError:
            return auth_pb2.ValidateJWTResponse(valid=False, error="Token expired")
        except jwt.InvalidTokenError as exc:
            return auth_pb2.ValidateJWTResponse(valid=False, error=str(exc))

    def CreateApiKey(
        self,
        request: auth_pb2.CreateApiKeyRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.ApiKeyResponse:
        logger.info("create_api_key", user_id=request.user_id, name=request.name)

        try:
            user_uuid = uuid.UUID(request.user_id)
        except ValueError:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Invalid user_id")
            return auth_pb2.ApiKeyResponse()

        raw_key = secrets.token_urlsafe(32)
        api_key = ApiKey.objects.create(
            user_id=user_uuid,
            key_hash=_hash_api_key(raw_key),
            name=request.name,
        )
        logger.info("api_key_created", key_id=str(api_key.id))
        return auth_pb2.ApiKeyResponse(
            key_id=str(api_key.id),
            raw_key=raw_key,
            name=api_key.name,
            created_at=api_key.created_at.isoformat(),
        )

    def ValidateApiKey(
        self,
        request: auth_pb2.ValidateApiKeyRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.ValidateApiKeyResponse:
        key_hash = _hash_api_key(request.raw_key)

        try:
            api_key = ApiKey.objects.get(key_hash=key_hash, is_active=True)
        except ApiKey.DoesNotExist:
            return auth_pb2.ValidateApiKeyResponse(
                valid=False, error="Invalid or revoked API key"
            )

        api_key.last_used = tz.now()
        api_key.save(update_fields=["last_used"])

        return auth_pb2.ValidateApiKeyResponse(
            valid=True,
            user_id=str(api_key.user_id),
            key_id=str(api_key.id),
        )

    def RevokeApiKey(
        self,
        request: auth_pb2.RevokeApiKeyRequest,
        context: grpc.ServicerContext,
    ) -> auth_pb2.RevokeApiKeyResponse:
        logger.info("revoke_api_key", key_id=request.key_id, user_id=request.user_id)

        updated = ApiKey.objects.filter(
            id=request.key_id,
            user_id=request.user_id,
            is_active=True,
        ).update(is_active=False)

        if not updated:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("API key not found or already revoked")
            return auth_pb2.RevokeApiKeyResponse(success=False)

        return auth_pb2.RevokeApiKeyResponse(success=True)


# ── Entrypoint ────────────────────────────────────────────────────────────────

def serve() -> None:
    port = os.environ.get("GRPC_PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    auth_pb2_grpc.add_AuthServiceServicer_to_server(AuthServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("auth_service_started", port=port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("auth_service_stopping")
        server.stop(grace=5)


if __name__ == "__main__":
    serve()
