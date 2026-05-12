from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _collect_services(argv: list[str]) -> set[str]:
    services: set[str] = set()
    for raw in argv:
        path = Path(raw).resolve()
        try:
            rel = path.relative_to(REPO)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "services":
            services.add(parts[1])
    return services


def _run_one(name: str, env_extra: dict[str, str], targets: list[str]) -> int:
    cwd = REPO / "services" / name
    if not cwd.is_dir():
        return 0
    env = os.environ.copy()
    pp = str(REPO)
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = pp + os.pathsep + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = pp
    env.update(env_extra)
    cmd = [sys.executable, "-m", "mypy", "--config-file", str(REPO / "pyproject.toml"), *targets]
    proc = subprocess.run(cmd, cwd=str(cwd), env=env)
    return int(proc.returncode)


def main() -> int:
    affected = _collect_services(sys.argv[1:])
    if not affected:
        return 0
    specs: dict[str, tuple[dict[str, str], list[str]]] = {
        "gateway": (
            {"DJANGO_SETTINGS_MODULE": "config.settings_pytest"},
            ["app", "config", "tests"],
        ),
        "auth-service": (
            {
                "DJANGO_SETTINGS_MODULE": "config.settings_pytest",
                "JWT_SECRET": "pytest-jwt-secret-not-for-production-min-32-bytes",
                "DJANGO_SECRET_KEY": "pytest-auth-django-secret-not-for-production",
            },
            ["app", "core", "config", "tests"],
        ),
        "ai-service": (
            {
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DATABASE_URL": "postgresql://podiq:podiq@localhost:5434/podiq_ai",
                "DJANGO_SECRET_KEY": "pytest-ai-django-secret-not-for-production",
            },
            ["app", "core", "config", "tests"],
        ),
        "analyzer-service": (
            {
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DATABASE_URL": "postgresql://podiq:podiq@localhost:5434/podiq_analyzer",
                "DJANGO_SECRET_KEY": "pytest-analyzer-django-secret-not-for-production",
            },
            ["app", "core", "config", "tests"],
        ),
    }
    codes = 0
    for svc in sorted(affected):
        if svc not in specs:
            continue
        env_extra, targets = specs[svc]
        codes |= _run_one(svc, env_extra, targets)
    return codes


if __name__ == "__main__":
    raise SystemExit(main())
