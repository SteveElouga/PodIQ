# Gateway — Le Chef d'Orchestre

## Analogie

Imagine la **réception d'un hôpital de haut niveau**.

- Les clients (frontend Angular, CLI, pipelines CI/CD) arrivent à la réception et font leur demande. Ils ne savent pas comment l'hôpital est organisé en interne — ils parlent uniquement à la réceptionniste.
- La réceptionniste (le Gateway) **comprend la demande**, **contacte les bons services** dans le bon ordre (le technicien de terrain d'abord, puis le médecin expert), et **assemble la réponse finale** à remettre au client.
- Si le client veut s'identifier, la réceptionniste transmet ses informations au **service d'accueil/sécurité** (auth-service) et retourne le badge d'accès.
- La réceptionniste ne fait **aucun diagnostic** elle-même — elle orchestre et transmet.

---

## Responsabilité

Le Gateway est le **seul point d'entrée** de PodIQ pour les clients externes. Il est responsable de :
- Exposer une **API GraphQL** sur `/graphql` (pour le frontend et la CLI)
- Orchestrer les appels gRPC entre les services backend dans le bon ordre
- Assembler les résultats et les retourner au client dans le format GraphQL attendu
- Déléguer l'authentification à l'auth-service
- Exposer un endpoint **REST** sur `/api/v1/cicd/scan` pour les pipelines CI/CD (auth via `X-Api-Key`, exit codes 0/1/2)

Il ne fait **aucun appel direct à Kubernetes**, **aucun appel à Ollama**, et **n'accède à aucune base de données autre que la sienne** (sessions Django).

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-gateway`** (port 5432).

Elle contient les tables internes à Django et les jobs d'analyse asynchrones :
- `django_session` — sessions web (si utilisées)
- Tables d'administration Django (si activées)
- `analysis_jobs` — jobs d'analyse de pods (UUID PK, statut `pending/running/complete/failed`, résultat JSON, erreur texte, horodatages)

---

## Interface GraphQL

Le Gateway expose une API GraphQL sur **`http://localhost:8080/graphql`**.

Le playground interactif est disponible à la même URL (en GET).

---

## Mutations disponibles

### `analyzeIncident` — Analyser un incident Kubernetes (asynchrone)

Déclenche une analyse complète d’un pod en échec. **L’appel retourne immédiatement** un `jobId` ; l’analyse tourne en arrière-plan via Dramatiq. Le client doit ensuite poller `analysisJob(jobId)` pour suivre l’avancement.

**Entrée :**
```graphql
mutation {
  analyzeIncident(podName: "mon-pod", namespace: "default") {
    jobId
    status
    createdAt
  }
}
```

**Ce que le Gateway fait en interne (mutation) :**

```
1. Crée un AnalysisJob en base (status=pending)
2. Enfile analyze_incident_task via Dramatiq → Redis
3. Retourne AnalysisJobType{jobId, status="pending", result=null, error=null, createdAt}
   (retour immédiat — pas d’attente gRPC)
```

**Ce que le worker Dramatiq fait en arrière-plan (`gateway-worker`) :**

```
1. analyzer_client.collect_pod(pod_name, namespace)  [status → running]
   └── L’analyzer-service va chercher logs + events dans Kubernetes

2. analyzer_client.scan_namespace(namespace, timestamp)
   └── L’analyzer-service liste tous les pods du namespace

3. Construit le namespace_context (corrélation temporelle)
   └── Fenêtre configurable : CORRELATION_WINDOW_MINUTES (défaut 15 min)
   └── Chaque pod reçoit in_correlation_window, seconds_before_reference

4. Memory Engine — ai_client.get_history(pod_name, namespace, limit=5)
   └── Récupère les 5 derniers incidents connus pour ce pod/namespace
   └── Transforme en PastIncident[] pour injection dans le prompt IA

5. ai_client.analyze_incident(request avec history injecté)
   └── Ollama voit les incidents passés → identifie récurrences, affine la cause
   └── Upsert dans incident_patterns (compteur d’occurrences)

6. Persiste le résultat → AnalysisJob{status=complete, result={...}}
   En cas d’erreur → AnalysisJob{status=failed, error="..."}
```

**Sortie immédiate (mutation) :**
```
jobId     : ID     — UUID du job, à utiliser pour poller
status    : String — toujours "pending" au retour de la mutation
result    : null   — pas encore disponible
error     : null
createdAt : String — ISO 8601
```

**Flux complet côté client :**
```
1. mutation analyzeIncident → jobId
2. query analysisJob(jobId) → status="pending"|"running"  (poller toutes les 2–5 s)
3. query analysisJob(jobId) → status="complete", result={...}
   ou                       → status="failed",   error="..."
```

**Pourquoi le Memory Engine est dans le Gateway et non dans l’AI Service ?**

Le Gateway est responsable de l’orchestration : il décide dans quel ordre appeler les services et quelles données assembler. L’AI Service reste pur — il reçoit toutes les données déjà préparées et se concentre uniquement sur l’analyse.

---

### `scanManifest` — Scanner un manifest avant déploiement

Analyse un fichier YAML Kubernetes pour détecter des risques de configuration.

**Entrée :**
```graphql
mutation {
  scanManifest(yamlContent: "<contenu yaml>", manifestType: "Deployment") {
    riskLevel
    summary
    risks {
      severity
      category
      description
      fix
    }
  }
}
```

**Ce que le Gateway fait en interne :**

```
1. analyzer_client.parse_manifest(yaml_content, manifest_type)
   └── L'analyzer-service parse et structure le YAML

2. Memory Engine — ai_client.get_history(pod_name=manifest_name, namespace, limit=5)
   └── Récupère les incidents passés liés à ce manifest/namespace
   └── Si ai-service indisponible → dégradation gracieuse, history=[] (scan non bloqué)

3. ai_client.scan_manifest(parsed_manifest, user_id, manifest_name, manifest_namespace, manifest_type, related_history)
   └── L'AI Service envoie à Ollama pour détecter les risques, enrichi par l'historique
   └── Persiste le résultat dans postgres-ai (analysis_type="predeploy")

4. Retourne ManifestScanResultType
```

**Sortie :**
```
riskLevel : String     — "safe" | "warning" | "block"
summary   : String     — résumé en langage naturel
risks     : [RiskItem] — liste des risques détectés
  severity    : String  — "low" | "medium" | "high" | "critical"
  category    : String  — "missing_env" | "probe" | "image_tag" | "memory" | "security"
  description : String
  fix         : String
```

---

### `register` — Créer un compte utilisateur

**Entrée :**
```graphql
mutation {
  register(email: "user@example.com", password: "secret123") {
    token
    userId
    email
  }
}
```

**Ce que le Gateway fait en interne :**
```
0. Validation du format email (_validate_email)
   └── Regex RFC : doit contenir @, domaine, TLD ≥ 2 chars
   └── Si invalide → GraphQLError PODIQ_VALIDATION_ERROR (sans appel gRPC)

1. auth_client.register(email, password)
   └── L'auth-service crée l'utilisateur et génère le JWT

2. Retourne AuthPayload
```

**Sortie :**
```
token  : String  — JWT valide 24h, à conserver côté client
userId : String  — UUID de l'utilisateur
email  : String
```

---

### `login` — Se connecter

**Entrée :**
```graphql
mutation {
  login(email: "user@example.com", password: "secret123") {
    token
    userId
    email
  }
}
```

**Sortie :** Identique à `register`.

> La validation du format email s'applique aussi à `login` — un email invalide retourne `PODIQ_VALIDATION_ERROR` sans appel gRPC.

---

### `createApiKey` — Créer une clé API (CI/CD)

Nécessite un JWT valide (`Authorization: Bearer <token>`). Retourne la clé brute **une seule fois** — à copier immédiatement.

**Entrée :**
```graphql
mutation {
  createApiKey(name: "github-actions-prod") {
    keyId
    rawKey
    name
    createdAt
  }
}
```

**Ce que le Gateway fait en interne :**
```
1. require_auth(info) → vérifie le JWT, extrait user_id
2. auth_client.create_api_key(user_id, name)
   └── auth-service génère une clé aléatoire (secrets.token_urlsafe(32))
   └── Stocke le hash SHA-256 dans api_keys, retourne la clé brute une seule fois
3. Retourne ApiKeyPayload{keyId, rawKey, name, createdAt}
```

**Sortie :**
```
keyId     : String  — UUID de la clé (pour revokeApiKey)
rawKey    : String  — clé brute (ex: "abc123...") — à conserver, non récupérable ensuite
name      : String  — nom donné à la clé
createdAt : String  — ISO 8601
```

> **Important :** `rawKey` n'est jamais stocké en clair côté serveur (SHA-256). Si vous le perdez, révoquez la clé et créez-en une nouvelle.

---

### `revokeApiKey` — Révoquer une clé API

**Entrée :**
```graphql
mutation {
  revokeApiKey(keyId: "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb")
}
```

**Sortie :** `Boolean` — `true` si révoquée, `false` si introuvable.

Le Gateway vérifie que la clé appartient bien à l'utilisateur authentifié (via `user_id` extrait du JWT) avant de la révoquer.

---

## Queries disponibles

### `analysisJob` — Suivre l'état d'un job d'analyse

Retourne l'état courant d'un job créé par `analyzeIncident`. À appeler en polling jusqu'à `status="complete"` ou `"failed"`.

**Entrée :**
```graphql
query {
  analysisJob(jobId: "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb") {
    jobId
    status
    result {
      errorType
      rootCause
      explanation
      solution
      confidence
      isRecurring
      recurrenceCount
      correlatedService
      correlationExplanation
    }
    error
    createdAt
  }
}
```

**Statuts possibles :**
| `status`    | Signification |
|-------------|---------------|
| `pending`   | En attente dans la file Dramatiq |
| `running`   | Worker en cours d'exécution |
| `complete`  | Analyse terminée — `result` est renseigné |
| `failed`    | Erreur — `error` contient le message |

**Sécurité :** le job n'est visible que par l'utilisateur qui l'a créé. Un autre `userId` reçoit `GraphQLError("Job not found")`.

---

### `analysisHistory` — Consulter l'historique d'un pod ou manifest

**Entrée :**
```graphql
query {
  analysisHistory(
    podName: "mon-pod"
    namespace: "default"
    limit: 10
    analysisType: "incident"   # optionnel : "" | "incident" | "predeploy"
  ) {
    id
    podName
    namespace
    errorType
    rootCause
    solution
    confidence
    isRecurring
    recurrenceCount
    createdAt
    analysisType
    riskLevel
  }
}
```

**Ce que le Gateway fait en interne :**
```
1. ai_client.get_history(pod_name, namespace, limit, analysis_type)
   └── Si analysis_type="" → retourne incidents + predeploy
   └── Si analysis_type="predeploy" → uniquement les scans manifest

2. Convertit les unix timestamps en ISO 8601 (ex: "2026-05-11T14:32:00")

3. Retourne [AnalysisHistoryItem]
```

---

## Endpoint REST CI/CD

### `POST /api/v1/cicd/scan` — Scanner un manifest depuis un pipeline

Endpoint REST dédié aux pipelines CI/CD. Authentification par **API Key** (pas de JWT).

**Headers :**
```
X-Api-Key: <clé brute créée via CreateApiKey>
Content-Type: application/json
```

**Body JSON :**
```json
{
  "yaml_content": "<contenu du manifest YAML>",
  "manifest_type": "Deployment"
}
```
`manifest_type` est optionnel.

**Réponse 200 :**
```json
{
  "exit_code": 0,
  "risk_level": "safe",
  "summary": "No critical issues found.",
  "risks": []
}
```

**Exit codes :**
| Code | `risk_level` | Signification |
|------|-------------|---------------|
| `0`  | `safe`      | Déploiement autorisé |
| `1`  | `warning`   | Déploiement autorisé, révision recommandée |
| `2`  | `block`     | Déploiement bloqué — risques critiques détectés |

**Erreurs :**
| HTTP | `code` | Cause |
|------|--------|-------|
| `401` | `PODIQ_TOKEN_MISSING` | Header `X-Api-Key` absent |
| `401` | `PODIQ_TOKEN_INVALID` | Clé invalide ou révoquée |
| `400` | `PODIQ_VALIDATION_ERROR` | `yaml_content` absent ou YAML invalide |
| `502` | `PODIQ_AUTH_GRPC_ERROR` | auth-service indisponible |
| `502` | `PODIQ_ANALYZER_GRPC_ERROR` | analyzer-service indisponible |
| `502` | `PODIQ_AI_GRPC_ERROR` | AI service indisponible |

**Ce que le Gateway fait en interne :**
```
1. Vérifie X-Api-Key → auth_client.validate_api_key(raw_key)
   └── auth-service vérifie le hash SHA-256 et le statut is_active

2. analyzer_client.parse_manifest(yaml_content, manifest_type)
   └── L'analyzer-service structure le YAML

3. ai_client.scan_manifest(parsed.raw_config, user_id, manifest_name, manifest_namespace, manifest_type, related_history=[])
   └── L'AI Service détecte les risques via Ollama
   └── Persiste le résultat dans postgres-ai (analysis_type="predeploy")

4. Mappe risk_level → exit_code et retourne JSON
```

**Exemple curl :**
```bash
curl -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: <votre-clé>" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "apiVersion: apps/v1\nkind: Deployment\n..."}'

# Exit code pipeable :
RESULT=$(curl -s ... | jq '.exit_code')
exit $RESULT
```

---

## Schéma GraphQL complet

```
Query
├── analysisJob(jobId) → AnalysisJobType          ← polling async
└── analysisHistory(podName, namespace, limit, analysisType?) → [AnalysisHistoryItem]

Mutation
├── analyzeIncident(podName, namespace) → AnalysisJobType  ← retourne immédiatement (async)
├── scanManifest(yamlContent, manifestType) → ManifestScanResultType
├── register(email, password) → AuthPayload
├── login(email, password) → AuthPayload
├── createApiKey(name) → ApiKeyPayload         ← JWT requis
└── revokeApiKey(keyId) → Boolean              ← JWT requis

REST
└── POST /api/v1/cicd/scan → {exit_code, risk_level, summary, risks[]}
```

---

## Clients gRPC internes

Le Gateway maintient un client gRPC léger pour chaque service backend.

| Client               | Service cible     | Port  | Méthodes                                        |
|----------------------|-------------------|-------|-------------------------------------------------|
| `analyzer_client.py` | analyzer-service  | 50052 | `collect_pod`, `scan_namespace`, `parse_manifest`|
| `ai_client.py`       | ai-service        | 50053 | `analyze_incident`, `scan_manifest`, `get_history`|
| `auth_client.py`     | auth-service      | 50051 | `register`, `login`, `validate_api_key`, `create_api_key`, `revoke_api_key` |

Chaque appel gRPC ouvre un canal dédié (simple, sans pool — à optimiser avec Redis en Étape 11).

### Processus HTTP et timeouts

La chaîne de timeouts est configurée pour couvrir l’inférence Ollama sur CPU :

| Couche | Valeur | Fichier |
|--------|--------|---------|
| Nginx `proxy_connect_timeout` | 10 s | `infra/nginx/default.conf` |
| Nginx `proxy_read_timeout` | **180 s** | `infra/nginx/default.conf` |
| Gunicorn `--timeout` | **180 s** | `services/gateway/Dockerfile` |

`analyzeIncident` est **asynchrone** — retour immédiat, pas de blocage worker. `scanManifest` reste **synchrone** : attend la fin de l’inférence Ollama. Si Ollama dépasse 180 s, le client reçoit `grpc_message: "timed out"` (GraphQL error) et non une page HTML 504.

### Worker Dramatiq (`gateway-worker`)

Le worker est lancé via `worker_main.py` qui :
1. Initialise Django (`django.setup()`) avant d’importer les acteurs Dramatiq — sans cela, l’import de `core.models` lève `AppRegistryNotReady`
2. Enregistre `JobFailureMiddleware` : si une tâche épuise ses retries sans jamais atteindre le bloc `except` (ex. crash au démarrage), le middleware marque automatiquement le job `failed` en base

```bash
# Commande dans docker-compose.yml
python -m dramatiq worker_main --processes 2 --threads 4
```

Les acteurs sont configurés avec `max_retries=2, time_limit=300_000` (5 min).

---

## Variables d'environnement

| Variable               | Obligatoire | Défaut       | Description                               |
|------------------------|-------------|--------------|-------------------------------------------|
| `DATABASE_URL`         | Oui         | —            | `postgresql://user:pass@postgres-gateway/db`|
| `DJANGO_SECRET_KEY`    | Oui         | —            | Clé secrète Django                        |
| `ANALYZER_GRPC_HOST`   | Non         | `analyzer-service` | Hôte de l'analyzer-service          |
| `ANALYZER_GRPC_PORT`   | Non         | `50052`      | Port de l'analyzer-service                |
| `AI_GRPC_HOST`         | Non         | `ai-service` | Hôte de l'AI Service                      |
| `AI_GRPC_PORT`         | Non         | `50053`      | Port de l'AI Service                      |
| `AUTH_GRPC_HOST`       | Non         | `auth-service`| Hôte de l'auth-service                   |
| `AUTH_GRPC_PORT`       | Non         | `50051`      | Port de l'auth-service                    |
| `REDIS_URL`            | Oui (prod)  | —            | `redis://redis:6379/0` — broker Dramatiq pour les jobs async |
| `CORS_ALLOWED_ORIGINS` | Non         | `*`          | Origins autorisées (CORS)                 |
| `CORRELATION_WINDOW_MINUTES` | Non   | `15`         | Fenêtre (en minutes) pour marquer les pods « dans la fenêtre de corrélation » avec le pod incident |

### Authentification des endpoints protégés

Les mutations `analyzeIncident`, `scanManifest` et la query `analysisHistory` requièrent un JWT valide dans le header HTTP :

```
Authorization: Bearer <token>
```

Le token est obtenu via `login` ou `register` (mutations GraphQL publiques).

En interne, le helper `app/auth.py::require_auth(info)` extrait le token, appelle **`auth-service` via gRPC** (`ValidateJWT`) et retourne le `user_id` si valide. En cas d'absence ou d'invalidité, une `PermissionError` est levée → GraphQL retourne une erreur `UNAUTHORIZED`.

Les mutations `register` et `login` restent **publiques** (aucun token requis).

### Dépannage rapide GraphQL

- **`Unexpected token '<', "<html>..." is not valid JSON`** : le navigateur reçoit du HTML (souvent **502**). Causes fréquentes : worker Gunicorn tué (timeout trop court — reconstruire l’image gateway après changement du `Dockerfile`), ou Nginx qui ne joint plus le gateway (voir `ERROR_RESOLVE.md`, résolution DNS `127.0.0.11`).
- **`grpc_message: "timed out"`** : dépassement côté ai-service / Ollama — augmenter `AI_TIMEOUT_SECONDS`, vérifier les logs `ai-service` et `ollama`, modèle recommandé **`mistral`** pour les longs prompts (voir `services/ai-service/README.md`).

---

## Communication avec les autres services

```
Client (Angular / CLI / CI)
         │
         ▼ HTTP GraphQL (port 8080)
      Gateway
    ┌────┼────────────────┐
    ▼    ▼                ▼
Auth  Analyzer          AI Service
gRPC  gRPC              gRPC
50051 50052             50053
```

Le Gateway est le **seul service visible de l'extérieur**. Tous les autres services sont internes au réseau Docker.

---

## Comment tester

### Tests unitaires (pytest)

**Python 3.14** en local est pris en charge : Strawberry est installé depuis une archive GitHub (commit pinné dans `requirements.txt`), nécessaire tant que PyPI ne publie pas ce correctif pour `dataclasses.Field` / **3.14**. L’image Docker reste en **Python 3.12** et utilise le même fichier de dépendances.

```bash
cd services/gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -v
```

Les contrôles **pre-commit** (Black, Ruff, mypy, etc.) s’exécutent depuis la **racine du dépôt** ; voir le README racine § « Pré-commit » et `pre-commit install`.

### 1. Démarrer toute la stack

```bash
docker compose up -d --build
docker compose logs -f gateway
```

### 2. Vérifier l'endpoint de santé

```bash
curl http://localhost:8080/healthz
# → {"status": "ok"}
```

### 3. Ouvrir le playground GraphQL

Naviguer vers `http://localhost:8080/graphql` dans le navigateur.

### 4. Tester l'inscription

```graphql
mutation {
  register(email: "test@podiq.io", password: "test1234") {
    token
    userId
    email
  }
}
```

### 5. Déclencher une analyse (async)

```graphql
mutation {
  analyzeIncident(podName: "crashloop-pod", namespace: "default") {
    jobId
    status
    createdAt
  }
}
```

### 6. Poller le résultat

```graphql
query {
  analysisJob(jobId: "<jobId retourné ci-dessus>") {
    status
    result {
      errorType
      rootCause
      solution
      confidence
      isRecurring
    }
    error
  }
}
```

Relancer cette query toutes les 2–5 secondes jusqu'à `status="complete"` ou `"failed"`.
