# PodIQ — Spécification Fonctionnelle

**Version** : 2.0
**Date** : 2026-05-20
**Public cible** : Équipe frontend Angular
**Source** : `PodIQ Hi-fi.html` — 9 sections, ~30 écrans

> **Note de mise à jour v2.0** — La v1.0 décrivait une API REST imaginaire. Cette version
> reflète l'implémentation backend réelle. **Toutes les opérations passent par GraphQL**
> (`POST /graphql`) sauf l'endpoint CI/CD (`POST /api/v1/cicd/scan`). Les fonctionnalités
> non encore implémentées sont marquées **[NON IMPLÉMENTÉ]** — le frontend doit les stubber
> jusqu'à leur disponibilité backend.

---

## Index des écrans

| # | Section | Écran | Route suggérée |
|---|---------|-------|----------------|
| 01 | Acquisition | Landing marketing | `/` |
| 02 | Acquisition | Login | `/login` |
| 03 | Acquisition | Signup (3 variantes) | `/signup` |
| 04 | Acquisition | Onboarding · Workspace | `/onboarding/workspace` |
| 05 | Acquisition | Onboarding · Choose plan | `/onboarding/plan` |
| 06 | Acquisition | Onboarding · Connect cluster | `/onboarding/cluster` |
| 07 | Acquisition | Onboarding · Invite team | `/onboarding/team` |
| 08 | Acquisition | Onboarding · Wire up alerts | `/onboarding/alerts` |
| 09 | Acquisition | Onboarding · Complete | `/onboarding/complete` |
| 10 | Cluster intelligence | Cluster dashboard | `/dashboard` |
| 11 | Cluster intelligence | Incident analysis | `/incidents/:id` |
| 12 | Differentiators | Memory engine | `/memory` |
| 13 | Differentiators | Cross-service correlation | `/correlation` |
| 14 | Pre-deploy + CI/CD | Pre-deploy scan | `/predeploy` |
| 15 | Pre-deploy + CI/CD | CI/CD integration | `/cicd` |
| 16 | Drill-downs | Incident inbox | `/incidents` |
| 17 | Drill-downs | Pod detail | `/pods/:name` |
| 18 | Drill-downs | Service detail | `/services/:name` |
| 19 | Drill-downs | Cluster detail | `/clusters/:name` |
| 20 | States | Empty · Day 0 | `/dashboard` (vide) |
| 21 | States | Cluster disconnected | `/dashboard` (erreur) |
| 22 | States | Notifications inbox | `/notifications` |
| 23 | States | Command palette ⌘K | overlay global |
| 24 | Settings | Settings · Notifications | `/settings/notifications` |
| 25 | Settings | Settings · Overview | `/settings` |
| 26 | Settings sub-pages | Workspace & team | `/settings/team` |
| 27 | Settings sub-pages | Memory tuning | `/settings/memory` |
| 28 | Settings sub-pages | Billing | `/settings/billing` |
| 29 | Settings sub-pages | SSO & security | `/settings/security` |
| 30 | Settings sub-pages | Create API key (modal) | overlay |
| 31 | Edges | PR preview | `/incidents/:id/pr-preview` |
| 32 | Edges | Pod activity · 24h | `/pods/:name/activity` |
| 33 | Edges | Postmortem | `/incidents/:id/postmortem` |
| 34 | Edges | Help & docs | `/help` |
| 35 | Edges | Mobile alerts (iOS) | app iOS — hors web scope |
| 36 | Edges | Privacy + cookie banner | overlay global |

---

## Conventions transverses

### Transport — GraphQL uniquement

Toutes les opérations passent par un seul endpoint :

```
POST /graphql          ← HTTP (queries + mutations)
WS   /graphql          ← WebSocket graphql-ws (subscriptions)
POST /api/v1/cicd/scan ← REST uniquement, auth X-Api-Key
```

Le playground interactif est disponible sur `http://localhost:8080/graphql`.

### Authentification — deux étapes

Le backend utilise un JWT en deux temps. Le frontend doit appliquer ce flux sans exception.

**Étape 1 — User-JWT (auth-service)**

```graphql
mutation Login($email: String!, $password: String!) {
  login(email: $email, password: $password) {
    token      # user-JWT, signé par auth-service
    userId
    email
  }
}
```

Ce token ne contient pas de `workspace_id` ni de `role`. Il sert uniquement à l'étape 2.

**Étape 2 — Workspace-JWT (gateway)**

```graphql
mutation SelectWorkspace($workspaceId: ID!) {
  selectWorkspace(workspaceId: $workspaceId) {
    token        # workspace-JWT, signé par gateway
    userId
    email
    workspaceId
    role         # "admin" | "member" | "viewer"
  }
}
```

Ce workspace-JWT est celui à stocker en mémoire et à envoyer dans `Authorization: Bearer <token>` pour toutes les requêtes authentifiées. `selectWorkspace` pose également un cookie `httpOnly refresh_token` (30 jours).

**Refresh**

```graphql
mutation {
  refreshToken {
    token
    userId
    email
    workspaceId
    role
  }
}
```

Lit le cookie `refresh_token` httpOnly, retourne un nouveau workspace-JWT, et pose un nouveau cookie (rotation automatique). À appeler avant expiration du workspace-JWT (durée configurable via `GATEWAY_JWT_ACCESS_EXPIRY_MINUTES`, défaut 60 min).

**WebSocket (subscriptions)**

Le token doit être passé dans le payload `connection_init` :

```json
{ "Authorization": "Bearer <workspace-jwt>" }
```

**SSO (Google, GitHub, SAML) — [NON IMPLÉMENTÉ]**

### Rôles & permissions

| Rôle | Lecture | Écriture | Admin (invitations, canaux, API keys) |
|------|---------|----------|---------------------------------------|
| `viewer` | ✅ | ❌ | ❌ |
| `member` | ✅ | ✅ (analyses) | ❌ |
| `admin` | ✅ | ✅ | ✅ |

Les mutations `createAlertRule`, `toggleAlertRule`, `connectChannel`, `disconnectChannel`, `setQuietHours`, `inviteMember`, `revokeInvitation`, `generateInviteLink`, `generateInstallToken`, `updateWorkspace` exigent le rôle `admin`.

### Format des erreurs GraphQL

Les erreurs sont retournées dans le champ `errors[]` standard GraphQL. Le champ `extensions` porte le code normalisé :

```json
{
  "errors": [
    {
      "message": "Workspace name must be 2–32 characters",
      "extensions": { "code": "VALIDATION" }
    }
  ]
}
```

Codes disponibles : `VALIDATION`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `INTERNAL`.

### Pagination

Aucune pagination cursor-based n'est implémentée. Les queries retournent des listes complètes. Le paramètre `limit` est disponible sur `analysisHistory` (défaut 10).

### Modèle de données (périmètre implémenté)

```
Workspace
  ├── Members (User × Role)
  ├── Clusters (statut, last_heartbeat)
  ├── InstallTokens
  ├── Invitations (pending | accepted | revoked | expired)
  ├── AlertRules (event_type, enabled)
  ├── NotificationChannels (slack | pagerduty | email | webhook | teams | discord)
  ├── QuietHours
  └── AnalysisJobs (pending | running | complete | failed)
        └── result: AnalysisResultType

AnalysisHistory (par pod_name + namespace)
  ├── error_type, root_cause, solution, confidence
  ├── is_recurring, recurrence_count
  └── correlated_service, correlation_explanation
```

Non implémenté : Nodes, Namespaces, Services, Deploys, SLOs, métriques temps réel, billing,
incidents lifecycle (ack/dismiss), postmortem, audit log, notifications in-app.

---

# 01 · Landing marketing

## 1. Vue d'ensemble
- **Route** : `/`
- **Rôle fonctionnel** : Présenter PodIQ aux visiteurs et orienter vers Login / Signup / Demo.
- **Acteurs** : Visiteur anonyme. Pas d'auth. SEO-friendly (SSR conseillé).

## 2. Composants et données affichées

| Composant | Type | Source | Règles |
|-----------|------|--------|--------|
| Nav top (Product, Use cases, Pricing, Docs, Changelog) | Liens statiques | Front | Sticky + blur backdrop au scroll |
| Hero — H1 "Your cluster doesn't have to crash twice." | Texte | Front (CMS-able) | — |
| Tag "New · Memory engine" | Tag + lien | Front | Cliquable → `/memory` |
| CTA primaire "Connect a cluster" | Bouton | Front | → `/signup` |
| CTA secondaire "Watch 90s demo" | Bouton | Front | → modal vidéo ou `/demo` |
| Hero visual — fake terminal | Statique | Front | Maquette UI — pas de live data |
| Logo strip (Meridian, Northwind, etc.) | Logos clients | Front (CMS-able) | — |
| Three-up features (Memory / Correlation / Pre-deploy) | Cards | Front | Liens vers `/memory`, `/correlation`, `/predeploy` |
| Big CTA dark "Stop debugging the same outage twice" | Bouton | Front | → `/signup` + `/demo` |
| Footer (Privacy, Terms, Security, Status) | Liens | Front | — |

## 3. Actions utilisateur

| Action | Comportement | API |
|--------|--------------|-----|
| Clic "Sign in" | Navigue `/login` | — |
| Clic "Get started" / "Connect a cluster" | Navigue `/signup` | — |
| Clic "Watch 90s demo" | Ouvre modal vidéo | — |
| Clic "Book a demo" | → `/demo` ou Calendly | — |

## 4. États
- **Initial** : statique, aucun chargement.

## 5. Règles métier
- **RM001** — Si visiteur déjà authentifié (cookie `refresh_token` valide) → afficher CTA "Open dashboard" au lieu de "Sign in" / "Get started".

## 6. Critères d'acceptation
```gherkin
Given je suis un visiteur anonyme
When je clique sur "Get started"
Then je suis redirigé vers /signup

Given je suis authentifié
When je visite /
Then le bouton "Get started" devient "Open dashboard"
And il pointe vers /dashboard
```

---

# 02 · Login

## 1. Vue d'ensemble
- **Route** : `/login`
- **Rôle** : Authentifier un utilisateur existant via email/password.
- **Acteurs** : Utilisateur enregistré.

## 2. Composants et données affichées

| Composant | Type | Source | Règles |
|-----------|------|--------|--------|
| Email field | Input | Saisie | Format email valide |
| Password field | Input password | Saisie | Non vide |
| Bouton "Sign in" | Submit | — | Actif si email + password renseignés |
| SSO buttons (Google, GitHub, SAML) | Buttons | — | **[NON IMPLÉMENTÉ]** |
| "Forgot password?" link | Lien | — | **[NON IMPLÉMENTÉ]** → `/forgot-password` |

## 3. Actions

### Sign in (email/password)

**Étape 1 — obtenir le user-JWT :**
```graphql
mutation Login($email: String!, $password: String!) {
  login(email: $email, password: $password) {
    token
    userId
    email
  }
}
```

**Étape 2 — sélectionner un workspace (nécessaire pour obtenir le workspace-JWT) :**
```graphql
mutation SelectWorkspace($workspaceId: ID!) {
  selectWorkspace(workspaceId: $workspaceId) {
    token
    userId
    email
    workspaceId
    role
  }
}
```

Si l'utilisateur n'a pas encore de workspace → rediriger vers `/onboarding/workspace`.
Si l'utilisateur a plusieurs workspaces → afficher un picker avant l'étape 2.

Pour récupérer la liste des workspaces de l'utilisateur (avec le user-JWT de l'étape 1) :
```graphql
query {
  listWorkspaces {
    id
    name
    slug
    plan
    role
    region
  }
}
```

**Erreurs possibles :**
- `UNAUTHENTICATED` — credentials invalides
- `VALIDATION` — email mal formé

## 4. États
- **Initial** : form vide.
- **Loading** : spinner sur "Sign in" pendant l'appel.
- **Erreur credentials** : message rouge sous le password.

## 5. Règles métier
- **RM010** — Pas de rate-limiting implémenté côté backend pour l'instant.
- **RM011** — SSO non disponible. Email/password uniquement.
- **RM012** — Le cookie `refresh_token` (30 jours) est posé automatiquement par `selectWorkspace`.

## 6. Critères d'acceptation
```gherkin
Given un utilisateur valide avec un workspace existant
When il soumet email + password corrects
Then il reçoit un user-JWT (étape 1)
And il appelle selectWorkspace avec son workspaceId
Then il reçoit un workspace-JWT + cookie refresh_token
And il est redirigé vers /dashboard
```

---

# 03 · Signup

3 designs proposés (`SignupSplit`, `SignupCentered`, `SignupPlanFirst`). Tous partagent la même logique backend.

## 1. Vue d'ensemble
- **Route** : `/signup`
- **Rôle** : Créer un compte utilisateur.
- **Acteurs** : Visiteur anonyme.

## 2. Données saisies

| Champ | Type | Requis | Règles |
|-------|------|--------|--------|
| Email | string | ✅ | RFC 5322 |
| Password | string | ✅ | Non vide (backend valide uniquement la présence) |
| ToS accepted | bool | ❌ backend | À valider côté front uniquement |

> **Note** : La sélection de plan au signup (plan, billing_cycle) et la vérification email
> (`email_verified`) ne sont **pas implémentées** côté backend. Le plan peut être renseigné
> lors de `createWorkspace`. La vérification email est absente.

## 3. Actions

### Signup email/password

```graphql
mutation Register($email: String!, $password: String!) {
  register(email: $email, password: $password) {
    token    # user-JWT
    userId
    email
  }
}
```

Après registration, enchaîner directement avec `createWorkspace` (onboarding step 1).

**Erreurs possibles :**
- `CONFLICT` — email déjà utilisé
- `VALIDATION` — email mal formé

## 4. Validation password (live)
Indicateur de force côté frontend uniquement (backend ne valide pas la complexité) :
- 1 barre : 8+ chars
- 2 barres : + 1 chiffre
- 3 barres : + 1 majuscule
- 4 barres : + 1 caractère spécial

## 5. États
- **Initial**, **Loading**, **Erreur email pris** (CONFLICT), **Erreur email invalide** (VALIDATION).

## 6. Règles métier
- **RM020** — Email unique insensible à la casse — sinon CONFLICT.
- **RM021** — Plan enterprise, billing, trial : **[NON IMPLÉMENTÉ]**.
- **RM023** — Blacklist domaines jetables : **[NON IMPLÉMENTÉ]**.

## 7. Critères d'acceptation
```gherkin
Given un email non utilisé
When je soumets signup avec email + password
Then un User est créé
And je reçois un user-JWT
And je suis redirigé vers /onboarding/workspace
```

---

# 04 · Onboarding — Step 1 : Workspace

## 1. Vue d'ensemble
- **Route** : `/onboarding/workspace`
- **Rôle** : Créer et configurer le workspace (nom, couleur, taille équipe, région).
- **Précondition** : user-JWT valide (étape post-register ou post-login sans workspace).

## 2. Composants et données saisies

| Champ | Type | Requis | Règles backend |
|-------|------|--------|----------------|
| Workspace name | string | ✅ | 2–32 chars |
| Accent color | hex string | ❌ | Défaut `#6366f1` |
| Team size | enum | ❌ | `solo` \| `2_10` \| `11_50` \| `50_plus` — défaut `solo` |
| Region | enum | ❌ | `eu` \| `us` \| `ap` — défaut `eu` |
| URL slug | — | auto | Dérivé du nom par le backend, non éditable via API |
| Workspace icon | — | — | **[NON IMPLÉMENTÉ]** (champ `icon_url` absent du backend) |

## 3. Actions

### Créer le workspace

```graphql
mutation CreateWorkspace(
  $name: String!
  $region: String
  $teamSize: String
  $accentColor: String
) {
  createWorkspace(
    name: $name
    region: $region
    teamSize: $teamSize
    accentColor: $accentColor
  ) {
    id
    name
    slug
    plan
    role
    region
    teamSize
    accentColor
    createdAt
  }
}
```

Le slug est auto-dérivé du nom (ex. "Acme Platform" → `acme-platform`) et rendu unique en
suffixant un compteur si nécessaire. Il n'existe pas d'endpoint de vérification de slug
disponible — retirer ce contrôle de l'UI ou afficher le slug généré en lecture seule après
soumission.

Après `createWorkspace`, appeler immédiatement `selectWorkspace` pour obtenir le workspace-JWT :

```graphql
mutation SelectWorkspace($workspaceId: ID!) {
  selectWorkspace(workspaceId: $workspaceId) {
    token
    userId
    email
    workspaceId
    role
  }
}
```

## 4. États
- **Initial** : champs pré-remplis (name = local part de l'email).
- **Loading submit** : bouton "Continue" disabled + spinner.
- **Erreur VALIDATION** : nom trop court/long.

## 5. Règles métier
- **RM030** — Slug non éditable par l'utilisateur ; immuable après création.
- **RM031** — Region permanente. Affiché en hint.
- **RM032** — Team size = télémétrie produit, n'affecte pas les permissions.
- **RM033** — Accent color = visuel UI uniquement.

## 6. Critères d'acceptation
```gherkin
Given tous les champs valides
When je clique Continue
Then createWorkspace est appelé
And selectWorkspace est enchaîné
And je possède un workspace-JWT avec role=admin
And je suis redirigé vers /onboarding/plan
```

---

# 05 · Onboarding — Step 2 : Choose plan

## 1. Vue d'ensemble
- **Route** : `/onboarding/plan`
- **Rôle** : Choisir Free / Pro / Enterprise.

> **[NON IMPLÉMENTÉ]** — Pas d'API de plans, pas d'intégration Stripe, pas de trial.
> Le champ `plan` est une string libre stockée dans le workspace. Cette étape est
> entièrement gérée côté frontend. Le backend accepte `plan` comme paramètre de
> `createWorkspace` mais ne l'applique pas à une subscription de paiement.

## 2. Implémentation recommandée

Afficher les 3 cartes (Free / Pro / Enterprise) de manière statique. À la sélection :

```graphql
mutation UpdateWorkspace($workspaceId: ID!, $plan: String) {
  # updateWorkspace ne supporte pas le champ plan actuellement.
  # Stocker le plan choisi localement et passer à l'étape suivante.
}
```

En l'état, stocker le plan choisi en `localStorage` ou dans le state Angular uniquement ;
ne pas bloquer le flow sur un appel backend.

## 3. Règles métier (UX cible — à implémenter backend)
- **RM040** — Trial 14j sur Pro = 1 fois par workspace.
- **RM041** — Enterprise → contact sales.

---

# 06 · Onboarding — Step 3 : Connect cluster

## 1. Vue d'ensemble
- **Route** : `/onboarding/cluster`
- **Rôle** : Installer l'agent PodIQ et attendre le premier ping.

## 2. Composants

| Composant | Type | Source |
|-----------|------|--------|
| Method picker (Helm / kubectl / Terraform) | 3 cards, radio | Front state |
| Snippet d'install avec le token | `pre` | Généré côté front avec le token reçu |
| Status "Waiting for first ping" | Polling ou WS | API |
| Bouton Copy | Action | Clipboard API |

## 3. Actions

### Récupérer le token d'installation

```graphql
mutation GenerateInstallToken($workspaceId: ID!) {
  generateInstallToken(workspaceId: $workspaceId) {
    token       # ex. "wsk_3f8a92c1e4d7b6"
    workspaceId
    expiresAt
  }
}
```

TTL : 24h (géré par `expires_at`). Appeler à nouveau si expiré.

Le snippet Helm à afficher (généré côté front) :
```bash
helm install podiq-agent podiq/agent \
  --set installToken=<token> \
  --set gateway=https://<votre-domaine>/graphql
```

### Attendre le premier ping — option A : polling

```graphql
query ClusterStatus($workspaceId: ID!) {
  clusterStatus(workspaceId: $workspaceId) {
    id
    name
    k8sVersion
    status      # "connected" | "disconnected"
    lastHeartbeat
    createdAt
  }
}
```

Poller toutes les 5s jusqu'à obtenir un cluster avec `status == "connected"`.

### Attendre le premier ping — option B : subscription (recommandé)

```graphql
subscription ClusterConnected($workspaceId: ID!) {
  clusterConnected(workspaceId: $workspaceId) {
    id
    name
    k8sVersion
    status
    lastHeartbeat
  }
}
```

Via WebSocket `graphql-ws`. Le stream émet **une seule fois** dès qu'un cluster `connected`
est détecté, puis se ferme.

## 4. États
- **Idle** : badge orange "Waiting for first ping" avec animation pulse.
- **Connected** : badge vert "Connected · \<cluster-name\>" + bouton Continue activé.
- **Timeout 10 min** : afficher troubleshoot tips inline.

## 5. Règles métier
- **RM050** — L'agent envoie `agentHeartbeat` avec le token → crée le `Cluster` lié au workspace.
- **RM051** — Agent en read-only strict : pas de `exec`, pas de `port-forward`.
- **RM052** — Une connexion = un cluster. Plusieurs clusters = relancer l'install.

## 6. Critères d'acceptation
```gherkin
Given un user à l'étape Connect cluster
When l'agent envoie un agentHeartbeat valide
Then le polling ou la subscription détecte la connexion sous 10s
And le bouton Continue s'active
```

---

# 07 · Onboarding — Step 4 : Invite team

## 1. Vue d'ensemble
- **Route** : `/onboarding/team`
- **Rôle** : Inviter des coéquipiers.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Email input + role select + bouton Add | Saisie |
| Liste invites pending | `listInvitations` |
| Role explainer (Admin/Member/Viewer) | Statique |
| Toggle auto-invite by domain | **[NON IMPLÉMENTÉ]** |
| Copy invite link | `generateInviteLink` |

## 3. Actions

### Ajouter une invitation

```graphql
mutation InviteMember($workspaceId: ID!, $email: String!, $role: String) {
  inviteMember(workspaceId: $workspaceId, email: $email, role: $role) {
    id
    token
    email
    role
    status    # "pending"
    expiresAt
    createdAt
  }
}
```

Rôles acceptés : `"admin"` | `"member"` | `"viewer"`. Défaut : `"member"`.

### Lister les invitations

```graphql
query ListInvitations($workspaceId: ID!, $status: String) {
  listInvitations(workspaceId: $workspaceId, status: $status) {
    id
    email
    role
    status    # "pending" | "accepted" | "revoked" | "expired"
    expiresAt
    createdAt
  }
}
```

### Révoquer une invitation

```graphql
mutation RevokeInvitation($invitationId: ID!) {
  revokeInvitation(invitationId: $invitationId)
}
```

### Générer un lien d'invitation (ouvert, sans email cible)

```graphql
mutation GenerateInviteLink($workspaceId: ID!) {
  generateInviteLink(workspaceId: $workspaceId) {
    token      # UUID — construire le lien : /join/<token>
    expiresAt
  }
}
```

Le frontend construit le lien : `https://<domaine>/join/<token>`.
La route `/join/:token` appelle `acceptInvitation(token)`.

### Accepter une invitation (route `/join/:token`)

L'utilisateur doit être authentifié (user-JWT ou workspace-JWT) avant d'appeler :

```graphql
mutation AcceptInvitation($token: String!) {
  acceptInvitation(token: $token) {
    token        # nouveau workspace-JWT
    workspaceId
    role
    userId
    email
  }
}
```

Retourne un workspace-JWT pour le workspace de l'invitation. Upgrade-only du rôle (jamais de downgrade).

## 4. États
- Invite list vide → "No invites yet".
- Status par invite : `pending` (⏱), `accepted` (✅), `revoked` (❌), `expired` (🕐).

## 5. Règles métier
- **RM060** — Invitation expire après 7 jours.
- **RM061** — Seul un admin peut inviter et révoquer.
- **RM062** — Auto-invite par domaine : **[NON IMPLÉMENTÉ]**.
- **RM063** — Limites membres par plan : **[NON IMPLÉMENTÉ]** côté backend.

---

# 08 · Onboarding — Step 5 : Wire up alerts

## 1. Vue d'ensemble
- **Route** : `/onboarding/alerts`
- **Rôle** : Configurer les règles d'alerte et les canaux de notification.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Toggles règles d'alerte | `createAlertRule` + `toggleAlertRule` |
| 6 channel cards (Slack, PagerDuty, Email, Webhook, Teams, Discord) | `connectChannel` |
| Quiet hours | `setQuietHours` |

## 3. Actions

### Créer une règle d'alerte

```graphql
mutation CreateAlertRule($workspaceId: ID!, $eventType: String!, $name: String) {
  createAlertRule(workspaceId: $workspaceId, eventType: $eventType, name: $name) {
    id
    workspaceId
    name
    eventType
    enabled
    createdAt
  }
}
```

`eventType` acceptés (valeurs de l'enum `AlertRule.EventType` backend) : à confirmer selon
le modèle Django — utiliser les valeurs retournées par les règles existantes.

### Activer / désactiver une règle

```graphql
mutation ToggleAlertRule($ruleId: ID!, $enabled: Boolean!) {
  toggleAlertRule(ruleId: $ruleId, enabled: $enabled) {
    id
    enabled
  }
}
```

### Connecter un canal de notification

```graphql
mutation ConnectChannel($workspaceId: ID!, $channelType: String!, $config: String!) {
  connectChannel(workspaceId: $workspaceId, channelType: $channelType, config: $config) {
    id
    workspaceId
    type
    enabled
    createdAt
  }
}
```

`channelType` : `"slack"` | `"pagerduty"` | `"email"` | `"webhook"` | `"teams"` | `"discord"`.

`config` est un **JSON sérialisé en string**. Exemples :
```json
// Slack
"{\"webhook_url\": \"https://hooks.slack.com/...\"}"

// PagerDuty
"{\"integration_key\": \"abc123\"}"

// Email
"{\"email\": \"ops@acme.io\"}"

// Webhook
"{\"url\": \"https://mon-serveur.io/podiq\", \"secret\": \"xyz\"}"

// Teams
"{\"webhook_url\": \"https://...\"}"

// Discord
"{\"webhook_url\": \"https://discord.com/api/webhooks/...\"}"
```

> **Pas d'OAuth redirect** — la configuration se fait par saisie directe des credentials
> (webhook URL, clé d'intégration, etc.).

### Déconnecter un canal

```graphql
mutation DisconnectChannel($channelId: ID!) {
  disconnectChannel(channelId: $channelId)
}
```

### Configurer les quiet hours

```graphql
mutation SetQuietHours(
  $workspaceId: ID!
  $enabled: Boolean!
  $startTime: String!
  $endTime: String!
  $timezone: String
  $weekdaysOnly: Boolean
) {
  setQuietHours(
    workspaceId: $workspaceId
    enabled: $enabled
    startTime: $startTime
    endTime: $endTime
    timezone: $timezone
    weekdaysOnly: $weekdaysOnly
  ) {
    id
    enabled
    startTime
    endTime
    timezone
    weekdaysOnly
  }
}
```

`startTime` / `endTime` : format `"HH:MM"` (ex. `"22:00"`, `"07:00"`).
`timezone` : IANA timezone (ex. `"Europe/Paris"`). Défaut `"UTC"`.

> **[NON IMPLÉMENTÉ]** — Il n'existe pas de query pour lister les règles existantes ou les
> canaux connectés. Le frontend doit maintenir l'état local jusqu'à l'implémentation des
> queries correspondantes.

## 4. États
- Channel connecté → tag vert + bouton Disconnect.
- Quiet hours actives → range affichée.

## 5. Règles métier
- **RM070** — Admin requis pour toutes ces mutations.
- **RM071** — Quiet hours ne bloque pas les alertes critiques (à implémenter dans l'envoi).
- **RM072** — Webhook nécessite URL `https://`.
- **RM073** — Dedupe : **[NON IMPLÉMENTÉ]**.

---

# 09 · Onboarding — Complete

## 1. Vue d'ensemble
- **Route** : `/onboarding/complete`
- **Rôle** : Confirmer la fin de l'onboarding.

## 2. Composants
- Big checkmark.
- Recap (workspace name, cluster, channels).
- Suggested next (add 2e cluster, install GitHub Action, take tour).

## 3. Actions

Marquer le workspace comme onboardé :

```graphql
mutation UpdateWorkspace($workspaceId: ID!, $name: String) {
  updateWorkspace(workspaceId: $workspaceId) {
    id
    onboardedAt
  }
}
```

> **Note** : `updateWorkspace` ne prend pas `onboarded_at` en paramètre explicite — ce champ
> est géré côté backend. À confirmer si l'update sans champs modifiés suffit à le setter,
> ou si un champ dédié doit être ajouté au backend.

- CTA "Open dashboard" → `/dashboard`.
- CTA "Take the tour" → flag `tour_seen` en `localStorage`.

## 5. Règles métier
- **RM080** — `workspace.onboarded_at` est présent dans `WorkspaceType`.

---

# 10 · Cluster dashboard

## 1. Vue d'ensemble
- **Route** : `/dashboard`
- **Rôle** : Vue principale santé cluster.

## 2. Composants implémentés

| Composant | Donnée | Source |
|-----------|--------|--------|
| Liste clusters | statut + last_heartbeat | `clusterStatus` |
| Analyses récentes (incidents) | historique par pod | `analysisHistory` |
| Subscription connexion cluster | temps réel | `clusterConnected` |
| Subscription statut job | temps réel | `jobStatus` |

## 2b. Composants non implémentés **[NON IMPLÉMENTÉ]**

| Composant | Roadmap |
|-----------|---------|
| KPI MTTR | Métriques agrégées — backend non implémenté |
| KPI Pages / Healthy pods | idem |
| Liste services + sparklines | Pas d'API services |
| Recent deploys | Pas d'API deploys |
| Cluster switcher avec métriques | Données basiques disponibles via `clusterStatus` |

## 3. Actions

### Récupérer les clusters du workspace

```graphql
query ClusterStatus($workspaceId: ID!) {
  clusterStatus(workspaceId: $workspaceId) {
    id
    name
    k8sVersion
    status          # "connected" | "disconnected"
    workspaceId
    lastHeartbeat   # ISO datetime ou null
    createdAt
  }
}
```

### Récupérer l'historique des analyses (feed d'incidents)

```graphql
query AnalysisHistory($podName: String!, $namespace: String!, $limit: Int) {
  analysisHistory(podName: $podName, namespace: $namespace, limit: $limit) {
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

> `analysisHistory` requiert `podName` + `namespace`. Pour le dashboard global, il n'existe
> pas de query "tous les incidents du workspace". À implémenter backend ou afficher l'historique
> des pods les plus récents connus du frontend.

### Subscription cluster connecté

```graphql
subscription ClusterConnected($workspaceId: ID!) {
  clusterConnected(workspaceId: $workspaceId) {
    id
    name
    status
    lastHeartbeat
  }
}
```

## 4. États
- **Loading** : skeleton + shimmer.
- **Empty** : voir écran 20 (Day 0) — `clusterStatus` retourne liste vide.
- **Disconnected** : voir écran 21 — `status == "disconnected"` ou `lastHeartbeat > 2 min`.
- **Nominal** : liste clusters + analyses récentes.

## 5. Règles métier
- **RM100** — Rafraîchissement toutes les 30s (polling `clusterStatus`) ou via subscription.
- **RM101** — Si `last_heartbeat > 2 min` → état `disconnected`.

---

# 11 · Incident analysis

## 1. Vue d'ensemble
- **Route** : `/incidents/:jobId`
- **Rôle** : Lancer et afficher le diagnostic d'un incident — root cause, confidence, mémoire, corrélation.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Header (pod, namespace, statut job) | `analysisJob` |
| Root cause + confidence % | `job.result.rootCause` + `job.result.confidence` |
| Explanation | `job.result.explanation` |
| Solution proposée | `job.result.solution` |
| Type d'erreur | `job.result.errorType` |
| Récurrence (Memory recall) | `job.result.isRecurring` + `job.result.recurrenceCount` |
| Corrélation inter-services | `job.result.correlatedService` + `job.result.correlationExplanation` |
| Progression temps réel | `jobStatus` subscription |

## 3. Actions

### Lancer une analyse

```graphql
mutation AnalyzeIncident(
  $podName: String!
  $namespace: String!
  $logs: String
  $events: String
  $describeOutput: String
) {
  analyzeIncident(
    podName: $podName
    namespace: $namespace
    logs: $logs
    events: $events
    describeOutput: $describeOutput
  ) {
    jobId
    status    # "pending"
    createdAt
  }
}
```

L'analyse est **asynchrone**. La mutation retourne immédiatement un `jobId`. Suivre la
progression via polling ou subscription.

### Suivre le statut — polling

```graphql
query AnalysisJob($jobId: ID!) {
  analysisJob(jobId: $jobId) {
    jobId
    status      # "pending" | "running" | "complete" | "failed"
    error
    createdAt
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
  }
}
```

### Suivre le statut — subscription (recommandé)

```graphql
subscription JobStatus($jobId: ID!) {
  jobStatus(jobId: $jobId) {
    jobId
    status
    error
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
  }
}
```

Le stream émet à chaque changement de statut et s'arrête quand `status == "complete"` ou `"failed"`.

## 4. États
- `pending` / `running` : spinner + "Analyzing..."
- `complete` : affichage complet du résultat.
- `failed` : afficher `job.error`.

## 5. Règles métier
- **RM110** — Apply fix, dismiss, acknowledge : **[NON IMPLÉMENTÉ]**.
- **RM111** — Confidence < 50% → afficher warning "Low confidence" côté front.
- **RM112** — Ré-ouverture d'incident : **[NON IMPLÉMENTÉ]**.

---

# 12 · Memory engine

## 1. Vue d'ensemble
- **Route** : `/memory`
- **Rôle** : Visualiser les patterns récurrents détectés par le moteur de mémoire.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Table analyses récurrentes | `analysisHistory` filtré sur `isRecurring == true` |
| Colonnes : pod, namespace, error type, occurrences, root cause | idem |
| Détail panel (clic ligne) | champs de `AnalysisHistoryItem` |

## 3. Actions

```graphql
query AnalysisHistory($podName: String!, $namespace: String!, $limit: Int) {
  analysisHistory(podName: $podName, namespace: $namespace, limit: $limit) {
    id
    podName
    namespace
    errorType
    rootCause
    isRecurring
    recurrenceCount
    createdAt
    analysisType
  }
}
```

Filtrer côté frontend sur `isRecurring == true`.

> **[NON IMPLÉMENTÉ]** — Il n'y a pas de query globale "tous les patterns du workspace".
> La gestion de patterns (édition, suppression, blacklist) n'est pas disponible.

## 4. Règles métier
- **RM120** — Expiration des patterns : **[NON IMPLÉMENTÉ]**.
- **RM121** — Patterns privés au workspace.

---

# 13 · Cross-service correlation

## 1. Vue d'ensemble
- **Route** : `/correlation` ou intégré dans l'écran 11 (incident analysis).

## 2. Composants
- Affichage de `correlatedService` et `correlationExplanation` issus de `AnalysisResultType`.
- Graphe SVG de dépendances : **[NON IMPLÉMENTÉ]** côté backend.

## 3. Données disponibles

Les champs de corrélation sont disponibles dans le résultat d'une analyse :

```graphql
result {
  correlatedService        # nom du service corrélé (ou null)
  correlationExplanation   # explication textuelle (ou null)
}
```

> Une API dédiée `/api/correlations` avec graphe (nodes/edges) n'existe pas. La corrélation
> est une info textuelle enrichie par le moteur AI, pas un graphe de dépendances calculé.

## 4. Règles métier
- **RM130** — Corrélation basée sur la fenêtre temporelle `CORRELATION_WINDOW_MINUTES` (défaut 15 min) et les données `namespace_pods` envoyées par l'agent.

---

# 14 · Pre-deploy scan

## 1. Vue d'ensemble
- **Route** : `/predeploy`
- **Rôle** : Scanner un manifeste K8s avant deploy.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Upload zone / paste YAML | Saisie |
| Risk level (low \| medium \| high \| critical) | `scanManifest.riskLevel` |
| Summary textuel | `scanManifest.summary` |
| Liste risques | `scanManifest.risks[]` |

## 3. Actions

### Scanner via GraphQL (frontend web)

```graphql
mutation ScanManifest($yamlContent: String!, $manifestType: String) {
  scanManifest(yamlContent: $yamlContent, manifestType: $manifestType) {
    riskLevel    # "low" | "medium" | "high" | "critical"
    summary
    risks {
      severity     # "low" | "medium" | "high" | "critical"
      category
      description
      fix
    }
  }
}
```

`manifestType` : optionnel (ex. `"Deployment"`, `"StatefulSet"`).

### Scanner via REST (CI/CD pipeline)

```
POST /api/v1/cicd/scan
Header: X-Api-Key: <api_key>
Content-Type: text/plain (ou application/x-yaml)
Body: <contenu YAML brut>
```

Exit codes : `0` (OK), `1` (warning), `2` (bloquant).

## 4. Règles métier
- **RM140** — Score de sécurité numérique (0-100) : **[NON IMPLÉMENTÉ]** — le backend retourne `riskLevel` (enum), pas un score numérique.
- **RM141** — Risques groupés par sévérité côté frontend.

---

# 15 · CI/CD integration

## 1. Vue d'ensemble
- **Route** : `/cicd`
- **Rôle** : Gérer les API keys pour pipelines CI/CD.

## 2. Composants
- Liste API keys existantes. **[NON IMPLÉMENTÉ]** — pas de query pour lister les keys.
- Bouton "Create key" → modal écran 30.
- Snippets GitHub Actions / GitLab CI (statiques côté frontend).

## 3. Actions

### Créer une API key

```graphql
mutation CreateApiKey($name: String!) {
  createApiKey(name: $name) {
    keyId
    rawKey     # valeur brute — afficher UNE SEULE FOIS
    name
    createdAt
  }
}
```

> Pas de `scopes` ni de `expiresAt` — ces champs ne sont pas implémentés.

### Révoquer une API key

```graphql
mutation RevokeApiKey($keyId: String!) {
  revokeApiKey(keyId: $keyId)
}
```

## 4. Règles métier
- **RM150** — `rawKey` affiché une seule fois. Non récupérable ensuite.
- **RM151** — Scopes : **[NON IMPLÉMENTÉ]**.
- **RM152** — La key s'utilise dans `POST /api/v1/cicd/scan` via `X-Api-Key: <rawKey>`.

---

# 16 · Incident inbox

## 1. Vue d'ensemble
- **Route** : `/incidents`
- **Rôle** : Liste paginée de toutes les analyses.

## 2. Composants
- Table analyses : pod, namespace, error type, confidence, date, is_recurring.
- Filtres : analysis_type, is_recurring.

## 3. Actions

> **[NON IMPLÉMENTÉ]** — Il n'existe pas de query "tous les incidents du workspace". La query
> `analysisHistory` requiert `podName` + `namespace`. Une query globale workspace-level est
> nécessaire côté backend pour cet écran.

En attendant, afficher les analyses récentes depuis les pods suivis ou un état vide.

## 4. Règles métier
- **RM160** — Bulk ack / dismiss : **[NON IMPLÉMENTÉ]**.

---

# 17 · Pod detail

## 1. Vue d'ensemble
- **Route** : `/pods/:name`
- **Rôle** : Détail complet d'un pod.

## 2. Composants disponibles
- Historique des analyses du pod via `analysisHistory(podName, namespace)`.
- Lancer une nouvelle analyse via `analyzeIncident`.

## 3. APIs

```graphql
query AnalysisHistory($podName: String!, $namespace: String!) {
  analysisHistory(podName: $podName, namespace: $namespace, limit: 20) {
    id
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

> **[NON IMPLÉMENTÉ]** — Events en temps réel, logs récents, métriques CPU/RAM, heatmap
> restarts : ces données proviennent de l'agent K8s et ne sont pas exposées via l'API gateway.

## 4. Règles métier
- **RM170** — Restart pod : **[NON IMPLÉMENTÉ]** (agent read-only strict).

---

# 18 · Service detail

## 1. Vue d'ensemble
- **Route** : `/services/:name`
- **Rôle** : Vue agrégée d'un service.

> **[NON IMPLÉMENTÉ]** — Le concept de "Service" (regroupement de pods) n'existe pas dans
> le backend actuel. Seuls les pods individuels sont trackés via `analysisHistory`.
> Cet écran nécessite une implémentation backend dédiée.

---

# 19 · Cluster detail

## 1. Vue d'ensemble
- **Route** : `/clusters/:name`
- **Rôle** : Vue de bas niveau d'un cluster.

## 2. Données disponibles

```graphql
query ClusterStatus($workspaceId: ID!) {
  clusterStatus(workspaceId: $workspaceId) {
    id
    name
    k8sVersion
    status
    lastHeartbeat
    createdAt
  }
}
```

> **[NON IMPLÉMENTÉ]** — Nodes, capacité CPU/RAM, namespaces, agent version : non exposés
> par l'API.

---

# 20 · Empty state (Day 0 dashboard)

## 1. Vue d'ensemble
- **Route** : `/dashboard` quand `clusterStatus` retourne une liste vide.

## 2. Composants
- Illustration "no data yet".
- CTA "Connect a cluster" → `/onboarding/cluster`.

## 3. Règles métier
- **RM200** — Si `clusterStatus([workspaceId]).length == 0` → afficher cet état.

---

# 21 · Cluster disconnected

## 1. Vue d'ensemble
- Bannière ou état d'erreur sur le dashboard.
- Déclencheur : `cluster.status == "disconnected"` ou `lastHeartbeat` > 2 min.

## 2. Composants
- Banner "Cluster \<name\> hasn't pinged in Xm".
- Troubleshooting steps (kubectl get pods, restart agent).
- `lastHeartbeat` affiché.

## 3. Règles métier
- **RM210** — `lastHeartbeat > 2 min` → état warning.
- **RM211** — `> 10 min` → état critical + email admin : **[NON IMPLÉMENTÉ]** (email automatique).

---

# 22 · Notifications inbox

## 1. Vue d'ensemble
- **Route** : `/notifications`

> **[NON IMPLÉMENTÉ]** — Les notifications in-app (centre de notifications, mark as read)
> ne sont pas implémentées. Les notifications externes (Slack, email, etc.) sont envoyées
> par le backend via Dramatiq mais ne sont pas listables depuis l'API.

---

# 23 · Command palette ⌘K

## 1. Vue d'ensemble
- Overlay global, déclenché par `⌘K` / `Ctrl+K`.

> **[NON IMPLÉMENTÉ]** — Pas d'endpoint de recherche globale. Implémenter côté frontend
> uniquement sur les données déjà chargées (clusters, analyses récentes) avec filtrage local.

---

# 24-25 · Settings (Overview + Notifications)

## 1. Vue d'ensemble
- **Route** : `/settings`, `/settings/notifications`

## 2. Composants Overview
- Liste sections : Workspace & team, Notifications, Memory, Billing, Security, API keys.

## 3. Composants Notifications
- Channels (réutilise `connectChannel` / `disconnectChannel`).
- Règles d'alerte (réutilise `createAlertRule` / `toggleAlertRule`).
- Quiet hours (réutilise `setQuietHours`).

Voir les mutations détaillées en section 08.

---

# 26 · Workspace & team

## 1. Vue d'ensemble
- **Route** : `/settings/team`
- **Rôle** : Gérer membres + invitations + rôles.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Table membres | **[NON IMPLÉMENTÉ]** — pas de query `listMembers` |
| Invitations pending | `listInvitations(workspaceId, status: "pending")` |
| Bouton "Invite member" | `inviteMember` |
| Révoquer invitation | `revokeInvitation` |
| Modifier rôle / retirer membre | **[NON IMPLÉMENTÉ]** |

## 3. APIs disponibles

```graphql
query ListInvitations($workspaceId: ID!) {
  listInvitations(workspaceId: $workspaceId) {
    id
    email
    role
    status
    expiresAt
    createdAt
  }
}
```

```graphql
mutation InviteMember($workspaceId: ID!, $email: String!, $role: String) {
  inviteMember(workspaceId: $workspaceId, email: $email, role: $role) {
    id
    email
    role
    status
    expiresAt
  }
}
```

## 4. Règles métier
- **RM260** — 1 admin minimum par workspace : **[NON IMPLÉMENTÉ]** côté backend (à valider côté front).
- **RM261** — Changement de rôle / suppression de membre : **[NON IMPLÉMENTÉ]**.

---

# 27 · Memory engine · tuning

## 1. Vue d'ensemble
- **Route** : `/settings/memory`

> **[NON IMPLÉMENTÉ]** — Configuration du moteur de mémoire (sensibilité, expiry, blacklist)
> non exposée par l'API. Le moteur tourne avec ses paramètres par défaut.

---

# 28 · Billing

## 1. Vue d'ensemble
- **Route** : `/settings/billing`

> **[NON IMPLÉMENTÉ]** — Aucune intégration Stripe ni gestion de subscription.
> Le champ `plan` du workspace est une string stockée localement (pas de paiement).

---

# 29 · SSO & security

## 1. Vue d'ensemble
- **Route** : `/settings/security`

> **[NON IMPLÉMENTÉ]** — SSO SAML/OIDC, force SSO, sessions actives, 2FA, audit log :
> non implémentés.

---

# 30 · Create API key (modal)

## 1. Vue d'ensemble
- Overlay sur `/settings/api-keys` ou `/cicd`.

## 2. Composants
- Input name.
- Bouton Create.
- Affichage one-shot de la clé.

> `scopes` et `expires_at` ne sont pas implémentés — retirer ces champs de l'UI ou les
> afficher comme "coming soon".

## 3. APIs

```graphql
mutation CreateApiKey($name: String!) {
  createApiKey(name: $name) {
    keyId
    rawKey    # afficher UNE SEULE FOIS, ne pas stocker
    name
    createdAt
  }
}
```

## 4. Règles métier
- **RM300** — `rawKey` non re-affichable. Hash stocké backend.
- **RM301** — Limite de 20 keys/workspace : **[NON IMPLÉMENTÉ]** côté backend.

---

# 31 · PR preview (Apply fix)

## 1. Vue d'ensemble
- **Route** : `/incidents/:id/pr-preview`

> **[NON IMPLÉMENTÉ]** — Création de PR GitHub non implémentée.

---

# 32 · Pod activity · 24h

## 1. Vue d'ensemble
- **Route** : `/pods/:name/activity`

> **[NON IMPLÉMENTÉ]** — Heatmap / timeline d'events non disponible via l'API.

---

# 33 · Postmortem

## 1. Vue d'ensemble
- **Route** : `/incidents/:id/postmortem`

> **[NON IMPLÉMENTÉ]** — Génération de postmortem non disponible.

---

# 34 · Help & docs

## 1. Vue d'ensemble
- **Route** : `/help`

> **[NON IMPLÉMENTÉ]** — Pas d'API de recherche docs ni de système de tickets.

---

# 35 · Mobile alerts (iOS) — [HORS SCOPE WEB]

Écran natif iOS. Spec mobile séparée.

> **[NON IMPLÉMENTÉ]** — Push notifications APNs et device registration non implémentés.

---

# 36 · Privacy + cookie banner

## 1. Vue d'ensemble
- Overlay sur première visite anonyme.
- **Rôle** : Conformité RGPD / CCPA.

## 2. Implémentation
- Géré entièrement côté frontend (localStorage / cookie consent 1 an).
- Pas d'API backend dédiée.

## 3. Règles métier
- **RM360** — Visiteurs EU : opt-in explicite obligatoire pour analytics/marketing.
- **RM361** — Cookie consent expire 12 mois.

---

## Annexe A — Récapitulatif des opérations GraphQL implémentées

### Mutations

| Opération | Paramètres | Retour | Auth requise |
|-----------|-----------|--------|--------------|
| `register` | `email`, `password` | `AuthPayload` | Non |
| `login` | `email`, `password` | `AuthPayload` | Non |
| `createApiKey` | `name` | `ApiKeyPayload` | user-JWT |
| `revokeApiKey` | `keyId` | `Boolean` | workspace-JWT |
| `createWorkspace` | `name`, `region?`, `teamSize?`, `accentColor?` | `WorkspaceType` | user-JWT |
| `selectWorkspace` | `workspaceId` | `WorkspaceAuthPayload` | user-JWT |
| `refreshToken` | — | `WorkspaceAuthPayload` | cookie refresh |
| `updateWorkspace` | `workspaceId`, `name?`, `accentColor?`, `teamSize?` | `WorkspaceType` | workspace-JWT admin |
| `analyzeIncident` | `podName`, `namespace`, `logs?`, `events?`, `describeOutput?` | `AnalysisJobType` | workspace-JWT |
| `scanManifest` | `yamlContent`, `manifestType?` | `ManifestScanResultType` | workspace-JWT |
| `generateInstallToken` | `workspaceId` | `InstallTokenPayload` | workspace-JWT admin |
| `agentHeartbeat` | (usage agent uniquement) | — | install token |
| `agentReportIncident` | (usage agent uniquement) | — | install token |
| `inviteMember` | `workspaceId`, `email`, `role?` | `InvitationPayload` | workspace-JWT admin |
| `revokeInvitation` | `invitationId` | `Boolean` | workspace-JWT admin |
| `acceptInvitation` | `token` | `WorkspaceAuthPayload` | user-JWT |
| `generateInviteLink` | `workspaceId` | `InvitationPayload` | workspace-JWT admin |
| `createAlertRule` | `workspaceId`, `eventType`, `name?` | `AlertRuleType` | workspace-JWT admin |
| `toggleAlertRule` | `ruleId`, `enabled` | `AlertRuleType` | workspace-JWT admin |
| `connectChannel` | `workspaceId`, `channelType`, `config` (JSON string) | `ChannelPayload` | workspace-JWT admin |
| `disconnectChannel` | `channelId` | `Boolean` | workspace-JWT admin |
| `setQuietHours` | `workspaceId`, `enabled`, `startTime`, `endTime`, `timezone?`, `weekdaysOnly?` | `QuietHoursType` | workspace-JWT admin |

### Queries

| Opération | Paramètres | Retour | Auth requise |
|-----------|-----------|--------|--------------|
| `listWorkspaces` | — | `[WorkspaceType]` | user-JWT |
| `currentWorkspace` | — | `WorkspaceType?` | workspace-JWT |
| `clusterStatus` | `workspaceId` | `[ClusterType]` | workspace-JWT |
| `analysisJob` | `jobId` | `AnalysisJobType` | workspace-JWT |
| `analysisHistory` | `podName`, `namespace`, `limit?`, `analysisType?` | `[AnalysisHistoryItem]` | workspace-JWT |
| `listInvitations` | `workspaceId`, `status?` | `[InvitationPayload]` | workspace-JWT admin |

### Subscriptions (WebSocket `graphql-ws`)

| Opération | Paramètres | Retour | Auth requise |
|-----------|-----------|--------|--------------|
| `clusterConnected` | `workspaceId` | `ClusterType` (stream) | workspace-JWT |
| `jobStatus` | `jobId` | `AnalysisJobType` (stream) | workspace-JWT |

### REST

| Endpoint | Auth | Usage |
|----------|------|-------|
| `POST /api/v1/cicd/scan` | `X-Api-Key: <rawKey>` | Scanner un YAML depuis un pipeline CI/CD |
| `GET /healthz` | Aucune | Healthcheck |

---

## Annexe B — Types GraphQL

```typescript
// AuthPayload — retourné par register + login
{ token: string; userId: string; email: string }

// WorkspaceAuthPayload — retourné par selectWorkspace + refreshToken + acceptInvitation
{ token: string; userId: string; email: string; workspaceId: string; role: string }

// WorkspaceType
{
  id: string; name: string; slug: string; plan: string; role: string;
  region: string; teamSize: string; accentColor: string;
  onboardedAt: string | null; createdAt: string
}

// ClusterType
{
  id: string; name: string; k8sVersion: string; status: string;
  workspaceId: string; lastHeartbeat: string | null; createdAt: string
}

// AnalysisJobType
{
  jobId: ID; status: string; error: string | null; createdAt: string;
  result: AnalysisResultType | null
}

// AnalysisResultType
{
  errorType: string; rootCause: string; explanation: string;
  solution: string; confidence: string; isRecurring: boolean;
  recurrenceCount: number; correlatedService: string | null;
  correlationExplanation: string | null
}

// AnalysisHistoryItem
{
  id: string; podName: string; namespace: string; errorType: string;
  rootCause: string; solution: string; confidence: string;
  isRecurring: boolean; recurrenceCount: number;
  createdAt: string; analysisType: string; riskLevel: string
}

// ManifestScanResultType
{
  riskLevel: string;  // "low" | "medium" | "high" | "critical"
  summary: string;
  risks: Array<{ severity: string; category: string; description: string; fix: string }>
}

// ApiKeyPayload
{ keyId: string; rawKey: string; name: string; createdAt: string }

// InstallTokenPayload
{ token: string; workspaceId: string; expiresAt: string }

// InvitationPayload
{
  id: string; token: string; email: string; role: string;
  status: string; expiresAt: string; createdAt: string
}

// AlertRuleType
{ id: string; workspaceId: string; name: string; eventType: string; enabled: boolean; createdAt: string }

// ChannelPayload
{ id: string; workspaceId: string; type: string; enabled: boolean; createdAt: string }

// QuietHoursType
{
  id: string; workspaceId: string; enabled: boolean;
  startTime: string; endTime: string; timezone: string; weekdaysOnly: boolean
}
```

---

## Annexe C — Fonctionnalités [NON IMPLÉMENTÉ] — Roadmap backend

| Fonctionnalité | Écrans concernés | Complexité estimée |
|----------------|------------------|--------------------|
| SSO (Google, GitHub, SAML) | 02, 29 | Haute |
| Vérification email | 03 | Moyenne |
| Billing / Stripe | 05, 28 | Haute |
| Slug check endpoint | 04 | Faible |
| Upload icon workspace | 04 | Faible |
| Query listMembers | 26 | Faible |
| Changement rôle / remove member | 26 | Faible |
| Incident lifecycle (ack, dismiss) | 11, 16 | Moyenne |
| Query incidents globale (workspace) | 10, 16 | Faible |
| Apply fix / PR GitHub | 11, 31 | Haute |
| Métriques cluster (KPIs, timeseries) | 10, 17, 18, 19 | Haute |
| API services + namespaces + nodes | 18, 19 | Moyenne |
| Notifications inbox (in-app) | 22 | Moyenne |
| Recherche globale (⌘K) | 23 | Moyenne |
| Memory tuning config | 27 | Faible |
| Postmortem | 33 | Moyenne |
| Pod activity timeline | 32 | Moyenne |
| Push notifications iOS | 35 | Haute |
| Query listAlertRules | 08, 24 | Faible |
| Query listChannels | 08, 24 | Faible |
| Rate limiting login | 02 | Faible |

---

## Annexe D — Glossaire

| Terme | Définition |
|-------|------------|
| user-JWT | Token signé par auth-service, ne contient pas de workspace_id. Durée courte. |
| workspace-JWT | Token signé par gateway, contient workspace_id + role. Durée configurable (défaut 60 min). |
| refresh_token | Cookie httpOnly signé par gateway. Durée 30 jours. Rotation à chaque appel refreshToken. |
| Workspace | Unité d'isolation tenant. 1 user peut appartenir à plusieurs. |
| Cluster | Cluster Kubernetes connecté via l'agent PodIQ. |
| Pod | Unité K8s trackée par l'agent. |
| AnalysisJob | Job d'analyse async créé par `analyzeIncident`. Suivi via `analysisJob` ou `jobStatus`. |
| Memory pattern | Détection de récurrence : `isRecurring=true` + `recurrenceCount` dans `AnalysisResultType`. |
| Confidence | Score textuel (ex. "high", "medium", "low") retourné par le LLM. |
| Heartbeat | Ping périodique de l'agent (toutes les 30s) via `agentHeartbeat`. |
| install_token | Token `wsk_xxx` généré par `generateInstallToken`, utilisé par l'agent pour s'identifier. |

---

**Fin du document.**
