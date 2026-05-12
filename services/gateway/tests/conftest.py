import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GRPC_ROOT = _REPO_ROOT / "shared" / "grpc"
_stub = types.ModuleType("stubs")
_stub.__path__ = [str(_GRPC_ROOT)]
sys.modules.setdefault("stubs", _stub)
