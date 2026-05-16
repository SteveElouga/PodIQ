#!/usr/bin/env python
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
_shared = _root / "shared" / "podiq_logging"
if _shared.is_dir():
    _p = str(_shared)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
