"""
Configures sys.path so that stubs.ai.ai_pb2 is importable
without Docker — points to shared/grpc/ at the repository root.
"""
import sys
import os

_shared_grpc = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "grpc")
)
if _shared_grpc not in sys.path:
    sys.path.insert(0, _shared_grpc)

import importlib
import types

_stubs_pkg = types.ModuleType("stubs")
_stubs_pkg.__path__ = [_shared_grpc]
_stubs_pkg.__package__ = "stubs"
sys.modules.setdefault("stubs", _stubs_pkg)
