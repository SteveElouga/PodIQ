def pytest_configure(config):
    """Injecte les variables d'environnement avant l'initialisation de Django."""
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql://podiq:podiq@localhost:5433/podiq_auth")
    os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
