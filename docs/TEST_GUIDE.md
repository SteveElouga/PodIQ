# Guide de test exhaustif — PodIQ

> **Version :** Phase 15 (stack MVP complète)
> **Audience :** Développeurs et testeurs du projet PodIQ
> **Objectif :** Tester chaque fonctionnalité de la plateforme pas à pas, comprendre son rôle, son implémentation, et vérifier chaque cas possible avec les résultats attendus.

---

## Table des matières

1. [Vue d'ensemble de l'architecture](#1-vue-densemble-de-larchitecture)
2. [Prérequis et mise en place](#2-prérequis-et-mise-en-place)
3. [Auth Service — Authentification et API Keys](#3-auth-service--authentification-et-api-keys)
4. [Gateway GraphQL — Mutations Auth](#4-gateway-graphql--mutations-auth)
5. [Gateway GraphQL — Analyse d'incident (async)](#5-gateway-graphql--analyse-dincident-async)
6. [Gateway GraphQL — Scan de manifest](#6-gateway-graphql--scan-de-manifest)
7. [Gateway GraphQL — Historique d'analyses](#7-gateway-graphql--historique-danalyses)
8. [Endpoint REST CI/CD](#8-endpoint-rest-cicd)
9. [Worker Dramatiq — Pipeline async](#9-worker-dramatiq--pipeline-async)
10. [Namespace Correlation — Corrélation temporelle](#10-namespace-correlation--corrélation-temporelle)
11. [Memory Engine — Incidents récurrents](#11-memory-engine--incidents-récurrents)
12. [Observabilité — Grafana + Loki](#12-observabilité--grafana--loki)
13. [Tests unitaires par service](#13-tests-unitaires-par-service)
14. [Scénarios end-to-end complets](#14-scénarios-end-to-end-complets)
15. [Matrice des cas de test](#15-matrice-des-cas-de-test)
16. [Dépannage rapide](#16-dépannage-rapide)

---

## 1. Vue d'ensemble de l'architecture

### Ce que PodIQ fait

PodIQ est une plateforme d'intelligence Kubernetes : elle **analyse les incidents de pods**, **mémorise les patterns récurrents**, **prédit les risques avant déploiement** et **bloque les pipelines CI/CD dangereux**.

### Flux de données complet

```
Client (curl / playground / Angular)
        │
        ▼ HTTP :8080 (nginx)
   ┌────────────────┐
   │    Gateway     │ Django + Strawberry GraphQL
   │    :8000       │ Dramatiq producer
   └────┬───────────┘
        │ gRPC
   ┌────┼──────────────────────────────┐
   ▼    ▼                              ▼
Auth  Analyzer-Service             AI-Service
:50051 :50052                       :50053
JWT   kubectl / STUB_MODE          Ollama :11434
      yaml parser                  Memory Engine
      namespace scanner            IncidentPattern
        │                                │
  postgres-auth                   postgres-ai
  (users, api_keys)               (analyses, incident_patterns)

   Gateway-Worker (Dramatiq consumer)
        │ consomme depuis Redis :6379
        │ appelle Analyzer + AI
        ▼
  postgres-gateway
  (analysis_jobs)
```

### Services et ports

| Service | Protocole | Port | Base |
|---|---|---|---|
| nginx (entrée externe) | HTTP | 8080 | — |
| gateway | HTTP | 8000 | postgres-gateway :5432 |
| gateway-worker | — (Dramatiq) | — | postgres-gateway :5432 |
| auth-service | gRPC | 50051 | postgres-auth :5433 |
| analyzer-service | gRPC | 50052 | postgres-analyzer :5434 |
| ai-service | gRPC | 50053 | postgres-ai :5435 |
| redis | TCP | 6379 | — |
| grafana | HTTP | 3000 | — |

---

## 2. Prérequis et mise en place

### 2.1 Prérequis logiciels

```bash
docker --version        # >= 24.x
docker compose version  # >= 2.x
curl --version          # pour les tests REST
python3 --version       # >= 3.12 (tests unitaires locaux)
```

### 2.2 Configuration initiale

```bash
# 1. Copier le fichier d'environnement
cp .env.example .env

# 2. Renseigner les variables obligatoires dans .env
POSTGRES_PASSWORD=podiq_secret_dev
JWT_SECRET=super_jwt_secret_dev
GRAFANA_ADMIN_PASSWORD=admin_secret
STUB_MODE=true          # utiliser des données K8s simulées (pas de vrai cluster)
OLLAMA_MODEL=mistral    # modèle recommandé
AI_TIMEOUT_SECONDS=120  # 2 min en dev CPU
```

### 2.3 Démarrer la stack complète

```bash
docker compose up -d --build

# Vérifier que tous les services sont healthy
docker compose ps

# Attendre que gateway soit healthy (peut prendre 30-60s)
docker compose logs -f gateway
# Signe de succès : "Booting worker with pid"
```

### 2.4 Vérification rapide de la stack

```bash
# Health check du gateway
curl http://localhost:8080/healthz
# Attendu : {"status": "ok"}

# Playground GraphQL accessible
curl -s http://localhost:8080/graphql | grep -i "graphql"
# Attendu : réponse HTML avec l'interface Strawberry
```

### 2.5 Stack minimale (sans Ollama, pour tester auth + gateway uniquement)

```bash
docker compose up -d --build postgres-auth postgres-gateway auth-service gateway nginx redis
```

---

## 3. Auth Service — Authentification et API Keys

### Ce que c'est

L'auth-service est le gardien de l'identité dans PodIQ. Il gère deux types d'authentification :
- **JWT** (JSON Web Token) pour les utilisateurs humains (frontend, CLI)
- **API Keys** pour les pipelines CI/CD automatisés

### Pourquoi c'est séparé du Gateway

Principe de séparation des responsabilités : le gateway ne stocke aucun secret, aucun hash de mot de passe. Toute décision d'authentification est déléguée à l'auth-service via gRPC. Le gateway est stateless côté auth.

### Implémentation — Modèles Django (postgres-auth)

```
users
  id            UUID (PK)
  email         VARCHAR (unique)
  password_hash VARCHAR (SHA-256 + SECRET_KEY pepper)
  created_at    TIMESTAMP

api_keys
  id            UUID (PK)
  user_id       UUID (référence croisée — pas de FK)
  key_hash      VARCHAR (SHA-256 de la clé brute)
  name          VARCHAR
  last_used     TIMESTAMP (nullable)
  is_active     BOOLEAN (default True)
  created_at    TIMESTAMP
```

### Implémentation — Hachage des mots de passe

Le mot de passe est haché avec `hashlib.sha256(password + SECRET_KEY)`. La comparaison utilise `hashlib.compare_digest()` pour être résistante aux attaques temporelles (timing attacks). La clé secrète Django sert de **pepper** — même si la base de données est compromise, les hashs ne sont pas exploitables sans la clé.

### 3.1 Register — Créer un compte

**Ce que ça fait :** Crée un nouvel utilisateur en base, génère un JWT valide 24h.

**Appel gRPC interne :** `AuthService.Register(RegisterRequest{email, password})`

**Test via Gateway GraphQL :**

```graphql
mutation {
  register(email: "alice@podiq.io", password: "MotDePasse123") {  # pragma: allowlist secret
    token
    userId
    email
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "register": {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "userId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "email": "alice@podiq.io"
    }
  }
}
```

**Cas de test — tous les scénarios :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Inscription normale | email valide + password | token JWT + userId |
| Email déjà utilisé | email existant en base | `GraphQLError: email already registered` |
| Email invalide | `"pas-un-email"` | `GraphQLError` (validation côté **gateway** — avant appel gRPC) |
| Password vide | `""` | `GraphQLError` |
| Appel sans Authorization | — (mutations publiques) | Succès — register est public |

**Vérification :**
```bash
# Décoder le JWT pour vérifier son contenu
echo "<token>" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# Attendu : {"user_id": "...", "email": "alice@podiq.io", "exp": <timestamp>}
```

---

### 3.2 Login — Se connecter

**Ce que ça fait :** Vérifie les credentials, génère un nouveau JWT.

**Test :**
```graphql
mutation {
  login(email: "alice@podiq.io", password: "MotDePasse123") {  # pragma: allowlist secret
    token
    userId
    email
  }
}
```

**Résultat attendu :** Identique à register — nouveau token JWT.

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Login correct | email + password corrects | nouveau token JWT |
| Mauvais password | bon email, mauvais password | `GraphQLError: Invalid credentials` |
| Email inconnu | email non enregistré | `GraphQLError: Invalid credentials` |
| Auth-service down | — | `GraphQLError: auth service unavailable` |

**Point important :** Les tokens JWT ont une durée de vie de **24h**. Après expiration, ValidateJWT retourne `valid=False` et les mutations protégées retourneront `PermissionError`.

---

### 3.3 Protection des mutations par JWT

**Ce que ça fait :** Les mutations `analyzeIncident`, `scanManifest` et la query `analysisHistory` et `analysisJob` exigent un JWT valide dans le header HTTP.

**Implémentation (gateway/app/auth.py) :**
```
require_auth(info)
  1. Extrait info.context.request.headers["Authorization"]
  2. Vérifie le format "Bearer <token>"
  3. Appelle auth_client.validate_jwt(token) via gRPC
  4. Si valid=True → retourne user_id
  5. Si valid=False → lève PermissionError
  6. Si gRPC error → lève GraphQLError("auth service unavailable")
```

**Test — appel protégé sans token :**
```bash
curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"test\", namespace: \"default\") { jobId } }"}'
```
**Résultat attendu :**
```json
{
  "data": null,
  "errors": [{"message": "Permission denied"}]
}
```

**Test — appel protégé avec token valide :**
```bash
TOKEN="<token obtenu via login>"
curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "mutation { analyzeIncident(podName: \"crashloop-pod\", namespace: \"default\") { jobId status } }"}'
```
**Résultat attendu :**
```json
{
  "data": {
    "analyzeIncident": {
      "jobId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "status": "pending"
    }
  }
}
```

---

### 3.4 API Keys — Pour les pipelines CI/CD

**Ce que c'est :** Les API Keys permettent à un pipeline automatisé d'appeler l'endpoint REST `/api/v1/cicd/scan` sans JWT humain. Elles ne sont pas liées à une session — elles peuvent être révoquées à tout moment.

**Principe de fonctionnement :**
1. L'utilisateur crée une API Key via GraphQL (futur — mutation `createApiKey`)
2. La clé brute est retournée **une seule fois** à la création
3. Seul le hash SHA-256 de la clé est stocké en base
4. Le pipeline envoie la clé brute dans le header `X-Api-Key`
5. L'auth-service hache la clé reçue et compare avec le hash en base
6. Si `is_active=True` et hash correspondant → accès autorisé

**Test direct de ValidateApiKey (via le CI/CD endpoint) :** Voir section 8.

---

## 4. Gateway GraphQL — Mutations Auth

### Pourquoi passer par le Gateway et non directement à l'auth-service ?

Le Gateway est le **seul point d'entrée externe**. Les services backend (auth, analyzer, ai) ne sont pas exposés à l'extérieur du réseau Docker. Toutes les communications clients passent par le Gateway qui délègue via gRPC.

### 4.1 Tester via le Playground Strawberry

Ouvrir `http://localhost:8080/graphql` dans un navigateur.

**Interface disponible :**
- Documentation des types GraphQL dans le panneau de droite
- Éditeur de requêtes avec auto-complétion
- Variables JSON dans le panneau inférieur

**Workflow typique :**
1. `register` → copier le `token`
2. Ajouter `{"Authorization": "Bearer <token>"}` dans les headers HTTP du playground
3. Exécuter les mutations protégées

---

## 5. Gateway GraphQL — Analyse d'incident (async)

### Ce que c'est

La fonctionnalité principale de PodIQ. Quand un pod Kubernetes est en échec (CrashLoopBackOff, OOMKilled, ImagePullBackOff...), l'utilisateur déclenche une analyse qui :
1. Collecte les logs, events, état du pod
2. Scanne le namespace pour détecter des pannes corrélées
3. Consulte l'historique d'incidents précédents du même pod
4. Envoie tout ça à un LLM (Ollama/Mistral) pour diagnostiquer

### Pourquoi asynchrone ?

L'analyse prend entre 5 et 120 secondes (inférence Ollama sur CPU). Un appel HTTP synchrone bloquerait le worker Gunicorn pendant toute cette durée. La solution : `analyzeIncident` crée un job et retourne immédiatement un `jobId`. Le client poll ensuite `analysisJob(jobId)` toutes les 2-5 secondes.

### Implémentation détaillée

**Étape 1 — Mutation (gateway/app/graphql/mutations/analyze.py) :**
```
_analyze_incident(info, pod_name, namespace)
  1. require_auth(info) → user_id (ou PermissionError)
  2. AnalysisJob.objects.create(user_id, pod_name, namespace)
     → status="pending", result=null, error=""
  3. analyze_incident_task.send(job_id, user_id, pod_name, namespace)
     → message Redis: queue "default", données sérialisées
  4. return AnalysisJobType{job_id, status="pending", result=null, error=null, created_at}
     (retour immédiat — ~5ms)
```

**Étape 2 — Worker (gateway/app/tasks.py) :**
```
analyze_incident_task(job_id, user_id, pod_name, namespace)
  1. AnalysisJob.objects.get(id=job_id) → status RUNNING, error="" + save  (error effacé à chaque retry)
  2. invoke_grpc(ANALYZER, collect_pod(pod_name, namespace))
     → PodData{pod_name, namespace, status, logs, events}
  3. invoke_grpc(ANALYZER, scan_namespace(namespace, timestamp))
     → NamespaceSnapshot{pods: [PodSummary...]}
  4. build_namespace_context(ns_snapshot, pod_data.pod_name)
     → [PodContext{pod_name, in_correlation_window, seconds_before_reference}]
  5. invoke_grpc(AI, get_history(pod_name, namespace, limit=5))
     → HistoryResponse{items: [PastIncident...]}
  6. Construit IncidentRequest{pod_name, namespace, status, logs, events, history, namespace_context}
  7. invoke_grpc(AI, analyze_incident(request))
     → AnalysisResult{error_type, root_cause, explanation, solution, confidence,
                       is_recurring, recurrence_count, correlated_service, correlation_explanation}
  8. job.result = {dict complet} ; job.status = COMPLETE ; job.save()

  En cas d'exception :
  8b. job.status = FAILED ; job.error = str(exc) ; job.save() ; raise
```

**Étape 3 — Polling (gateway/app/graphql/queries/job.py) :**
```
_analysis_job(info, job_id)
  1. require_auth(info) → user_id
  2. AnalysisJob.objects.get(id=job_id, user_id=user_id)
     (filtre par user_id → isolation stricte entre utilisateurs)
  3. Si status=COMPLETE → construit AnalysisResultType depuis job.result JSON
  4. Retourne AnalysisJobType{job_id, status, result, error, created_at}
```

### 5.1 Test complet de l'analyse d'incident

#### Étape 1 — Déclencher l'analyse

```bash
TOKEN="<votre token JWT>"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation Analyze($pod: String!, $ns: String!) { analyzeIncident(podName: $pod, namespace: $ns) { jobId status createdAt } }",
    "variables": {"pod": "crashloop-pod", "ns": "default"}
  }'
```

**Résultat attendu (immédiat, ~100ms) :**
```json
{
  "data": {
    "analyzeIncident": {
      "jobId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "status": "pending",
      "createdAt": "2026-05-17T08:00:00"
    }
  }
}
```

#### Étape 2 — Poller le statut

```bash
JOB_ID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"query\": \"query Poll(\$id: ID!) { analysisJob(jobId: \$id) { jobId status result { errorType rootCause explanation solution confidence isRecurring recurrenceCount correlatedService correlationExplanation } error } }\",
    \"variables\": {\"id\": \"$JOB_ID\"}
  }"
```

**Résultat pendant l'analyse (status=running) :**
```json
{
  "data": {
    "analysisJob": {
      "jobId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "status": "running",
      "result": null,
      "error": null
    }
  }
}
```

**Résultat après analyse complète (status=complete) :**
```json
{
  "data": {
    "analysisJob": {
      "jobId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "status": "complete",
      "result": {
        "errorType": "CrashLoopBackOff",
        "rootCause": "Le container redémarre en boucle en raison d'un manque de mémoire",
        "explanation": "Le pod dépasse les limites mémoire définies dans le manifest...",
        "solution": "Augmenter les memory limits ou réduire la consommation de l'application",
        "confidence": "high",
        "isRecurring": false,
        "recurrenceCount": 0,
        "correlatedService": null,
        "correlationExplanation": null
      },
      "error": null
    }
  }
}
```

### 5.2 Cas de test — tous les scénarios

| Scénario | Condition | Status final | Champ renseigné |
|---|---|---|---|
| Analyse réussie | Worker OK, Ollama répond | `complete` | `result` |
| Analyzer indisponible | analyzer-service down | `failed` | `error: "gRPC connection refused"` |
| AI indisponible | ai-service down | `failed` | `error: "gRPC connection refused"` |
| Timeout Ollama | Inférence > 5min | `failed` | `error: "time limit exceeded"` |
| Job inexistant | jobId inconnu | — | `GraphQLError: Job not found` |
| Mauvais utilisateur | jobId d'un autre user | — | `GraphQLError: Job not found` |
| UUID invalide | jobId = "pas-un-uuid" | — | `GraphQLError: Job not found` |
| Sans token | Authorization absent | — | `PermissionError` |
| Token expiré | JWT > 24h | — | `PermissionError` |

### 5.3 Vérifier l'état du job en base de données

```bash
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway -c \
  "SELECT id, user_id, pod_name, namespace, status, error, created_at FROM analysis_jobs ORDER BY created_at DESC LIMIT 5;"
```

**Résultat attendu :**
```
   id   | user_id  | pod_name      | namespace | status   | error | created_at
--------+----------+---------------+-----------+----------+-------+-----------
 aaa... | bbb...   | crashloop-pod | default   | complete |       | 2026-05-17...
```

### 5.4 Vérifier la file Redis (pendant l'exécution)

```bash
docker compose exec redis redis-cli LLEN dramatiq:default.msgs
# Attendu pendant traitement : 1
# Attendu après traitement   : 0
```

### 5.5 Vérifier les logs du worker

```bash
docker compose logs gateway-worker --since 5m
```

**Attendu (succès) :**
```
{"timestamp": "...", "level": "info", "service": "gateway-worker", "event": "task_analyze_start", "job_id": "...", "pod": "crashloop-pod", "namespace": "default"}
{"timestamp": "...", "level": "info", "service": "gateway-worker", "event": "task_analyze_complete", "job_id": "..."}
```

**Attendu (échec) :**
```
{"timestamp": "...", "level": "error", "service": "gateway-worker", "event": "task_analyze_failed", "job_id": "...", "error": "..."}
```

---

## 6. Gateway GraphQL — Scan de manifest

### Ce que c'est

Avant de faire `kubectl apply`, l'utilisateur peut faire analyser son manifest YAML par PodIQ. L'IA détecte les risques de configuration **présents dans le manifest** : image avec tag `latest`, absence de resource limits (memory/CPU), absence de probes de santé, contexte de sécurité dangereux (`privileged`, `runAsRoot`), credentials en clair dans les variables d'environnement.

### Pourquoi c'est différent d'analyzeIncident

- `analyzeIncident` : analyse un pod **déjà en échec** dans le cluster
- `scanManifest` : analyse un manifest YAML **avant déploiement** (prévention)

### Implémentation

```
scanManifest(yamlContent, manifestType) — SYNCHRONE
  1. require_auth(info) → user_id
  2. invoke_grpc(ANALYZER, parse_manifest(yaml_content.strip(), manifest_type))
     → ParsedManifest{env_vars, resource_limits, probes, image, raw_config}
  3. _fetch_history(manifest_name, namespace) → [PastIncident] (Memory Engine — risques passés du même manifest)
  4. invoke_grpc(AI, scan_manifest(parsed.raw_config, related_history=history))
     → ManifestScanResult{risk_level, summary, risks[{severity, category, description, fix}]}
  5. return ManifestScanResultType
```

**Note :** Cette mutation est **synchrone** — elle attend la fin de l'inférence Ollama. Avec `--timeout 180` sur Gunicorn, la limite est de 3 minutes.

### 6.1 Test avec un manifest dangereux

```bash
MANIFEST='apiVersion: apps/v1
kind: Deployment
metadata:
  name: risky-app
spec:
  template:
    spec:
      containers:
      - name: app
        image: myapp:latest
        env:
        - name: DB_PASSWORD
          value: "hardcoded_password_123"'

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "$(python3 -c "
import json
query = '''mutation {
  scanManifest(yamlContent: \"\"\"$MANIFEST\"\"\", manifestType: \"Deployment\") {
    riskLevel
    summary
    risks { severity category description fix }
  }
}'''
print(json.dumps({'query': query}))
")"
```

**Alternative via playground :**
```graphql
mutation {
  scanManifest(
    yamlContent: """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: risky-app
spec:
  template:
    spec:
      containers:
      - name: app
        image: myapp:latest
""",
    manifestType: "Deployment"
  ) {
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

**Résultat attendu :**
```json
{
  "data": {
    "scanManifest": {
      "riskLevel": "block",
      "summary": "Le manifest présente des risques critiques : image sans tag fixe, absence de resource limits",
      "risks": [
        {
          "severity": "high",
          "category": "image_tag",
          "description": "L'image utilise le tag 'latest' — les déploiements ne sont pas reproductibles",
          "fix": "Utiliser un tag de version fixe, ex: myapp:1.2.3"
        },
        {
          "severity": "critical",
          "category": "security",
          "description": "Variable d'environnement DB_PASSWORD avec valeur en clair dans le manifest",
          "fix": "Utiliser un Secret Kubernetes et le référencer via secretKeyRef"
        }
      ]
    }
  }
}
```

### 6.2 Cas de test

| Scénario | Input | riskLevel attendu | Catégorie détectée |
|---|---|---|---|
| Manifest sain | YAML complet avec limits, probes, tag fixe | `safe` | — |
| Tag latest | `image: app:latest` | `warning` ou `block` | `image_tag` |
| Pas de memory limits | Absence de `resources.limits.memory` | `warning` | `memory` |
| Pas de CPU limits | Absence de `resources.limits.cpu` | `warning` | `resource` |
| Probe absente | Absence de `livenessProbe` / `readinessProbe` | `warning` | `probe` |
| Privileged mode | `securityContext.privileged: true` | `block` | `security` |
| Secret en clair | Env var avec valeur password en clair **dans le manifest** | `block` | `sensitive_credentials` |
| YAML invalide | Contenu non parseable | GraphQLError: YAML parsing failed | — |
| yaml_content vide | `""` | GraphQLError | — |
| manifestType absent | — (optionnel) | Analyse avec type autodétecté | — |
| Sans token | — | PermissionError | — |

---

## 7. Gateway GraphQL — Historique d'analyses

### Ce que c'est

Permet de consulter les analyses précédentes d'un pod. Utile pour comprendre si un incident est récurrent et voir comment il a été résolu dans le passé.

### Implémentation

```
analysisHistory(podName, namespace, limit=10) — SYNCHRONE
  1. require_auth(info) → user_id
  2. invoke_grpc(AI, get_history(pod_name, namespace, limit))
     → HistoryResponse{items: [HistoryItem{id, error_type, root_cause, solution,
                                           confidence, is_recurring, recurrence_count,
                                           created_at (unix timestamp)}]}
  3. Convertit chaque created_at unix → ISO 8601
     ex: 1747468800 → "2026-05-17T08:00:00"
  4. return [AnalysisHistoryItem]
```

**Note architecture :** L'historique est stocké dans **postgres-ai** (dans la table `analyses`), pas dans postgres-gateway. Le Gateway délègue la lecture à l'ai-service via gRPC — il ne lit jamais directement la base d'un autre service.

### 7.1 Test

```graphql
query {
  analysisHistory(podName: "crashloop-pod", namespace: "default", limit: 5) {
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
  }
}
```

**Résultat attendu (après au moins une analyse complète) :**
```json
{
  "data": {
    "analysisHistory": [
      {
        "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "podName": "crashloop-pod",
        "namespace": "default",
        "errorType": "CrashLoopBackOff",
        "rootCause": "Memory limit too low",
        "solution": "Increase memory limits",
        "confidence": "high",
        "isRecurring": false,
        "recurrenceCount": 1,
        "createdAt": "2026-05-17T08:00:00"
      }
    ]
  }
}
```

### 7.2 Cas de test

| Scénario | Condition | Résultat attendu |
|---|---|---|
| Historique existant | Analyses passées pour ce pod | Liste triée desc par date |
| Pod sans historique | Premier incident | `[]` (liste vide) |
| limit=1 | — | Maximum 1 entrée |
| limit=100 | — | Toutes les entrées (max 100) |
| Sans token | — | `PermissionError` |
| namespace différent | Même pod, autre namespace | Résultats filtrés au namespace |

---

## 8. Endpoint REST CI/CD

### Ce que c'est

Un endpoint HTTP REST (pas GraphQL) dédié aux pipelines CI/CD automatisés. Il permet à un script de vérifier un manifest YAML **avant le déploiement** et de bloquer le pipeline si des risques critiques sont détectés.

**Différence avec scanManifest GraphQL :**
- GraphQL : utilisateurs humains, authentification JWT
- REST : pipelines automatisés, authentification par API Key (`X-Api-Key`)
- Les exit codes (0/1/2) sont directement utilisables dans un `exit $?` shell

### Principe de fonctionnement

```
POST /api/v1/cicd/scan
  1. Lit X-Api-Key header
     → Si absent : 401 PODIQ_TOKEN_MISSING
  2. auth_client.validate_api_key(raw_key)
     → Si invalid/révoquée : 401 PODIQ_TOKEN_INVALID
     → Si auth-service down : 502 PODIQ_AUTH_GRPC_ERROR
  3. Parse le body JSON {"yaml_content": "...", "manifest_type": "..."}
     → Si JSON invalide : 400 PODIQ_VALIDATION_ERROR
     → Si yaml_content absent/vide : 400 PODIQ_VALIDATION_ERROR
  4. analyzer_client.parse_manifest(yaml_content.strip(), manifest_type)
     → Si analyzer down : 502 PODIQ_ANALYZER_GRPC_ERROR
  5. ai_client.scan_manifest(parsed.raw_config, related_history=[])
     → Si AI down : 502 PODIQ_AI_GRPC_ERROR
  6. _RISK_TO_EXIT = {"safe": 0, "warning": 1, "block": 2}
  7. Retourne 200 {"exit_code": N, "risk_level": "...", "summary": "...", "risks": [...]}
```

### 8.1 Préparation — Créer une API Key

La mutation `createApiKey` est exposée en GraphQL (requiert un JWT valide) :

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

```bash
TOKEN="<votre token JWT>"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "mutation { createApiKey(name: \"github-actions-prod\") { keyId rawKey name createdAt } }"}'
```

**Résultat attendu :**
```json
{
  "data": {
    "createApiKey": {
      "keyId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "rawKey": "podiq_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "github-actions-prod",
      "createdAt": "2026-05-17T08:00:00"
    }
  }
}
```

**Important — `rawKey` est retourné une seule fois** : il n'est jamais stocké en clair. Seul le hash SHA-256 est conservé en base. Sauvegarder la valeur immédiatement.

### 8.2 Test du cas nominal (manifest sain)

```bash
API_KEY="podiq-dev-key-xxxxxxxx"  # pragma: allowlist secret

curl -s -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_content": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: safe-app\nspec:\n  template:\n    spec:\n      containers:\n      - name: app\n        image: myapp:1.2.3\n        resources:\n          limits:\n            memory: 256Mi\n            cpu: 500m",
    "manifest_type": "Deployment"
  }'
```

**Résultat attendu :**
```json
{
  "exit_code": 0,
  "risk_level": "safe",
  "summary": "No critical issues detected. Deployment configuration follows best practices.",
  "risks": []
}
```

### 8.3 Test du cas bloquant (manifest dangereux)

```bash
curl -s -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_content": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: risky\nspec:\n  template:\n    spec:\n      containers:\n      - name: app\n        image: app:latest\n        securityContext:\n          privileged: true",
    "manifest_type": "Deployment"
  }'
```

**Résultat attendu :**
```json
{
  "exit_code": 2,
  "risk_level": "block",
  "summary": "Critical security risks detected. Deployment blocked.",
  "risks": [
    {
      "severity": "critical",
      "category": "security",
      "description": "Container runs in privileged mode — full host access",
      "fix": "Remove securityContext.privileged: true"
    }
  ]
}
```

### 8.4 Intégration dans un pipeline shell

```bash
#!/bin/bash
set -e

RESULT=$(curl -s -X POST http://gateway:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $PODIQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"yaml_content\": \"$(cat deployment.yaml | jq -Rs .)\", \"manifest_type\": \"Deployment\"}")

EXIT_CODE=$(echo "$RESULT" | jq '.exit_code')
SUMMARY=$(echo "$RESULT" | jq -r '.summary')

echo "PodIQ scan result: $SUMMARY"
echo "Exit code: $EXIT_CODE"

if [ "$EXIT_CODE" -eq 2 ]; then
  echo "DEPLOYMENT BLOCKED by PodIQ — critical risks detected"
  echo "$RESULT" | jq '.risks[]'
  exit 1
fi
```

### 8.5 Cas de test exhaustifs

| Scénario | Input | HTTP Code | exit_code | code JSON |
|---|---|---|---|---|
| Manifest sain | YAML correct, key valide | 200 | 0 | — |
| Manifest warning | YAML avec best-practice warning | 200 | 1 | — |
| Manifest bloquant | YAML avec risques critiques | 200 | 2 | — |
| API Key absente | Pas de header X-Api-Key | 401 | — | `PODIQ_TOKEN_MISSING` |
| API Key invalide | Clé inconnue en base | 401 | — | `PODIQ_TOKEN_INVALID` |
| API Key révoquée | is_active=False | 401 | — | `PODIQ_TOKEN_INVALID` |
| Body non JSON | body = `"texte brut"` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| yaml_content absent | `{}` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| yaml_content vide | `{"yaml_content": ""}` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| manifest_type absent | Champ optionnel omis | 200 | dépend de l'IA | — |
| Méthode GET | GET au lieu de POST | 405 | — | Django 405 |
| Analyzer down | analyzer-service arrêté | 502 | — | `PODIQ_ANALYZER_GRPC_ERROR` |
| AI down | ai-service arrêté | 502 | — | `PODIQ_AI_GRPC_ERROR` |
| Auth down | auth-service arrêté | 502 | — | `PODIQ_AUTH_GRPC_ERROR` |

### 8.6 Tester les cas d'erreur

```bash
# Token manquant
curl -v -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "test"}'
# Attendu : HTTP 401, {"code": "PODIQ_TOKEN_MISSING", "message": "Missing X-Api-Key header"}

# Token invalide
curl -v -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: clé-inexistante-12345" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "test"}'
# Attendu : HTTP 401, {"code": "PODIQ_TOKEN_INVALID", ...}

# Body JSON invalide
curl -v -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d 'pas du json'
# Attendu : HTTP 400, {"code": "PODIQ_VALIDATION_ERROR", ...}

# Tester avec auth-service arrêté
docker compose stop auth-service
curl -v -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "test"}'
# Attendu : HTTP 502, {"code": "PODIQ_AUTH_GRPC_ERROR", ...}
docker compose start auth-service
```

---

## 9. Worker Dramatiq — Pipeline async

### Ce que c'est

Le `gateway-worker` est un processus Dramatiq séparé du gateway HTTP. Il consomme les messages de la file Redis et exécute le pipeline d'analyse complet en arrière-plan. Il partage le même code que le gateway (même image Docker, même `DATABASE_URL`), mais démarre avec une commande différente.

### Architecture du worker

```
docker compose run: ["python", "-m", "dramatiq", "worker_main", "--processes", "2", "--threads", "4"]
                                                      ▲
                                            worker_main.py :
                                              1. django.setup()          ← résout AppRegistryNotReady
                                              2. JobFailureMiddleware     ← marque FAILED après retries épuisés
                                              3. import app.tasks         ← enregistre analyze_incident_task
                                            → configure RedisBroker
                                            → attend des messages
```

### Broker en tests vs production

| Environnement | REDIS_URL | Broker | Comportement |
|---|---|---|---|
| Tests unitaires | `""` (vide dans settings_pytest.py) | `StubBroker` | Le task est appelé directement, sans Redis |
| Docker dev | `redis://redis:6379/0` | `RedisBroker` | Messages dans Redis, worker séparé |

### 9.1 Vérifier que le worker tourne

```bash
docker compose ps gateway-worker
# Attendu : status "running"

docker compose logs gateway-worker --tail 20
# Attendu : "dramatiq: Worker(processes=2, threads=4) is ready"
```

### 9.2 Tester la résilience — worker arrêté pendant une analyse

```bash
# 1. Déclencher une analyse
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"test\", namespace: \"default\") { jobId } }"}'

# 2. Arrêter le worker IMMÉDIATEMENT
docker compose stop gateway-worker

# 3. Vérifier le statut — le message est dans Redis, pas encore consommé
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"query { analysisJob(jobId: \\\"$JOB_ID\\\") { status } }\"}"
# Attendu : status="pending" (pas encore pris en charge)

docker compose exec redis redis-cli LLEN dramatiq:default.msgs
# Attendu : 1 (message en attente)

# 4. Redémarrer le worker
docker compose start gateway-worker

# 5. Poller jusqu'à completion
# Le worker récupère le message et traite le job
```

### 9.3 Tester max_retries=2 (3 tentatives au total)

Le décorateur `@dramatiq.actor(max_retries=2)` signifie que si le task lève une exception, Dramatiq le retentera jusqu'à 2 fois (3 tentatives au total) avec un délai exponentiel.

**Comportement de l'état du job pendant les retries :**
- Au démarrage de chaque tentative : `status=running`, `error=""` (effacé)
- Si la tentative échoue : `status=failed`, `error="<message>"`
- Si Dramatiq relance : `status=running`, `error=""` (effacé à nouveau)
- Après épuisement des retries : `status=failed`, `error="..."` (définitif via `JobFailureMiddleware`)

> **Note :** Il est normal de voir temporairement `status=running` **avec** un champ `error` non vide si une tentative précédente a échoué et qu'un retry vient de démarrer. Ce n'est pas un bug — c'est l'état entre le moment où le retry commence (status → running, error → "") et l'écriture en base. Après le fix `job.error=""`, l'état intermédiaire n'expose plus l'erreur précédente.

```bash
# Arrêter l'AI service pour simuler une erreur persistante
docker compose stop ai-service

# Déclencher une analyse
# ...

# Observer les logs du worker
docker compose logs -f gateway-worker
# Attendu :
# Tentative 1 : "task_analyze_start" → exception → "task_analyze_failed"
# Tentative 2 : (après délai) même chose
# Tentative 3 : (après délai) même chose
# Après 3 échecs : JobFailureMiddleware → job.status=FAILED définitif

docker compose start ai-service
```

### 9.4 Vérifier la persistance après redémarrage du worker

Les messages Dramatiq sont persistés dans Redis avec `appendonly yes` (configuré dans docker-compose). Si le worker redémarre avant de traiter un message, ce message reste dans Redis et sera traité au redémarrage.

```bash
# Confirmer que Redis persiste les données
docker compose restart gateway-worker
docker compose logs gateway-worker --tail 5
# Le worker reprend le traitement des messages en attente
```

---

## 10. Namespace Correlation — Corrélation temporelle

### Ce que c'est

Quand un pod est en échec, d'autres pods du même namespace sont peut-être tombés juste avant. Si `db-service` crashe 30 secondes avant `api-service`, ce n'est probablement pas une coïncidence. Cette fonctionnalité enrichit l'analyse avec un **contexte de namespace** pour que l'IA puisse détecter ces relations causales.

### Implémentation (gateway/app/namespace_correlation.py)

```
build_namespace_context(ns_snapshot, target_pod_name) → [PodContext]
  Pour chaque pod dans ns_snapshot.pods (sauf le pod cible) :
    1. Vérifie si le pod a eu des erreurs récentes
    2. Calcule seconds_before_reference = incident_ts - pod_error_ts
    3. in_correlation_window = abs(seconds_before_reference) < CORRELATION_WINDOW_SECONDS
       (CORRELATION_WINDOW_MINUTES * 60, défaut 15 minutes)
    4. Retourne PodContext{pod_name, in_correlation_window, seconds_before_reference, error_timestamp}
```

**Variable d'environnement :** `CORRELATION_WINDOW_MINUTES` (défaut `15` dans settings.py).

### Ce que l'IA fait avec ce contexte

Le contexte de namespace est injecté dans le prompt Ollama. L'IA peut alors répondre :
- `correlated_service: "db-service"` — ce service était en échec au même moment
- `correlation_explanation: "db-service a crashé 45 secondes avant api-service, causant probablement la dépendance manquante"`

### Test avec STUB_MODE

En `STUB_MODE=true`, l'analyzer-service génère des données fictives. Le namespace snapshot contiendra des pods simulés avec des timestamps d'erreur fictifs — idéal pour tester la corrélation sans vrai cluster.

```bash
# Vérifier la configuration
docker compose exec gateway python manage.py shell -c "
from django.conf import settings
print('CORRELATION_WINDOW_MINUTES:', getattr(settings, 'CORRELATION_WINDOW_MINUTES', 15))
"

# Après une analyse complète, vérifier si une corrélation a été détectée
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"query { analysisJob(jobId: \\\"$JOB_ID\\\") { result { correlatedService correlationExplanation } } }\"}"
```

---

## 11. Memory Engine — Incidents récurrents

### Ce que c'est

À chaque analyse complète, l'ai-service **mémorise** le résultat dans deux tables :
- `analyses` : chaque analyse individuelle (historique complet)
- `incident_patterns` : compteur de récurrence par `(pod_name, namespace, error_type)` — **upsert** à chaque analyse

Lors de la prochaine analyse du même pod, le gateway récupère cet historique via `get_history()` et l'injecte dans le prompt Ollama. L'IA peut alors répondre "oui, ce pod a déjà eu ce problème 3 fois" et adapter sa solution.

### Implémentation dans ai-service

```
AnalyzeIncident(request):
  ...analyse et obtient result...
  _save_analysis(result, request)  → INSERT dans analyses
  _upsert_pattern(result, request) → INSERT ... ON CONFLICT (pod_name, namespace, error_type)
                                      DO UPDATE SET occurrence_count = occurrence_count + 1,
                                                    last_seen = now(),
                                                    last_solution = result.solution
  result.is_recurring = (occurrence_count > 1)
  result.recurrence_count = occurrence_count
```

### Test de la récurrence

```bash
# 1. Analyser le même pod 2 fois

# Première analyse
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"recurring-pod\", namespace: \"default\") { jobId } }"}'

# Attendre completion puis vérifier
# isRecurring attendu : false, recurrenceCount : 1

# Deuxième analyse (même pod, même namespace)
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"recurring-pod\", namespace: \"default\") { jobId } }"}'

# Attendre completion puis vérifier
# isRecurring attendu : true, recurrenceCount : 2
```

### Vérifier en base ai-service

```bash
docker compose exec postgres-ai psql -U podiq -d podiq_ai -c \
  "SELECT pod_name, namespace, error_type, occurrence_count, first_seen, last_seen
   FROM incident_patterns
   ORDER BY occurrence_count DESC LIMIT 10;"
```

### Vérifier l'historique via GraphQL

```graphql
query {
  analysisHistory(podName: "recurring-pod", namespace: "default", limit: 10) {
    errorType
    isRecurring
    recurrenceCount
    createdAt
  }
}
```

**Résultat attendu (après 2 analyses) :**
```json
[
  {"errorType": "CrashLoopBackOff", "isRecurring": true, "recurrenceCount": 2, "createdAt": "..."},
  {"errorType": "CrashLoopBackOff", "isRecurring": false, "recurrenceCount": 1, "createdAt": "..."}
]
```

---

## 12. Observabilité — Grafana + Loki

### Ce que c'est

Tous les services PodIQ émettent des logs structurés JSON (via `structlog`). Promtail collecte ces logs depuis le socket Docker et les envoie à Loki. Grafana expose un dashboard de visualisation.

### Structure d'un log structlog

```json
{
  "timestamp": "2026-05-17T08:00:00.123456Z",
  "level": "info",
  "service": "gateway-worker",
  "event": "task_analyze_complete",
  "job_id": "aaa-bbb-ccc",
  "pod": "crashloop-pod",
  "namespace": "default"
}
```

### 12.1 Démarrer la stack observabilité

```bash
docker compose up -d loki promtail grafana

# Attendre que Loki soit healthy
docker compose logs loki | grep "started"
```

### 12.2 Accéder à Grafana

```
URL : http://localhost:3000
Login : admin
Password : valeur de GRAFANA_ADMIN_PASSWORD dans .env
```

### 12.3 Vérifier le dashboard podiq-overview

1. Menu → **Dashboards** → dossier **PodIQ** → **PodIQ — Vue d'ensemble**
2. Sélectionner un intervalle de temps (ex: "Last 1 hour")

**Panels à vérifier :**

**Section Pipeline d'analyse**

| Panel | LogQL utilisé | Ce qu'on cherche |
|---|---|---|
| Jobs démarrés | `event="task_analyze_start"` | ≥ 1 après une analyse |
| Analyses complètes | `event="task_analyze_complete"` | = Jobs démarrés si tout va bien |
| Analyses échouées | `event="task_analyze_failed"` | 0 (fond rouge si > 0) |
| Incidents récurrents | `event="task_analyze_complete" \| is_recurring="true"` | Compte des récurrences détectées |
| Pipeline (events) | `event=~"task_analyze.*"` (timeseries par event) | Courbes start/complete/failed |
| Flux analyse | `event=~"task_analyze.*"` (logs défilants) | Détail des événements worker |

**Section Santé des services**

| Panel | LogQL utilisé | Ce qu'on cherche |
|---|---|---|
| Erreurs (tous services) | `level="ERROR"` | 0 (fond rouge si > 0) |
| Erreurs gRPC | `event="grpc_call_failed"` | Fond jaune si > 0, rouge si > 3 |
| Timeouts Ollama | `event="ollama_timeout"` | 0 attendu (fond orange si > 0) |
| JWT invalides | `event="jwt_invalid"` | 0 attendu (fond rouge si > 0) |
| Erreurs gRPC par service | `event="grpc_call_failed"` (timeseries par service) | Identifier quel service échoue |
| Ollama req/timeouts | `event=~"ollama_request\|ollama_response_ok\|ollama_timeout"` | Rapport req/réponses/timeouts |

**Section Auth**

| Panel | LogQL utilisé | Ce qu'on cherche |
|---|---|---|
| Événements Auth | `event=~"auth_register\|auth_login\|jwt_invalid"` (timeseries) | Volume d'authentifications |
| Accès refusés | `event=~"jwt_invalid\|auth_login_failed\|api_key_invalid"` (logs) | Tentatives invalides |

**Section Pre-deploy**

| Panel | LogQL utilisé | Ce qu'on cherche |
|---|---|---|
| Scans safe | `event="scan_manifest_complete" \| risk_level="safe"` | Nombre de manifests validés |
| Scans warning | `event="scan_manifest_complete" \| risk_level="warning"` | Manifests avec risques modérés |
| Scans bloqués | `event="scan_manifest_complete" \| risk_level="block"` | Manifests bloqués (critique) |
| Total scans | `event="scan_manifest_complete"` | Volume total de scans |
| Distribution | `event="scan_manifest_complete"` (timeseries par risk_level) | Évolution safe/warning/block |

> **Note :** Les panels stat affichent `0` (pas "No data") quand aucun événement ne correspond dans la période sélectionnée — c'est le comportement normal.

### 12.4 Tester la pipeline de logs

```bash
# Vérifier que les labels Promtail sont correctement appliqués
# Dans Grafana Explore → Loki :
# {namespace="podiq"}              → tous les services
# {namespace="podiq", service="gateway"} → gateway uniquement
# {namespace="podiq", service="gateway-worker"} → worker
# {namespace="podiq"} | json | level="error" → erreurs uniquement
```

### 12.5 Vérifier que les logs sont en JSON

```bash
docker compose logs gateway --tail 5
# Attendu (en mode Docker avec PODIQ_SERVICE_NAME set) :
# {"timestamp": "...", "level": "info", "service": "gateway", "event": "..."}
```

---

## 13. Tests unitaires par service

### Principe

Les tests unitaires de chaque service s'exécutent **sans Docker, sans Postgres, sans Redis**. Ils utilisent :
- **SQLite en mémoire** (`settings_pytest.py`) pour le gateway et auth-service
- **StubBroker** (REDIS_URL="") pour Dramatiq
- **unittest.mock.patch** pour remplacer tous les appels gRPC

### 13.1 Exécuter tous les tests

```bash
# Depuis la racine du dépôt
./scripts/run_all_tests.sh

# Ou individuellement :
cd services/gateway && python3 -m pytest -v
cd services/auth-service && python3 -m pytest -v
cd services/ai-service && python3 -m pytest -v
cd services/analyzer-service && python3 -m pytest -v
```

### 13.2 Tests du Gateway

**Fichiers de tests :**
```
services/gateway/tests/
  conftest.py                  — setup Django, stubs path, StubBroker
  test_mutations_analyze.py    — mutation analyzeIncident + actor Dramatiq
  test_query_job.py            — query analysisJob (polling)
  test_cicd.py                 — endpoint REST /api/v1/cicd/scan
  test_scan.py (si existant)   — mutation scanManifest
  test_history.py (si existant)— query analysisHistory
```

**Exécuter avec couverture :**
```bash
cd services/gateway
python3 -m pytest -v --tb=short 2>&1 | head -80

# Résultat attendu :
# PASSED tests/test_mutations_analyze.py::TestAnalyzeIncidentMutation::test_returns_job_id
# PASSED tests/test_mutations_analyze.py::TestAnalyzeIncidentMutation::test_returns_pending_status
# PASSED tests/test_mutations_analyze.py::TestAnalyzeIncidentMutation::test_task_is_sent_with_correct_args
# PASSED tests/test_mutations_analyze.py::TestAnalyzeIncidentTask::test_task_marks_job_complete
# PASSED tests/test_mutations_analyze.py::TestAnalyzeIncidentTask::test_task_marks_job_failed_on_exception
# PASSED tests/test_query_job.py::TestAnalysisJobQuery::test_pending_job_returns_pending_status
# PASSED tests/test_query_job.py::TestAnalysisJobQuery::test_complete_job_returns_result
# PASSED tests/test_query_job.py::TestAnalysisJobQuery::test_wrong_user_cannot_read_job
# PASSED tests/test_query_job.py::TestAnalysisJobQuery::test_unknown_job_raises_graphql_error
# PASSED tests/test_cicd.py::TestCicdAuth::...
# ...
# XX passed in X.XXs
```

**Ce que teste `test_mutations_analyze.py` :**
- `test_returns_job_id` : la mutation retourne un jobId (UUID du job créé)
- `test_returns_pending_status` : le statut initial est "pending"
- `test_result_is_none_while_pending` : result=null au retour de la mutation
- `test_error_is_none_while_pending` : error=null au retour de la mutation
- `test_returns_created_at` : created_at est renseigné
- `test_task_is_sent_with_correct_args` : le task Dramatiq est appelé avec `(job_id, user_id, pod_name, namespace)`
- `test_job_created_with_user_pod_namespace` : AnalysisJob.objects.create reçoit les bons args
- `test_task_marks_job_complete` : après exécution complète, job.status=COMPLETE et job.result contient les champs attendus
- `test_task_stores_full_result_fields` : confidence, is_recurring, recurrence_count sont présents dans result
- `test_task_marks_job_failed_on_exception` : si gRPC lève une exception, job.status=FAILED et job.error contient le message

**Ce que teste `test_query_job.py` :**
- `test_pending_job_returns_pending_status` : statut pending retourné correctement
- `test_running_job_returns_running_status` : statut running retourné correctement
- `test_complete_job_returns_result` : résultat désérialisé depuis le JSON du job
- `test_failed_job_returns_error` : error retourné, result=null
- `test_job_id_in_response` : le jobId retourné correspond au job créé
- `test_unknown_job_raises_graphql_error` : UUID inconnu → GraphQLError("Job not found")
- `test_wrong_user_cannot_read_job` : autre userId → GraphQLError("Job not found")
- `test_invalid_uuid_raises_graphql_error` : UUID non valide → GraphQLError("Job not found")
- `test_complete_job_correlated_service_is_set` : correlated_service et correlation_explanation désérialisés
- `test_raises_permission_error_without_token` : absence de header → PermissionError

### 13.3 Tests du CI/CD (test_cicd.py)

**Catégories testées :**
- `TestCicdAuth` : token manquant, token invalide, token révoqué (valid=False)
- `TestCicdInputValidation` : body non-JSON, yaml_content absent, yaml_content vide, method GET
- `TestCicdScanResults` : exit_code 0/1/2 selon risk_level, champs summary et risks retournés, appels gRPC corrects avec bons arguments, gRPC errors → 502

### 13.4 Tests dans Docker

```bash
docker compose run --rm --no-deps gateway python -m pytest -v
docker compose run --rm --no-deps auth-service python -m pytest -v
docker compose run --rm --no-deps ai-service python -m pytest -v
docker compose run --rm --no-deps analyzer-service python -m pytest -v
```

---

## 14. Scénarios end-to-end complets

Ces scénarios nécessitent la **stack complète** démarrée (avec `STUB_MODE=true` si pas de cluster Kubernetes).

### Préparer les variables

```bash
# S'inscrire et stocker le token
RESPONSE=$(curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { register(email: \"e2e@podiq.io\", password: \"Test1234!\") { token } }"}')
TOKEN=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['register']['token'])")
echo "Token : $TOKEN"
```

---

### Scénario A — Premier incident, pod inconnu

**Objectif :** Analyser un pod pour la première fois. L'IA n'a aucun historique — elle traite l'incident comme nouveau.

**Résultat attendu :**
- `isRecurring: false`
- `recurrenceCount: 1`
- Un enregistrement dans `incident_patterns` avec `occurrence_count=1`

```bash
# 1. Déclencher
RESP=$(curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"new-pod\", namespace: \"staging\") { jobId } }"}')
JOB_ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['analyzeIncident']['jobId'])")
echo "Job ID : $JOB_ID"

# 2. Attendre completion (poller toutes les 5s)
for i in {1..24}; do
  STATUS=$(curl -s -X POST http://localhost:8080/graphql \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"query { analysisJob(jobId: \\\"$JOB_ID\\\") { status } }\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['analysisJob']['status'])")
  echo "[$i] Status: $STATUS"
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done

# 3. Lire le résultat complet
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"query { analysisJob(jobId: \\\"$JOB_ID\\\") { status result { errorType rootCause solution confidence isRecurring recurrenceCount } error } }\"}" \
  | python3 -m json.tool

# 4. Vérifier la base ai-service
docker compose exec postgres-ai psql -U podiq -d podiq_ai \
  -c "SELECT pod_name, namespace, error_type, occurrence_count FROM incident_patterns WHERE pod_name='new-pod';"
```

---

### Scénario B — Incident récurrent (même pod, 2ème fois)

**Objectif :** Démontrer que le Memory Engine détecte la récurrence.

```bash
# Re-analyser le même pod
RESP=$(curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"new-pod\", namespace: \"staging\") { jobId } }"}')
JOB_ID2=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['analyzeIncident']['jobId'])")

# Attendre et vérifier
# ...

# Résultat attendu sur la 2ème analyse :
# isRecurring: true
# recurrenceCount: 2
# La solution de l'IA devrait mentionner le pattern récurrent

# Vérifier l'historique
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "query { analysisHistory(podName: \"new-pod\", namespace: \"staging\", limit: 5) { isRecurring recurrenceCount createdAt } }"}' \
  | python3 -m json.tool
```

---

### Scénario C — Pipeline CI/CD qui bloque un déploiement

**Objectif :** Intégration CI/CD complète — manifest dangereux détecté et pipeline stoppé.

```bash
# Créer l'API Key (voir section 8.1)
# ...

# Tester avec manifest critique
RESULT=$(curl -s -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "yaml_content": "apiVersion: v1\nkind: Pod\nmetadata:\n  name: danger-pod\nspec:\n  containers:\n  - name: app\n    image: myapp:latest\n    securityContext:\n      runAsRoot: true\n      privileged: true",
    "manifest_type": "Pod"
  }')

echo $RESULT | python3 -m json.tool
EXIT_CODE=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin)['exit_code'])")
echo "Exit code : $EXIT_CODE"

# Résultat attendu :
# exit_code: 2
# risk_level: "block"
# risks contient des items severity=critical
```

---

### Scénario D — Scan de manifest puis analyse d'incident

**Objectif :** Workflow complet prédéploiement → incident → analyse.

```bash
# 1. Scanner le manifest avant déploiement
curl -s -X POST http://localhost:8080/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { scanManifest(yamlContent: \"apiVersion: apps/v1\\nkind: Deployment\\n...\") { riskLevel summary } }"}' \
  | python3 -m json.tool

# 2. Si safe → déployer (dans un vrai cluster)
# kubectl apply -f manifest.yaml

# 3. Le pod crashe malgré tout → analyser
# ... (voir scénario A)
```

---

## 15. Matrice des cas de test

### Auth

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| A01 | register | email unique + password | token JWT + userId | Critique |
| A02 | register | email déjà utilisé | GraphQLError | Critique |
| A03 | login | credentials corrects | nouveau token JWT | Critique |
| A04 | login | mauvais password | GraphQLError | Critique |
| A05 | Token JWT | mutation protégée sans token | PermissionError | Critique |
| A06 | Token JWT | token expiré | PermissionError | Critique |
| A07 | Token JWT | token invalide | PermissionError | Critique |
| A08 | API Key | clé valide → CI/CD | 200 + exit_code | Critique |
| A09 | API Key | clé révoquée → CI/CD | 401 PODIQ_TOKEN_INVALID | Critique |

### Analyse d'incident

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| I01 | analyzeIncident | pod + namespace valides | jobId + status=pending | Critique |
| I02 | analysisJob poll | pendant exécution | status=running | Haute |
| I03 | analysisJob poll | après succès | status=complete + result complet | Critique |
| I04 | analysisJob poll | après échec gRPC | status=failed + error | Critique |
| I05 | analysisJob | jobId inconnu | GraphQLError "Job not found" | Haute |
| I06 | analysisJob | jobId d'un autre user | GraphQLError "Job not found" | Critique |
| I07 | analysisJob | UUID invalide | GraphQLError "Job not found" | Haute |
| I08 | Memory Engine | 1ère analyse | isRecurring=false, recurrenceCount=1 | Haute |
| I09 | Memory Engine | 2ème analyse même pod | isRecurring=true, recurrenceCount=2 | Haute |
| I10 | Corrélation NS | pods correlés dans fenêtre | correlatedService renseigné | Haute |

### Scan de manifest

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| S01 | scanManifest | YAML sain | riskLevel=safe | Critique |
| S02 | scanManifest | YAML avec warning | riskLevel=warning | Critique |
| S03 | scanManifest | YAML critique | riskLevel=block | Critique |
| S04 | scanManifest | YAML invalide | GraphQLError | Haute |
| S05 | scanManifest | yaml_content vide | GraphQLError | Haute |
| S06 | scanManifest | manifestType absent | analyse autodétectée | Moyenne |

### CI/CD REST

| ID | Fonctionnalité | Input | HTTP | exit_code | Criticité |
|---|---|---|---|---|---|
| C01 | /api/v1/cicd/scan | clé valide, manifest safe | 200 | 0 | Critique |
| C02 | /api/v1/cicd/scan | clé valide, manifest warning | 200 | 1 | Critique |
| C03 | /api/v1/cicd/scan | clé valide, manifest block | 200 | 2 | Critique |
| C04 | /api/v1/cicd/scan | X-Api-Key absent | 401 | — | Critique |
| C05 | /api/v1/cicd/scan | clé invalide | 401 | — | Critique |
| C06 | /api/v1/cicd/scan | body JSON invalide | 400 | — | Haute |
| C07 | /api/v1/cicd/scan | yaml_content absent | 400 | — | Haute |
| C08 | /api/v1/cicd/scan | analyzer down | 502 | — | Haute |
| C09 | /api/v1/cicd/scan | ai down | 502 | — | Haute |
| C10 | /api/v1/cicd/scan | méthode GET | 405 | — | Moyenne |

### Résilience

| ID | Fonctionnalité | Condition | Résultat attendu | Criticité |
|---|---|---|---|---|
| R01 | Worker Dramatiq | worker arrêté, redémarré | message Redis consommé au redémarrage | Critique |
| R02 | Worker Dramatiq | ai-service down | job failed après 3 tentatives | Haute |
| R03 | Worker Dramatiq | max_retries=2 atteint | job status=failed définitif | Haute |
| R04 | Gateway | auth-service down | GraphQLError auth unavailable | Haute |

---

## 16. Dépannage rapide

### Le playground GraphQL retourne du HTML au lieu de JSON

**Cause probable :** Worker Gunicorn tué par timeout (analyse synchrone longue).
```bash
docker compose logs gateway | grep "WORKER TIMEOUT"
# Si oui : vérifier que --timeout 180 est bien dans le Dockerfile gateway
# et reconstruire : docker compose build --no-cache gateway && docker compose up -d gateway
```

### Status du job reste "pending" indéfiniment

**Cause probable :** Le gateway-worker ne tourne pas, ou Redis est inaccessible.
```bash
docker compose ps gateway-worker
docker compose logs gateway-worker --tail 20
docker compose exec redis redis-cli ping  # doit retourner PONG
docker compose exec redis redis-cli LLEN dramatiq:default.msgs  # nb de messages en attente
```

### Status du job reste "running" indéfiniment

**Cause probable :** Ollama en train d'inférer (peut prendre 2-5min sur CPU), ou processus bloqué.
```bash
docker compose logs ai-service --tail 20  # vérifier si Ollama répond
docker compose logs gateway-worker --tail 20
```

### Status "running" avec champ `error` non vide

**C'est normal** : cela indique qu'une tentative précédente a échoué (ex: timeout Ollama) et qu'un retry est en cours. Avec `max_retries=2`, le job a jusqu'à 3 tentatives. Le champ `error` est effacé à chaque nouveau démarrage de tentative.

```bash
# Vérifier dans les logs si un retry est en cours
docker compose logs gateway-worker --tail 20 | grep task_analyze
# Attendu si retry en cours : task_analyze_start sans task_analyze_complete récent
# Attendu si échec définitif : status="failed" en base
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, status, error, created_at FROM analysis_jobs ORDER BY created_at DESC LIMIT 3;"
```

### Erreur "collect 0 items" dans les tests unitaires

```bash
# Vérifier que PYTHONPATH pointe vers le bon endroit
cd services/gateway && python3 -m pytest -v --collect-only

# Si le dossier tests/ n'existe pas dans l'image :
docker compose build --no-cache gateway
docker compose run --rm --no-deps gateway python -m pytest -v tests/
```

### Logs non visibles dans Grafana

```bash
# Vérifier que Promtail collecte les logs
docker compose logs promtail | grep -i "error"
# Vérifier que les conteneurs ont bien le préfixe "podiq-"
docker ps --format "{{.Names}}" | grep podiq

# Test direct de l'API Loki
curl -s http://localhost:3100/ready
# Attendu : "ready"

curl -s "http://localhost:3100/loki/api/v1/query?query={namespace=\"podiq\"}" | python3 -m json.tool
```

### Erreur "grpc_message: timed out"

```bash
# Vérifier le timeout Ollama
docker compose exec ai-service env | grep AI_TIMEOUT
# Si vide, la valeur par défaut code est 30s — peut être trop court

# Dans .env, augmenter :
AI_TIMEOUT_SECONDS=120
docker compose up -d ai-service

# Vérifier que le modèle Ollama est disponible
docker compose exec ollama ollama list
# Si vide : docker compose exec ollama ollama pull mistral
```

### Tester la connectivité gRPC entre services

```bash
# Depuis le gateway, vérifier la connexion à auth-service
docker compose exec gateway python -c "
import grpc
from stubs.auth import auth_pb2_grpc, auth_pb2
channel = grpc.insecure_channel('auth-service:50051')
stub = auth_pb2_grpc.AuthServiceStub(channel)
try:
    resp = stub.Login(auth_pb2.LoginRequest(email='x', password='x'), timeout=5)
except grpc.RpcError as e:
    print(f'gRPC status: {e.code()} — {e.details()}')
"
# Si grpc.StatusCode.UNAUTHENTICATED → auth-service répond (credentials incorrects, normal)
# Si grpc.StatusCode.UNAVAILABLE    → auth-service ne répond pas
```
