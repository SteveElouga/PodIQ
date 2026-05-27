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
[K8s Cluster]                     [PodIQ SaaS]
  PodIQ Agent ──HTTPS GraphQL──▶  API Gateway (Django ASGI)
  (pod in cluster)                      ↓ gRPC
  collects: logs/events/describe   ┌────┼──────────┐
  sends: agentReportIncident       ↓    ↓          ↓
                              [Analyzer] [AI Svc] [Auth]
[Frontend Angular / CLI]       YAML       Ollama   JWT
  ↓ GraphQL + REST (CI/CD)    Parser     Memory   API Keys
  ↓ WebSocket (subscriptions)  only      Engine
                                 │          │         │
                            [postgres- [postgres- [postgres-
                             analyzer]   ai]        auth]

[postgres-gateway] ← Gateway sessions, workspaces, clusters

  Redis (Dramatiq queue + cache)
  Loki Log Driver → Loki → Grafana
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
| analyzer-service | 50052 | YAML manifest parsing only (ParseManifest gRPC) | postgres-analyzer |
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

### Démarrage — Makefile (recommandé)

```bash
make up          # démarre tous les services (docker compose up -d --build)
make down        # arrêter tous les services
make logs        # suivre tous les logs
make ps          # état des conteneurs
```

### Simuler un agent avec un vrai cluster

Le script `scripts/agent_simulate.sh` simule ce que ferait l'agent K8s déployé dans un cluster :

```bash
# Déployer les pods de test (CrashLoopBackOff, OOMKilled, ImagePullBackOff, missing config)
make agent-pods     # kubectl apply -f k8s/test-pods/
make agent-status   # vérifier l'état
make agent-clean    # supprimer les pods de test

# Simuler un incident complet
./scripts/agent_simulate.sh <install_token> <pod_name> [namespace] [workspace_jwt]
# Exemple :
./scripts/agent_simulate.sh wsk_xxx podiq-test-crashloop default
```

Le script collecte logs/events/describe via kubectl, envoie `agentHeartbeat` + `agentReportIncident`,
puis poll `analysisJob` jusqu'à `complete`. Le 4e argument est le JWT workspace-scoped
(obtenu via `mutation selectWorkspace`) — sans lui, le poll est ignoré et la commande curl
est affichée pour relance manuelle.

### Start all services (direct)
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
docker compose up -d loki grafana
```
Le **Loki Docker Log Driver** est configuré au niveau du daemon Docker — aucun conteneur Promtail à démarrer.
Requête Loki dans Grafana → `{namespace="podiq"}` ou `{service="auth-service"}`

### Generate gRPC stubs (when proto files are added)
```bash
# From proto directory
python -m grpc_tools.protoc -I. --python_out=../shared/grpc --grpc_python_out=../shared/grpc <service>/<service>.proto
```

## Critical Architecture Rules

1. **Never call Ollama from Gateway** — always go through ai-service via gRPC
2. **Truncate logs at 2000 lines in the agent** — the agent caps logs before sending; ai-service receives pre-truncated data
3. **Analysis jobs are always async** — Gateway never blocks on AI calls
4. **Gateway is lightweight** — orchestration only, no business logic
5. **Mask secrets in the agent** — before sending logs to gateway; gateway never inspects log content
6. **Memory Engine lives in ai-service** — reads its own PostgreSQL (postgres-ai) to enrich prompts
7. **CI/CD endpoint is REST** — exit codes 0/1/2, not GraphQL
8. **incident_patterns: upsert on every analysis** — unique key `(workspace_id, pod_name, namespace, error_type)` — tenant-scoped since migration `0002`; `workspace_id` is propagated via gRPC proto field from gateway
9. **namespace_pods JSON sent by the agent** — `_build_namespace_context()` in gateway/tasks.py parses it and builds `List[PodContext]` for temporal correlation; `CORRELATION_WINDOW_MINUTES` (env var, default 15) controls the window
10. **Each service has its own PostgreSQL** — no service reads another service's database
11. **No cross-service FK constraints** — cross-service references are plain UUIDs, enforced at application level via gRPC
12. **Django ORM + migrations in every service** — each service runs `python manage.py migrate` on startup
13. **No stub_grpc.py in production** — every service must have a real `app/grpc_server.py` with full implementation
14. **grpcio-tools is a dev/build dependency only** — never include it in service requirements.txt (only in requirements-dev.txt at root)
15. **Password hashing uses Argon2id** (OWASP params: time=2, mem=64 MB, parallelism=2, salt_len=16) via `argon2-cffi` — `_hash_password()` generates a unique random salt per call; `_verify_password()` transparently handles legacy SHA-256+pepper hashes during migration (detected by `_needs_rehash()`); rehash happens automatically on first successful login
16. **Each service has its own README.md** — must document analogie, gRPC interface, DB schema, env vars, and test procedure in French
17. **Documentation must always be kept up to date** — any code change that affects behaviour, interface, env vars, or architecture must be reflected immediately in the relevant README.md(s) and in CLAUDE.md. Never leave docs describing a state that no longer matches the code.

## Redis

See **[REDIS.md](./docs/REDIS.md)** for the complete Redis guidelines.

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
- `analyses` — analysis results (incident, predeploy, cicd); `workspace_id` UUID nullable (tenant isolation — NULL = legacy data pre-migration `0002`)
- `incident_patterns` — Memory Engine key table, upsert on `(workspace_id, pod_name, namespace, error_type)`; `workspace_id` nullable (NULL = legacy global data)

### postgres-analyzer (analyzer-service)
- `logs_snapshots` — raw logs/events/describe output
- `namespace_snapshots` — namespace state at incident time for correlation

### postgres-gateway (gateway)
- Django sessions and admin tables
- `analysis_jobs` — async incident analysis jobs (UUID PK, user_id, workspace_id, pod_name, namespace, status pending/running/complete/failed, result JSON, error text)
- `workspaces` — tenant workspaces (UUID PK, owner_id, name, slug, plan, region, team_size, accent_color)
- `workspace_members` — user roles within a workspace (workspace FK, user_id UUID, role admin/member/viewer)
- `install_tokens` — agent install tokens (workspace FK, token wsk_xxx, expires_at, used)
- `clusters` — registered K8s clusters (workspace FK, install_token FK, name, k8s_version, status, last_heartbeat)
- `invitations` — workspace invitations (workspace FK, email, role, token UUID, status, expires_at)
- `alert_rules` — per-workspace notification rules (workspace FK, event_type, enabled)
- `notification_channels` — destinations (workspace FK, type slack/pagerduty/email/webhook/teams/discord, config JSON)
- `quiet_hours` — notification suppression window (workspace OneToOne, start_time, end_time, timezone)

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `POSTGRES_PASSWORD` — shared password for all 4 postgres instances
- `JWT_SECRET` — required (auth-service)
- `GRAFANA_ADMIN_PASSWORD` — required
- `OLLAMA_HOST` — defaults to `http://ollama:11434`
- `GATEWAY_JWT_SECRET` — signs workspace-scoped access tokens (1h) — required
- `GATEWAY_JWT_ACCESS_EXPIRY_MINUTES` — access token lifetime, default 60
- `GATEWAY_REFRESH_SECRET` — signs httpOnly refresh tokens (30d) — required
- `GATEWAY_REFRESH_EXPIRY_DAYS` — refresh token lifetime, default 30
- `JWT_EXPIRY_MINUTES` — durée de vie du user-JWT émis par auth-service (défaut **1440** = 24h) ; à configurer dans auth-service
- `CORS_ALLOWED_ORIGINS` — whitelist for frontend origins (required for httpOnly cookies)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — optional SMTP for invitation emails + email alert channel
- gRPC host/port variables for internal service communication
- Each service has its own `DATABASE_URL` pointing to its dedicated postgres container
- `REDIS_MAXMEMORY` — limite mémoire du conteneur Redis (ex. `256mb` en dev), utilisée par `docker-compose` avec `--maxmemory-policy allkeys-lru`
- `AI_TIMEOUT_SECONDS` — timeout HTTP ai-service → Ollama (défaut **30** dans le code ; mettre **300** en dev sur CPU pour laisser le temps à l'inférence Mistral)
- Gateway : Uvicorn (ASGI) remplace Gunicorn depuis phase-16 — requis pour les GraphQL Subscriptions (WebSocket). CMD dans `services/gateway/Dockerfile` : `uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 2`. Utiliser **`uvicorn[standard]`** (pas `uvicorn` seul) — le `[standard]` inclut `websockets` et `httptools`, requis pour le protocole `graphql-ws`.
- Gateway ASGI router (`config/asgi.py`) : route `/graphql` vers `strawberry.asgi.GraphQL` (HTTP + WebSocket via `graphql-ws`) ; tout le reste vers Django. `starlette>=0.27.0,<1.0` est une dépendance directe requise par `strawberry.asgi.GraphQL` — l'ajouter à `requirements.txt`.
- `require_auth()` gère deux contextes : dict Starlette (HTTP + WebSocket) et objet Django legacy. WebSocket → token via `connection_params["Authorization"]` dans le payload `connection_init`. HTTP → `request.headers["Authorization"]`.
- Nginx : **deux blocs `location`** dans `infra/nginx/default.conf`. `/graphql` : `proxy_read_timeout 300s`, `proxy_send_timeout 300s`, `proxy_buffering off`, headers WebSocket (`Upgrade`, `Connection` via `map $http_upgrade`). `/` : `proxy_read_timeout 180s`, `proxy_send_timeout 180s`, `Connection: ""`.
- `OLLAMA_MODEL` — en dev, **`mistral`** recommandé pour gros prompts ; modèles type « thinking » peuvent échouer sur `/api/chat` malgré une RAM correcte
- Logs applicatifs : **`PODIQ_SERVICE_NAME`**, **`LOG_FORMAT=json|console`** et **`LOG_LEVEL`** sont définis dans les **Dockerfiles** des services ; surcharge possible via Compose ou variables passées aux conteneurs.

## gRPC Communication

Proto files in `proto/` directory define service contracts:
- `proto/analyzer/analyzer.proto` — **ParseManifest only** (CollectPod + ScanNamespace supprimés — la collecte K8s est faite par l'agent directement dans le cluster)
- `proto/ai/ai.proto` — AnalyzeIncident, ScanManifest, **GetAnalysisHistory** — tous portent `workspace_id` (tenant isolation)
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

- Logs flow: Docker containers stdout → **Loki Docker Log Driver** (plugin daemon) → Loki → Grafana
- **Aucun Promtail en dev** — le plugin log driver pousse les logs directement depuis le daemon Docker vers `http://host.docker.internal:3100/loki/api/v1/push`. Aucun `/var/run/docker.sock` monté dans un conteneur (SOC2 §8.5).
- Labels Loki : `namespace="podiq"`, `service="<nom-service>"` — configurés via `loki-external-labels` dans `docker-compose.yml`
- Filtrer par service dans Grafana Explore → Loki : `{service="auth-service"}`
- Config Loki : `infra/loki/loki-config.yml` (baked dans image via Dockerfile) — rétention **90 jours** (SOC2 §7.3)
- Config K8s production (Promtail DaemonSet) : `infra/promtail/Dockerfile.k8s-reference` + `docs/observability-k8s.md`
- Dashboard : `infra/grafana/provisioning/dashboards/podiq-overview.json` — 9 sections, 58 panneaux
- Grafana accessible at http://localhost:3000 (credentials dans .env)

## Development Order

1. ✅ Docker Compose complete (4 postgres instances + all services)
2. ✅ Django setup + ORM models + migrations in each service independently
   - auth-service: users, api_keys
   - ai-service: analyses, incident_patterns
   - analyzer-service: logs_snapshots, namespace_snapshots
   - gateway: Django sessions only
3. ✅ proto gRPC → generate stubs (auth, analyzer, ai + GetAnalysisHistory)
4. ✅ Analyzer Service: ParseManifest only (CollectPod + ScanNamespace supprimés — collecte K8s déplacée vers l'agent)
5. ✅ AI Service: AnalyzeIncident + ScanManifest + GetAnalysisHistory
6. ✅ Auth Service: Register + Login + ValidateJWT + CreateApiKey + ValidateApiKey + RevokeApiKey
7. ✅ Gateway GraphQL: schema complet (analyzeIncident, scanManifest, register, login, createApiKey, revokeApiKey, analysisHistory)
8. ✅ Loki + Grafana configurés via Loki Docker Log Driver (labels service/namespace, rétention 90j — SOC2 §7.3) ; Promtail supprimé en dev, Dockerfile.k8s-reference + docs/observability-k8s.md pour K8s prod
9. ✅ README.md dans chaque service (FR, avec analogies, I/O gRPC, DB, env vars)
10. ✅ Memory Engine (gateway appelle GetHistory avant AnalyzeIncident, injecte history[])
11. ✅ Temporal correlation agent-based — agent envoie `namespace_pods` JSON → `_build_namespace_context()` dans gateway/tasks.py → `PodContext.in_correlation_window` enrichi (`CORRELATION_WINDOW_MINUTES` configurable)
12. ✅ Pre-deploy scan REST complet
13. ✅ CI/CD REST endpoint + API Keys (POST /api/v1/cicd/scan)
14. ✅ Redis Queue Dramatiq (flux async complet)
15. ✅ Dashboard Grafana podiq-overview.json
16. ✅ Agent GraphQL-first — `agentHeartbeat` + `agentReportIncident` mutations ; script `scripts/agent_simulate.sh` ; manifests de test `k8s/test-pods/`
17. ✅ Phase 16 — Auth + Workspace + Agent + Invitations + Notifications
    - JWT en deux temps : user-JWT (auth-service gRPC) → workspace-JWT (gateway, GATEWAY_JWT_SECRET)
    - `require_auth()` retourne `TokenContext{user_id, email, workspace_id, role}` — décode localement si workspace-JWT (fast path), sinon gRPC fallback. Lève **`GraphQLError`** (jamais `PermissionError`) avec `extensions["code"]` : `PODIQ_TOKEN_MISSING` (header absent/vide) ou `PODIQ_TOKEN_INVALID` (JWT invalide/expiré)
    - **Erreurs GraphQL standardisées** — `app/api_codes.py` : tout `raise GraphQLError` porte `extensions=graphql_error_extensions(ErrorCode.XXX)`. Codes : `PODIQ_TOKEN_MISSING`, `PODIQ_TOKEN_INVALID`, `PODIQ_UNAUTHORIZED`, `PODIQ_FORBIDDEN`, `PODIQ_NOT_FOUND`, `PODIQ_CONFLICT`, `PODIQ_VALIDATION_ERROR`. Jamais de `PermissionError` propagé au client.
    - Refresh token httpOnly cookie (GATEWAY_REFRESH_SECRET, 30j, rotation à chaque appel)
    - Gateway ASGI : `strawberry.asgi.GraphQL` (pas `AsyncGraphQLView`) — `/graphql` supporte HTTP + WebSocket (`graphql-ws`). `uvicorn[standard]` + `starlette` requis.
    - `config/asgi.py` : ASGI router — `/graphql` → Starlette/Strawberry, reste → Django. `info.context` est un dict `{"request": ..., "response": ...}` (pas un objet).
    - Toutes les mutations/queries sont `async def` avec `sync_to_async(_func)(args)` — obligatoire sous ASGI pour le Django ORM synchrone.
    - GraphQL Subscriptions WebSocket (`graphql-ws`) : `clusterConnected(workspaceId)` + `jobStatus(jobId)` — DB polling async toutes les 2-3s
    - Agent GraphQL-first : `agentHeartbeat` + `agentReportIncident` mutations (pas de REST). `install_token.used=True` = cluster enregistré, pas token invalidé — l'agent réutilise le même token indéfiniment (seule l'expiry est vérifiée).
    - `generateInstallToken` + `clusterStatus` pour le frontend onboarding
    - `agentHeartbeat` pose automatiquement `workspace.onboarded_at = now()` au **premier heartbeat** d'un cluster (`created=True` + `workspace.onboarded_at is None`) — signal canonique de fin d'onboarding pour le frontend
    - Invitations : `inviteMember`, `revokeInvitation`, `acceptInvitation`, `generateInviteLink`, `listInvitations`. `acceptInvitation` : upgrade-only du rôle (viewer < member < admin) via `_ROLE_PRIORITY` — jamais de downgrade.
    - Notifications : `AlertRule`, `NotificationChannel` (6 types), `QuietHours`, `send_notifications_task` Dramatiq
    - Migrations gateway : 0002_workspace + 0003_invitations_alerts
    - **user-JWT : pas de mécanisme de refresh** — le user-JWT est un credential de transition (24h, `JWT_EXPIRY_MINUTES=1440`). Son seul usage est d'appeler `selectWorkspace` ou `createWorkspace`. Si expiré, l'utilisateur se reconnecte (`login`). Pas de refresh cookie pour le user-JWT — seul le workspace-JWT dispose d'un refresh httpOnly (30j).
    - **user-JWT valide sans workspace (onboarding)** : si l'utilisateur se reconnecte et n'a pas encore terminé l'onboarding, `listWorkspaces` avec le user-JWT retourne la liste de ses workspaces. Si `onboarded_at is null` sur le workspace → frontend redirige vers le step d'installation agent. Si plusieurs workspaces → frontend présente la sélection ; `onboarded_at is null` sur un workspace particulier = onboarding de ce workspace encore incomplet.
    - **Tenant isolation complète (phase 17 — post-launch fix)** :
      - `analysisJob` / `jobStatus` filtrés par `workspace_id` (plus par `user_id` seul)
      - `workspace_id` propagé dans `proto/ai/ai.proto` (champs 8/7/5 sur IncidentRequest/ManifestScanRequest/HistoryRequest)
      - Migration `0002_workspace_id` dans ai-service : `workspace_id` nullable sur `analyses` et `incident_patterns`
      - `incident_patterns` unique sur `(workspace_id, pod_name, namespace, error_type)`
      - Tous les filtres gRPC et sauvegardes dans `ai-service/app/grpc_server.py` scopés par `workspace_id`
      - Gateway passe `workspace_id` dans `tasks.py`, `ai_client.py`, `scan_manifest.py`, `history.py`
      - SOC2 v1.4 : R-12 ajouté, §13.2 mis à jour, roadmap P1 fermé
18. 🔲 Frontend Angular
19. 🔲 services/agent/ (Phase 3c — agent Python service + Helm chart)
