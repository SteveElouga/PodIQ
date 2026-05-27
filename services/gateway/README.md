# Gateway — Le Chef d'Orchestre

## Analogie

Imagine la **réception d'un hôpital de haut niveau**.

- Les clients (frontend Angular, CLI, pipelines CI/CD) arrivent à la réception et font leur demande. Ils ne savent pas comment l'hôpital est organisé en interne — ils parlent uniquement à la réceptionniste.
- La réceptionniste (le Gateway) **comprend la demande**, **contacte les bons services** dans le bon ordre, et **assemble la réponse finale** à remettre au client.
- Si le client veut s'identifier, la réceptionniste transmet ses informations au **service d'accueil/sécurité** (auth-service) et retourne le badge d'accès.
- La réceptionniste ne fait **aucun diagnostic** elle-même — elle orchestre et transmet.

---

## Responsabilité

Le Gateway est le **seul point d'entrée** de PodIQ pour les clients externes. Il est responsable de :

- Exposer une **API GraphQL** sur `/graphql` (queries, mutations, subscriptions WebSocket)
- Gérer l'authentification en **deux temps** : user-JWT (auth-service) → workspace-JWT (gateway)
- Gérer les **workspaces multi-tenant** : création, sélection, membres, invitations
- Réceptionner les heartbeats et incidents de l'**agent K8s** via mutations GraphQL
- Orchestrer les appels gRPC entre les services backend
- Envoyer des **notifications** (Slack, PagerDuty, email, webhook, Teams, Discord) via Dramatiq
- Exposer un endpoint **REST** sur `/api/v1/cicd/scan` (auth via `X-Api-Key`, exit codes 0/1/2)

Il ne fait **aucun appel direct à Kubernetes**, **aucun appel à Ollama**, et **n'accède à aucune base de données autre que la sienne**.

---

## Architecture ASGI

Depuis la phase 16, le Gateway tourne sous **Uvicorn (ASGI)** — non plus Gunicorn (WSGI). Cela permet les subscriptions GraphQL via WebSocket.

### Routage ASGI (`config/asgi.py`)

```
Request HTTP/WS
      │
      ▼
application(scope, receive, send)   ← ASGI router custom
      │
      ├─ path == "/graphql"  ──►  strawberry.asgi.GraphQL   (HTTP + WebSocket)
      │                           └─ wrappé dans CORSMiddleware (starlette)
      │
      └─ autres paths  ──────►  get_asgi_application()      (Django : healthz, CI/CD REST)
```

**Pourquoi `strawberry.asgi.GraphQL` plutôt que `AsyncGraphQLView` pour `/graphql` ?**

`AsyncGraphQLView` (Django) gère uniquement HTTP. Pour le protocole WebSocket `graphql-ws` (subscriptions depuis le playground), il faut `strawberry.asgi.GraphQL` (Starlette-based) qui gère les deux.

> **Piège rencontré :** `uvicorn` de base ne supporte pas WebSocket — le log indiquait
> `No supported WebSocket library detected`. Fix : `uvicorn[standard]` dans `requirements.txt`
> (installe `websockets` automatiquement).

---

## Authentification — JWT deux étapes

### Étape 1 — User-JWT (auth-service)

```graphql
mutation { login(email, password) { token userId email } }
```

Retourne un JWT léger signé par auth-service : `{ user_id, email, iat, exp }`.

### Étape 2 — Workspace-JWT (gateway)

```graphql
mutation { selectWorkspace(workspaceId: "...") { token workspaceId role } }
```

Gateway vérifie le user-JWT via gRPC, récupère le `WorkspaceMember` en base, et signe un JWT enrichi avec `GATEWAY_JWT_SECRET` :
```json
{ "user_id": "...", "email": "...", "workspace_id": "...", "role": "admin", "exp": ... }
```

**Ce workspace-JWT est décodé localement (fast path)** dans `require_auth()` sans appel gRPC.

### Refresh token (cookie httpOnly)

- Mis en place automatiquement par `selectWorkspace` et `login`
- Cookie `refresh_token` : `HttpOnly`, `Secure` (prod), `SameSite=Strict`, path `/graphql`
- Rotation à chaque appel → `refreshToken` mutation retourne un nouveau access token + rotate le cookie
- Durée : `GATEWAY_REFRESH_EXPIRY_DAYS` (défaut 30 jours)

### `require_auth()` — `app/auth.py`

Retourne un `TokenContext(user_id, email, workspace_id, role)`.

Lève **toujours `GraphQLError`** (jamais `PermissionError`) avec un code machine dans `extensions["code"]` :
| Cas | Code `extensions["code"]` |
|-----|--------------------------|
| Header absent ou format non-Bearer | `PODIQ_TOKEN_MISSING` |
| Token vide | `PODIQ_TOKEN_MISSING` |
| JWT invalide / expiré (gRPC) | `PODIQ_TOKEN_INVALID` |

Gère **trois layouts de contexte Strawberry** :
| Contexte | Cas | Extraction |
|----------|-----|-----------|
| `dict{"request": ...}` HTTP | ASGI / Django view | `ctx["request"].headers["Authorization"]` |
| `dict{"connection_params": ...}` WS | WebSocket subscription | `ctx["connection_params"]["Authorization"]` |
| Objet avec `.request` | Legacy fallback | `ctx.request.headers["Authorization"]` |

> **Piège rencontré :** `AsyncGraphQLView` retourne un dict `{"request": ..., "response": ...}`.
> `hasattr(ctx, "request")` retourne `False` sur un dict Python → le token n'était jamais lu.
> Fix : vérifier `isinstance(ctx, dict)` en premier, puis chercher `connection_params` (WebSocket)
> avant les headers HTTP.

---

## Gestion des erreurs de token — Arbres de décision

### Phase 1 — User-JWT (post-login, avant selectWorkspace)

Le user-JWT est un credential de transition : il ne sert qu'à `createWorkspace` et `selectWorkspace`.
**Il n'existe pas de mécanisme de refresh pour le user-JWT** — expiration = reconnexion obligatoire.

```
Appel avec user-JWT
        │
        ├─ PODIQ_TOKEN_MISSING  →  rediriger vers /login
        ├─ PODIQ_TOKEN_INVALID  →  rediriger vers /login
        │   (expiré après 24h, signature invalide, token vide)
        └─ Succès               →  continuer l'onboarding
```

**Pourquoi pas de refresh pour le user-JWT ?**
Le user-JWT est transitoire par conception : il expire en 24h (env `JWT_EXPIRY_MINUTES=1440` dans
auth-service). Sa seule raison d'être est d'obtenir un workspace-JWT via `selectWorkspace`.
Gérer un refresh cycle pour lui ajouterait de la complexité sans bénéfice réel — si l'utilisateur
met 24h entre son `login` et son `selectWorkspace`, il re-login simplement.

### Phase 2 — Workspace-JWT (post-selectWorkspace, opérations métier)

```
Appel avec workspace-JWT
        │
        ├─ PODIQ_TOKEN_MISSING  →  rediriger vers /login (re-login complet)
        │
        ├─ PODIQ_TOKEN_INVALID  →  appeler mutation { refreshToken }
        │   (workspace-JWT expiré après 1h)       │
        │                               ┌──────────┴──────────┐
        │                         Succès (cookie OK)     Échec (cookie expiré/absent)
        │                               │                      │
        │                      retry l'appel original   re-login → selectWorkspace
        │
        ├─ PODIQ_FORBIDDEN      →  afficher message "droits insuffisants"
        │   (authentifié mais pas admin, etc.)     Ne jamais déconnecter — l'utilisateur
        │                                          est valide, juste pas autorisé pour cette action
        │
        └─ PODIQ_AUTH_GRPC_ERROR  →  afficher "service temporairement indisponible", retry
```

### Re-login avec onboarding incomplet

Quand l'utilisateur se reconnecte (user-JWT obtenu) et n'a pas encore fini l'onboarding :

```
login → user-JWT obtenu
        │
        ▼
listWorkspaces (avec user-JWT)
        │
        ├─ 0 workspace          →  rediriger vers createWorkspace (premier onboarding)
        │
        ├─ 1 workspace
        │       │
        │       └─ onboarded_at is null  →  selectWorkspace → workspace-JWT
        │                                   → rediriger vers wizard installation agent
        │           (onboarded_at not null) →  selectWorkspace → accès normal
        │
        └─ N workspaces
                │
                ├─ Présenter la liste de sélection au frontend
                │   (chaque workspace indique si onboarded_at is null)
                │
                └─ Après sélection → selectWorkspace → workspace-JWT
                    → si onboarded_at is null : wizard agent pour ce workspace
                    → sinon : accès normal
```

> **Signal canonique** : `workspace.onboarded_at` est posé par le backend automatiquement
> au **premier `agentHeartbeat`** reçu pour ce workspace. Le frontend ne doit jamais
> le poser lui-même — il se contente de le lire.

---

## Base de données — `postgres-gateway`

### Tables

| Table | Description |
|-------|-------------|
| `analysis_jobs` | Jobs d'analyse async (UUID PK, user_id, workspace_id, status, result JSON) |
| `workspaces` | Tenants (UUID PK, owner_id, name, slug, plan, region, team_size, accent_color) |
| `workspace_members` | Rôles par workspace (workspace FK, user_id UUID, role admin/member/viewer) |
| `install_tokens` | Tokens d'install agent (workspace FK, token `wsk_xxx`, expires_at, used) |
| `clusters` | Clusters K8s enregistrés (workspace FK, install_token FK, name, k8s_version, status, last_heartbeat) |
| `invitations` | Invitations membres (workspace FK, email, token UUID, role, status, expires_at) |
| `alert_rules` | Règles de notification (workspace FK, event_type, enabled) |
| `notification_channels` | Destinations (workspace FK, type, config JSON, enabled) |
| `quiet_hours` | Fenêtre de silence (workspace OneToOne, start/end time, timezone) |

### Migrations

| Fichier | Contenu |
|---------|---------|
| `0001_initial.py` | `analysis_jobs` |
| `0002_workspace.py` | `workspaces`, `workspace_members`, `install_tokens`, `clusters` |
| `0003_invitations_alerts.py` | `invitations`, `alert_rules`, `notification_channels`, `quiet_hours` |

---

## Schéma GraphQL complet

```
Query
├── analysisJob(jobId) → AnalysisJobType
├── analysisHistory(podName, namespace, limit, analysisType?) → [AnalysisHistoryItem]
├── listWorkspaces() → [WorkspaceType]
├── currentWorkspace() → WorkspaceType
├── clusterStatus(workspaceId) → [ClusterType]
└── listInvitations(workspaceId, status?) → [InvitationPayload]

Mutation
├── ── Auth ──────────────────────────────────────────────────────
│   register(email, password) → AuthPayload
│   login(email, password) → AuthPayload
│   createApiKey(name) → ApiKeyPayload
│   revokeApiKey(keyId) → Boolean
│
├── ── Workspace ─────────────────────────────────────────────────
│   createWorkspace(name, region?, teamSize?, accentColor?) → WorkspaceType
│   selectWorkspace(workspaceId) → WorkspaceAuthPayload   ← émet workspace-JWT + cookie
│   refreshToken() → WorkspaceAuthPayload                 ← lit le cookie httpOnly
│   updateWorkspace(workspaceId, name?, accentColor?, teamSize?) → WorkspaceType
│
├── ── Analysis ──────────────────────────────────────────────────
│   analyzeIncident(podName, namespace) → AnalysisJobType  (async)
│   scanManifest(yamlContent, manifestType?) → ManifestScanResultType
│
├── ── Agent ─────────────────────────────────────────────────────
│   generateInstallToken(workspaceId) → InstallTokenPayload
│   agentHeartbeat(installToken, clusterName, k8sVersion?) → ClusterType
│   agentReportIncident(installToken, podName, namespace, logs?, events?, describeOutput?) → AnalysisJobType
│
├── ── Invitations ───────────────────────────────────────────────
│   inviteMember(workspaceId, email, role?) → InvitationPayload
│   revokeInvitation(invitationId) → Boolean
│   acceptInvitation(token) → WorkspaceAuthPayload
│   generateInviteLink(workspaceId) → InvitationPayload
│
└── ── Notifications ─────────────────────────────────────────────
    createAlertRule(workspaceId, eventType, name?) → AlertRuleType
    toggleAlertRule(ruleId, enabled) → AlertRuleType
    connectChannel(workspaceId, channelType, config) → ChannelPayload
    disconnectChannel(channelId) → Boolean
    setQuietHours(workspaceId, enabled, startTime, endTime, timezone?, weekdaysOnly?) → QuietHoursType

Subscription  (WebSocket — protocole graphql-ws)
├── clusterConnected(workspaceId) → ClusterType   ← poll DB toutes les 2s
└── jobStatus(jobId) → AnalysisJobType            ← poll DB toutes les 3s
```

---

## Détail des mutations — Auth & Workspace

### `register` / `login`

Validation email par regex avant tout appel gRPC. Un email invalide retourne `PODIQ_VALIDATION_ERROR` sans appel réseau.

```graphql
mutation { register(email: "user@example.com", password: "MotDePasse123!") { token userId email } }  # pragma: allowlist secret
mutation { login(email: "user@example.com", password: "MotDePasse123!") { token userId email } }  # pragma: allowlist secret
```

Le token retourné est un **user-JWT** (auth-service) — valide uniquement pour `selectWorkspace`.

### `createWorkspace`

Nécessite un user-JWT ou workspace-JWT. Crée le workspace et ajoute le créateur comme `admin`.

```graphql
mutation {
  createWorkspace(name: "Acme SRE", region: "eu", teamSize: "2_10") {
    id slug plan role createdAt
  }
}
```

### `selectWorkspace`

Échange le user-JWT contre un workspace-JWT + pose le cookie refresh.

```graphql
mutation {
  selectWorkspace(workspaceId: "649eec90-...") {
    token workspaceId role userId email
  }
}
```

### `refreshToken`

Lit le cookie `refresh_token` (httpOnly), valide, retourne un nouveau access token + rotate le cookie.

```graphql
mutation { refreshToken { token workspaceId role } }
```

---

## Détail des mutations — Agent

L'agent K8s s'authentifie via `installToken` dans le payload — il n'a pas de JWT utilisateur.

### `generateInstallToken`

Génère un token `wsk_xxx` valide 24h. L'admin copie ce token dans le Helm chart.

```graphql
mutation { generateInstallToken(workspaceId: "...") { token expiresAt } }
```

### `agentHeartbeat`

Appelé par l'agent au démarrage et périodiquement. Crée ou met à jour le `Cluster`.

```graphql
mutation {
  agentHeartbeat(installToken: "wsk_xxx", clusterName: "prod-eu", k8sVersion: "1.29") {
    id name status lastHeartbeat
  }
}
```

> **Note implémentation :** le flag `used=True` sur l'`InstallToken` signifie « cluster enregistré »,
> pas « token invalidé ». L'agent réutilise le même token pour tous ses appels ultérieurs.
> `_resolve_install_token()` vérifie uniquement l'expiration, pas le flag `used`.

> **`onboarded_at` — signal de fin d'onboarding :** au **premier** heartbeat d'un cluster
> (`Cluster` créé = `created=True`), le gateway pose automatiquement
> `workspace.onboarded_at = now()` **si et seulement si** `workspace.onboarded_at is None`.
> Ce champ est immuable une fois posé (ajout d'un second cluster ne l'écrase pas).
> Le frontend consulte `onboarded_at` pour savoir si l'utilisateur doit encore passer
> par le wizard d'installation agent.

### `agentReportIncident`

L'agent envoie un incident détecté. Crée un `AnalysisJob` et l'enfile dans Dramatiq.

```graphql
mutation {
  agentReportIncident(
    installToken: "wsk_xxx"
    podName: "api-pod"
    namespace: "production"
    logs: "..."
    events: "..."
  ) { jobId status }
}
```

L'agent collecte `logs`, `events`, `describeOutput` et `namespacePods` directement dans le cluster via `kubectl`, puis les envoie dans ce payload. Le worker Dramatiq (`analyze_incident_task`) les reçoit et construit le contexte namespace (`_build_namespace_context`) pour la corrélation temporelle avant de les transmettre à l'AI Service.

---

## Détail des mutations — Invitations

### `inviteMember`

Admin uniquement. Révoque tout invite pending existant pour le même email+workspace, puis crée un nouvel invite.

```graphql
mutation {
  inviteMember(workspaceId: "...", email: "colleague@test.com", role: "member") {
    id
    token   # UUID à mettre dans le lien /join?token=xxx
    status
    expiresAt
  }
}
```

> **Important :** le champ `id` et le champ `token` sont deux UUID distincts.
> `acceptInvitation` attend le champ **`token`**, pas l'`id`.

### `acceptInvitation`

Accepte l'invitation et retourne directement un workspace-JWT + cookie refresh.
Ne rétrograde jamais un rôle existant (admin ne peut pas être ramené à member).

```graphql
mutation {
  acceptInvitation(token: "b1eceb49-5c7f-40dd-b94c-622a34b64197") {
    token workspaceId role
  }
}
```

> **Bug corrigé :** `update_or_create` avec `defaults={"role": invite.role}` écrasait le rôle
> même si le membre était déjà admin. Remplacé par `get_or_create` + upgrade uniquement si
> le nouveau rôle est plus élevé (`_ROLE_PRIORITY` : viewer=1, member=2, admin=3).

### `generateInviteLink`

Crée une invitation sans email cible (lien ouvert, rôle `member` par défaut).

---

## Subscriptions WebSocket

Le playground à `http://localhost:8080/graphql` supporte les subscriptions via WebSocket.
Pour envoyer le token d'authentification, utiliser la section **Headers** du playground :
```json
{ "Authorization": "Bearer <workspace-JWT>" }
```
GraphiQL envoie ce header comme payload du message `connection_init` (protocole `graphql-ws`).
Strawberry expose ce payload dans `info.context["connection_params"]`.

### `clusterConnected`

Reste ouvert jusqu'à ce qu'un cluster avec `status=CONNECTED` apparaisse dans le workspace.

```graphql
subscription {
  clusterConnected(workspaceId: "649eec90-...") {
    id name status k8sVersion lastHeartbeat
  }
}
```

### `jobStatus`

Pousse les mises à jour d'un job jusqu'à `complete` ou `failed`.

```graphql
subscription {
  jobStatus(jobId: "ffffffff-...") {
    jobId status result { errorType rootCause solution } error
  }
}
```

---

## Notifications — `send_notifications_task`

Déclenché automatiquement par `analyze_incident_task` quand un job passe en `complete` (si `workspace_id` est renseigné).

Flux :
```
1. Récupère les AlertRule activées pour (workspace_id, event_type)
2. Vérifie QuietHours — si période de silence active, skip sauf event_type="crashloop" (P1)
3. Dispatch vers chaque NotificationChannel actif du workspace
```

| Type | Méthode | Config JSON |
|------|---------|-------------|
| `slack` / `discord` / `teams` | Webhook HTTP POST | `{"webhook_url": "..."}` |
| `pagerduty` | Events API v2 | `{"routing_key": "..."}` |
| `webhook` | HTTP POST custom | `{"url": "...", "secret": "..."}` |
| `email` | SMTP (envs `SMTP_*`) | `{"address": "alerts@acme.io"}` |

---

## Endpoint REST CI/CD

### `POST /api/v1/cicd/scan`

Authentification par API Key (`X-Api-Key`). Exit codes 0/1/2 pour les pipelines GitHub Actions.

```bash
curl -X POST http://localhost:8080/api/v1/cicd/scan \
  -H "X-Api-Key: <clé>" \
  -H "Content-Type: application/json" \
  -d '{"yaml_content": "apiVersion: ...", "manifest_type": "Deployment"}'
```

| Exit code | `risk_level` | Signification |
|-----------|-------------|---------------|
| `0` | `safe` | Déploiement autorisé |
| `1` | `warning` | Révision recommandée |
| `2` | `block` | Déploiement bloqué |

---

## Standardisation des erreurs GraphQL — `app/api_codes.py`

Toutes les erreurs GraphQL du gateway portent un code machine stable dans `extensions["code"]`.
**Aucun `PermissionError` Python** n'est jamais propagé au client — tout est converti en `GraphQLError`.

### Codes d'erreur (`ErrorCode`)

| Code | HTTP équiv. | Quand |
|------|-------------|-------|
| `PODIQ_TOKEN_MISSING` | 401 | Header absent, vide, ou format non-Bearer |
| `PODIQ_TOKEN_INVALID` | 401 | JWT expiré, signature invalide, type incorrect |
| `PODIQ_UNAUTHORIZED` | 401 | Install token invalide ou expiré (agent) |
| `PODIQ_FORBIDDEN` | 403 | Authentifié mais non autorisé (pas membre, pas admin) |
| `PODIQ_NOT_FOUND` | 404 | Workspace, invitation, job, cluster, règle introuvable |
| `PODIQ_CONFLICT` | 409 | Invitation déjà utilisée, expirée, ou slug déjà pris |
| `PODIQ_VALIDATION_ERROR` | 400 | Données invalides (email, rôle, team_size, JSON malformé) |
| `PODIQ_AUTH_GRPC_ERROR` | 502 | Appel gRPC vers auth-service échoué |
| `PODIQ_AI_GRPC_ERROR` | 502 | Appel gRPC vers ai-service échoué |
| `PODIQ_AI_TIMEOUT` | 504 | Timeout Ollama |
| `PODIQ_INTERNAL_ERROR` | 500 | Erreur interne non anticipée |

### Format de réponse en cas d'erreur

```json
{
  "data": null,
  "errors": [{
    "message": "You are not a member of this workspace",
    "extensions": {
      "code": "PODIQ_FORBIDDEN"
    }
  }]
}
```

### Règles d'implémentation

- `require_auth()` lève `GraphQLError` (jamais `PermissionError`) — codes `TOKEN_MISSING` ou `TOKEN_INVALID`
- Chaque `raise GraphQLError(...)` doit avoir `extensions=graphql_error_extensions(ErrorCode.XXX)`
- Les erreurs gRPC passent par `raise_graphql_from_grpc()` dans `grpc_errors.py` qui mappe les statuts gRPC vers les `ErrorCode` appropriés

---

## Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|----------|-------------|--------|-------------|
| `DATABASE_URL` | Oui | — | `postgresql://user:pass@postgres-gateway/db` |  <!-- pragma: allowlist secret -->
| `DJANGO_SECRET_KEY` | Oui | — | Clé secrète Django |
| `GATEWAY_JWT_SECRET` | Oui | — | Signe les workspace-JWT (access tokens 1h) |
| `GATEWAY_JWT_ACCESS_EXPIRY_MINUTES` | Non | `60` | Durée du workspace-JWT (access token) |
| `JWT_EXPIRY_MINUTES` | Non | `1440` | Durée du user-JWT (auth-service) — 24h par défaut ; pas de refresh pour ce token |
| `GATEWAY_REFRESH_SECRET` | Oui | — | Signe les refresh tokens (httpOnly cookie) |
| `GATEWAY_REFRESH_EXPIRY_DAYS` | Non | `30` | Durée du refresh token |
| `CORS_ALLOWED_ORIGINS` | Oui (prod) | — | Ex : `http://localhost:4200,http://localhost:8080` |
| `REDIS_URL` | Oui | — | `redis://redis:6379/0` — broker Dramatiq |
| `ANALYZER_GRPC_HOST/PORT` | Non | `analyzer-service:50052` | |
| `AI_GRPC_HOST/PORT` | Non | `ai-service:50053` | |
| `AUTH_GRPC_HOST/PORT` | Non | `auth-service:50051` | |
| `SMTP_HOST/PORT/USER/PASSWORD` | Non | — | Emails d'invitation + canal `email` |
| `CORRELATION_WINDOW_MINUTES` | Non | `15` | Fenêtre corrélation namespace |
| `AI_TIMEOUT_SECONDS` | Non | `30` | Timeout vers Ollama (300 recommandé en dev CPU pour l'inférence Mistral) |

---

## Dépendances notables

| Paquet | Rôle |
|--------|------|
| `uvicorn[standard]` | Serveur ASGI + support WebSocket (`websockets` inclus) |
| `starlette` | Requis par `strawberry.asgi.GraphQL` et `CORSMiddleware` |
| `PyJWT` | Décodage/encodage JWT workspace (fast path local) |
| `httpx` | Dispatch HTTP sortant vers canaux de notification |
| `strawberry-graphql[django]` | GraphQL — version GitHub pinn ée (compatibilité Python 3.14) |

> **Piège :** `uvicorn` sans `[standard]` ne détecte pas de librairie WebSocket et répond
> `Unsupported upgrade request` à toute connexion WS. Log visible dans `docker logs podiq-gateway`.

---

## Timeouts Nginx

Deux `location` blocks distincts dans `infra/nginx/default.conf` :

| Location | `proxy_read_timeout` | `Connection` header | Pourquoi |
|----------|---------------------|---------------------|---------|
| `/graphql` | 300 s | `$connection_upgrade` (map) | WebSocket upgrade + SSE streaming |
| `/` | 180 s | `""` (strip) | HTTP standard |

La `map $http_upgrade $connection_upgrade` garantit :
- WebSocket → `Connection: upgrade`
- HTTP normal → `Connection: keep-alive`

---

## Erreurs connues et corrections appliquées

### `You cannot call this from an async context`
**Cause :** `AsyncGraphQLView` s'exécute dans une event loop asyncio ; Django ORM est synchrone.
**Fix :** Toutes les fonctions resolver internes (`_xxx`) restent synchrones. Les `@strawberry.mutation` / `@strawberry.field` sont `async def` et wrappent avec `sync_to_async(_xxx)(...)`.

### `{isTrusted: true}` dans le playground (subscriptions)
**Cause 1 :** Nginx avec `proxy_set_header Connection ""` coupe le handshake WebSocket.
**Cause 2 :** `AsyncGraphQLView` ne supporte pas WebSocket — `strawberry.asgi.GraphQL` est requis.
**Cause 3 :** `uvicorn` (sans `[standard]`) n'a pas de librairie WebSocket.
**Fix :** Voir section Architecture ASGI + Nginx ci-dessus.

### `Cannot return null for non-nullable field Subscription.clusterConnected`
**Cause :** `require_auth()` utilisait `hasattr(info.context, "request")` — retourne `False` sur un
dict Python → token jamais lu → `GraphQLError` silencieuse → Strawberry collapse en `null`.
**Fix :** `_header_from_dict_ctx()` vérifie `isinstance(ctx, dict)` et cherche `connection_params`
(WebSocket) avant les headers HTTP.

### `'dict' object has no attribute 'response'`
**Cause :** `_set_refresh_cookie` faisait `info.context.response.set_cookie(...)` — accès attribut
sur un dict.
**Fix :** `_get_response(info)` retourne `ctx.get("response")` si dict, sinon `getattr(ctx, "response")`.

### `Invitation not found or already used` (avec le bon token)
**Cause :** L'utilisateur a passé le champ `id` de l'invitation à `acceptInvitation` au lieu du champ `token`. Les deux sont des UUID distincts.
**Fix :** Aucun changement de code — comprendre la distinction `id` ≠ `token` dans `InvitationPayload`.

### `Admin access required` malgré JWT role=admin
**Cause :** `acceptInvitation` utilisait `update_or_create` avec `defaults={"role": invite.role}`,
ce qui écrasait le rôle admin existant avec le rôle de l'invitation (member).
**Fix :** `get_or_create` + upgrade uniquement si `_ROLE_PRIORITY[invite.role] > _ROLE_PRIORITY[member.role]`.

---

## Comment tester (flux complet)

### 1. Démarrer

```bash
make up
# ou
docker compose up -d --build
```

### 2. Créer un compte et un workspace

```graphql
mutation { register(email: "steve@test.com", password: "test1234") { token } }  # pragma: allowlist secret
# → copier le token (user-JWT)

mutation { createWorkspace(name: "Mon Workspace") { id slug } }
# → copier le workspace id

mutation { selectWorkspace(workspaceId: "<id>") { token workspaceId role } }
# → copier le workspace-JWT — utiliser pour toutes les opérations suivantes
```

### 3. Tester l'agent

```graphql
# Générer un install token
mutation { generateInstallToken(workspaceId: "<id>") { token expiresAt } }

# Simuler l'agent (heartbeat)
mutation {
  agentHeartbeat(installToken: "wsk_xxx", clusterName: "test", k8sVersion: "1.29") {
    id name status
  }
}

# Simuler un incident
mutation {
  agentReportIncident(installToken: "wsk_xxx", podName: "api-pod", namespace: "default") {
    jobId status
  }
}
```

### 4. Tester les subscriptions (playground)

Ajouter dans Headers : `{"Authorization": "Bearer <workspace-JWT>"}`

```graphql
subscription {
  clusterConnected(workspaceId: "<id>") { id name status }
}
# → reste ouvert ; se déclenche dès qu'agentHeartbeat est appelé

subscription {
  jobStatus(jobId: "<jobId>") { jobId status result { errorType } error }
}
```

### 5. Tester les invitations

```graphql
mutation {
  inviteMember(workspaceId: "<id>", email: "colleague@test.com", role: "member") {
    id token status expiresAt   # ← utiliser le champ "token" pour acceptInvitation
  }
}

mutation {
  acceptInvitation(token: "<token du champ token, pas id>") {
    token workspaceId role
  }
}

query {
  listInvitations(workspaceId: "<id>") { id email role status }
}
```

### 6. Tests unitaires

```bash
cd services/gateway
python3 -m pytest -v
# → 95 tests, 0 failures
```
