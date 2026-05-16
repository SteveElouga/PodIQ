# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PodIQ is an AI-powered Kubernetes incident intelligence platform. It analyzes pod failures, remembers incident patterns, predicts issues before deployment, correlates incidents across services, and blocks dangerous CI/CD deployments.

**Key differentiators vs K8sGPT/Komodor:**
- Incident Memory: stores and detects recurring patterns
- Pre-deploy Scanner: analyzes YAML manifests before `kubectl apply`
- Cross-Service Correlation: detects causal relationships between services
- CI/CD Pipeline Gate: blocks deployments with dangerous configurations

## Architecture

```
[Frontend Angular / CLI]
         ↓ GraphQL + REST (CI/CD)
  [API Gateway Django]
         ↓ gRPC
   ┌─────┼───────────────┐
   ↓     ↓               ↓
[Analyzer]  [AI Service]  [Auth]
  Service   Ollama client  JWT
 kubectl    Memory Engine  API Keys
 YAML       Correlator
 Parser
   │           │             │
[postgres- [postgres-   [postgres-
 analyzer]   ai]          auth]

[postgres-gateway] ← Gateway sessions

  Redis (Dramatiq queue + cache)
  Promtail → Loki → Grafana
```

**Principe fondamental : chaque service est indépendant.**
- Chaque service possède sa propre base PostgreSQL
- Aucun service n'accède à la base d'un autre service
- Toute communication inter-service passe exclusivement par gRPC
- Les références croisées sont des UUIDs applicatifs (pas de FK cross-service)

## Services

| Service | Port | Responsibility | Own Database |
|---------|------|----------------|--------------|
| gateway | 8000 | GraphQL API, REST CI/CD endpoint, orchestration | postgres-gateway |
| analyzer-service | 50052 | K8s interaction, YAML parsing, namespace scanning | postgres-analyzer |
| ai-service | 50053 | Ollama client, Memory Engine, temporal correlation | postgres-ai |
| auth-service | 50051 | JWT auth, API Key management for CI/CD | postgres-auth |
| postgres-gateway | 5432 | Gateway sessions (Django admin) | — |
| postgres-auth | 5433 | users, api_keys | — |
| postgres-analyzer | 5434 | logs_snapshots, namespace_snapshots | — |
| postgres-ai | 5435 | analyses, incident_patterns | — |
| redis | 6379 | Async queue (Dramatiq), cache | — |
| ollama | 11434 | Local AI (Mistral 7B) | — |
| grafana | 3000 | Observability dashboard | — |
| nginx | 8080 | Reverse proxy | — |

## Development Commands

### Tests unitaires (Python)

Chaque service a son propre `pytest.ini`, `PYTHONPATH` implicite (répertoire du service) et `app.*`. **Ne pas** lancer `pytest` depuis la racine du dépôt pour collecter toute l’arborescence : le `pytest.ini` à la racine **ignore** le dossier `services/` pour éviter les erreurs `No module named 'tests.*'`.

Le **gateway** et **auth-service** utilisent `config.settings_pytest` (SQLite en mémoire, pas besoin de `.env` ni de Postgres pour les tests unitaires). Leur `tests/conftest.py` enregistre le paquet `stubs` vers `shared/grpc` **depuis le clone du dépôt**, ou vers `/app/stubs` **dans l’image Docker**. Pour **auth-service**, `conftest.py` définit aussi `JWT_SECRET` et `DJANGO_SECRET_KEY` par défaut pour l’import de `app.grpc_server`.

Les tests **locaux du gateway** peuvent utiliser **Python 3.14** : le `requirements.txt` installe **Strawberry GraphQL** depuis une archive GitHub (commit pinné), car la version PyPI ne gère pas encore `dataclasses.Field(..., doc=...)` sous 3.14.

```bash
cd services/gateway && python3 -m pytest -v
cd services/analyzer-service && python3 -m pytest -v
cd services/ai-service && python3 -m pytest -v
cd services/auth-service && python3 -m pytest -v
```

Tous les services (sans Postgres pour gateway ni auth-service en tests unitaires) :

```bash
./scripts/run_all_tests.sh
```

### Pre-commit (qualité avant commit)

À la racine du dépôt : `pip install -r requirements-dev.txt`, puis `pre-commit install`. Les hooks appliquent notamment Black, Ruff, détection de secrets (`detect-secrets` avec `.secrets.baseline`), yamllint, hadolint sur les Dockerfiles et mypy sur les paquets Python des services Django (`scripts/run_mypy_precommit.py`). Le répertoire `stubs/` du clone contient des liens symboliques vers `shared/grpc/` pour que les imports `stubs.*` utilisés par les services soient résolus par les outils locaux.

- `pre-commit run` **sans argument** ne s’exécute que sur les fichiers **déjà dans l’index** (`git add`) ; si l’index ne contient aucun fichier concerné, la sortie « no files to check » est normale.
- Pour une validation sur tout le dépôt : `pre-commit run --all-files`.
- Si **detect-secrets** signale une mise à jour de `.secrets.baseline` (décalages de lignes), régénérer ou mettre à jour la baseline comme documenté dans le dépôt, puis **stager** le fichier avant de recommitter.

Vérification manuelle ponctuelle : `pre-commit run --all-files`.

### Tests unitaires dans un conteneur Docker

Les Dockerfiles posent le code dans `/app` et les stubs gRPC dans `/app/stubs`. Après `docker compose build` (ou `up --build`), lancer pytest **à la place** du `CMD` du service, sans démarrer toute la stack :

```bash
docker compose run --rm --no-deps gateway python -m pytest -v
docker compose run --rm --no-deps auth-service python -m pytest -v
docker compose run --rm --no-deps ai-service python -m pytest -v
docker compose run --rm --no-deps analyzer-service python -m pytest -v
```

Le répertoire de travail est déjà `/app`. Ces suites n’ont pas besoin de Postgres ni de Redis pour les réglages pytest actuels.

En cas de **`collected 0 items`** dans l’image : vérifier `ls -la /app/tests` (le dossier doit exister) puis **`docker compose build --no-cache <service>`** si le `.dockerignore` venait d’être modifié. Lancer explicitement : `python -m pytest -v tests/`. **Ne pas** coller la sortie de pytest dans le shell (les lignes `===` ne sont pas des commandes). Une erreur **`unrecognized arguments: -#`** vient en général d’un **`#` collé à `-v`** (ex. copier-coller depuis du Markdown) ou d’un tiret parasite : la commande doit être exactement `python -m pytest -v` ou `python -m pytest -v tests/`.

### Start all services
```bash
docker compose up -d --build
```

### Stop all services
```bash
docker compose down
```

### View logs
```bash
docker compose logs -f <service-name>
```

### Access services
- Gateway GraphQL playground: http://localhost:8080/graphql
- Gateway healthcheck: http://localhost:8080/healthz
- Grafana: http://localhost:3000 (admin / valeur GRAFANA_ADMIN_PASSWORD dans .env)
- PostgreSQL gateway: localhost:5432
- PostgreSQL auth: localhost:5433
- PostgreSQL analyzer: localhost:5434
- PostgreSQL ai: localhost:5435

### Tester uniquement auth + gateway (sans Ollama ni Kubernetes)
```bash
docker compose up -d --build postgres-auth postgres-gateway auth-service gateway nginx
```

### Lancer la stack observabilité (logs)
```bash
docker compose up -d loki promtail grafana
```
Requête Loki dans Grafana → `{namespace="podiq"}` ou `{service="auth-service"}`

### Generate gRPC stubs (when proto files are added)
```bash
# From proto directory
python -m grpc_tools.protoc -I. --python_out=../shared/grpc --grpc_python_out=../shared/grpc <service>/<service>.proto
```

## Critical Architecture Rules

1. **Never call Ollama from Gateway** — always go through ai-service via gRPC
2. **Truncate logs at 2000 lines in analyzer-service** — never in ai-service
3. **Analysis jobs are always async** — Gateway never blocks on AI calls
4. **Gateway is lightweight** — orchestration only, no business logic
5. **Mask secrets in analyzer-service** — before any transmission to ai-service
6. **Memory Engine lives in ai-service** — reads its own PostgreSQL (postgres-ai) to enrich prompts
7. **CI/CD endpoint is REST** — exit codes 0/1/2, not GraphQL
8. **incident_patterns: upsert on every analysis** — unique key `(pod_name, namespace, error_type)`
9. **namespace_snapshots collected on every incident analysis** — even if correlation is partial
10. **Each service has its own PostgreSQL** — no service reads another service's database
11. **No cross-service FK constraints** — cross-service references are plain UUIDs, enforced at application level via gRPC
12. **Django ORM + migrations in every service** — each service runs `python manage.py migrate` on startup
13. **No stub_grpc.py in production** — every service must have a real `app/grpc_server.py` with full implementation
14. **grpcio-tools is a dev/build dependency only** — never include it in service requirements.txt (only in requirements-dev.txt at root)
15. **Password hashing uses SHA-256 + Django SECRET_KEY as pepper** — via `hashlib.compare_digest` for timing-attack resistance
16. **Each service has its own README.md** — must document analogie, gRPC interface, DB schema, env vars, and test procedure in French
17. **Documentation must always be kept up to date** — any code change that affects behaviour, interface, env vars, or architecture must be reflected immediately in the relevant README.md(s) and in CLAUDE.md. Never leave docs describing a state that no longer matches the code.

## Redis

See **[REDIS.md](./REDIS.md)** for the complete Redis guidelines.

Any time code touches Redis — cache reads/writes, Dramatiq queue, rate limiting, locks, or any new Redis usage — apply the rules in REDIS.md without exception:
- Key naming: `podiq:{service}:{type}:{id}`
- TTL mandatory on every cache key
- Cache-aside pattern with PostgreSQL fallback
- No persistent data in Redis (PostgreSQL only)
- Pipelining for multi-key operations
- `SCAN` instead of `KEYS` in all environments
- Connection pooling at service startup

## Code Conventions

- Python 3.12 everywhere, type hints required on all functions
- Pydantic v2 for all inter-service data models and AI responses
- `structlog` pour tous les logs applicatifs — jamais `print` ni `logging` standard. La configuration partagée est dans **`shared/podiq_logging/structlog_setup.py`** : en conteneur (`LOG_FORMAT` défini à `json` dans les Dockerfiles ou **`PODIQ_SERVICE_NAME`** présent), une ligne = un objet JSON avec au minimum **`timestamp`** (ISO UTC), **`level`**, **`service`** (`gateway`, `auth-service`, `analyzer-service`, `ai-service`), **`event`** (slug snake_case). Hors Docker sans ces variables : rendu console lisible. **`LOG_LEVEL`** pilote le seuil (défaut `INFO`). Les `pytest.ini` des services ajoutent **`pythonpath = ../../shared/podiq_logging`** pour résoudre ce module sans masquer le paquet **`grpc`** (`grpcio`).
- Ruff for linting, Black for formatting
- Pytest for tests, target >70% coverage
- **Application language:** all runtime strings, comments, and docstrings in Python under `services/` (including tests and stubs) are **English**. **README.md** per service and project documentation (e.g. CLAUDE.md narrative) remain **French** as product docs.

## Database Schema

Each service owns its tables in its own PostgreSQL instance. No cross-service DB access.

### postgres-auth (auth-service)
- `users` — user accounts
- `api_keys` — CI/CD pipeline authentication

### postgres-ai (ai-service)
- `analyses` — analysis results (incident, predeploy, cicd)
- `incident_patterns` — Memory Engine key table, upsert on `(pod_name, namespace, error_type)`

### postgres-analyzer (analyzer-service)
- `logs_snapshots` — raw logs/events/describe output
- `namespace_snapshots` — namespace state at incident time for correlation

### postgres-gateway (gateway)
- Django sessions and admin tables
- `analysis_jobs` — async incident analysis jobs (UUID PK, user_id, pod_name, namespace, status pending/running/complete/failed, result JSON, error text)

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `POSTGRES_PASSWORD` — shared password for all 4 postgres instances
- `JWT_SECRET` — required (auth-service)
- `GRAFANA_ADMIN_PASSWORD` — required
- `OLLAMA_HOST` — defaults to `http://ollama:11434`
- `STUB_MODE` — `true` makes analyzer-service return fake K8s data (dev without a cluster); always `false` in production
- gRPC host/port variables for internal service communication
- Each service has its own `DATABASE_URL` pointing to its dedicated postgres container
- `REDIS_MAXMEMORY` — limite mémoire du conteneur Redis (ex. `256mb` en dev), utilisée par `docker-compose` avec `--maxmemory-policy allkeys-lru`
- `AI_TIMEOUT_SECONDS` — timeout HTTP ai-service → Ollama (défaut **30** dans le code ; souvent **120** en dev sur CPU)
- Gateway : Gunicorn est lancé avec **`--timeout 180`** dans `services/gateway/Dockerfile` pour couvrir `analyzeIncident` pendant l’inférence ; sans cela, erreurs HTML/502 côté playground si le worker est tué à 30 s
- `OLLAMA_MODEL` — en dev, **`mistral`** recommandé pour gros prompts ; modèles type « thinking » peuvent échouer sur `/api/chat` malgré une RAM correcte
- Logs applicatifs : **`PODIQ_SERVICE_NAME`**, **`LOG_FORMAT=json|console`** et **`LOG_LEVEL`** sont définis dans les **Dockerfiles** des services ; surcharge possible via Compose ou variables passées aux conteneurs.

## gRPC Communication

Proto files in `proto/` directory define service contracts:
- `proto/analyzer/analyzer.proto` — CollectPod, ScanNamespace, ParseManifest
- `proto/ai/ai.proto` — AnalyzeIncident, ScanManifest, **GetAnalysisHistory**
- `proto/auth/auth.proto` — Register, Login, ValidateJWT, CreateApiKey, ValidateApiKey, RevokeApiKey

Generated stubs go in `shared/grpc/`. Each service COPY only its own stubs via Dockerfile (build context = project root `.`).

### Régénérer les stubs après modification d'un proto
```bash
cd proto
python -m grpc_tools.protoc -I. --python_out=../shared/grpc --grpc_python_out=../shared/grpc ai/ai.proto
# Puis corriger l'import dans shared/grpc/ai/ai_pb2_grpc.py :
# from ai import ai_pb2  →  from . import ai_pb2
```

## Observability

- Logs flow: Docker containers stdout → Promtail → Loki → Grafana
- Promtail lit le socket Docker (`/var/run/docker.sock`) — aucune modification du code des services
- Labels Promtail : `namespace="podiq"`, `service="<nom-service>"`, `container`, `stream`
- Filtrer par service dans Grafana Explore → Loki : `{service="auth-service"}`
- Config : `infra/loki/loki-config.yml`, `infra/promtail/promtail-config.yml`
- Grafana accessible at http://localhost:3000 (credentials dans .env)

## Development Order

1. ✅ Docker Compose complete (4 postgres instances + all services)
2. ✅ Django setup + ORM models + migrations in each service independently
   - auth-service: users, api_keys
   - ai-service: analyses, incident_patterns
   - analyzer-service: logs_snapshots, namespace_snapshots
   - gateway: Django sessions only
3. ✅ proto gRPC → generate stubs (auth, analyzer, ai + GetAnalysisHistory)
4. ✅ Analyzer Service: CollectPod + ScanNamespace + ParseManifest
5. ✅ AI Service: AnalyzeIncident + ScanManifest + GetAnalysisHistory
6. ✅ Auth Service: Register + Login + ValidateJWT + CreateApiKey + ValidateApiKey + RevokeApiKey
7. ✅ Gateway GraphQL: schema complet (analyzeIncident, scanManifest, register, login, analysisHistory)
8. ✅ Loki + Promtail + Grafana configurés (labels service/namespace, rétention 7j)
9. ✅ README.md dans chaque service (FR, avec analogies, I/O gRPC, DB, env vars)
10. ✅ Memory Engine (gateway appelle GetHistory avant AnalyzeIncident, injecte history[])
11. ✅ Namespace scan + temporal correlation (`namespace_context` enrichment, `CORRELATION_WINDOW_MINUTES`, `PodContext.in_correlation_window`)
12. ✅ Pre-deploy scan REST complet
13. ✅ CI/CD REST endpoint + API Keys (POST /api/v1/cicd/scan)
14. ✅ Redis Queue Dramatiq (flux async complet)
15. ✅ Dashboard Grafana podiq-overview.json
16. 🔲 Frontend Angular
17. 🔲 CLI
