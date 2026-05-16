import sys
import types
from pathlib import Path

_here = Path(__file__).resolve().parent
_service_root = _here.parent
_repo_root = _service_root.parent.parent
_grpc_root = _repo_root / "shared" / "grpc"
if not _grpc_root.is_dir():
    _grpc_root = _service_root / "stubs"

_grpc_str = str(_grpc_root)
if _grpc_str not in sys.path:
    sys.path.insert(0, _grpc_str)

_stubs_pkg = types.ModuleType("stubs")
_stubs_pkg.__path__ = [_grpc_str]
_stubs_pkg.__package__ = "stubs"
sys.modules.setdefault("stubs", _stubs_pkg)
