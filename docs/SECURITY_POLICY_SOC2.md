# Politique de Sécurité SOC 2 — PodIQ

> **Version :** 1.4
> **Date d'entrée en vigueur :** 2026-05-24
> **Propriétaire :** Équipe Sécurité PodIQ
> **Classification :** Confidentiel — Usage interne et auditeurs accrédités
> **Révision :** Annuelle ou à chaque changement d'architecture majeur

---

## Table des matières

1. [Objet et périmètre](#1-objet-et-périmètre)
2. [Référentiel et critères de confiance (TSC)](#2-référentiel-et-critères-de-confiance-tsc)
3. [CC1 — Environnement de contrôle](#3-cc1--environnement-de-contrôle)
4. [CC2 — Communication et information](#4-cc2--communication-et-information)
5. [CC3 — Évaluation des risques](#5-cc3--évaluation-des-risques)
6. [CC4 — Activités de contrôle](#6-cc4--activités-de-contrôle)
7. [CC5 — Surveillance des contrôles](#7-cc5--surveillance-des-contrôles)
8. [CC6 — Contrôles d'accès logiques et physiques](#8-cc6--contrôles-daccès-logiques-et-physiques)
9. [CC7 — Opérations système](#9-cc7--opérations-système)
10. [CC8 — Gestion des changements](#10-cc8--gestion-des-changements)
11. [CC9 — Gestion des risques liés aux tiers](#11-cc9--gestion-des-risques-liés-aux-tiers)
12. [A1 — Disponibilité (Availability)](#12-a1--disponibilité-availability)
13. [C1 — Confidentialité](#13-c1--confidentialité)
14. [PI1 — Intégrité du traitement](#14-pi1--intégrité-du-traitement)
15. [Réponse aux incidents de sécurité](#15-réponse-aux-incidents-de-sécurité)
16. [Formation et sensibilisation](#16-formation-et-sensibilisation)
17. [Annexes](#17-annexes)

---

## 1. Objet et périmètre

### 1.1 Objet

Ce document définit la politique de sécurité de **PodIQ**, plateforme SaaS d'intelligence des incidents Kubernetes, en conformité avec le cadre **SOC 2 Type II** de l'AICPA (American Institute of Certified Public Accountants) selon les Trust Services Criteria (TSC).

### 1.2 Périmètre du système

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| **gateway** | Django ASGI / Strawberry GraphQL / Uvicorn | API publique (GraphQL + REST CI/CD) |
| **auth-service** | Django / gRPC | Authentification, JWT, API Keys |
| **ai-service** | Django / gRPC / Ollama | Moteur IA, Memory Engine |
| **analyzer-service** | Django / gRPC | Analyse manifests YAML |
| **postgres-gateway/auth/ai/analyzer** | PostgreSQL 16 | Persistence isolée par service |
| **redis** | Redis 7 | File Dramatiq + cache éphémère |
| **nginx** | Nginx | Reverse proxy, terminaison TLS |
| **Agent K8s** | Python | Collecteur in-cluster, émetteur GraphQL |
| **Frontend Angular** | Angular | Interface utilisateur (phase 18) |
| **Observabilité** | Loki Docker Log Driver / Loki / Grafana | Journalisation centralisée (sans socket Docker) |

### 1.3 Périmètre organisationnel

La présente politique s'applique à :
- Tous les membres de l'équipe d'ingénierie PodIQ
- Les prestataires externes ayant accès aux systèmes de production
- Les environnements : développement, staging, production

### 1.4 Exclusions

- Les clusters Kubernetes **clients** (hors périmètre direct — l'agent est déployé par le client dans son propre cluster)
- Les systèmes d'hébergement de l'infrastructure sous-jacente (responsabilité du fournisseur cloud)

---

## 2. Référentiel et critères de confiance (TSC)

PodIQ s'engage sur les cinq Trust Services Criteria applicables :

| Critère | Statut | Justification |
|---------|--------|---------------|
| **Security (CC)** | ✅ Requis | Critère de base SOC 2 |
| **Availability (A1)** | ✅ In-scope | SaaS 24/7, agents K8s critiques |
| **Confidentiality (C1)** | ✅ In-scope | Logs K8s, données incidents clients |
| **Processing Integrity (PI1)** | ✅ In-scope | Analyses IA et résultats CI/CD gates |
| **Privacy (P)** | ⚠️ Hors scope v1 | Aucune donnée personnelle nominative traitée en masse |

---

## 3. CC1 — Environnement de contrôle

### 3.1 Gouvernance de la sécurité

- Un **Responsable Sécurité** (ou Security Champion) est nommé au sein de l'équipe ingénierie ; il est propriétaire de ce document et des actions correctives.
- La sécurité est intégrée dans le cycle de développement (**Security by Design**) : chaque PR est soumise à une revue de code incluant un volet sécurité.
- Un comité de revue sécurité se réunit **trimestriellement** pour évaluer les risques, les incidents et l'état des contrôles.

### 3.2 Politiques complémentaires

Ce document est accompagné des politiques spécialisées suivantes (à maintenir à jour) :

| Document | Emplacement |
|----------|-------------|
| Guide Redis (clés, TTL, patterns) | `docs/REDIS.md` |
| Guide de tests | `docs/TEST_GUIDE.md` |
| Template MR sécurité | `docs/MR_TEMPLATE.md` |
| Spécification fonctionnelle frontend | `docs/Specification_fonctionnelle_PodIQ_Frontend.md` |

### 3.3 Propriété du code et responsabilités

- Tout code mergé en `main` doit avoir au moins **une approbation** d'un pair.
- Le merge direct en `main` est interdit sans PR.
- Les secrets ne peuvent pas être commités (enforced par `detect-secrets` en pre-commit hook).

---

## 4. CC2 — Communication et information

### 4.1 Documentation des interfaces

- Chaque service possède son propre `README.md` (en français) documentant : interface gRPC, schéma DB, variables d'environnement, procédure de test.
- `CLAUDE.md` à la racine constitue le document de référence architectural maintenu en temps réel avec le code.
- Toute modification de comportement, d'interface ou d'architecture **doit** être reflétée immédiatement dans les README et CLAUDE.md concernés.

### 4.2 Communication des incidents

- Les incidents de sécurité sont notifiés aux clients affectés dans un délai de **72 heures** après confirmation (conformité RGPD / bonnes pratiques SOC 2).
- Les canaux de notification supportés : Slack, PagerDuty, email, webhook, Teams, Discord (via `NotificationChannel`).

### 4.3 Journalisation applicative

- **`structlog`** est l'unique bibliothèque de logs autorisée — `print` et `logging` standard sont interdits.
- Chaque log JSON contient au minimum : `timestamp` (ISO UTC), `level`, `service`, `event` (slug snake_case).
- Les logs ne doivent **jamais** contenir de secrets, credentials, tokens, ou données personnelles sensibles.
- `LOG_LEVEL` est configurable par service (défaut `INFO` en production, `DEBUG` interdit en prod).

---

## 5. CC3 — Évaluation des risques

### 5.1 Registre des risques

| ID | Risque | Probabilité | Impact | Score | Contrôle |
|----|--------|-------------|--------|-------|----------|
| R-01 | Exfiltration de logs K8s clients (contenant secrets) | Moyen | Critique | **Haut** | Masquage obligatoire dans l'agent avant envoi ; TLS enforced |
| R-02 | Compromission JWT / refresh token | Moyen | Critique | **Haut** | Rotation tokens, httpOnly cookie, expiry 1h/30j |
| R-03 | Injection dans les manifests YAML (CI/CD gate) | Faible | Élevé | **Moyen** | Parsing isolé (analyzer-service), validation Pydantic v2 |
| R-04 | Accès non autorisé inter-services | Faible | Critique | **Moyen** | Réseau Docker isolé, gRPC only, pas d'accès DB croisé |
| R-05 | Exposition de secrets via variables d'environnement | Moyen | Critique | **Haut** | `.env` hors repo, detect-secrets, Vault en prod |
| R-06 | DoS sur l'API GraphQL (queries complexes) | Moyen | Élevé | **Moyen** | Rate limiting Nginx, timeout Uvicorn |
| R-07 | Indisponibilité Ollama (inférence CPU lente) | Élevé | Moyen | **Moyen** | `AI_TIMEOUT_SECONDS`, jobs async Dramatiq, état `failed` |
| R-08 | Corruption Redis (perte file Dramatiq) | Faible | Moyen | **Faible** | Redis non-persistant pour données critiques (PostgreSQL source of truth) |
| R-09 | Compromission API Key CI/CD | Moyen | Élevé | **Moyen** | SHA-256 + pepper, révocation immédiate, scope limité |
| R-10 | Accès physique non autorisé à l'infra cloud | Faible | Élevé | **Moyen** | Responsabilité fournisseur cloud (AWS/GCP/Azure) |
| R-11 | ~~Accès au daemon Docker via socket Promtail (`/var/run/docker.sock`)~~ | ~~Moyen~~ | ~~Critique~~ | ✅ **Résolu** | Promtail supprimé — log driver Loki (push, sans socket). Doc K8s : `docs/observability-k8s.md` |
| R-12 | Patterns d'incidents partagés entre workspaces dans `ai-service` (`incident_patterns` clé globale) | Moyen | Élevé | **Moyen** | **Planned** — `workspace_id` propagé dans les protos, modèles et filtres gRPC (phase 17). Correction complète : migration `0002_workspace_id` en cours de déploiement. Résidu : données historiques antérieures à la migration sans `workspace_id`. |

### 5.2 Processus d'évaluation des risques

- Revue du registre des risques **trimestrielle**.
- Toute nouvelle fonctionnalité doit faire l'objet d'une **analyse de risque rapide** (Threat Modeling) dans la PR.
- Les risques *Haut* et *Critique* sont traités en priorité dans le backlog sécurité.

---

## 6. CC4 — Activités de contrôle

### 6.1 Contrôles techniques automatisés (pre-commit)

Les hooks pre-commit suivants sont **obligatoires** et appliqués à toute contribution :

| Hook | Outil | Objectif |
|------|-------|----------|
| Formatage Python | Black | Cohérence du code |
| Linting Python | Ruff | Détection d'erreurs statiques |
| Détection de secrets | `detect-secrets` + `.secrets.baseline` | Blocage des secrets commités |
| Validation YAML | yamllint | Intégrité des manifests |
| Validation Dockerfiles | hadolint | Bonnes pratiques images Docker |
| Typage statique | mypy | Sécurité des types Python |

```bash
# Installation obligatoire pour tout développeur
pip install -r requirements-dev.txt
pre-commit install
```

### 6.2 Contrôles de qualité du code

- **Couverture de tests** : objectif > 70% par service
- **Tests unitaires** : exécutés en isolation (SQLite en mémoire, sans Postgres ni Redis pour gateway et auth)
- **Tests Docker** : `docker compose run --rm --no-deps <service> python -m pytest -v`
- **Revue de code** : au moins 1 approbateur, checklist sécurité (voir MR_TEMPLATE.md)

### 6.3 Contrôle des dépendances

- Les versions de dépendances sont **pinnées** dans `requirements.txt` de chaque service.
- `grpcio-tools` est **dev/build only** — interdit dans les `requirements.txt` des services.
- Les images Docker de base sont versionnées (`postgres:16-alpine`, `redis:7-alpine`, `ollama/ollama:0.23.2`).
- Audit trimestriel des dépendances avec `pip-audit` ou Dependabot.

---

## 7. CC5 — Surveillance des contrôles

### 7.1 Observabilité centralisée

```
[Services Docker] → stdout → Loki Docker Log Driver → Loki → Grafana
                             (plugin daemon Docker, sans /var/run/docker.sock)
```

- **Labels** : `namespace="podiq"`, `service="<nom-service>"`, `container`, `stream` — injectés par le log driver
- **Rétention Loki** : **90 jours** (2160h — SOC2 §7.3) — baked dans l'image `infra/loki/`
- **Dashboard Grafana** : `podiq-overview.json` — 9 sections : infrastructure, authentification, analyses IA, CI/CD gate, Redis, Agent K8s, Workspaces & Invitations, Notifications, logs bruts
- **Requêtes Loki recommandées** :
  - Toutes les erreurs : `{namespace="podiq"} |= "ERROR"`
  - Alertes sécurité : `{namespace="podiq"} |= "unauthorized" or |= "invalid_token" or |= "forbidden"`
  - Activité CI/CD gate : `{service="gateway"} |= "cicd_scan"`

### 7.2 Alertes de sécurité

Les événements suivants doivent déclencher une alerte via `AlertRule` + `NotificationChannel` :

| Événement | Seuil | Canal |
|-----------|-------|-------|
| Échecs d'authentification répétés | > 5 en 5 min / IP | PagerDuty + Slack |
| Token invalide (API Key révoquée) | Chaque occurrence | Slack |
| Job CI/CD bloqué (exit code 2) | Chaque occurrence | Slack + webhook |
| Erreur gRPC inter-services | > 10 en 1 min | PagerDuty |
| Indisponibilité service (healthcheck) | > 30s | PagerDuty |
| Tentative d'accès à `/admin` Django | Chaque occurrence hors IP whitelist | Email |

### 7.3 Revue des journaux

- Les logs de sécurité sont conservés **minimum 90 jours** en production.
- Une revue hebdomadaire des logs d'erreur est effectuée par le Security Champion.
- Les logs d'accès Nginx sont analysés pour détecter les patterns d'abus.

---

## 8. CC6 — Contrôles d'accès logiques et physiques

### 8.1 Authentification et autorisation

#### Flux d'authentification à deux étapes

```
[Client] → login(email, password)
    → auth-service gRPC (ValidateJWT)
    → user-JWT (auth-service, JWT_SECRET)
    → selectWorkspace(workspaceId)
    → workspace-JWT (gateway, GATEWAY_JWT_SECRET, 1h)
    + refresh token (httpOnly cookie, GATEWAY_REFRESH_SECRET, 30j)
```

| Mécanisme | Standard | Durée | Usage |
|-----------|----------|-------|-------|
| User JWT | HMAC-SHA256 | 60 min | Authentification initiale |
| Workspace JWT | HMAC-SHA256 | 60 min | Accès aux ressources workspace |
| Refresh token | HMAC-SHA256 | 30 jours | Renouvellement, httpOnly cookie |
| API Key | SHA-256 + pepper | Sans expiry | CI/CD pipelines uniquement |
| Install Token | UUID aléatoire (`wsk_xxx`) | Configurable | Agent K8s onboarding |

#### Règles JWT

- **`require_auth()`** : decode local si workspace-JWT (fast path), sinon fallback gRPC.
- Le refresh token est **rotatif** : un nouveau token est émis à chaque appel.
- Les tokens révoqués sont invalidés immédiatement (liste de révocation ou blacklist Redis avec TTL).

#### Rôles et permissions (RBAC)

| Rôle | Permissions |
|------|-------------|
| `admin` | Toutes opérations workspace + gestion membres + invitations |
| `member` | Lecture/écriture incidents, scans, analyses |
| `viewer` | Lecture seule |

- **Upgrade-only** : `acceptInvitation` ne peut que monter le rôle (`viewer < member < admin`). Jamais de downgrade automatique.
- `_ROLE_PRIORITY` enforced au niveau applicatif dans gateway.

### 8.2 Gestion des secrets

#### En développement

```bash
cp .env.example .env
# Modifier toutes les valeurs "change_me_*" avant démarrage
```

| Secret | Variable | Exigence minimale |
|--------|----------|-------------------|
| JWT Secret auth | `JWT_SECRET` | 64 caractères aléatoires |
| Gateway JWT | `GATEWAY_JWT_SECRET` | 64 caractères aléatoires |
| Refresh Secret | `GATEWAY_REFRESH_SECRET` | 64 caractères aléatoires |
| Django Secret Key | `DJANGO_SECRET_KEY` | 50 caractères aléatoires |
| PostgreSQL Password | `POSTGRES_PASSWORD` | 32 caractères minimum |
| API Key Salt | `API_KEY_SALT` | 32 caractères aléatoires |

#### En production

- Les secrets sont stockés dans un **gestionnaire de secrets** (ex. HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager).
- **Aucun secret ne peut figurer dans un fichier commité** (enforced par `detect-secrets`).
- Rotation trimestrielle des secrets de signature JWT.
- Rotation immédiate en cas de suspicion de compromission.

### 8.3 Hachage des mots de passe

**Algorithme : Argon2id** (vainqueur du Password Hashing Competition 2015 — conforme OWASP, NIST SP 800-63B, ANSSI)

```python
# services/auth-service/app/grpc_server.py
_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2,
                     hash_len=32, salt_len=16)
# Paramètres OWASP minimums : time=2, mem=64 MB, p=2
# Sel aléatoire unique généré à chaque appel — résistance rainbow tables
```

Format stocké : `$argon2id$v=19$m=65536,t=2,p=2$<salt>$<hash>`

**Migration transparente** : les hachages legacy SHA-256+pepper (64 caractères hex) sont détectés au login par `_needs_rehash()` et automatiquement mis à niveau vers Argon2id sans interruption de service ni réinitialisation de mot de passe.

| Propriété | Argon2id | SHA-256+pepper (remplacé) |
|-----------|----------|--------------------------|
| Résistance GPU/ASIC | ✅ Memory-hard (64 MB) | ❌ Rapide sur GPU |
| Sel unique par hash | ✅ 16 octets aléatoires | ❌ Absent |
| Recommandé OWASP 2024 | ✅ | ❌ |
| Statut | ✅ **Actif** | 🔄 Migration transparente en cours |

### 8.4 Isolation réseau

```
[Internet] → Nginx (8080) → gateway (8000)
                                ↓ gRPC (réseau Docker interne)
                         auth-service (50051)
                         analyzer-service (50052)
                         ai-service (50053)
                                ↓
                         postgres-* (5432-5435) [non exposé publiquement]
                         redis (6379) [non exposé publiquement]
```

- **Règle** : seuls `nginx` et `gateway` sont exposés publiquement.
- `postgres-*` et `redis` sont accessibles **uniquement** depuis le réseau Docker interne.
- Les services gRPC ne sont pas accessibles depuis Internet.
- En production Kubernetes : NetworkPolicies enforced entre namespaces.

### 8.5 Principe du moindre privilège

- Chaque service ne possède qu'un accès à **sa propre base de données**.
- Aucun service ne peut lire la base d'un autre service — architecture physiquement séparée (4 instances Postgres distinctes).
- Les communications inter-services se font **exclusivement** par gRPC — aucun accès direct à la DB d'un pair.
- L'agent K8s ne dispose que d'un `install_token` limité aux mutations `agentHeartbeat` et `agentReportIncident`.

### 8.6 Sécurité des WebSockets (GraphQL Subscriptions)

- Authentification via `connection_params["Authorization"]` dans le payload `connection_init`.
- Timeout configurable dans Nginx (`proxy_read_timeout 300s`, `proxy_send_timeout 300s`).
- `proxy_buffering off` pour les streams WebSocket.

---

## 9. CC7 — Opérations système

### 9.1 Sécurité des conteneurs Docker

- Toutes les images de base utilisent des tags versionnés (pas de `latest`).
- **hadolint** vérifie les Dockerfiles à chaque commit.
- `grpcio-tools` est exclu des images de production (dev-only).
- Les Dockerfiles définissent `PODIQ_SERVICE_NAME`, `LOG_FORMAT=json`, `LOG_LEVEL` pour les logs structurés.
- En production : images scannées avec **Trivy** ou **Docker Scout** avant déploiement.

### 9.2 Limites et protections opérationnelles

| Limite | Valeur | Justification |
|--------|--------|---------------|
| Logs tronqués par l'agent | 2 000 lignes max | Prévention DoS/exfiltration volumétrique |
| Timeout AI | `AI_TIMEOUT_SECONDS` (600s dev, 120s prod recommandé) | Isolation des pannes Ollama |
| Fenêtre de corrélation | `CORRELATION_WINDOW_MINUTES` (15 min) | Limitation du scope des corrélations |
| Profondeur historique | `INCIDENT_HISTORY_DEPTH` (5) | Maîtrise mémoire/latence |
| Mémoire Redis | `REDIS_MAXMEMORY` (256mb) + `allkeys-lru` | Prévention OOM |

### 9.3 Sécurité Nginx

```nginx
# Headers de sécurité obligatoires en production
add_header X-Frame-Options "DENY";
add_header X-Content-Type-Options "nosniff";
add_header X-XSS-Protection "1; mode=block";
add_header Referrer-Policy "strict-origin-when-cross-origin";
add_header Content-Security-Policy "default-src 'self'; ...";
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

- TLS 1.2 minimum requis en production (TLS 1.3 recommandé).
- Certificats gérés via Let's Encrypt ou fournisseur cloud.
- `CORS_ALLOWED_ORIGINS` : whitelist explicite, pas de wildcard `*` en production.

### 9.4 Gestion du CI/CD Gate

Le endpoint REST CI/CD (`POST /api/v1/cicd/scan`) doit respecter :

| Code de sortie | Signification | Action pipeline |
|---------------|---------------|-----------------|
| `0` | Manifest sain | Déploiement autorisé |
| `1` | Avertissements | Déploiement autorisé avec warnings |
| `2` | Configurations dangereuses | **Déploiement bloqué** |

- Authentification par **API Key** uniquement (pas de JWT utilisateur).
- Les API Keys sont scopées au workspace et révocables immédiatement.
- L'audit log de chaque scan CI/CD est conservé dans `postgres-ai` (table `analyses`).

---

## 10. CC8 — Gestion des changements

### 10.1 Processus de développement sécurisé (Secure SDLC)

```
Développement → Pre-commit hooks → PR Review → CI/CD Tests → Staging → Production
      ↓                ↓                ↓              ↓           ↓
  Threat Model   detect-secrets    Revue sécu      pytest >70%  Smoke tests
                 hadolint          MR_TEMPLATE      mypy clean
                 ruff/black        1+ approbateur
```

### 10.2 Règles de la MR/PR

Toute PR modifiant la sécurité doit documenter :
- [ ] Impact sur l'authentification / autorisation
- [ ] Nouveaux secrets ou variables d'environnement
- [ ] Modification des interfaces gRPC (proto)
- [ ] Impact sur les logs (données sensibles ?)
- [ ] Tests de régression sécurité ajoutés

### 10.3 Gestion des migrations de base de données

- Chaque service gère ses propres migrations Django (`python manage.py migrate` au démarrage).
- Les migrations sont versionnées dans le repo.
- Aucune migration destructive sans plan de rollback documenté.
- Les migrations cross-service sont **interdites** (chaque service owns sa DB).

### 10.4 Gestion des versions de dépendances

- Audit mensuel avec `pip-audit` ou Dependabot.
- Les vulnérabilités **critiques** (CVSS ≥ 9.0) sont corrigées sous **48 heures**.
- Les vulnérabilités **élevées** (CVSS 7.0-8.9) sont corrigées sous **7 jours**.
- Les vulnérabilités **moyennes** (CVSS 4.0-6.9) sont traitées dans le sprint suivant.

---

## 11. CC9 — Gestion des risques liés aux tiers

### 11.1 Composants tiers critiques

| Composant | Fournisseur | Risque | Contrôle |
|-----------|-------------|--------|----------|
| PostgreSQL 16 | PostgreSQL Global Dev Group | Vulnérabilités DB | Versions pinnées, patches rapides |
| Redis 7 | Redis Ltd | Accès non autorisé | Non exposé publiquement, réseau interne |
| Ollama / Mistral | Ollama Inc / Mistral AI | Fuite données via modèle | Déploiement local uniquement, pas de cloud AI |
| Nginx | F5 Inc | Exposition publique | Headers sécurité, TLS enforced |
| Grafana/Loki | Grafana Labs | Accès logs | Authentification Grafana obligatoire |
| Strawberry GraphQL | strawberry-graphql | Injection GraphQL | Validation input, depth limiting |

### 11.2 Politique AI/LLM (Ollama/Mistral)

> **Principe fondamental** : le modèle AI (Mistral 7B) tourne **localement** via Ollama. Aucune donnée client n'est envoyée à un service AI externe (OpenAI, Anthropic, etc.).

- L'`OLLAMA_MODEL` recommandé est `mistral` — les modèles "thinking" sont interdits en production (incompatibilité `/api/chat`).
- Gateway n'appelle **jamais** Ollama directement — toujours via `ai-service` gRPC.
- Les données K8s (logs, events, describe) passent par ai-service sans persistance externe.

### 11.3 Évaluation des nouveaux tiers

Avant d'intégrer une nouvelle dépendance ou un service externe :
1. Revue de sécurité du package (CVE history, mainteneurs)
2. Évaluation de la transmission de données sensibles
3. Validation par le Security Champion
4. Documenter dans la MR le rationnel sécurité

---

## 12. A1 — Disponibilité (Availability)

### 12.1 Objectifs de niveau de service (SLO)

| Métrique | Objectif Cible |
|----------|----------------|
| Disponibilité API GraphQL | ≥ 99.5% par mois |
| Temps de réponse P95 (hors AI) | < 500 ms |
| Temps de réponse P95 (analyse AI) | < 60s (async job) |
| RTO (Recovery Time Objective) | < 4 heures |
| RPO (Recovery Point Objective) | < 1 heure (backup PostgreSQL) |

### 12.2 Architecture haute disponibilité

- **Jobs asynchrones** : toutes les analyses AI passent par Dramatiq/Redis — la gateway ne bloque jamais sur Ollama.
- **Statuts de jobs** : `pending → running → complete/failed` — la UI poll via GraphQL Subscription.
- **Healthchecks** : chaque service expose un endpoint healthcheck Docker.
- **Restart policies** : `restart: unless-stopped` dans docker-compose.

### 12.3 Plan de sauvegarde

| Donnée | Fréquence backup | Rétention | Stockage |
|--------|-----------------|-----------|----------|
| postgres-auth | Quotidien | 30 jours | Stockage chiffré hors-site |
| postgres-gateway | Quotidien | 30 jours | Stockage chiffré hors-site |
| postgres-ai | Quotidien | 90 jours | Stockage chiffré hors-site |
| postgres-analyzer | Quotidien | 30 jours | Stockage chiffré hors-site |
| Logs Loki | Streaming | 90 jours prod | Stockage objet |

- **Redis** : pas de backup — données éphémères (Dramatiq queue, cache). La persistance est dans PostgreSQL.
- Les backups sont **chiffrés au repos** (AES-256).
- Les restaurations sont testées **trimestriellement**.

### 12.4 Plan de reprise d'activité (PRA)

En cas d'incident majeur :

1. **Détection** (< 5 min) : alerte Grafana/PagerDuty
2. **Triage** (< 15 min) : identification du service impacté
3. **Isolation** (< 30 min) : `docker compose stop <service>` ou NetworkPolicy K8s
4. **Restauration** (< 4h) : rollback image ou restauration backup
5. **Post-mortem** (< 48h) : rapport 5 Pourquoi + actions correctives

---

## 13. C1 — Confidentialité

### 13.1 Classification des données

| Classification | Exemples | Contrôles |
|---------------|----------|-----------|
| **Critique** | JWT secrets, API keys, passwords, DJANGO_SECRET_KEY | Vault, rotation, jamais loggé |
| **Confidentiel** | Logs K8s clients, events, describe output | TLS in transit, chiffrement au repos, accès restreint |
| **Interne** | Résultats d'analyses, patterns incidents | Authentification requise, RBAC workspace |
| **Public** | Documentation API (schéma GraphQL public) | Pas de contrôle spécifique |

### 13.2 Protection des données K8s clients

Les logs, events et describe des pods clients sont des données **hautement confidentielles** :

- **Masquage obligatoire dans l'agent** : avant envoi à la gateway, l'agent masque les secrets détectés dans les logs (variables d'environnement, tokens, passwords).
- **Transit chiffré** : TLS enforced entre agent et gateway (HTTPS/WSS).
- **Isolation par workspace** : un utilisateur n'accède qu'aux données de son workspace.
- **Pas d'accès cross-workspace** : enforced via `require_auth()` + `workspace_id` dans le token.
- **Stockage isolé** : `postgres-analyzer` (logs_snapshots) et `postgres-ai` (analyses) sont des bases dédiées, non accessibles depuis l'extérieur.

> ⚠️ **Limitation connue — Planned (R-12)** : La table `incident_patterns` dans `postgres-ai` utilisait historiquement une clé unique globale `(pod_name, namespace, error_type)` sans `workspace_id`. La propagation de `workspace_id` dans les protos gRPC, les modèles et les filtres de `ai-service` est en cours (migration `0002_workspace_id`). Les analyses créées **après** cette migration sont correctement scopées par workspace. Les données antérieures (avant phase 17) sans `workspace_id` sont marquées `NULL` et restent globales — elles ne contaminent pas les nouvelles analyses qui filtrent explicitement par `workspace_id`. L'isolation complète est garantie pour toutes les nouvelles données.

### 13.3 Protection des données en transit

- Toutes les communications client ↔ nginx : **HTTPS/TLS 1.2+**.
- Agent K8s ↔ gateway : **HTTPS** (pas de HTTP en production).
- Inter-services gRPC : **mTLS recommandé en production** (TLS gRPC avec certificats clients).
- Redis et PostgreSQL : connexions sur réseau Docker interne (chiffrement réseau overlay en production K8s).

### 13.4 Rétention et suppression des données

| Données | Rétention | Suppression |
|---------|-----------|-------------|
| Logs K8s (logs_snapshots) | 90 jours | Suppression automatique par cron |
| Analyses AI | 90 jours | Suppression à la demande du client |
| Incident patterns | Indéfini (Memory Engine) | Sur demande de suppression workspace |
| API Keys révoquées | 30 jours audit | Suppression automatique |
| Refresh tokens expirés | 7 jours | Nettoyage automatique |

---

## 14. PI1 — Intégrité du traitement

### 14.1 Intégrité des analyses AI

- Chaque analyse AI est persistée dans `postgres-ai` avec un UUID unique et un timestamp.
- Les résultats d'analyse incluent le modèle utilisé (`OLLAMA_MODEL`) et la version.
- Les jobs d'analyse ont des états traçables : `pending → running → complete/failed`.
- En cas d'erreur AI, le statut `failed` est stocké avec le message d'erreur (jamais silencieux).

### 14.2 Intégrité du CI/CD Gate

- Le résultat du scan CI/CD (exit code 0/1/2) est **déterministe** pour un manifest donné.
- Chaque scan est loggé avec : workspace_id, api_key_id, timestamp, manifest_hash, résultat.
- Les faux négatifs (configurations dangereuses non détectées) sont documentés dans un backlog sécurité.

### 14.3 Intégrité des données PostgreSQL

- **Contrainte d'unicité** : `incident_patterns` a une contrainte unique sur `(pod_name, namespace, error_type)` — upsert à chaque analyse.
- Les UUID sont utilisés comme clés primaires partout.
- Les références cross-services sont des UUID applicatifs (pas de FK contraints au niveau DB) — validés par gRPC.
- Les migrations sont appliquées au démarrage (`python manage.py migrate`) et versionnées.

### 14.4 Validation des entrées

- **Pydantic v2** est utilisé pour valider toutes les données inter-services.
- Les manifests YAML sont parsés dans un service isolé (`analyzer-service`) — jamais dans gateway.
- Les inputs GraphQL sont validés par le schéma Strawberry avant traitement.
- La longueur des logs est plafonnée à `MAX_LOG_LINES=2000` côté agent.

---

## 15. Réponse aux incidents de sécurité

### 15.1 Définition des niveaux de sévérité

| Niveau | Critères | Délai de réponse | Exemples |
|--------|----------|-----------------|----------|
| **P0 - Critique** | Compromission active, fuite de données | < 1 heure | Exfiltration DB, credentials compromis |
| **P1 - Élevé** | Vulnérabilité exploitable sans patch | < 4 heures | CVSS ≥ 9.0 non patché, accès non autorisé |
| **P2 - Moyen** | Risque élevé sans exploitation confirmée | < 24 heures | Misconfiguration exposée, CVSS 7-8.9 |
| **P3 - Faible** | Amélioration sécurité, low risk | < 1 semaine | Hardening, CVSS < 7 |

### 15.2 Procédure de réponse aux incidents

```
1. DÉTECTION
   └─ Alerte Grafana / rapport utilisateur / scan automatique

2. CLASSIFICATION (< 30 min)
   └─ Attribution P0/P1/P2/P3
   └─ Notification Security Champion

3. CONTAINMENT (< 1h pour P0, < 4h pour P1)
   ├─ Isoler le service impacté
   ├─ Révoquer les credentials compromis
   └─ Activer le mode maintenance si nécessaire

4. ÉRADICATION
   ├─ Identifier la cause racine
   ├─ Appliquer le correctif
   └─ Vérifier l'absence d'autres vecteurs

5. RÉCUPÉRATION
   ├─ Restaurer le service
   ├─ Valider l'intégrité des données
   └─ Surveiller 24h post-incident

6. POST-MORTEM (< 72h)
   ├─ Rapport 5 Pourquoi
   ├─ Timeline de l'incident
   ├─ Actions correctives (avec responsable et date)
   └─ Communication clients si données affectées
```

### 15.3 Contacts d'urgence sécurité

| Rôle | Contact |
|------|---------|
| Security Champion | [À compléter] |
| Responsable Technique | [À compléter] |
| Communication clients | nyobeelouga5@gmail.com |
| Hébergeur / Cloud Provider | [Contacts support À compléter] |

---

## 16. Formation et sensibilisation

### 16.1 Formation obligatoire

Tout membre de l'équipe doit compléter annuellement :

- [ ] Formation sécurité des APIs (OWASP API Security Top 10)
- [ ] Formation sécurité Kubernetes (RBAC, NetworkPolicies, PSS)
- [ ] Sensibilisation phishing et ingénierie sociale
- [ ] Formation gestion des secrets et variables d'environnement
- [ ] Procédures de réponse aux incidents PodIQ

### 16.2 Checklist onboarding développeur

Un nouveau membre de l'équipe doit, avant son premier commit :

- [ ] Lire CLAUDE.md, REDIS.md et ce document
- [ ] Configurer pre-commit hooks (`pre-commit install`)
- [ ] Configurer son gestionnaire de mots de passe
- [ ] Activer l'authentification multi-facteurs (MFA) sur tous les outils
- [ ] Obtenir des accès nominatifs (pas de comptes partagés)
- [ ] Signer la politique de confidentialité et sécurité

---

## 17. Annexes

### Annexe A — Variables d'environnement sensibles

| Variable | Usage | Sensibilité | Rotation |
|----------|-------|-------------|----------|
| `JWT_SECRET` | Signature tokens auth | ⚠️ Critique | Trimestrielle |
| `GATEWAY_JWT_SECRET` | Signature workspace tokens | ⚠️ Critique | Trimestrielle |
| `GATEWAY_REFRESH_SECRET` | Signature refresh tokens | ⚠️ Critique | Trimestrielle |
| `DJANGO_SECRET_KEY` | CSRF, sessions, password pepper | ⚠️ Critique | Annuelle |
| `POSTGRES_PASSWORD` | Accès toutes les DB | ⚠️ Critique | Semestrielle |
| `API_KEY_SALT` | Hachage API Keys | ⚠️ Critique | Annuelle |
| `GRAFANA_ADMIN_PASSWORD` | Admin dashboard | 🔶 Élevé | Annuelle |
| `SMTP_PASSWORD` | Envoi emails | 🔶 Élevé | Annuelle |

### Annexe B — Ports exposés

| Port | Service | Accès | Production |
|------|---------|-------|------------|
| 8080 | nginx | Public Internet | TLS obligatoire |
| 8000 | gateway | Interne Docker uniquement | — |
| 50051 | auth-service gRPC | Interne Docker uniquement | mTLS recommandé |
| 50052 | analyzer-service gRPC | Interne Docker uniquement | mTLS recommandé |
| 50053 | ai-service gRPC | Interne Docker uniquement | mTLS recommandé |
| 5432 | postgres-gateway | Interne Docker uniquement | Jamais public |
| 5433 | postgres-auth | Interne Docker uniquement | Jamais public |
| 5434 | postgres-analyzer | Interne Docker uniquement | Jamais public |
| 5435 | postgres-ai | Interne Docker uniquement | Jamais public |
| 6379 | redis | Interne Docker uniquement | Jamais public |
| 11434 | ollama | Interne Docker uniquement | Jamais public |
| 3000 | grafana | Admin uniquement | VPN/bastion |

### Annexe C — OWASP Top 10 API — Couverture PodIQ

| Risque OWASP API | Contrôle PodIQ |
|-----------------|----------------|
| API1 — Broken Object Level Authorization | RBAC workspace, `require_auth()` vérifie workspace_id |
| API2 — Broken Authentication | JWT double (auth + workspace), refresh rotation, httpOnly |
| API3 — Broken Object Property Level Authorization | Strawberry schema typing strict |
| API4 — Unrestricted Resource Consumption | Rate limiting Nginx, `MAX_LOG_LINES`, `AI_TIMEOUT_SECONDS` |
| API5 — Broken Function Level Authorization | `require_auth()` sur toutes mutations/queries |
| API6 — Unrestricted Access to Sensitive Business Flows | API Keys scopées, CI/CD endpoint séparé |
| API7 — Server Side Request Forgery | Ollama en interne uniquement, pas d'URL client acceptée |
| API8 — Security Misconfiguration | hadolint, yamllint, headers Nginx sécurisés |
| API9 — Improper Inventory Management | CLAUDE.md maintenu, README par service |
| API10 — Unsafe Consumption of APIs | Pydantic v2 validation, gRPC typed interfaces |

### Annexe D — Roadmap sécurité

| Priorité | Action | Échéance |
|----------|--------|----------|
| ✅ ~~P0~~ | ~~Migrer hachage passwords de SHA-256 vers Argon2id~~ — **Résolu 2026-05-25** : Argon2id (time=2, mem=64 MB, p=2) implémenté dans auth-service ; migration transparente au login ; 47 tests verts | ~~Q3 2026~~ |
| ✅ ~~P1~~ | ~~Propager `workspace_id` dans les protos gRPC ai-service, filtres `Analysis` + `IncidentPattern`, migration `0002_workspace_id`~~ — **Résolu 2026-05-26** : isolation tenant complète pour toutes nouvelles analyses ; données historiques (avant migration) restent NULL (comportement global acceptable) | ~~Q3 2026~~ |
| 🔴 P0 | Mettre en place HashiCorp Vault pour les secrets production | Q3 2026 |
| 🔴 P0 | Activer TLS gRPC (mTLS) inter-services en production | Q3 2026 |
| 🟠 P1 | Configurer Dependabot pour audit automatique des dépendances | Q2 2026 |
| 🟠 P1 | Ajouter scan Trivy dans la CI sur chaque image Docker | Q2 2026 |
| ✅ ~~P0~~ | ~~Supprimer le mount `/var/run/docker.sock` de Promtail~~ — **Résolu 2026-05-25** : Promtail supprimé, log driver Loki actif sur 12 services, 0 socket monté | ~~Q3 2026~~ |
| ✅ ~~P1~~ | ~~Augmenter rétention Loki à 90 jours~~ — **Résolu 2026-05-25** : `retention_period: 2160h` dans `infra/loki/loki-config.yml`, image reconstruite | ~~Q2 2026~~ |
| 🟡 P2 | Implémenter rate limiting applicatif (par user/IP) sur GraphQL | Q3 2026 |
| 🟡 P2 | Ajouter depth limiting et complexity limiting GraphQL | Q3 2026 |
| 🟡 P2 | Mettre en place des tests de pénétration trimestriels | Q4 2026 |
| 🟢 P3 | Certification SOC 2 Type I — audit externe | Q1 2027 |
| 🟢 P3 | Certification SOC 2 Type II — audit externe (12 mois) | Q1 2028 |

---

## Historique des révisions

| Version | Date | Auteur | Modifications |
|---------|------|--------|---------------|
| 1.0 | 2026-05-24 | Équipe PodIQ | Création initiale |
| 1.1 | 2026-05-25 | Équipe PodIQ | Ajout R-11 (docker.sock Promtail) ; roadmap P0 socket + P1 rétention Loki 90j |
| 1.2 | 2026-05-25 | Équipe PodIQ | Clôture R-11 : Promtail → log driver Loki (0 docker.sock) ; rétention 168h → 2160h (90j) ; doc K8s prod ajoutée |
| 1.3 | 2026-05-25 | Équipe PodIQ | §8.3 mis à jour : SHA-256+pepper → Argon2id (OWASP, memory-hard, sel unique) ; roadmap P0 Argon2id fermé ; 47 tests auth verts |
| 1.4 | 2026-05-26 | Équipe PodIQ | Ajout R-12 (patterns cross-workspace) ; §13.2 limitation connue documentée ; roadmap P1 propagation `workspace_id` fermée ; correction filtre `analysisJob`/`jobStatus` par `workspace_id` |

---

*Ce document est classifié **Confidentiel**. Toute diffusion externe doit être approuvée par le Responsable Sécurité.*

*Prochaine révision : **2027-05-24** ou à tout changement d'architecture majeur.*
