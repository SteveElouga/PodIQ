# MR — chore/structured-logging-json

---

## Avant de soumettre la MR

- [x] Le titre de la MR suit le format conventionnel (`feat/fix/chore/refactor/docs(scope): description`)
- [x] La branche cible est correcte (`develop`, pas `main`)
- [x] Les conflits sont résolus
- [x] Les `print` et logs de debug temporaires sont supprimés
- [ ] `pre-commit run --all-files` passe sans erreur (Black, Ruff, mypy, detect-secrets)
- [x] Les tests unitaires passent localement (`./scripts/run_all_tests.sh`)
- [ ] Le lien vers la tâche est ajouté ci-dessous (section Références)

---

## Références

- **Tâche / ticket :** _(à renseigner)_
- **MR(s) dépendantes :** `chore/pre-commit-stack` (mergée dans cette branche — `.pre-commit-config.yaml`, `.secrets.baseline`, `pyproject.toml`)
- **Proto modifié :** non

---

## Contexte

Deux problèmes coexistaient dans la base de code :

1. **Logging non uniforme** : chaque service utilisait `print`, `logging.getLogger`, ou des appels `structlog` sans configuration partagée. En conteneur, les logs étaient illisibles par Loki (format texte brut, pas de champ `service`, pas de `timestamp` ISO UTC).
2. **Aucun garde-fou qualité** : rien n'empêchait de committer du code mal formaté (Black/Ruff), des secrets, des Dockerfiles mal écrits, ou des types invalides (mypy). L'absence de `.pre-commit-config.yaml` rendait l'installation du hook inutilisable sur les autres branches.

Cette MR installe la couche d'observabilité de base (structlog JSON) et la chaîne de qualité pré-commit, deux prérequis pour les étapes suivantes (Dramatiq, dashboard Grafana).

---

## Changements

### Logging structuré (`feat(logging)` + `refactor(grpc_server)`)

- **`shared/podiq_logging/structlog_setup.py`** *(nouveau)* : module partagé `configure_podiq_logging()`. Détecte `LOG_FORMAT` (`json` | `console`) et `PODIQ_SERVICE_NAME` pour choisir le renderer. Chaque ligne de log JSON contient au minimum `timestamp` (ISO UTC), `level`, `service`, `event` (slug snake_case). Seuil piloté par `LOG_LEVEL` (défaut `INFO`).
- **`services/*/Dockerfile`** (gateway, auth-service, analyzer-service, ai-service) : ajout des variables `PODIQ_SERVICE_NAME`, `LOG_FORMAT=json`, `LOG_LEVEL=INFO` — le mode JSON s'active automatiquement en conteneur.
- **`services/*/config/settings.py`** et **`settings_pytest.py`** : appel `configure_podiq_logging()` au démarrage Django.
- **`services/*/manage.py`** : appel `configure_podiq_logging()` avant le bootstrap Django CLI.
- **`services/*/pytest.ini`** : ajout de `../../shared/podiq_logging` dans `pythonpath` pour résoudre le module en local sans polluer l'import `grpc`.
- **`services/ai-service/app/grpc_server.py`**, **`analyzer-service`**, **`auth-service`** : refactoring de la résolution du chemin vers `structlog_setup.py` — si `/app/shared/podiq_logging/structlog_setup.py` (Docker) n'existe pas, remonte les répertoires parents jusqu'à trouver `shared/podiq_logging/` (développement local).

### Qualité pré-commit (`feat(pre-commit)`)

- **`.pre-commit-config.yaml`** *(nouveau)* : hooks configurés —
  - `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-json`, `check-toml`, `check-merge-conflict`, `check-added-large-files` (512 KB max)
  - `no-commit-to-branch` : bloque les commits directs sur `main` / `master`
  - **Black 25.1.0** : formatage Python
  - **Ruff v0.11.9** : linting + autofix
  - **detect-secrets v1.5.0** : détection de secrets avec baseline
  - **yamllint v1.37.1** : validation YAML (config `.yamllint.yml`)
  - **hadolint** : lint des Dockerfiles
  - **mypy 1.15.0** : vérification des types sur les services Django (`scripts/run_mypy_precommit.py`)
- **`.secrets.baseline`** *(nouveau)* : baseline detect-secrets initiale (fichiers existants audités).
- **`.yamllint.yml`** *(nouveau)* : règles YAML (longueur de ligne 120, commentaires, espaces).
- **`pyproject.toml`** *(nouveau)* : configuration de Black, Ruff et mypy centralisée pour les hooks et les outils locaux.
- **`scripts/run_mypy_precommit.py`** *(nouveau)* : script mypy ciblant uniquement les paquets Django des services, avec résolution dynamique des stubs gRPC.
- **`requirements-dev.txt`** : ajout de `structlog` (déjà dans `requirements.txt` des services — ici pour les outils locaux).

### Correctif gRPC → GraphQL (`fix(gateway)`)

- **`services/gateway/app/grpc_errors.py`** : `raise_graphql_from_grpc()` + `invoke_grpc()` — toute erreur gRPC est convertie en `GraphQLError` avec un code PodIQ lisible. Un seul log `grpc_call_failed` (niveau `warning`) avec `grpc_status` et `service` — plus de tracebacks bruts dans les logs.
- **`services/gateway/app/graphql/mutations/auth.py`**, **`analyze.py`**, **`scan_manifest.py`**, **`queries/history.py`** : tous les appels gRPC sont wrappés via `invoke_grpc()` ou `raise_graphql_from_grpc()`.
- **`services/gateway/app/auth.py`** : `require_auth()` utilise `raise_graphql_from_grpc()` pour les erreurs de transport ; lève `PermissionError` pour les tokens manquants/invalides.

### Documentation

- **`CLAUDE.md`** : section logging ajoutée (`structlog`, `LOG_FORMAT`, `PODIQ_SERVICE_NAME`, `LOG_LEVEL`, `pythonpath pytest.ini`).
- **`README.md`** : section observabilité mise à jour ; guide pre-commit (installation, `pre-commit run --all-files`, régénération baseline detect-secrets).
- **`docs/ERROR_RESOLVE.md`** *(déplacé depuis racine)* : guide de résolution des erreurs fréquentes.
- **`docs/REDIS.md`** *(déplacé depuis racine)* : guidelines Redis déplacées dans `docs/`.

---

## Impact architectural

- [ ] Nouveau message proto / modification d'un `.proto` existant (stubs régénérés)
- [ ] Nouvelle migration Django (`makemigrations` + `migrate` requis au déploiement)
- [x] Nouvelle variable d'environnement (`.env.example` mis à jour) — `PODIQ_SERVICE_NAME`, `LOG_FORMAT`, `LOG_LEVEL`
- [ ] Nouveau service dans `docker-compose.yml`
- [ ] Modification du schéma Redis (clé, TTL, structure)
- [ ] Modification de l'API GraphQL publique (schema Strawberry)

> **Note déploiement :** les trois variables d'env sont définies dans les Dockerfiles. Aucune action requise côté `.env` pour les environnements Docker. En local (hors Docker), les logs s'affichent en mode `console` lisible par défaut.

---

## Comment tester

**Prérequis :**

- Variables d'env : aucune obligatoire en mode test local
- Python ≥ 3.12 avec l'environnement virtuel activé

**Tests unitaires :**

```bash
./scripts/run_all_tests.sh
# Attendu : 172/172 tests passent (52 gateway + 58 analyzer + 23 ai-service + 39 auth-service)
```

**Vérifier les logs JSON en conteneur :**

```bash
docker compose up -d --build auth-service
docker compose logs -f auth-service
# Chaque ligne doit être un objet JSON avec : timestamp, level, service, event
```

**Requête Loki dans Grafana (après démarrage de la stack observabilité) :**

```bash
docker compose up -d loki promtail grafana
# Grafana → http://localhost:3000 → Explore → Loki
# Requête : {service="auth-service"} | json
```

**Tester le hook pre-commit localement :**

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

**Tester la conversion gRPC → GraphQL :**

```bash
docker compose up -d --build postgres-auth auth-service gateway nginx
# Playground : http://localhost:8080/graphql
# Mutation avec token invalide → doit retourner GraphQLError propre, pas de traceback dans les logs
```

---

## Screenshots / Logs

Exemple de log JSON attendu en conteneur :

```json
{"timestamp": "2026-05-12T12:00:00Z", "level": "INFO", "service": "auth-service", "event": "mutation_register", "email": "alice@example.com"}
{"timestamp": "2026-05-12T12:00:00Z", "level": "WARNING", "service": "gateway", "event": "grpc_call_failed", "grpc_status": "UNAVAILABLE", "service_name": "auth"}
```
