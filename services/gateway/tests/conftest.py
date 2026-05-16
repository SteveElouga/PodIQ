import sys
import types
from pathlib import Path

_here = Path(__file__).resolve().parent
_service_root = _here.parent
_repo_root = _service_root.parent.parent
_grpc_root = _repo_root / "shared" / "grpc"
if not _grpc_root.is_dir():
    _grpc_root = _service_root / "stubs"
_stub = types.ModuleType("stubs")
_stub.__path__ = [str(_grpc_root)]
sys.modules.setdefault("stubs", _stub)
