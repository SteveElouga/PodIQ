import grpc
from django.conf import settings

from stubs.auth import auth_pb2, auth_pb2_grpc


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(f"{settings.AUTH_GRPC_HOST}:{settings.AUTH_GRPC_PORT}")


def validate_jwt(token: str) -> auth_pb2.ValidateJWTResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.ValidateJWT(auth_pb2.ValidateJWTRequest(token=token))


def validate_api_key(raw_key: str) -> auth_pb2.ValidateApiKeyResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.ValidateApiKey(auth_pb2.ValidateApiKeyRequest(raw_key=raw_key))


def register(email: str, password: str) -> auth_pb2.AuthResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.Register(auth_pb2.RegisterRequest(email=email, password=password))


def login(email: str, password: str) -> auth_pb2.AuthResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.Login(auth_pb2.LoginRequest(email=email, password=password))


def create_api_key(user_id: str, name: str) -> auth_pb2.ApiKeyResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.CreateApiKey(
            auth_pb2.CreateApiKeyRequest(user_id=user_id, name=name)
        )


def revoke_api_key(key_id: str, user_id: str) -> auth_pb2.RevokeApiKeyResponse:
    with _channel() as channel:
        stub = auth_pb2_grpc.AuthServiceStub(channel)
        return stub.RevokeApiKey(
            auth_pb2.RevokeApiKeyRequest(key_id=key_id, user_id=user_id)
        )
