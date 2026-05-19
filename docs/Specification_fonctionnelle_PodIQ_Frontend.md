# PodIQ — Spécification Fonctionnelle

**Version** : 1.0
**Date** : 2026-05-18
**Public cible** : Équipe backend (Django / DRF)
**Source** : `PodIQ Hi-fi.html` — 9 sections, ~30 écrans

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

### Authentification
- Toutes les routes hors `/`, `/login`, `/signup`, `/help`, `/legal/*` exigent un JWT valide dans `Authorization: Bearer <token>`.
- Le JWT porte `workspace_id`, `user_id`, `role` (`admin` | `member` | `viewer`).
- Refresh via `POST /api/auth/refresh` avec un cookie `httpOnly` `refresh_token`.

### Format de réponse standard
```json
{
  "data": { ... } | [ ... ],
  "meta": { "page": 1, "per_page": 50, "total": 1247, "next": "..." }
}
```
Erreurs :
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Workspace name must be lowercase.",
    "fields": { "workspace.name": "must be lowercase" }
  }
}
```

### Codes d'erreur normalisés
| Code HTTP | `error.code` | Sens |
|-----------|--------------|------|
| 400 | `VALIDATION_FAILED` | Payload invalide |
| 401 | `UNAUTHENTICATED` | Pas de JWT ou expiré |
| 403 | `FORBIDDEN` | Rôle insuffisant |
| 404 | `NOT_FOUND` | Ressource absente |
| 409 | `CONFLICT` | Ressource existe déjà (slug pris, etc.) |
| 422 | `BUSINESS_RULE_VIOLATION` | Règle métier (RMxxx) bloquée |
| 429 | `RATE_LIMITED` | Throttling |
| 503 | `CLUSTER_DISCONNECTED` | Agent K8s injoignable |

### Pagination
- Cursor-based par défaut sur les listes longues (incidents, events).
- Paramètres : `?cursor=<opaque>&limit=50`.

### Rôles & permissions
| Rôle | Lecture | Écriture | Admin (billing/SSO/API keys) |
|------|---------|----------|-------------------------------|
| `viewer` | ✅ | ❌ | ❌ |
| `member` | ✅ | ✅ (incidents, fixes, PR) | ❌ |
| `admin` | ✅ | ✅ | ✅ |

### Modèle de données (vue d'ensemble)
```
Workspace
  ├── Plan (free | pro | enterprise)
  ├── Region (eu | us | ap)
  ├── Members (User × Role)
  ├── Clusters
  │     ├── Nodes
  │     ├── Namespaces
  │     ├── Services
  │     └── Pods (events, metrics)
  ├── Incidents
  │     ├── RootCause
  │     ├── MemoryMatches
  │     └── ProposedFix → PullRequest
  ├── MemoryPatterns
  ├── AlertRules + Channels
  ├── APIKeys
  └── AuditLog
```

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
| Clic logo strip | Navigation vers case studies (futur) | — |

## 4. États
- **Initial** : statique, aucun chargement.
- **Erreur** : N/A (purement statique).

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
- **Rôle** : Authentifier un utilisateur existant via SSO ou email/password.
- **Acteurs** : Utilisateur enregistré.

## 2. Composants et données affichées
Layout : 2 colonnes (form gauche / value prop droite).

| Composant | Type | Source | Règles |
|-----------|------|--------|--------|
| SSO buttons (Google, GitHub, SAML SSO) | Buttons | Front | OAuth redirect |
| Email field | Input | Saisie | Format email valide |
| Password field | Input password | Saisie | Min 8 chars |
| "Remember this device" | Checkbox | Saisie | Bool |
| "Forgot password?" link | Lien | — | → `/forgot-password` |
| Bouton "Sign in" | Submit | — | Active si email + password renseignés |
| Carte live "auth-api recovered" (visuel droite) | Statique | Front | Décor uniquement |
| SAML/OIDC hint box | Statique | Front | — |

## 3. Actions

### Sign in (email/password)
- **Déclencheur** : submit form
- **API** : `POST /api/auth/login`
- **Payload** :
```json
{ "email": "luc@acme.io", "password": "...", "remember": true }
```
- **Réponse 200** :
```json
{
  "data": {
    "user": { "id": "u_...", "email": "...", "role": "admin" },
    "workspace": { "id": "w_...", "slug": "acme-platform" },
    "access_token": "<jwt>",
    "expires_in": 3600
  }
}
```
Set cookie `refresh_token` httpOnly.
- **Validation** :
  - email : format RFC 5322
  - password : non vide
- **Erreurs** :
  - 401 `INVALID_CREDENTIALS`
  - 403 `EMAIL_NOT_VERIFIED` → afficher banner
  - 403 `SSO_REQUIRED` (workspace force SSO)
  - 429 `RATE_LIMITED` (5 tentatives / 10 min)

### SSO
- **Google** : `GET /api/auth/oauth/google/init` → redirect 302.
- **GitHub** : `GET /api/auth/oauth/github/init` → redirect.
- **SAML** : `POST /api/auth/saml/init` avec domaine email → redirect IdP.
- Callback : `/api/auth/oauth/<provider>/callback?code=...`

## 4. États
- **Initial** : form vide.
- **Loading** : spinner sur "Sign in" pendant l'appel.
- **Erreur credentials** : message rouge sous le password.
- **Erreur email non vérifié** : lien "Resend verification".
- **Erreur SSO forcé** : message + bouton "Continue with SSO".

## 5. Règles métier
- **RM010** — Après 5 échecs en 10 min → 429 + captcha optionnel.
- **RM011** — Si workspace `force_sso = true` → bloquer email/password pour les membres internes.
- **RM012** — `remember = true` → refresh token 30 jours, sinon 24h.

## 6. Critères d'acceptation
```gherkin
Given un utilisateur valide
When il soumet email + password corrects
Then il reçoit un JWT et un cookie refresh_token
And il est redirigé vers /dashboard

Given un workspace avec force_sso = true
When un membre tente email/password
Then 403 SSO_REQUIRED s'affiche
```

[AMBIGUÏTÉ] Le design affiche un compteur stats côté droit (MTTR, Pages, Memory) — données live workspace public ou décor ? **À CONFIRMER** : si live, prévoir endpoint public `GET /api/public/stats/:workspace_slug`.

---

# 03 · Signup (3 variantes)

3 designs proposés (`SignupSplit`, `SignupCentered`, `SignupPlanFirst`). Tous partagent la même logique backend ; le choix UI est cosmétique.

## 1. Vue d'ensemble
- **Route** : `/signup`
- **Rôle** : Créer un compte + workspace + sélectionner un plan.
- **Acteurs** : Visiteur anonyme.

## 2. Données saisies
| Champ | Type | Requis | Règles |
|-------|------|--------|--------|
| Email | string | ✅ | RFC 5322, domaine non blacklisté |
| Password | string | ✅ (si pas SSO) | Min 12 chars, 1 maj, 1 min, 1 chiffre |
| Plan | enum | ✅ | `free` \| `pro` \| `enterprise` |
| Billing cycle | enum | ✅ si `pro` | `monthly` \| `annual` |
| ToS accepted | bool | ✅ | Doit être `true` |

## 3. Actions

### Signup email/password
- **API** : `POST /api/auth/signup`
- **Payload** :
```json
{
  "email": "luc@acme.io",
  "password": "...",
  "plan": "pro",
  "billing_cycle": "monthly",
  "tos_accepted": true
}
```
- **Réponse 201** : crée `User`, déclenche email de vérification, retourne JWT temporaire (scope = `onboarding`).
- **Side effects** :
  1. Création `User` avec `email_verified = false`
  2. Envoi email vérification
  3. Création stub `Workspace` (sera finalisé à l'étape 1 de l'onboarding)
  4. Réservation trial 14j si `plan = pro`

### Signup SSO
- Même flow que Login SSO, mais avec `?intent=signup`. À la première connexion, marquer `is_new_user = true` pour rediriger vers `/onboarding/workspace`.

## 4. Validation password (live)
Indicateur 4-barres :
- 1 barre : 8+ chars
- 2 barres : + 1 chiffre
- 3 barres : + 1 majuscule
- 4 barres : + 1 caractère spécial

Renvoyer côté front sans appel API ; backend revalide à submit.

## 5. États
- **Initial**, **Loading**, **Erreur email pris** (`409 EMAIL_TAKEN`), **Erreur ToS** (`422`), **Erreur plan invalide** (`400`).

## 6. Règles métier
- **RM020** — Email doit être unique (insensitive case) — sinon 409.
- **RM021** — `plan = enterprise` → ne crée pas de subscription Stripe, marque `requires_sales_contact = true`, route → `/sales/contact`.
- **RM022** — Trial 14j s'applique uniquement à `pro` au premier signup workspace.
- **RM023** — Domaines email jetables (mailinator, etc.) bloqués.

## 7. Critères d'acceptation
```gherkin
Given un email non utilisé
When je soumets signup avec plan=pro, billing_cycle=monthly
Then un User est créé avec email_verified=false
And un trial 14j Pro est attaché au futur workspace
And je reçois un JWT scope=onboarding
And je suis redirigé vers /onboarding/workspace
```

---

# 04 · Onboarding — Step 1 : Workspace

## 1. Vue d'ensemble
- **Route** : `/onboarding/workspace`
- **Rôle** : Finaliser le workspace (nom, slug, icon, accent color, taille équipe, région).
- **Précondition** : JWT scope `onboarding` ou utilisateur authentifié sans workspace finalisé.

## 2. Composants et données saisies

| Champ | Type | Requis | Règles | Source |
|-------|------|--------|--------|--------|
| Workspace name | string | ✅ | 3–32 chars, `[a-z0-9-]` | Saisie |
| URL slug | string | ✅ | Dérivé auto du nom, éditable, unique global | Saisie + check API |
| Workspace icon | image | ❌ | PNG/JPG ≤ 2 MB, square | Upload |
| Accent color | hex | ✅ | Parmi 6 presets | Saisie |
| Team size | enum | ✅ | `solo` \| `2_10` \| `11_50` \| `50_plus` | Saisie |
| Region | enum | ✅ | `eu` \| `us` \| `ap` | Saisie |

## 3. Actions

### Check slug disponibilité (debounced 300ms)
- **API** : `GET /api/workspaces/check-slug?slug=acme-platform`
- **Réponse** : `{ "available": true }` ou `{ "available": false, "suggestion": "acme-platform-2" }`

### Submit
- **API** : `PATCH /api/onboarding/workspace`
- **Payload** :
```json
{
  "name": "acme-platform",
  "slug": "acme-platform",
  "icon_url": "https://cdn.../w_xxx.png",
  "accent_color": "#d97706",
  "team_size": "2_10",
  "region": "eu"
}
```
- **Réponse 200** : workspace finalisé, nouveau JWT scope = `full`, redirection `/onboarding/plan`.

## 4. États
- **Initial** : champs pré-remplis si retour utilisateur (nom = local part de l'email).
- **Slug check en cours** : icône loader à droite du champ.
- **Slug pris** : badge rouge + suggestion cliquable.
- **Loading submit** : bouton "Continue" disabled + spinner.

## 5. Règles métier
- **RM030** — Slug unique global, immuable après création (rename = ticket support).
- **RM031** — Region permanente (pas de migration auto). Affiché en hint.
- **RM032** — Team size = télémétrie produit, n'affecte pas les permissions.
- **RM033** — Accent color = visuel UI uniquement.

## 6. Critères d'acceptation
```gherkin
Given je tape un slug déjà pris
When le check API retourne available=false
Then une suggestion s'affiche
And le bouton Continue est désactivé

Given tous les champs valides
When je clique Continue
Then PATCH /api/onboarding/workspace est appelé
And je suis redirigé vers /onboarding/plan
```

---

# 05 · Onboarding — Step 2 : Choose plan

## 1. Vue d'ensemble
- **Route** : `/onboarding/plan`
- **Rôle** : Choisir Free / Pro / Enterprise + cycle de facturation.
- **Précondition** : workspace finalisé. Saute cette étape si le plan a déjà été choisi au signup ; **mais** doit être atteignable via "Change plan" si le user est arrivé par SSO sans plan.

## 2. Données affichées
| Composant | Source |
|-----------|--------|
| Toggle Monthly/Annual (−20%) | Front state |
| 3 plan cards | `GET /api/plans` |
| Trial banner 14j | Si plan sélectionné = pro |

## 3. Actions

### Get plans
- **API** : `GET /api/plans`
- **Réponse** :
```json
{
  "data": [
    { "id": "free",       "price_monthly": 0,   "price_annual": 0,    "features": [...] },
    { "id": "pro",        "price_monthly": 49,  "price_annual": 470,  "features": [...], "trial_days": 14 },
    { "id": "enterprise", "price_monthly": null,"price_annual": null, "features": [...], "contact_sales": true }
  ]
}
```

### Submit plan
- **API** : `PATCH /api/workspaces/:id/plan`
- **Payload** :
```json
{ "plan": "pro", "billing_cycle": "monthly" }
```
- Si `enterprise` → ne pas créer de subscription Stripe, marquer `pending_sales = true` et router vers Step 3 quand même (commercial gère hors flow).

## 4. États
- Sélection radio par card.
- "Selected" sur Pro par défaut.
- Loading sur submit.

## 5. Règles métier
- **RM040** — Trial 14j sur Pro = 1 fois par workspace, jamais réactivable.
- **RM041** — Si downgrade Pro → Free pendant le trial, le trial est perdu.
- **RM042** — Enterprise ne charge rien automatiquement.

## 6. Critères d'acceptation
```gherkin
Given je choisis Pro monthly
When je clique Continue
Then un trial Stripe de 14j est créé (status=trialing)
And je passe à Step 3
```

---

# 06 · Onboarding — Step 3 : Connect cluster

## 1. Vue d'ensemble
- **Route** : `/onboarding/cluster`
- **Rôle** : Installer l'agent PodIQ et attendre le premier ping.

## 2. Composants
| Composant | Type | Source |
|-----------|------|--------|
| Method picker (Helm / kubectl / Terraform) | 3 cards, radio | Front state |
| Snippet d'install | `pre` éditable | Généré côté front avec le workspace token |
| Status "Waiting for first ping" | Polling | API |
| Bouton Copy | Action | Clipboard API |

## 3. Actions

### Récupérer le token d'installation
- **API** : `GET /api/workspaces/:id/install-token`
- **Réponse** :
```json
{ "token": "wsk_3f8a92c1e4d7b6", "expires_at": "2026-05-19T..." }
```
TTL : 24h. Régénérable.

### Polling du premier ping
- **API** : `GET /api/clusters/pending-ping`
- Polling 5s, ou WebSocket `wss://api/realtime?topic=workspace.<id>.cluster.connected`.
- **Réponse 200** : `{ "data": { "cluster": { "id": "c_...", "name": "prod-eu-west-1", "version": "1.29.3" } } }` quand l'agent a phoné.

## 4. États
- **Idle (recherche)** : badge orange "Waiting for first ping" pulse.
- **Connected** : badge vert "Connected · prod-eu-west-1" + bouton Continue activé.
- **Timeout 10 min** : afficher troubleshoot tips inline.

## 5. Règles métier
- **RM050** — L'agent K8s envoie un `POST /api/agent/heartbeat` avec le token → crée `Cluster` lié au workspace.
- **RM051** — Agent en `read-only` strict : pas de `exec`, pas de `port-forward`.
- **RM052** — Une connexion = un cluster. Plusieurs clusters = relancer l'install dans un autre context.

## 6. Critères d'acceptation
```gherkin
Given un user à l'étape Connect cluster
When l'agent envoie un heartbeat valide
Then le polling détecte la connexion sous 10s
And le bouton Continue s'active
```

---

# 07 · Onboarding — Step 4 : Invite team

## 1. Vue d'ensemble
- **Route** : `/onboarding/team`
- **Rôle** : Inviter des coéquipiers et configurer auto-invite par domaine.

## 2. Composants
| Composant | Source |
|-----------|--------|
| Email input + role select + bouton Add | Saisie |
| Liste invites pending | `GET /api/invitations` |
| Role explainer (Admin/Member/Viewer) | Statique |
| Toggle auto-invite by domain | API |
| Copy invite link | Action |

## 3. Actions

### Ajouter une invitation
- **API** : `POST /api/invitations`
- **Payload** :
```json
{ "email": "marie@acme.io", "role": "admin" }
```
- **Réponse 201** : `{ "data": { "id": "inv_...", "email": "...", "role": "admin", "status": "sent", "sent_at": "..." } }`

### Lister
- **API** : `GET /api/invitations?status=pending`

### Auto-invite
- **API** : `PATCH /api/workspaces/:id/auto-invite`
- **Payload** : `{ "enabled": true, "domain": "acme.io", "default_role": "member" }`
- **Validation** : domaine doit matcher l'email de l'admin courant.

### Copy invite link
- Génère un lien à usage limité : `GET /api/invitations/link` → `{ "url": "https://acme.podiq.io/join/abc123", "expires_at": "..." }`.

## 4. États
- Invite list vide → état "No invites yet".
- Status par invite : `sent` (vert ✓), `draft` (gris ⏱), `accepted`, `revoked`.

## 5. Règles métier
- **RM060** — Email d'invitation expire au bout de 7j.
- **RM061** — Un invité peut être assigné à un rôle ≤ celui de l'inviteur.
- **RM062** — Auto-invite ne s'applique qu'à `member`/`viewer` (jamais admin).
- **RM063** — Workspace plan `free` limité à 3 membres totaux, `pro` à 50, `enterprise` illimité.

## 6. Critères d'acceptation
```gherkin
Given un workspace pro avec 49 membres
When j'invite un 50e
Then 422 BUSINESS_RULE_VIOLATION (RM063)
```

---

# 08 · Onboarding — Step 5 : Wire up alerts

## 1. Vue d'ensemble
- **Route** : `/onboarding/alerts`
- **Rôle** : Choisir règles de sévérité et canaux de notification.

## 2. Composants
| Composant | Source |
|-----------|--------|
| 4 toggles règles | Front state → API |
| 6 channel cards (Slack, PagerDuty, Email, Webhook, Teams, Discord) | `GET /api/channels/available` |
| Quiet hours toggle + range | API |

## 3. Actions

### Liste règles par défaut
- **API** : `GET /api/alert-rules/defaults` → 4 rules pré-cochées.

### Activer/désactiver une règle
- **API** : `PATCH /api/alert-rules/:id`
- **Payload** : `{ "enabled": true }`

### Connecter un channel
- **Slack/PD/Teams/Discord** : OAuth flow → `GET /api/channels/:type/connect` → redirect.
- **Webhook** : modal pour saisir URL + secret → `POST /api/channels` payload `{ type: "webhook", url, secret }`.
- **Email** : déjà connecté implicitement (l'email du compte).

### Quiet hours
- **API** : `PATCH /api/workspaces/:id/quiet-hours`
- **Payload** : `{ "enabled": true, "start": "22:00", "end": "07:00", "tz": "Europe/Paris", "weekdays_only": true }`

## 4. États
- Channel `disabled` (ex: Teams "Coming soon") → bouton désactivé.
- Channel `connected` → tag vert + lien Configure.

## 5. Règles métier
- **RM070** — Au moins 1 channel doit être connecté pour valider l'étape (sauf bouton "Skip — wire later").
- **RM071** — Quiet hours ne bloque PAS les alertes P1 (crit).
- **RM072** — Channel Webhook nécessite une URL `https://`.
- **RM073** — Dedupe par défaut : 5 min crit, 10 min warn.

## 6. Critères d'acceptation
```gherkin
Given un channel Slack connecté
When un pod entre en CrashLoopBackOff
And la règle "Pod CrashLoop" est ON
Then une notification est envoyée au channel Slack
```

---

# 09 · Onboarding — Complete

## 1. Vue d'ensemble
- **Route** : `/onboarding/complete`
- **Rôle** : Confirmer la fin de l'onboarding.

## 2. Composants
- Big checkmark.
- Recap (workspace name, cluster, team count, channels).
- Suggested next (add 2e cluster, install GitHub Action, take tour).

## 3. Actions
- CTA "Open dashboard" → `/dashboard`.
- CTA "Take the tour" → onboarding tour overlay sur le dashboard (LocalStorage flag `tour_seen`).

## 4. États
- État unique de succès. Si on y arrive avec onboarding incomplet → rediriger vers la 1re étape manquante.

## 5. Règles métier
- **RM080** — `workspace.onboarded_at` est set à cette étape.

---

# 10 · Cluster dashboard

## 1. Vue d'ensemble
- **Route** : `/dashboard` (ou `/clusters/:slug`)
- **Rôle** : Vue principale santé cluster en temps réel.

## 2. Composants

| Composant | Donnée | Source |
|-----------|--------|--------|
| KPI MTTR | string (4m) | `GET /api/clusters/:id/metrics?range=24h` |
| KPI Pages | string (12) | idem |
| KPI Memory patterns | number | idem |
| KPI healthy pods | "298 / 312" | idem |
| Liste services (top N) | array | `GET /api/services?cluster=...&sort=health` |
| Active incidents | array | `GET /api/incidents?status=open` |
| Sparklines par service | timeseries | `GET /api/services/:id/timeseries` |
| Cluster switcher (sidebar) | list | `GET /api/clusters` |
| Recent deploys ribbon | array | `GET /api/deploys?recent=true` |

## 3. Actions
- Clic sur service row → `/services/:name`
- Clic sur incident → `/incidents/:id`
- Range picker (1h/24h/7d/30d) → refetch metrics
- Cluster switcher → switch context

## 4. États
- **Loading** : skeleton + shimmer.
- **Empty** : voir écran 20 (Day 0).
- **Disconnected** : voir écran 21.
- **Nominal** : KPIs + tableau.

## 5. Règles métier
- **RM100** — Tous les chiffres se rafraîchissent toutes les 30s (polling ou WS).
- **RM101** — Si `cluster.last_heartbeat > 2 min` → état `disconnected`.

## 6. Critères d'acceptation
```gherkin
Given un cluster connecté avec 312 pods
When 14 pods sont unhealthy
Then le KPI "Healthy pods" affiche "298 / 312"
```

---

# 11 · Incident analysis

## 1. Vue d'ensemble
- **Route** : `/incidents/:id`
- **Rôle** : Diagnostic complet d'un incident — root cause, blast radius, memory matches, fix proposé.

## 2. Composants

| Composant | Source |
|-----------|--------|
| Header (titre, pod, sévérité, time) | `GET /api/incidents/:id` |
| Tag CRASHLOOPBACKOFF, restarts count | idem |
| Root cause card + confidence % | `incident.root_cause` |
| Memory recall list (n prior matches) | `incident.memory_matches[]` |
| Blast radius graph | `incident.blast_radius` |
| Proposed fix (PR diff) | `incident.proposed_fix` |
| Action buttons : Apply fix, Open PR, Dismiss | — |
| Timeline events | `GET /api/incidents/:id/timeline` |

## 3. Actions

### Apply fix
- **API** : `POST /api/incidents/:id/apply-fix`
- Crée une PR GitHub (via integration) ou affiche le YAML à appliquer si pas d'intégration.

### Dismiss
- **API** : `POST /api/incidents/:id/dismiss`
- **Payload** : `{ "reason": "false_positive" | "duplicate" | "resolved_manually", "note": "..." }`

### Acknowledge
- **API** : `POST /api/incidents/:id/ack`

## 4. États
- `open`, `acknowledged`, `mitigating`, `resolved`, `dismissed`.

## 5. Règles métier
- **RM110** — Apply fix nécessite rôle `member` mini.
- **RM111** — Confidence < 50% → bouton Apply fix grisé + tooltip "Low confidence, review manually".
- **RM112** — Un incident résolu peut être ré-ouvert dans les 24h s'il reflambe.

---

# 12 · Memory engine

## 1. Vue d'ensemble
- **Route** : `/memory`
- **Rôle** : Liste tous les patterns appris et leur fréquence.

## 2. Composants
| Composant | Source |
|-----------|--------|
| Search + filtres (service, severity) | Front state |
| Table patterns | `GET /api/memory-patterns` |
| Colonnes : fingerprint, première vue, dernière vue, occurrences, services impactés | idem |
| Détail panel (clic ligne) | `GET /api/memory-patterns/:id` |

## 3. Actions
- Recherche full-text → query param `?q=`
- Filtre service → `?service=auth-api`
- Édition manuelle d'un pattern (admin) → `PATCH /api/memory-patterns/:id`
- Suppression pattern → `DELETE /api/memory-patterns/:id` (admin only)

## 4. Règles métier
- **RM120** — Patterns expirent au bout de 90j sans occurrence (plan Free) ou jamais (Pro+).
- **RM121** — Pattern privé au workspace, jamais partagé cross-workspace.

---

# 13 · Cross-service correlation

## 1. Vue d'ensemble
- **Route** : `/correlation` (ou intégré dans Incident)
- **Rôle** : Visualiser le blast radius — quels services dépendent du service en panne.

## 2. Composants
- Graphe SVG (nodes = services, edges = dépendances HTTP/gRPC).
- Edges colorés par statut (crit/warn/ok).
- Sidebar list services impactés avec %.

## 3. Données
- **API** : `GET /api/correlations?root_service=auth-api&window=15m`
- **Réponse** :
```json
{
  "data": {
    "root": { "id": "svc_authapi", "name": "auth-api", "status": "crit" },
    "edges": [
      { "from": "auth-api", "to": "payments", "error_rate_delta": 1.0, "label": "5xx 100%" },
      { "from": "auth-api", "to": "checkout", "error_rate_delta": 0.7, "label": "5xx 70%" }
    ]
  }
}
```

## 4. Règles métier
- **RM130** — Détection basée sur les traces (OTel) si disponibles, sinon sur les métriques HTTP.

---

# 14 · Pre-deploy scan

## 1. Vue d'ensemble
- **Route** : `/predeploy`
- **Rôle** : Scanner un manifeste K8s avant deploy et matcher avec memory patterns.

## 2. Composants
| Composant | Source |
|-----------|--------|
| Upload zone / paste YAML | Saisie |
| Diff vs version précédente | Calculé backend |
| Liste warnings/errors | `POST /api/predeploy/scan` |
| Score safety 0-100 | idem |

## 3. Actions

### Scan
- **API** : `POST /api/predeploy/scan`
- **Payload** :
```json
{ "manifest": "<yaml>", "target_cluster": "prod-eu-west-1", "service": "auth-api" }
```
- **Réponse** :
```json
{
  "data": {
    "score": 72,
    "findings": [
      { "severity": "crit", "rule": "missing_env", "field": "DATABASE_URL", "matches_pattern": "p_abc", "history": "Caused 3 prior outages" }
    ]
  }
}
```

## 4. Règles métier
- **RM140** — Score < 50 = bloquant (CI fail) si CI/CD integration activée en mode strict.
- **RM141** — Findings groupés par sévérité.

---

# 15 · CI/CD integration

## 1. Vue d'ensemble
- **Route** : `/cicd`
- **Rôle** : Gérer les API keys + webhooks pour intégrer PodIQ à GitHub Actions/GitLab CI/CircleCI.

## 2. Composants
- Liste API keys avec scope.
- Bouton "Create key" → modal écran 30.
- Boutons d'install GitHub Action, GitLab CI snippet.
- Webhook events list.

## 3. Actions
- CRUD API keys : `GET/POST/DELETE /api/keys`
- Liste webhooks : `GET /api/webhooks`

## 4. Règles métier
- **RM150** — API key visible 1 seule fois à la création (irrécupérable ensuite).
- **RM151** — Scopes : `read:incidents`, `write:predeploy`, `admin:workspace`.

---

# 16 · Incident inbox

## 1. Vue d'ensemble
- **Route** : `/incidents`
- **Rôle** : Liste paginée de tous les incidents avec filtres.

## 2. Composants
- Filtres : status, severity, service, cluster, range.
- Table incidents : title, severity, status, service, age, assignee.
- Bulk actions : ack, dismiss, assign.

## 3. Actions
- **API** : `GET /api/incidents?status=open&severity=crit&cursor=...`
- Bulk ack : `POST /api/incidents/bulk-ack` payload `{ ids: [...] }`

## 4. Règles métier
- **RM160** — Viewer ne voit pas les boutons d'action bulk.

---

# 17 · Pod detail

## 1. Vue d'ensemble
- **Route** : `/pods/:name`
- **Rôle** : Détail complet d'un pod : events, logs récents, métriques, restarts.

## 2. Composants
- Header pod (name, ns, node, image, age).
- Tabs : Overview / Events / Logs / Metrics / Memory matches.
- Quick actions : Restart pod (member+), Open shell (admin) [À CONFIRMER si exec autorisé — design dit read-only strict, contradiction].

## 3. APIs
- `GET /api/pods/:name`
- `GET /api/pods/:name/events`
- `GET /api/pods/:name/logs?tail=200`
- `GET /api/pods/:name/metrics?range=1h`

[AMBIGUÏTÉ] Le bouton "Restart pod" est-il dans le scope read-only ? **À CONFIRMER**.

---

# 18 · Service detail

## 1. Vue d'ensemble
- **Route** : `/services/:name`
- **Rôle** : Vue agrégée d'un service (n pods, SLOs, deploys récents, incidents).

## 2. Composants
- Header service + SLO badges.
- Sparklines (latency p50/p95/p99, error rate, RPS).
- Tableau pods.
- Liste deploys récents.
- Incidents history.

## 3. APIs
- `GET /api/services/:name`
- `GET /api/services/:name/pods`
- `GET /api/services/:name/timeseries?metric=latency_p99&range=24h`
- `GET /api/services/:name/deploys`

---

# 19 · Cluster detail

## 1. Vue d'ensemble
- **Route** : `/clusters/:name`
- **Rôle** : Vue de bas niveau d'un cluster — nodes, capacity, version K8s.

## 2. Composants
- Nodes table (cpu/mem/pods alloc).
- Namespaces.
- Agent status (version, last heartbeat).

## 3. APIs
- `GET /api/clusters/:name`
- `GET /api/clusters/:name/nodes`
- `GET /api/clusters/:name/namespaces`

---

# 20 · Empty state (Day 0 dashboard)

## 1. Vue d'ensemble
- **Route** : `/dashboard` quand aucun cluster connecté ou cluster vide.
- **Rôle** : Onboarder l'utilisateur sur un dashboard vide.

## 2. Composants
- Illustration "no data yet".
- CTA "Connect a cluster" → `/onboarding/cluster`.
- Sample data toggle (mode demo) → flag `?demo=true`.

## 3. Règles métier
- **RM200** — Si `workspace.clusters.count == 0` → toujours afficher cet état au lieu du dashboard nominal.

---

# 21 · Cluster disconnected (error state)

## 1. Vue d'ensemble
- **Rôle** : Avertir que l'agent a stoppé de phoner.

## 2. Composants
- Banner rouge "Cluster <name> hasn't pinged in 5m".
- Troubleshooting steps (kubectl get pods, restart agent).
- Last seen timestamp.

## 3. Règles métier
- **RM210** — `last_heartbeat > 2 min` → état warning.
- **RM211** — `> 10 min` → état critical + email admin.

---

# 22 · Notifications inbox

## 1. Vue d'ensemble
- **Route** : `/notifications`
- **Rôle** : Centre de notifications in-app.

## 2. Composants
- Liste notifications (incidents, mentions, system).
- Mark all as read.
- Filtres.

## 3. APIs
- `GET /api/notifications?unread=true`
- `POST /api/notifications/mark-read` payload `{ ids: [...] }`

---

# 23 · Command palette ⌘K

## 1. Vue d'ensemble
- Overlay global, déclenché par `⌘K` ou `Ctrl+K`.
- **Rôle** : Navigation + actions rapides.

## 2. Composants
- Input search.
- Liste résultats catégorisés : Pods, Services, Incidents, Actions, Settings.
- Keyboard nav (↑↓ Enter Esc).

## 3. APIs
- `GET /api/search?q=auth&types=pod,service,incident&limit=10`

## 4. Règles métier
- **RM230** — Résultats triés par fréquence d'accès personnelle, puis recency.

---

# 24-25 · Settings (Overview + Notifications)

## 1. Vue d'ensemble
- **Route** : `/settings`, `/settings/notifications`
- **Rôle** : Hub de configuration workspace.

## 2. Composants Overview
- Liste sections : Workspace & team, Notifications, Memory, Billing, Security, API keys.
- Aperçu par section.

## 3. Composants Notifications
- Channels list (réutilise onboarding step 5).
- Règles d'alerte (réutilise).
- Quiet hours.

---

# 26 · Workspace & team

## 1. Vue d'ensemble
- **Route** : `/settings/team`
- **Rôle** : Gérer membres + invitations + rôles.

## 2. Composants
- Table membres (avatar, name, email, role, last active).
- Bouton "Invite member" → modal.
- Section pending invites.
- Bulk actions (change role, remove).

## 3. APIs
- `GET /api/members`
- `PATCH /api/members/:id` `{ role: "admin" }`
- `DELETE /api/members/:id`
- `POST /api/invitations` (déjà couvert)

## 4. Règles métier
- **RM260** — Un workspace doit avoir ≥ 1 admin actif.
- **RM261** — On ne peut pas se retirer soi-même si on est le seul admin.

---

# 27 · Memory engine · tuning

## 1. Vue d'ensemble
- **Route** : `/settings/memory`
- **Rôle** : Tuner sensibilité du moteur de mémoire.

## 2. Composants
- Slider sensitivity (0–100).
- Slider min confidence to surface (0–100).
- Slider expiry days.
- Pattern blacklist input.

## 3. APIs
- `GET /api/workspaces/:id/memory-config`
- `PATCH /api/workspaces/:id/memory-config` payload `{ sensitivity: 70, min_confidence: 50, expiry_days: 90, blacklist: [...] }`

---

# 28 · Billing

## 1. Vue d'ensemble
- **Route** : `/settings/billing`
- **Rôle** : Plan actuel, payment method, factures, usage.

## 2. Composants
- Plan card (current plan, next bill date, amount).
- Bouton "Change plan".
- Payment method (Stripe Elements).
- Liste factures (`GET /api/invoices`).
- Usage meter (clusters / pods).

## 3. APIs
- `GET /api/billing/subscription`
- `POST /api/billing/portal` → URL Stripe Customer Portal.
- `GET /api/invoices` paginated.

## 4. Règles métier
- **RM280** — Admin uniquement.
- **RM281** — Cancel = downgrade au prochain cycle, pas immédiat.

---

# 29 · SSO & security

## 1. Vue d'ensemble
- **Route** : `/settings/security`
- **Rôle** : Configurer SSO SAML/OIDC, force SSO, sessions.

## 2. Composants
- SAML config (Entity ID, ACS URL, IdP metadata upload).
- Toggle "Force SSO for all members".
- Liste sessions actives (`GET /api/sessions`).
- Audit log link.
- 2FA enforcement toggle.

## 3. APIs
- `GET/POST /api/sso/saml`
- `PATCH /api/workspaces/:id/security` payload `{ force_sso, require_2fa, session_timeout_min }`

## 4. Règles métier
- **RM290** — Pro plan minimum pour SAML.
- **RM291** — Enterprise pour SCIM provisioning.

---

# 30 · Create API key (modal)

## 1. Vue d'ensemble
- Modal overlay sur `/settings/api-keys` ou `/cicd`.
- **Rôle** : Créer une nouvelle API key.

## 2. Composants
- Input name.
- Scopes (checkboxes).
- Expiration (date picker, max 1 an).
- Bouton Create.

## 3. APIs
- `POST /api/keys`
- **Payload** : `{ "name": "github-ci", "scopes": ["read:incidents", "write:predeploy"], "expires_at": "2027-05-18" }`
- **Réponse 201** : `{ "data": { "id": "ak_...", "name": "...", "token": "podiq_live_abc...", "scopes": [...] } }`
- **IMPORTANT** : `token` retourné une seule fois.

## 4. Règles métier
- **RM300** — Token jamais re-affiché. Hash stocké backend.
- **RM301** — Limite : 20 keys / workspace.

---

# 31 · PR preview (Apply fix)

## 1. Vue d'ensemble
- **Route** : `/incidents/:id/pr-preview`
- **Rôle** : Prévisualiser le diff avant de créer la PR GitHub.

## 2. Composants
- Diff viewer (before/after YAML).
- Commit message éditable.
- Repository + branch picker.
- Bouton "Open PR" / "Copy patch".

## 3. APIs
- `GET /api/incidents/:id/fix/preview`
- `POST /api/incidents/:id/fix/pr` payload `{ repo, branch, commit_message }`

---

# 32 · Pod activity · 24h

## 1. Vue d'ensemble
- **Route** : `/pods/:name/activity`
- **Rôle** : Heatmap / timeline détaillée des events sur 24h.

## 2. Composants
- Heatmap par heure × type d'event.
- Liste filtrée events.

## 3. APIs
- `GET /api/pods/:name/activity?range=24h&granularity=hour`

---

# 33 · Postmortem

## 1. Vue d'ensemble
- **Route** : `/incidents/:id/postmortem`
- **Rôle** : Document postmortem auto-généré à partir de la timeline + diagnostic.

## 2. Composants
- Markdown rendered.
- Sections : Summary, Timeline, Root cause, Resolution, Action items.
- Bouton "Export PDF", "Copy markdown".

## 3. APIs
- `GET /api/incidents/:id/postmortem`
- `POST /api/incidents/:id/postmortem/regenerate`

---

# 34 · Help & docs

## 1. Vue d'ensemble
- **Route** : `/help`
- **Rôle** : Centre d'aide in-app (docs, FAQs, contact support).

## 2. Composants
- Search docs.
- Liens vers articles.
- Bouton "Contact support" → ticket.

## 3. APIs
- `GET /api/help/search?q=...`
- `POST /api/help/tickets` payload `{ subject, body, attachments }`

---

# 35 · Mobile alerts (iOS) — [HORS SCOPE WEB]

Écran natif iOS. Spec mobile séparée. Le backend doit exposer :
- Push notifications via APNs.
- Endpoint device registration : `POST /api/devices` `{ platform: "ios", token: "..." }`.

---

# 36 · Privacy + cookie banner

## 1. Vue d'ensemble
- Overlay sur première visite anonyme.
- **Rôle** : Conformité RGPD / CCPA.

## 2. Composants
- Banner bottom.
- Boutons : Accept all, Reject non-essential, Customize.
- Modal préférences (cookie categories).

## 3. Données
- `POST /api/consent` payload `{ analytics: true, marketing: false, functional: true }` → cookie 1 an.

## 4. Règles métier
- **RM360** — Visiteurs EU : opt-in explicite obligatoire pour analytics/marketing.
- **RM361** — Cookie consent expire 12 mois.

---

## Annexe — Glossaire

| Terme | Définition |
|-------|------------|
| Workspace | Unité d'isolation tenant. 1 user peut appartenir à plusieurs. |
| Cluster | Cluster Kubernetes connecté via l'agent PodIQ. |
| Pod | Unité K8s, watched par l'agent. |
| Service | Regroupement logique de pods (typiquement un Deployment). |
| Memory pattern | Empreinte d'un incident passé, réutilisée pour diagnostics futurs. |
| Confidence | Score 0-100 de probabilité que la root cause proposée soit correcte. |
| Blast radius | Ensemble des services affectés par cascade. |
| Heartbeat | Ping périodique de l'agent au backend (toutes les 30s). |

---

## Annexe — Tags à clarifier

Recherche `[AMBIGUÏTÉ]` et `[À CONFIRMER]` dans ce document.

| Tag | Section | Question |
|-----|---------|----------|
| [AMBIGUÏTÉ] | 02 Login | Stats live workspace public ou décor ? |
| [AMBIGUÏTÉ] | 17 Pod detail | Restart pod compatible avec agent read-only ? |
| [À CONFIRMER] | 27 Memory tuning | Sensibilité globale workspace ou per-service ? |
| [À CONFIRMER] | 32 Pod activity | Granularité min = heure ou minute ? |

---

**Fin du document.**
