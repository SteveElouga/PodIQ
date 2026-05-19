# Guide de test exhaustif — PodIQ

> **Version :** Phase 16 (Auth + Workspace + Agent + Invitations + Notifications + Subscriptions)
> **Audience :** Développeurs et testeurs du projet PodIQ
> **Objectif :** Tester chaque fonctionnalité de la plateforme pas à pas, comprendre son rôle, son implémentation, et vérifier chaque cas possible avec les résultats attendus.

---

## Table des matières

1. [Vue d'ensemble de l'architecture](#1-vue-densemble-de-larchitecture)
2. [Prérequis et mise en place](#2-prérequis-et-mise-en-place)
3. [Auth Service — Authentification et API Keys](#3-auth-service--authentification-et-api-keys)
4. [Gateway GraphQL — Mutations Auth](#4-gateway-graphql--mutations-auth)
5. [Workspace — JWT en deux temps](#5-workspace--jwt-en-deux-temps)
6. [Agent — Connexion de cluster Kubernetes](#6-agent--connexion-de-cluster-kubernetes)
7. [Invitations — Gestion des membres](#7-invitations--gestion-des-membres)
8. [Alertes et Notifications](#8-alertes-et-notifications)
9. [GraphQL Subscriptions WebSocket](#9-graphql-subscriptions-websocket)
10. [Gateway GraphQL — Analyse d'incident (async)](#10-gateway-graphql--analyse-dincident-async)
11. [Gateway GraphQL — Scan de manifest](#11-gateway-graphql--scan-de-manifest)
12. [Gateway GraphQL — Historique d'analyses](#12-gateway-graphql--historique-danalyses)
13. [Endpoint REST CI/CD](#13-endpoint-rest-cicd)
14. [Worker Dramatiq — Pipeline async](#14-worker-dramatiq--pipeline-async)
15. [Namespace Correlation — Corrélation temporelle](#15-namespace-correlation--corrélation-temporelle)
16. [Memory Engine — Incidents récurrents](#16-memory-engine--incidents-récurrents)
17. [Observabilité — Grafana + Loki](#17-observabilité--grafana--loki)
18. [Tests unitaires par service](#18-tests-unitaires-par-service)
19. [Scénarios end-to-end complets](#19-scénarios-end-to-end-complets)
20. [Matrice des cas de test](#20-matrice-des-cas-de-test)
21. [Dépannage rapide](#21-dépannage-rapide)

---

## 1. Vue d'ensemble de l'architecture

### Ce que PodIQ fait

PodIQ est une plateforme d'intelligence Kubernetes : elle **analyse les incidents de pods**, **mémorise les patterns récurrents**, **prédit les risques avant déploiement** et **bloque les pipelines CI/CD dangereux**. Depuis la Phase 16, la plateforme est **multi-tenant** : chaque utilisateur appartient à un ou plusieurs **workspaces**, et chaque opération est scoped au workspace.

### Flux de données complet

```
Client (curl / playground / Angular)
        │
        ▼ HTTP/WebSocket :8080 (nginx)
   ┌────────────────────────────────┐
   │    Gateway (ASGI — Uvicorn)    │ strawberry.asgi.GraphQL
   │    :8000                       │ /graphql → WebSocket (graphql-ws)
   │                                │ Dramatiq producer
   └────┬───────────────────────────┘
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
  (analysis_jobs, workspaces, workspace_members, install_tokens,
   clusters, invitations, alert_rules, notification_channels, quiet_hours)
```

### JWT en deux temps (Phase 16)

```
Étape 1 — Authentification identité
  mutation { register } ou mutation { login }
  → retourne user-JWT signé par auth-service
    { user_id, email, exp }

Étape 2 — Sélection workspace
  mutation { selectWorkspace(workspaceId) }
  → gateway valide le user-JWT via gRPC auth-service
  → vérifie WorkspaceMember dans postgres-gateway
  → retourne workspace-JWT signé par gateway (GATEWAY_JWT_SECRET)
    { user_id, email, workspace_id, role, exp }

Toutes les opérations protégées utilisent le workspace-JWT.
require_auth() : décode localement si workspace-JWT (fast path),
                 sinon valide via gRPC auth-service (fallback).
```

### Services et ports

| Service | Protocole | Port | Base |
|---|---|---|---|
| nginx (entrée externe) | HTTP + WebSocket | 8080 | — |
| gateway | HTTP + WebSocket (ASGI) | 8000 | postgres-gateway :5432 |
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
GATEWAY_JWT_SECRET=gateway_jwt_secret_dev        # signe les workspace-JWT (1h)
GATEWAY_REFRESH_SECRET=gateway_refresh_secret_dev # signe les refresh tokens (30j)
CORS_ALLOWED_ORIGINS=http://localhost:4200        # whitelist frontend (requis pour cookies httpOnly)
OLLAMA_MODEL=mistral    # modèle recommandé
AI_TIMEOUT_SECONDS=120  # 2 min en dev CPU
```

> **Note :** `STUB_MODE` n'est **pas** à définir dans `.env` — il est géré automatiquement par le Makefile (`make up-mock` le force à `true`, `make up-cluster` le force à `false`).

### 2.3 Démarrer la stack complète

Deux modes disponibles via le Makefile :

**Mode mock (sans cluster Kubernetes) — recommandé pour débuter :**
```bash
make up-mock

# Vérifier que tous les services sont healthy
make ps

# Attendre que gateway soit healthy (peut prendre 30-60s)
make logs-gateway
# Signe de succès : "Application startup complete."  (Uvicorn ASGI)
```

**Mode cluster réel (minikube requis) :**
```bash
make cluster-start   # démarre minikube
make cluster-config  # génère le kubeconfig Docker-compatible
make up-cluster      # démarre la stack avec kubeconfig monté

make cluster-pods    # déploie les pods de test en échec
make cluster-status  # vérifie l'état des pods
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

### 2.5 Stack minimale (sans Ollama, pour tester auth + gateway + workspace)

```bash
docker compose up -d --build postgres-auth postgres-gateway auth-service gateway nginx redis
```

> Cette commande `docker compose` directe est acceptable pour la stack minimale.
> Pour la stack complète, toujours utiliser `make up-mock` ou `make up-cluster`.

---

## 3. Auth Service — Authentification et API Keys

### Ce que c'est

L'auth-service est le gardien de l'identité dans PodIQ. Il gère deux types d'authentification :
- **JWT** (JSON Web Token) pour les utilisateurs humains (frontend, CLI)
- **API Keys** pour les pipelines CI/CD automatisés

### Pourquoi c'est séparé du Gateway

Principe de séparation des responsabilités : le gateway ne stocke aucun secret, aucun hash de mot de passe. Toute décision d'authentification d'identité est déléguée à l'auth-service via gRPC. Le workspace (logique business) reste dans le gateway.

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

**Ce que ça fait :** Crée un nouvel utilisateur en base, génère un user-JWT valide 24h.

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

> **Note Phase 16 :** Le token retourné est un **user-JWT** — il contient `{user_id, email}` uniquement. Pour accéder aux opérations métier (analyzeIncident, etc.), il faut ensuite appeler `selectWorkspace` pour obtenir un **workspace-JWT** avec `{user_id, email, workspace_id, role}`.

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Inscription normale | email valide + password | token user-JWT + userId |
| Email déjà utilisé | email existant en base | `GraphQLError: email already registered` |
| Email invalide | `"pas-un-email"` | `GraphQLError` (validation côté gateway) |
| Password vide | `""` | `GraphQLError` |
| Appel sans Authorization | — (mutations publiques) | Succès — register est public |

**Vérifier le contenu du user-JWT :**
```bash
echo "<token>" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# Attendu : {"user_id": "...", "email": "alice@podiq.io", "exp": <timestamp>}
# Pas de workspace_id ni role — c'est normal pour un user-JWT
```

---

### 3.2 Login — Se connecter

**Ce que ça fait :** Vérifie les credentials, génère un nouveau user-JWT.

```graphql
mutation {
  login(email: "alice@podiq.io", password: "MotDePasse123") {  # pragma: allowlist secret
    token
    userId
    email
  }
}
```

**Résultat attendu :** Identique à register — nouveau user-JWT.

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Login correct | email + password corrects | nouveau user-JWT |
| Mauvais password | bon email, mauvais password | `GraphQLError: Invalid credentials` |
| Email inconnu | email non enregistré | `GraphQLError: Invalid credentials` |
| Auth-service down | — | `GraphQLError: auth service unavailable` |

---

### 3.3 Protection des mutations par JWT

**Ce que ça fait :** Les mutations protégées exigent un JWT valide (user-JWT ou workspace-JWT) dans le header HTTP.

**Implémentation (gateway/app/auth.py) — `require_auth(info)` :**
```
1. Extrait le header Authorization du contexte (HTTP ou WebSocket connection_params)
2. Vérifie le format "Bearer <token>"
3. Fast path : si GATEWAY_JWT_SECRET est défini et le token contient workspace_id
   → décode localement, retourne TokenContext{user_id, email, workspace_id, role}
4. Fallback : appelle auth_client.validate_jwt(token) via gRPC
   → si valid=True → retourne TokenContext{user_id, email}
   → si valid=False → lève PermissionError
   → si gRPC error → lève GraphQLError("auth service unavailable")
```

**Contextes gérés :**
- **HTTP** : `request.headers["Authorization"]`
- **WebSocket** : `connection_params["Authorization"]` (browsers ne peuvent pas envoyer des headers WS)
- **Legacy Django** : `ctx.request.headers["Authorization"]`

**Test — appel protégé sans token :**
```bash
curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { analyzeIncident(podName: \"test\", namespace: \"default\") { jobId } }"}'
# Attendu : {"data": null, "errors": [{"message": "Permission denied"}]}
```

---

### 3.4 API Keys — Pour les pipelines CI/CD

**Ce que c'est :** Les API Keys permettent à un pipeline automatisé d'appeler l'endpoint REST `/api/v1/cicd/scan` sans JWT humain.

**Principe :**
1. L'utilisateur crée une API Key via `mutation { createApiKey }` (nécessite un JWT)
2. La clé brute est retournée **une seule fois** à la création
3. Seul le hash SHA-256 est stocké en base
4. Le pipeline envoie la clé brute dans le header `X-Api-Key`
5. Si `is_active=True` et hash correspondant → accès autorisé

**Test direct :** Voir section 13.

---

## 4. Gateway GraphQL — Mutations Auth

### Pourquoi passer par le Gateway et non directement à l'auth-service ?

Le Gateway est le **seul point d'entrée externe**. Les services backend (auth, analyzer, ai) ne sont pas exposés à l'extérieur du réseau Docker.

### 4.1 Tester via le Playground Strawberry

Ouvrir `http://localhost:8080/graphql` dans un navigateur.

**Workflow complet Phase 16 :**
1. `register` → copier le `token` (user-JWT)
2. `createWorkspace` → copier l'`id`
3. `selectWorkspace(workspaceId)` → copier le nouveau `token` (workspace-JWT)
4. Ajouter `{"Authorization": "Bearer <workspace-token>"}` dans les headers HTTP du playground
5. Exécuter les mutations protégées

> **Note WebSocket :** Pour les subscriptions, le playground envoie le token via le payload `connection_init` (`{"Authorization": "Bearer <token>"}`), pas via un header HTTP — les navigateurs ne peuvent pas envoyer de headers personnalisés sur les connexions WebSocket.

---

## 5. Workspace — JWT en deux temps

### Ce que c'est

Un **workspace** est un tenant dans PodIQ. Chaque utilisateur peut appartenir à plusieurs workspaces avec des rôles différents (`admin`, `member`, `viewer`). Après `register`/`login`, l'utilisateur doit sélectionner un workspace pour obtenir un **workspace-JWT** qui donne accès à toutes les opérations métier.

### Implémentation — Modèles Django (postgres-gateway)

```
workspaces
  id            UUID (PK)
  owner_id      UUID (cross-service — pas de FK vers postgres-auth)
  name          VARCHAR(32)   [a-z0-9 -]
  slug          VARCHAR (unique global, immuable après création)
  plan          VARCHAR (free|pro|enterprise, default=free)
  region        VARCHAR (eu|us|ap)
  team_size     VARCHAR (solo|2_10|11_50|50_plus)
  accent_color  VARCHAR (#rrggbb)
  onboarded_at  TIMESTAMP (nullable)
  created_at    TIMESTAMP

workspace_members
  workspace     FK → workspaces
  user_id       UUID (cross-service)
  role          VARCHAR (admin|member|viewer)
  joined_at     TIMESTAMP
  UNIQUE(workspace, user_id)
```

### 5.1 Créer un workspace

Requiert un user-JWT ou workspace-JWT dans le header.

```graphql
mutation {
  createWorkspace(
    name: "Mon Workspace"
    slug: "mon-workspace"
    region: "eu"
    teamSize: "2_10"
  ) {
    id
    slug
    name
    plan
    region
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "createWorkspace": {
      "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "slug": "mon-workspace",
      "name": "Mon Workspace",
      "plan": "free",
      "region": "eu"
    }
  }
}
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Création normale | nom + slug valides | workspace créé, rôle admin |
| Slug déjà utilisé | slug existant en base | `GraphQLError: slug already taken` |
| Slug invalide | `"Mon Workspace!"` (majuscules/spéciaux) | `GraphQLError: validation` |
| Sans token | — | `PermissionError` |

**Vérifier en base :**
```bash
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, owner_id, name, slug, plan FROM workspaces ORDER BY created_at DESC LIMIT 3;"

docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT workspace_id, user_id, role FROM workspace_members ORDER BY joined_at DESC LIMIT 5;"
```

---

### 5.2 Sélectionner un workspace — obtenir le workspace-JWT

**Ce que ça fait :** Valide que l'utilisateur est membre du workspace, puis signe et retourne un workspace-JWT enrichi avec `workspace_id` et `role`. C'est le token à utiliser pour toutes les opérations métier.

```graphql
mutation {
  selectWorkspace(workspaceId: "uuid-du-workspace") {
    token       # workspace-JWT : {user_id, email, workspace_id, role, exp}
    workspaceId
    role
    userId
    email
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "selectWorkspace": {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "workspaceId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "role": "admin",
      "userId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "email": "alice@podiq.io"
    }
  }
}
```

**Vérifier le contenu du workspace-JWT :**
```bash
echo "<workspace-token>" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# Attendu :
# {
#   "user_id": "...",
#   "email": "alice@podiq.io",
#   "workspace_id": "...",
#   "role": "admin",
#   "exp": <timestamp>
# }
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Sélection normale | workspaceId valide, user membre | workspace-JWT avec workspace_id + role |
| Pas membre du workspace | workspaceId d'un autre tenant | `PermissionError` |
| Workspace inexistant | UUID inconnu | `GraphQLError: Workspace not found` |
| Avec user-JWT | token sans workspace_id | Succès (fallback gRPC) |
| Avec workspace-JWT | token avec workspace_id | Succès (fast path local) |
| Sans token | — | `PermissionError` |

---

### 5.3 Refresh Token — rotation httpOnly cookie

**Ce que c'est :** `selectWorkspace` (et `register`/`login`) posent un cookie httpOnly `refresh_token` en réponse. Ce cookie est inaccessible depuis JavaScript — il est envoyé automatiquement par le navigateur. La mutation `refreshToken` échange le cookie contre un nouveau workspace-JWT et rotate le cookie.

**Cookie posé automatiquement par le serveur :**
```
Set-Cookie: refresh_token=<jwt>; HttpOnly; Secure; SameSite=Strict;
            Path=/graphql; Max-Age=2592000
```

**Mutation refreshToken :**
```graphql
mutation {
  refreshToken {
    token       # nouveau workspace-JWT (1h)
    workspaceId
    role
    userId
    email
  }
}
```

> Le cookie est envoyé automatiquement par le navigateur — pas besoin de le passer manuellement.

**Via curl (simuler le cookie) :**
```bash
# Récupérer le cookie lors du selectWorkspace
curl -s -c cookies.txt -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d "{\"query\": \"mutation { selectWorkspace(workspaceId: \\\"$WS_ID\\\") { token } }\"}"

# Utiliser le cookie pour refresher le token
curl -s -b cookies.txt -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { refreshToken { token workspaceId role } }"}'
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Refresh normal | cookie refresh_token valide | nouveau workspace-JWT + nouveau cookie |
| Cookie absent | pas de cookie refresh_token | `GraphQLError: No refresh token` |
| Cookie expiré | cookie > 30j | `GraphQLError: Refresh token expired` |
| Cookie invalide | signature incorrecte | `GraphQLError` |

---

### 5.4 Lister les workspaces et workspace courant

```graphql
query {
  listWorkspaces {
    id
    name
    slug
    plan
    role
  }
}

query {
  currentWorkspace {
    id
    name
    slug
    plan
    region
  }
}
```

> `currentWorkspace` lit le `workspace_id` depuis le workspace-JWT — requiert donc un workspace-JWT (pas un user-JWT).

---

## 6. Agent — Connexion de cluster Kubernetes

### Ce que c'est

L'agent PodIQ tourne **dans** le cluster Kubernetes du client. Il s'authentifie via un `installToken` (format `wsk_xxx`) et communique avec le gateway en GraphQL-first (pas de REST). Le gateway enregistre le cluster et met à jour son statut.

**Avantage vs kubeconfig :** L'agent fait une connexion **sortante** depuis le cluster — aucun port d'API server exposé à l'extérieur.

### Implémentation — Modèles Django (postgres-gateway)

```
install_tokens
  id         UUID (PK)
  workspace  FK → workspaces
  token      VARCHAR (wsk_xxx, unique)
  expires_at TIMESTAMP
  used       BOOLEAN (default False)
  # used=True signifie "cluster enregistré", pas "token invalidé"
  # L'agent réutilise le même token indéfiniment — seule l'expiry est vérifiée

clusters
  id              UUID (PK)
  workspace       FK → workspaces
  install_token   FK → install_tokens (unique)
  name            VARCHAR
  k8s_version     VARCHAR
  status          VARCHAR (pending|connected|disconnected)
  last_heartbeat  TIMESTAMP
```

### 6.1 Générer un install token

Requiert un workspace-JWT avec rôle `admin`.

```graphql
mutation {
  generateInstallToken(workspaceId: "uuid") {
    id
    token      # wsk_xxx — à utiliser dans la commande d'installation Helm/kubectl
    expiresAt
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "generateInstallToken": {
      "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "token": "wsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "expiresAt": "2026-06-19T08:00:00+00:00"
    }
  }
}
```

---

### 6.2 Simuler un heartbeat agent

En production, l'agent binary appelle cette mutation. En dev, on la simule avec curl.

```graphql
mutation {
  agentHeartbeat(
    installToken: "wsk_xxx"
    clusterName: "prod-eu"
    k8sVersion: "1.29.3"
  ) {
    id
    name
    status
    lastHeartbeat
    k8sVersion
  }
}
```

**Via curl (sans workspace-JWT — l'agent s'authentifie via installToken) :**
```bash
INSTALL_TOKEN="wsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"mutation { agentHeartbeat(installToken: \\\"$INSTALL_TOKEN\\\", clusterName: \\\"test-cluster\\\", k8sVersion: \\\"1.29.3\\\") { id name status lastHeartbeat } }\"}" \
  | python3 -m json.tool
```

**Résultat attendu (premier heartbeat) :**
```json
{
  "data": {
    "agentHeartbeat": {
      "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "name": "test-cluster",
      "status": "connected",
      "lastHeartbeat": "2026-05-19T08:00:00+00:00"
    }
  }
}
```

**Vérifier en base :**
```bash
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, name, status, k8s_version, last_heartbeat FROM clusters ORDER BY last_heartbeat DESC LIMIT 3;"

# install_token.used doit être True après le premier heartbeat
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, used, expires_at FROM install_tokens ORDER BY created_at DESC LIMIT 3;"
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Premier heartbeat | token valide (used=False) | cluster créé, status=connected, used=True |
| Heartbeat suivant | même token (used=True) | `last_heartbeat` mis à jour — token réutilisable |
| Token expiré | expires_at < now | `GraphQLError: Install token expired` |
| Token inconnu | UUID aléatoire | `GraphQLError: Invalid install token` |

> **Important :** `used=True` signifie "cluster a été enregistré", **pas** "token révoqué". L'agent réutilise le même token pour tous les heartbeats ultérieurs — seule l'expiry est vérifiée.

---

### 6.3 Reporter un incident depuis l'agent

```graphql
mutation {
  agentReportIncident(
    installToken: "wsk_xxx"
    podName: "auth-api-xxxx"
    namespace: "production"
    logs: "Error: ECONNREFUSED..."
    events: "BackOff pulling image"
    describeOutput: "State: Waiting, Reason: CrashLoopBackOff"
  ) {
    jobId
    accepted
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "agentReportIncident": {
      "jobId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "accepted": true
    }
  }
}
```

> L'agent déclenche un `analyzeIncident` async — le job est créé en base et le worker Dramatiq prend le relais.

---

### 6.4 Vérifier le statut du cluster

```graphql
query {
  clusterStatus(workspaceId: "uuid") {
    id
    name
    status
    k8sVersion
    lastHeartbeat
  }
}
```

---

## 7. Invitations — Gestion des membres

### Ce que c'est

Un admin de workspace peut inviter d'autres utilisateurs par email. L'invité reçoit un lien contenant un `token` (UUID). En cliquant sur le lien, le frontend appelle `acceptInvitation(token)` et obtient directement un workspace-JWT pour le nouveau workspace.

### Implémentation — Modèle Django (postgres-gateway)

```
invitations
  id                 UUID (PK)
  workspace          FK → workspaces
  email              VARCHAR
  role               VARCHAR (admin|member|viewer)
  token              UUID (unique — c'est ce champ qui est passé à acceptInvitation)
  status             VARCHAR (pending|accepted|revoked|expired)
  invited_by_user_id UUID (cross-service)
  expires_at         TIMESTAMP (default: now + 7 jours)
  created_at         TIMESTAMP
```

> **Distinction importante :** Le champ `id` (UUID interne de l'invitation) et le champ `token` (UUID de l'invitation publique) sont **deux UUIDs différents**. `acceptInvitation` prend le **`token`**, pas l'`id`.

### 7.1 Inviter un membre

Requiert workspace-JWT avec rôle `admin`.

```graphql
mutation {
  inviteMember(
    workspaceId: "uuid-du-workspace"
    email: "bob@podiq.io"
    role: "member"
  ) {
    id       # UUID interne (pour revokeInvitation)
    token    # UUID d'invitation publique (pour acceptInvitation) ← NE PAS CONFONDRE
    email
    role
    status
    expiresAt
    createdAt
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "inviteMember": {
      "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "token": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      "email": "bob@podiq.io",
      "role": "member",
      "status": "pending",
      "expiresAt": "2026-05-26T08:00:00+00:00",
      "createdAt": "2026-05-19T08:00:00+00:00"
    }
  }
}
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Invitation normale | email + role valides | invitation pending, token retourné |
| Email déjà invité | email existant pending | ancienne invitation révoquée, nouvelle créée |
| Rôle invalide | `role: "superadmin"` | `GraphQLError: Invalid role` |
| Non admin | workspace-JWT rôle=member | `PermissionError: Only admins can invite members` |
| Sans token | — | `PermissionError` |

---

### 7.2 Accepter une invitation

**Requiert un JWT de l'invité** (user-JWT ou workspace-JWT d'un autre workspace). L'invité doit être enregistré avant d'accepter.

> **CRITIQUE :** Passer le champ **`token`** de l'invitation, **PAS** le champ `id`. Tous deux sont des UUIDs mais différents.

```graphql
mutation {
  # Utiliser invitation.token (bbbbbbbb-...), PAS invitation.id (aaaaaaaa-...)
  acceptInvitation(token: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb") {
    token       # workspace-JWT pour le nouveau workspace
    workspaceId
    role
    userId
    email
  }
}
```

**Résultat attendu :**
```json
{
  "data": {
    "acceptInvitation": {
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "workspaceId": "uuid-du-workspace",
      "role": "member",
      "userId": "uuid-de-bob",
      "email": "bob@podiq.io"
    }
  }
}
```

**Logique de rôle — upgrade-only :**
- Si Bob n'est pas encore membre → ajouté avec `role` de l'invitation
- Si Bob est déjà membre avec un rôle **inférieur** → rôle mis à jour (upgrade)
- Si Bob est déjà membre avec un rôle **supérieur** → rôle inchangé (pas de downgrade)
- Priorité : `viewer (1) < member (2) < admin (3)`

```
Exemple : Bob est admin, invitation avec role=member
→ Bob reste admin (pas de downgrade)
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Acceptation normale | token valide, user existant | workspace-JWT + status=accepted |
| Token invalide | UUID aléatoire | `GraphQLError: Invitation not found or already used` |
| Passer invitation.id au lieu de invitation.token | mauvais UUID | `GraphQLError: Invitation not found or already used` |
| Invitation déjà acceptée | status=accepted | `GraphQLError: Invitation is accepted` |
| Invitation révoquée | status=revoked | `GraphQLError: Invitation is revoked` |
| Invitation expirée | expires_at < now | `GraphQLError: Invitation expired` |
| Upgrade rôle | user viewer, invitation member | rôle mis à jour → member |
| Pas de downgrade | user admin, invitation member | rôle inchangé → admin |
| Sans token | — | `PermissionError` |

**Vérifier en base :**
```bash
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, email, status, role, token FROM invitations ORDER BY created_at DESC LIMIT 5;"

# Vérifier le rôle du membre après acceptation
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT workspace_id, user_id, role FROM workspace_members ORDER BY joined_at DESC LIMIT 5;"
```

---

### 7.3 Révoquer une invitation

Requiert workspace-JWT avec rôle `admin`. Utilise le champ `id` de l'invitation (pas le token).

```graphql
mutation {
  revokeInvitation(invitationId: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") # invitation.id
}
```

**Résultat attendu :** `true`

---

### 7.4 Générer un lien d'invitation (sans email cible)

```graphql
mutation {
  generateInviteLink(workspaceId: "uuid") {
    id
    token    # à intégrer dans l'URL frontend : /join?token=<token>
    status
    expiresAt
  }
}
```

> Lien ouvert — n'importe qui avec le token peut rejoindre le workspace (role=member par défaut).

---

### 7.5 Lister les invitations

Requiert workspace-JWT avec rôle `admin`.

```graphql
query {
  listInvitations(workspaceId: "uuid", status: "pending") {
    id
    token
    email
    role
    status
    expiresAt
    createdAt
  }
}
```

**Cas de test :**

| Scénario | Input | Résultat attendu |
|---|---|---|
| Liste normale | workspaceId valide | liste triée desc par createdAt |
| Filtrer par statut | `status: "pending"` | uniquement les invitations pending |
| Statut vide | `status: ""` | toutes les invitations |
| Non admin | rôle member | `PermissionError: Admin access required` |

---

## 8. Alertes et Notifications

### Ce que c'est

Les alertes permettent de configurer des règles de notification par événement (`crashloop`, `oom`, `predeploy_block`, `fix_found`). Les notifications sont envoyées via des canaux configurables (Slack, PagerDuty, Email, Webhook, Teams, Discord). Des plages de silence (`quiet_hours`) permettent de supprimer les notifications non-critiques la nuit.

### Implémentation — Modèles Django (postgres-gateway)

```
alert_rules
  id          UUID (PK)
  workspace   FK → workspaces
  name        VARCHAR
  event_type  VARCHAR (crashloop|oom|predeploy_block|fix_found)
  enabled     BOOLEAN (default True)
  created_at  TIMESTAMP

notification_channels
  id        UUID (PK)
  workspace FK → workspaces
  type      VARCHAR (slack|pagerduty|email|webhook|teams|discord)
  config    JSONField
  enabled   BOOLEAN

quiet_hours
  id           UUID (PK)
  workspace    FK → workspaces (unique)
  enabled      BOOLEAN
  start_time   TIME
  end_time     TIME
  timezone     VARCHAR
  weekdays_only BOOLEAN
```

### 8.1 Créer une règle d'alerte

```graphql
mutation {
  createAlertRule(
    workspaceId: "uuid"
    name: "CrashLoop Alerts"
    eventType: "crashloop"
  ) {
    id
    name
    eventType
    enabled
  }
}
```

### 8.2 Activer/désactiver une règle

```graphql
mutation {
  toggleAlertRule(ruleId: "uuid", enabled: false) {
    id
    enabled
  }
}
```

### 8.3 Connecter un canal de notification

```graphql
# Slack (Incoming Webhook — pas d'OAuth nécessaire)
mutation {
  connectChannel(
    workspaceId: "uuid"
    type: "slack"
    config: "{\"webhook_url\": \"https://hooks.slack.com/services/xxx/yyy/zzz\"}"
  ) {
    id
    type
    enabled
  }
}

# PagerDuty
mutation {
  connectChannel(
    workspaceId: "uuid"
    type: "pagerduty"
    config: "{\"routing_key\": \"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"}"
  ) {
    id
    type
    enabled
  }
}

# Webhook custom
mutation {
  connectChannel(
    workspaceId: "uuid"
    type: "webhook"
    config: "{\"url\": \"https://my-service.io/hook\", \"secret\": \"my-secret\"}"
  ) {
    id
    type
    enabled
  }
}
```

### 8.4 Configurer les plages de silence

```graphql
mutation {
  setQuietHours(
    workspaceId: "uuid"
    enabled: true
    startTime: "23:00"
    endTime: "07:00"
    timezone: "Europe/Paris"
    weekdaysOnly: false
  ) {
    id
    enabled
    startTime
    endTime
    timezone
  }
}
```

> **Note RM071 :** Les alertes `crashloop` ignorent les quiet hours — elles sont toujours envoyées (incidents P1).

### 8.5 Flux de déclenchement

```
analyze_incident_task (worker Dramatiq)
  → fin de job → status=COMPLETE
  → send_notifications_task.send(workspace_id, event_type, context)

send_notifications_task (worker Dramatiq)
  1. Vérifie AlertRule actives pour ce workspace + event_type
  2. Vérifie QuietHours — si période silencieuse ET event_type != "crashloop" → skip
  3. Pour chaque NotificationChannel enabled → dispatch_channel(channel, context)
```

---

## 9. GraphQL Subscriptions WebSocket

### Ce que c'est

Les subscriptions permettent au frontend de recevoir des mises à jour en temps réel sans polling. Elles utilisent le protocole **WebSocket (`graphql-ws`)** — pas SSE. Deux subscriptions sont disponibles :

- `clusterConnected(workspaceId)` — pousse l'événement quand l'agent envoie son premier heartbeat
- `jobStatus(jobId)` — pousse les mises à jour de statut d'un job d'analyse

### Architecture WebSocket

```
Browser / Client
    │ ws://localhost:8080/graphql
    ▼
nginx (/graphql location)
    │ WebSocket upgrade (Upgrade: websocket, Connection: upgrade)
    ▼
Gateway Uvicorn ASGI
    │ strawberry.asgi.GraphQL
    ▼
Subscription resolver
    │ DB polling async toutes les 2-3s
    ▼ yield results
Client reçoit les événements
```

**Particularités :**
- Auth via `connection_params["Authorization"]` dans le payload `connection_init` (pas un header HTTP)
- Nginx : bloc `/graphql` séparé avec `proxy_set_header Upgrade $http_upgrade`
- `uvicorn[standard]` requis — le package `websockets` est inclus dans `[standard]`

### 9.1 Tester `clusterConnected` via le playground

1. Ouvrir `http://localhost:8080/graphql`
2. Dans les headers de connexion WS, ajouter : `{"Authorization": "Bearer <workspace-JWT>"}`
3. Lancer la subscription :

```graphql
subscription {
  clusterConnected(workspaceId: "uuid-du-workspace") {
    id
    name
    status
    k8sVersion
    lastHeartbeat
  }
}
```

4. Dans un autre onglet/terminal, simuler un heartbeat agent (section 6.2)
5. La subscription doit recevoir le cluster connecté automatiquement

**Résultat attendu quand l'agent pings :**
```json
{
  "data": {
    "clusterConnected": {
      "id": "uuid",
      "name": "test-cluster",
      "status": "connected",
      "k8sVersion": "1.29.3",
      "lastHeartbeat": "2026-05-19T08:00:00+00:00"
    }
  }
}
```

### 9.2 Tester `jobStatus` via le playground

```graphql
subscription {
  jobStatus(jobId: "uuid-du-job") {
    jobId
    status
    result {
      errorType
      rootCause
      solution
      confidence
    }
    error
  }
}
```

Déclencher une analyse en parallèle (section 10.1) — la subscription poussera les transitions `pending → running → complete/failed`.

### 9.3 Tester via wscat (CLI)

```bash
npm install -g wscat

# Connexion avec auth
wscat -c "ws://localhost:8080/graphql" \
  -s "graphql-ws" \
  --header "Content-Type: application/json"

# Une fois connecté, envoyer le payload connection_init avec le token
{"type":"connection_init","payload":{"Authorization":"Bearer <workspace-JWT>"}}

# Abonnement
{"id":"1","type":"subscribe","payload":{"query":"subscription { clusterConnected(workspaceId: \"uuid\") { id name status } }"}}

# Désabonnement
{"id":"1","type":"complete"}
```

### 9.4 Cas de test

| Scénario | Input | Résultat attendu |
|---|---|---|
| Auth valide | workspace-JWT dans connection_params | subscription ouverte |
| Auth manquante | pas de connection_params | `PermissionError` fermant la connexion |
| Auth invalide | token expiré | `PermissionError` |
| Cluster connecté | agentHeartbeat appelé | événement poussé au client |
| Job terminé | analyse complète | jobStatus pousse status=complete + result |
| Déconnexion | client ferme WS | subscription proprement terminée |

### 9.5 Erreurs fréquentes

**`{isTrusted: true}` dans le playground (pas de message d'erreur) :**
```
Cause : Nginx ne forwarde pas le WebSocket upgrade
Vérifier infra/nginx/default.conf :
  - map $http_upgrade $connection_upgrade { ... } doit être présent
  - location /graphql { proxy_set_header Upgrade $http_upgrade; ... }
```

**`"Missing or invalid token format"` dans la subscription :**
```
Cause : Le token est envoyé dans les headers HTTP du playground,
        pas dans connection_params (comportement navigateur).
Solution : Dans le playground, utiliser le champ "Connection Settings"
           pour ajouter {"Authorization": "Bearer <token>"} dans connection_params,
           PAS dans les HTTP headers.
```

**`"Cannot return null for non-nullable field Subscription.clusterConnected"` :**
```
Cause : require_auth() échoue silencieusement dans le contexte WebSocket.
        info.context est un dict, pas un objet — hasattr(ctx, "request") retourne False.
Solution : Vérifier que le token est bien dans connection_params, pas dans les headers HTTP.
```

---

## 10. Gateway GraphQL — Analyse d'incident (async)

### Ce que c'est

La fonctionnalité principale de PodIQ. Quand un pod Kubernetes est en échec (CrashLoopBackOff, OOMKilled, ImagePullBackOff...), l'utilisateur déclenche une analyse qui :
1. Collecte les logs, events, état du pod
2. Scanne le namespace pour détecter des pannes corrélées
3. Consulte l'historique d'incidents précédents du même pod
4. Envoie tout ça à un LLM (Ollama/Mistral) pour diagnostiquer

### Pourquoi asynchrone ?

L'analyse prend entre 5 et 120 secondes (inférence Ollama sur CPU). Un appel HTTP synchrone bloquerait le serveur pendant toute cette durée. La solution : `analyzeIncident` crée un job et retourne immédiatement un `jobId`. Le client poll ensuite `analysisJob(jobId)` toutes les 2-5 secondes (ou utilise la subscription `jobStatus`).

### Implémentation détaillée

**Étape 1 — Mutation (gateway/app/graphql/mutations/analyze.py) :**
```
_analyze_incident(info, pod_name, namespace)
  1. require_auth(info) → TokenContext{user_id, workspace_id, role}
  2. AnalysisJob.objects.create(user_id, workspace_id, pod_name, namespace)
     → status="pending", result=null, error=""
  3. analyze_incident_task.send(job_id, user_id, pod_name, namespace)
     → message Redis: queue "default", données sérialisées
  4. return AnalysisJobType{job_id, status="pending", result=null, error=null, created_at}
     (retour immédiat — ~5ms)
```

**Étape 2 — Worker (gateway/app/tasks.py) :**
```
analyze_incident_task(job_id, user_id, pod_name, namespace)
  1. AnalysisJob.objects.get(id=job_id) → status RUNNING, error="" + save
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

**Étape 3 — Polling ou Subscription :**
```
Option A (polling) : query { analysisJob(jobId) } toutes les 2-5s
Option B (subscription) : subscription { jobStatus(jobId) } — push automatique
```

### 10.1 Test complet de l'analyse d'incident

#### Étape 1 — Déclencher l'analyse

```bash
WS_TOKEN="<workspace-JWT obtenu via selectWorkspace>"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
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
      "createdAt": "2026-05-19T08:00:00"
    }
  }
}
```

#### Étape 2 — Poller le statut

```bash
JOB_ID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d "{
    \"query\": \"query Poll(\$id: ID!) { analysisJob(jobId: \$id) { jobId status result { errorType rootCause explanation solution confidence isRecurring recurrenceCount correlatedService correlationExplanation } error } }\",
    \"variables\": {\"id\": \"$JOB_ID\"}
  }"
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

### 10.2 Cas de test — tous les scénarios

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
| Token expiré | workspace-JWT > 1h | — | `PermissionError` |

### 10.3 Vérifier l'état du job en base de données

```bash
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway -c \
  "SELECT id, user_id, pod_name, namespace, status, error, created_at FROM analysis_jobs ORDER BY created_at DESC LIMIT 5;"
```

### 10.4 Vérifier la file Redis

```bash
docker compose exec redis redis-cli LLEN dramatiq:default.msgs
# Attendu pendant traitement : 1
# Attendu après traitement   : 0
```

---

## 11. Gateway GraphQL — Scan de manifest

### Ce que c'est

Avant de faire `kubectl apply`, l'utilisateur peut faire analyser son manifest YAML par PodIQ. L'IA détecte les risques de configuration **présents dans le manifest** : image avec tag `latest`, absence de resource limits, absence de probes, contexte de sécurité dangereux, credentials en clair.

### 11.1 Test avec un manifest dangereux

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
        securityContext:
          privileged: true
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
      "summary": "Risques critiques détectés : image sans tag fixe, mode privilégié",
      "risks": [
        {
          "severity": "critical",
          "category": "security",
          "description": "Container runs in privileged mode — full host access",
          "fix": "Remove securityContext.privileged: true"
        }
      ]
    }
  }
}
```

### 11.2 Cas de test

| Scénario | Input | riskLevel attendu |
|---|---|---|
| Manifest sain | YAML complet avec limits, probes, tag fixe | `safe` |
| Tag latest | `image: app:latest` | `warning` ou `block` |
| Pas de memory limits | Absence de `resources.limits.memory` | `warning` |
| Privileged mode | `securityContext.privileged: true` | `block` |
| Secret en clair | Env var password en clair | `block` |
| YAML invalide | Contenu non parseable | `GraphQLError: YAML parsing failed` |
| yaml_content vide | `""` | `GraphQLError` |
| Sans token | — | `PermissionError` |

---

## 12. Gateway GraphQL — Historique d'analyses

### Ce que c'est

Permet de consulter les analyses précédentes d'un pod. Utile pour comprendre si un incident est récurrent.

### 12.1 Test

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

### 12.2 Cas de test

| Scénario | Condition | Résultat attendu |
|---|---|---|
| Historique existant | Analyses passées pour ce pod | Liste triée desc par date |
| Pod sans historique | Premier incident | `[]` (liste vide) |
| limit=1 | — | Maximum 1 entrée |
| Sans token | — | `PermissionError` |

---

## 13. Endpoint REST CI/CD

### Ce que c'est

Un endpoint HTTP REST (pas GraphQL) dédié aux pipelines CI/CD automatisés. Il permet de vérifier un manifest YAML avant le déploiement et de bloquer le pipeline si des risques critiques sont détectés.

### Principe de fonctionnement

```
POST /api/v1/cicd/scan
  1. Lit X-Api-Key header → validate_api_key via gRPC auth-service
  2. Parse body JSON {"yaml_content": "...", "manifest_type": "..."}
  3. analyzer_client.parse_manifest(yaml_content.strip(), manifest_type)
  4. ai_client.scan_manifest(parsed.raw_config, related_history=[])
  5. _RISK_TO_EXIT = {"safe": 0, "warning": 1, "block": 2}
  6. Retourne 200 {"exit_code": N, "risk_level": "...", "summary": "...", "risks": [...]}
```

### 13.1 Créer une API Key

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

**Important — `rawKey` est retourné une seule fois.** Seul le hash SHA-256 est conservé.

### 13.2 Test du cas nominal

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
  "summary": "No critical issues detected.",
  "risks": []
}
```

### 13.3 Intégration dans un pipeline shell

```bash
#!/bin/bash
set -e
RESULT=$(curl -s -X POST http://gateway:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $PODIQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"yaml_content\": \"$(cat deployment.yaml | jq -Rs .)\", \"manifest_type\": \"Deployment\"}")
EXIT_CODE=$(echo "$RESULT" | jq '.exit_code')
if [ "$EXIT_CODE" -eq 2 ]; then
  echo "DEPLOYMENT BLOCKED by PodIQ"
  exit 1
fi
```

### 13.4 Cas de test exhaustifs

| Scénario | Input | HTTP Code | exit_code | code JSON |
|---|---|---|---|---|
| Manifest sain | YAML correct, key valide | 200 | 0 | — |
| Manifest warning | YAML avec warnings | 200 | 1 | — |
| Manifest bloquant | YAML avec risques critiques | 200 | 2 | — |
| API Key absente | Pas de header X-Api-Key | 401 | — | `PODIQ_TOKEN_MISSING` |
| API Key invalide | Clé inconnue en base | 401 | — | `PODIQ_TOKEN_INVALID` |
| API Key révoquée | is_active=False | 401 | — | `PODIQ_TOKEN_INVALID` |
| Body non JSON | body = `"texte brut"` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| yaml_content absent | `{}` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| yaml_content vide | `{"yaml_content": ""}` | 400 | — | `PODIQ_VALIDATION_ERROR` |
| Méthode GET | GET au lieu de POST | 405 | — | Django 405 |
| Analyzer down | analyzer-service arrêté | 502 | — | `PODIQ_ANALYZER_GRPC_ERROR` |
| AI down | ai-service arrêté | 502 | — | `PODIQ_AI_GRPC_ERROR` |
| Auth down | auth-service arrêté | 502 | — | `PODIQ_AUTH_GRPC_ERROR` |

---

## 14. Worker Dramatiq — Pipeline async

### Ce que c'est

Le `gateway-worker` est un processus Dramatiq séparé du gateway HTTP. Il consomme les messages de la file Redis et exécute le pipeline d'analyse complet en arrière-plan. Depuis Phase 16, il traite aussi `send_notifications_task`.

### Architecture du worker

```
CMD: ["python", "-m", "dramatiq", "worker_main", "--processes", "2", "--threads", "4"]
                                                    ▲
                                          worker_main.py :
                                            1. django.setup()
                                            2. JobFailureMiddleware
                                            3. import app.tasks  (analyze_incident_task)
                                            4. import app.notifications.tasks (send_notifications_task)
                                          → configure RedisBroker → attend des messages
```

### 14.1 Vérifier que le worker tourne

```bash
docker compose ps gateway-worker
docker compose logs gateway-worker --tail 20
# Attendu : "dramatiq: Worker(processes=2, threads=4) is ready"
```

### 14.2 Cas de test résilience

```bash
# Arrêter le worker pendant une analyse
docker compose stop gateway-worker
# → message dans Redis, status=pending
docker compose start gateway-worker
# → worker reprend, status passe à running puis complete
```

### 14.3 Comportement des retries (max_retries=2)

| Tentative | Status en base | Champ error |
|---|---|---|
| Démarrage 1ère tentative | `running` | `""` (effacé) |
| Échec 1ère tentative | `failed` | message de l'exception |
| Démarrage 2ème tentative (retry) | `running` | `""` (effacé) |
| Épuisement des 3 tentatives | `failed` | message définitif (via `JobFailureMiddleware`) |

> Il est normal de voir `status=running` avec `error` non vide temporairement — c'est l'état entre le moment où le retry commence et l'écriture en base `error=""`.

---

## 15. Namespace Correlation — Corrélation temporelle

### Ce que c'est

Quand un pod est en échec, d'autres pods du même namespace sont peut-être tombés juste avant. Cette fonctionnalité enrichit l'analyse avec un **contexte de namespace** pour que l'IA puisse détecter des relations causales.

### Implémentation

```
build_namespace_context(ns_snapshot, target_pod_name) → [PodContext]
  Pour chaque pod dans ns_snapshot.pods (sauf le pod cible) :
    1. Vérifie si le pod a eu des erreurs récentes
    2. in_correlation_window = abs(seconds_before_reference) < CORRELATION_WINDOW_SECONDS
       (défaut : CORRELATION_WINDOW_MINUTES * 60 = 15 min)
    3. Retourne PodContext{pod_name, in_correlation_window, seconds_before_reference}
```

**Variable d'environnement :** `CORRELATION_WINDOW_MINUTES` (défaut `15`).

### Test avec STUB_MODE

En `STUB_MODE=true`, l'analyzer-service génère des données fictives avec des pods simulés dans le namespace. Après une analyse complète, vérifier si `correlatedService` est renseigné dans le résultat.

---

## 16. Memory Engine — Incidents récurrents

### Ce que c'est

À chaque analyse complète, l'ai-service **mémorise** le résultat et incrémente le compteur de récurrence par `(pod_name, namespace, error_type)`. Lors de la prochaine analyse du même pod, le gateway injecte cet historique dans le prompt Ollama.

### Test de la récurrence

```bash
# 1. Première analyse → isRecurring: false, recurrenceCount: 1
# 2. Deuxième analyse (même pod) → isRecurring: true, recurrenceCount: 2

# Vérifier en base ai-service
docker compose exec postgres-ai psql -U podiq -d podiq_ai -c \
  "SELECT pod_name, namespace, error_type, occurrence_count FROM incident_patterns ORDER BY occurrence_count DESC LIMIT 10;"
```

---

## 17. Observabilité — Grafana + Loki

### Ce que c'est

Tous les services PodIQ émettent des logs structurés JSON (via `structlog`). Promtail collecte ces logs depuis le socket Docker et les envoie à Loki. Grafana expose un dashboard de visualisation.

### 17.1 Accéder à Grafana

```
URL : http://localhost:3000
Login : admin
Password : valeur de GRAFANA_ADMIN_PASSWORD dans .env
```

### 17.2 Vérifier le dashboard podiq-overview

Menu → **Dashboards** → dossier **PodIQ** → **PodIQ — Vue d'ensemble**

**Panels Phase 16 supplémentaires à vérifier :**

| Panel | Ce qu'on cherche |
|---|---|
| Workspace events | Événements createWorkspace, selectWorkspace |
| Invitation events | invitation_sent, invitation_accepted |
| Agent heartbeats | cluster_connected, last_heartbeat |
| Notification dispatches | Canaux déclenchés par send_notifications_task |

### 17.3 Requêtes Loki utiles

```
{namespace="podiq"}                                    → tous les services
{namespace="podiq", service="gateway"}                 → gateway uniquement
{namespace="podiq", service="gateway-worker"}          → worker
{namespace="podiq"} | json | level="error"            → erreurs uniquement
{namespace="podiq"} | json | event="invitation_sent"  → invitations envoyées
{namespace="podiq"} | json | event="cluster_connected"→ heartbeats agent
```

---

## 18. Tests unitaires par service

### Principe

Les tests unitaires de chaque service s'exécutent **sans Docker, sans Postgres, sans Redis**. Ils utilisent :
- **SQLite en mémoire** (`settings_pytest.py`) pour gateway et auth-service
- **StubBroker** (REDIS_URL="") pour Dramatiq
- **unittest.mock.patch** pour tous les appels gRPC

### 18.1 Exécuter tous les tests

```bash
# Depuis la racine du dépôt
./scripts/run_all_tests.sh

# Ou individuellement :
cd services/gateway && python3 -m pytest -v
cd services/auth-service && python3 -m pytest -v
cd services/ai-service && python3 -m pytest -v
cd services/analyzer-service && python3 -m pytest -v
```

### 18.2 Tests du Gateway

**Fichiers de tests :**
```
services/gateway/tests/
  conftest.py                    — setup Django, stubs path, StubBroker
  test_mutations_analyze.py      — mutation analyzeIncident + actor Dramatiq
  test_mutations_auth.py         — register, login (appels _register/_login directs)
  test_mutations_workspace.py    — createWorkspace, selectWorkspace
  test_mutations_agent.py        — agentHeartbeat, agentReportIncident, generateInstallToken
  test_mutations_invitation.py   — inviteMember, acceptInvitation, revokeInvitation
  test_mutations_notifications.py— createAlertRule, connectChannel, setQuietHours
  test_query_job.py              — query analysisJob (polling)
  test_query_invitations.py      — listInvitations
  test_subscriptions.py          — clusterConnected, jobStatus
  test_cicd.py                   — endpoint REST /api/v1/cicd/scan
```

**Note importante `test_mutations_auth.py` :** Les fonctions internes `_register` et `_login` ne prennent pas de paramètre `info` — elles délèguent directement à gRPC. Les appels de test sont `_register(email=..., password=...)` sans `info=None`.

**Exécuter avec couverture :**
```bash
cd services/gateway
python3 -m pytest -v --tb=short 2>&1 | head -100
```

### 18.3 Tests dans Docker

```bash
docker compose run --rm --no-deps gateway python -m pytest -v
docker compose run --rm --no-deps auth-service python -m pytest -v
docker compose run --rm --no-deps ai-service python -m pytest -v
docker compose run --rm --no-deps analyzer-service python -m pytest -v
```

---

## 19. Scénarios end-to-end complets

Ces scénarios nécessitent la **stack complète** démarrée (`make up-mock`).

### Préparer les variables de base

```bash
GQL="http://localhost:8080/graphql"

# Register
RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -d '{"query":"mutation{register(email:\"e2e@podiq.io\",password:\"Test1234!\"){token userId}}"}')
USER_TOKEN=$(echo $RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['register']['token'])")
USER_ID=$(echo $RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['register']['userId'])")
echo "User Token: $USER_TOKEN"
```

---

### Scénario A — Workspace complet (register → workspace → analyse)

```bash
# 1. Créer un workspace (avec user-JWT)
WS_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d '{"query":"mutation{createWorkspace(name:\"Test WS\",slug:\"test-ws-e2e\",region:\"eu\"){id slug}}"}')
WS_ID=$(echo $WS_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['createWorkspace']['id'])")
echo "Workspace ID: $WS_ID"

# 2. Sélectionner le workspace → workspace-JWT
WS_TOKEN_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d "{\"query\":\"mutation{selectWorkspace(workspaceId:\\\"$WS_ID\\\"){token role workspaceId}}\"}")
WS_TOKEN=$(echo $WS_TOKEN_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['selectWorkspace']['token'])")
echo "Workspace Token: $WS_TOKEN"

# 3. Analyser un incident avec le workspace-JWT
RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d '{"query":"mutation{analyzeIncident(podName:\"e2e-pod\",namespace:\"default\"){jobId status}}"}')
JOB_ID=$(echo $RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['analyzeIncident']['jobId'])")
echo "Job ID: $JOB_ID"

# 4. Poller jusqu'à completion
for i in {1..24}; do
  STATUS=$(curl -s -X POST $GQL -H "Authorization: Bearer $WS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"query{analysisJob(jobId:\\\"$JOB_ID\\\"){status}}\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['analysisJob']['status'])")
  echo "[$i] Status: $STATUS"
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done
```

---

### Scénario B — Invitation et onboarding collaborateur

```bash
# Bob s'inscrit
BOB_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -d '{"query":"mutation{register(email:\"bob@podiq.io\",password:\"BobPass123!\"){token}}"}')
BOB_TOKEN=$(echo $BOB_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['register']['token'])")

# Alice (admin) invite Bob
INV_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d "{\"query\":\"mutation{inviteMember(workspaceId:\\\"$WS_ID\\\",email:\\\"bob@podiq.io\\\",role:\\\"member\\\"){id token status}}\"}")
INV_TOKEN=$(echo $INV_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['inviteMember']['token'])")
echo "Invitation token: $INV_TOKEN"

# Bob accepte l'invitation (avec son user-JWT)
# IMPORTANT : utiliser invitation.token, pas invitation.id
ACCEPT_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -d "{\"query\":\"mutation{acceptInvitation(token:\\\"$INV_TOKEN\\\"){token workspaceId role}}\"}")
echo $ACCEPT_RESP | python3 -m json.tool

# Bob a maintenant un workspace-JWT pour le workspace d'Alice
BOB_WS_TOKEN=$(echo $ACCEPT_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['acceptInvitation']['token'])")

# Vérifier que Bob est membre
curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d "{\"query\":\"query{listInvitations(workspaceId:\\\"$WS_ID\\\"){email status role}}\"}" \
  | python3 -m json.tool
```

---

### Scénario C — Agent connect → subscription → clusterConnected

```bash
# 1. Générer un install token (admin)
INSTALL_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d "{\"query\":\"mutation{generateInstallToken(workspaceId:\\\"$WS_ID\\\"){id token expiresAt}}\"}")
INSTALL_TOKEN=$(echo $INSTALL_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['generateInstallToken']['token'])")
echo "Install Token: $INSTALL_TOKEN"

# 2. Ouvrir la subscription clusterConnected dans le playground (voir section 9.1)
#    subscription { clusterConnected(workspaceId: "$WS_ID") { id name status } }

# 3. Simuler le heartbeat agent (déclenche la subscription)
curl -s -X POST $GQL -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation{agentHeartbeat(installToken:\\\"$INSTALL_TOKEN\\\",clusterName:\\\"test-cluster\\\",k8sVersion:\\\"1.29.3\\\"){id name status lastHeartbeat}}\"}" \
  | python3 -m json.tool

# 4. La subscription doit avoir reçu l'événement automatiquement
#    → vérifier dans le playground

# 5. Vérifier le statut du cluster
curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d "{\"query\":\"query{clusterStatus(workspaceId:\\\"$WS_ID\\\"){id name status k8sVersion lastHeartbeat}}\"}" \
  | python3 -m json.tool
```

---

### Scénario D — Pipeline CI/CD bloquant

```bash
# Créer une API Key
AK_RESP=$(curl -s -X POST $GQL -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WS_TOKEN" \
  -d '{"query":"mutation{createApiKey(name:\"ci-test\"){keyId rawKey}}"}')
API_KEY=$(echo $AK_RESP | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['createApiKey']['rawKey'])")

# Tester avec manifest critique
RESULT=$(curl -s -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content":"apiVersion:v1\nkind:Pod\nmetadata:\n  name:danger\nspec:\n  containers:\n  - name:app\n    image:app:latest\n    securityContext:\n      privileged:true","manifest_type":"Pod"}')
echo $RESULT | python3 -m json.tool
# exit_code attendu : 2
```

---

## 20. Matrice des cas de test

### Auth

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| A01 | register | email unique + password | user-JWT + userId | Critique |
| A02 | register | email déjà utilisé | `GraphQLError` | Critique |
| A03 | login | credentials corrects | nouveau user-JWT | Critique |
| A04 | login | mauvais password | `GraphQLError` | Critique |
| A05 | JWT | mutation protégée sans token | `PermissionError` | Critique |
| A06 | JWT | token expiré | `PermissionError` | Critique |
| A07 | API Key | clé valide → CI/CD | 200 + exit_code | Critique |
| A08 | API Key | clé révoquée → CI/CD | 401 `PODIQ_TOKEN_INVALID` | Critique |

### Workspace & JWT deux temps

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| W01 | createWorkspace | nom + slug valides | workspace créé, owner=admin | Critique |
| W02 | createWorkspace | slug déjà pris | `GraphQLError: slug already taken` | Critique |
| W03 | selectWorkspace | user est membre | workspace-JWT avec workspace_id + role | Critique |
| W04 | selectWorkspace | user non membre | `PermissionError` | Critique |
| W05 | refreshToken | cookie refresh valide | nouveau workspace-JWT + rotation cookie | Haute |
| W06 | refreshToken | cookie absent | `GraphQLError: No refresh token` | Haute |
| W07 | workspace-JWT fast path | token avec workspace_id | décodé localement (pas de gRPC) | Haute |
| W08 | user-JWT fallback | token sans workspace_id | validé via gRPC auth-service | Haute |

### Agent

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| AG01 | generateInstallToken | workspaceId valide, admin | token wsk_xxx | Critique |
| AG02 | generateInstallToken | non admin | `PermissionError` | Haute |
| AG03 | agentHeartbeat | token valide (used=False) | cluster créé, status=connected, used=True | Critique |
| AG04 | agentHeartbeat | token valide (used=True) | last_heartbeat mis à jour | Critique |
| AG05 | agentHeartbeat | token expiré | `GraphQLError: Install token expired` | Critique |
| AG06 | agentReportIncident | token valide | jobId créé, accepted=true | Critique |
| AG07 | clusterStatus | workspaceId avec cluster | statut cluster retourné | Haute |

### Invitations

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| INV01 | inviteMember | email + role, admin | invitation pending + token | Critique |
| INV02 | inviteMember | email déjà invité | ancienne révoquée, nouvelle créée | Haute |
| INV03 | inviteMember | non admin | `PermissionError` | Critique |
| INV04 | acceptInvitation | invitation.token valide | workspace-JWT + status=accepted | Critique |
| INV05 | acceptInvitation | invitation.id (mauvais champ) | `GraphQLError: not found` | Critique |
| INV06 | acceptInvitation | invitation expirée | `GraphQLError: Invitation expired` | Haute |
| INV07 | acceptInvitation | upgrade rôle (viewer→member) | rôle mis à jour | Haute |
| INV08 | acceptInvitation | pas de downgrade (admin→member) | rôle inchangé | Critique |
| INV09 | revokeInvitation | invitationId, admin | invitation revoked | Haute |
| INV10 | listInvitations | workspaceId, admin | liste triée desc | Haute |
| INV11 | listInvitations | non admin | `PermissionError` | Haute |

### Subscriptions WebSocket

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| SUB01 | clusterConnected | workspace-JWT dans connection_params | subscription ouverte | Critique |
| SUB02 | clusterConnected | auth manquante | `PermissionError` | Critique |
| SUB03 | clusterConnected | agentHeartbeat appelé | événement poussé | Critique |
| SUB04 | jobStatus | analyse complète | status=complete + result poussés | Haute |

### Analyse d'incident

| ID | Fonctionnalité | Input | Résultat attendu | Criticité |
|---|---|---|---|---|
| I01 | analyzeIncident | pod + namespace valides | jobId + status=pending | Critique |
| I02 | analysisJob | pendant exécution | status=running | Haute |
| I03 | analysisJob | après succès | status=complete + result | Critique |
| I04 | analysisJob | après échec gRPC | status=failed + error | Critique |
| I05 | analysisJob | jobId inconnu | `GraphQLError: Job not found` | Haute |
| I06 | analysisJob | jobId d'un autre user | `GraphQLError: Job not found` | Critique |
| I07 | Memory Engine | 1ère analyse | isRecurring=false | Haute |
| I08 | Memory Engine | 2ème analyse même pod | isRecurring=true, recurrenceCount=2 | Haute |

### CI/CD REST

| ID | Fonctionnalité | Input | HTTP | exit_code | Criticité |
|---|---|---|---|---|---|
| C01 | /api/v1/cicd/scan | clé valide, manifest safe | 200 | 0 | Critique |
| C02 | /api/v1/cicd/scan | clé valide, manifest block | 200 | 2 | Critique |
| C03 | /api/v1/cicd/scan | X-Api-Key absent | 401 | — | Critique |
| C04 | /api/v1/cicd/scan | body JSON invalide | 400 | — | Haute |
| C05 | /api/v1/cicd/scan | analyzer down | 502 | — | Haute |

### Résilience

| ID | Fonctionnalité | Condition | Résultat attendu | Criticité |
|---|---|---|---|---|
| R01 | Worker Dramatiq | worker arrêté, redémarré | message Redis consommé au redémarrage | Critique |
| R02 | Worker Dramatiq | ai-service down | job failed après 3 tentatives | Haute |
| R03 | Gateway ASGI | uvicorn[standard] absent | WebSocket échoue au démarrage | Critique |

---

## 21. Dépannage rapide

### WebSocket — `{isTrusted: true}` sans message d'erreur dans le playground

**Cause :** Nginx ne forwarde pas le WebSocket upgrade.
```bash
# Vérifier la config nginx
cat infra/nginx/default.conf | grep -A 10 "location /graphql"
# Doit contenir :
#   proxy_set_header Upgrade $http_upgrade;
#   proxy_set_header Connection $connection_upgrade;
# ET en dehors du block :
#   map $http_upgrade $connection_upgrade { default upgrade; '' keep-alive; }
```

### WebSocket — `"Missing or invalid token format"` dans la subscription

**Cause :** Le token est dans les HTTP headers du playground au lieu des `connection_params`.
```
Solution : Dans le playground Strawberry, utiliser "Connection Settings" (icône engrenage)
pour passer {"Authorization": "Bearer <token>"} dans les connection_params WebSocket.
Les navigateurs ne peuvent pas envoyer de headers personnalisés sur les connexions WebSocket.
```

### WebSocket — `"Cannot return null for non-nullable field Subscription.clusterConnected"`

**Cause :** `require_auth()` reçoit un dict Starlette mais cherche un objet Django.
```bash
# Vérifier que app/auth.py contient _header_from_dict_ctx()
# et que require_auth() appelle isinstance(ctx, dict) avant hasattr(ctx, "request")
grep -n "_header_from_dict_ctx\|isinstance.*dict" services/gateway/app/auth.py
```

### Invitation — `"Invitation not found or already used"` avec un UUID valide

**Cause :** Passage du champ `id` au lieu du champ `token` — ce sont deux UUIDs différents.
```
acceptInvitation prend invitation.token (le UUID public de l'invitation)
                 PAS invitation.id (le UUID interne de la ligne en base)

Vérifier en base :
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT id, token, status FROM invitations ORDER BY created_at DESC LIMIT 3;"
```

### "Admin access required" malgré un rôle admin dans le JWT

**Cause historique :** Bug corrigé en Phase 16 — `acceptInvitation` utilisait `update_or_create` avec `defaults={"role": invite.role}`, ce qui écrasait le rôle admin avec member. Corrigé avec `get_or_create` + upgrade-only via `_ROLE_PRIORITY`.
```bash
# Vérifier le rôle en base si le problème persiste
docker compose exec postgres-gateway psql -U podiq -d podiq_gateway \
  -c "SELECT user_id, role FROM workspace_members WHERE workspace_id='<uuid>';"
# Si rôle incorrect : UPDATE workspace_members SET role='admin' WHERE user_id='<uuid>';
# Puis re-sélectionner le workspace pour obtenir un nouveau JWT avec le bon rôle
```

### `'dict' object has no attribute 'response'` dans selectWorkspace

**Cause :** Code accédant à `info.context.response` comme attribut sur un dict Starlette.
```
Solution : workspace.py doit utiliser _get_response(info) et _get_request(info)
qui font ctx.get("response") si isinstance(ctx, dict).
Vérifier que ces helpers existent dans services/gateway/app/graphql/mutations/workspace.py
```

### "Install token already used" sur agentReportIncident

**Cause historique :** Bug corrigé en Phase 16 — le code rejetait les tokens avec `used=True`.
```
La sémantique correcte : used=True signifie "cluster enregistré", pas "token révoqué".
L'agent réutilise le même token indéfiniment. Seule l'expiry est vérifiée.
Vérifier services/gateway/app/graphql/mutations/agent.py : la fonction
_resolve_install_token ne doit PAS contenir de vérification "if token.used: raise"
```

### Le playground GraphQL retourne du HTML au lieu de JSON

**Cause probable (pré-Phase 16) :** Worker Gunicorn tué par timeout. Depuis Phase 16, le gateway utilise Uvicorn ASGI — ce problème ne se produit plus.
```bash
docker compose logs gateway | grep -i "error\|startup complete"
# Doit afficher "Application startup complete." (Uvicorn)
# Pas "Booting worker with pid" (Gunicorn)
```

### Status du job reste "pending" indéfiniment

```bash
docker compose ps gateway-worker
docker compose logs gateway-worker --tail 20
docker compose exec redis redis-cli ping  # doit retourner PONG
docker compose exec redis redis-cli LLEN dramatiq:default.msgs
```

### Status du job reste "running" indéfiniment

```bash
docker compose logs ai-service --tail 20  # vérifier si Ollama répond
docker compose logs gateway-worker --tail 20
```

### Erreur "grpc_message: timed out"

```bash
# Dans .env, augmenter :
AI_TIMEOUT_SECONDS=120
docker compose up -d ai-service

# Vérifier que le modèle Ollama est disponible
docker compose exec ollama ollama list
# Si vide : docker compose exec ollama ollama pull mistral
```

### Collect 0 items dans les tests unitaires

```bash
cd services/gateway && python3 -m pytest -v --collect-only
docker compose build --no-cache gateway
docker compose run --rm --no-deps gateway python -m pytest -v tests/
```

### Logs non visibles dans Grafana

```bash
docker compose logs promtail | grep -i "error"
curl -s http://localhost:3100/ready  # Attendu : "ready"
```

### Tester la connectivité gRPC entre services

```bash
docker compose exec gateway python -c "
import grpc
from stubs.auth import auth_pb2_grpc, auth_pb2
channel = grpc.insecure_channel('auth-service:50051')
stub = auth_pb2_grpc.AuthServiceStub(channel)
try:
    resp = stub.Login(auth_pb2.LoginRequest(email='x', password='x'), timeout=5)
except grpc.RpcError as e:
    print(f'gRPC status: {e.code()} — {e.details()}')
# UNAUTHENTICATED → auth-service répond (credentials incorrects, normal)
# UNAVAILABLE     → auth-service ne répond pas
"
```
