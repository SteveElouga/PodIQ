import os
import sys
import types
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET",
    "pytest-jwt-secret-not-for-production-min-32-bytes",
)
os.environ.setdefault(
    "DJANGO_SECRET_KEY",
    "pytest-auth-django-secret-not-for-production",
)

_here = Path(__file__).resolve().parent
_service_root = _here.parent
_repo_root = _service_root.parent.parent
_grpc_root = _repo_root / "shared" / "grpc"
if not _grpc_root.is_dir():
    _grpc_root = _service_root / "stubs"
_stub = types.ModuleType("stubs")
_stub.__path__ = [str(_grpc_root)]
sys.modules.setdefault("stubs", _stub)
