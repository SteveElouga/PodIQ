# PodIQ — AI-Powered Kubernetes Incident Intelligence Platform

> **"Ton cluster a une mémoire. PodIQ la lit."**

PodIQ est une plateforme SaaS DevOps qui ne se contente pas d'analyser une erreur Kubernetes — elle la comprend dans son contexte historique, prédit les problèmes avant qu'ils arrivent, corrèle les incidents entre services, et bloque les déploiements dangereux en CI/CD.

**Ce que les concurrents (K8sGPT, Komodor, Botkube) ne font pas :**
- Mémoriser les patterns d'incidents pour détecter les récurrences
- Analyser un manifest YAML **avant** `kubectl apply` pour prédire les crashs
- Corréler un crash dans service A avec une dégradation dans service B
- Bloquer nativement un pipeline CI/CD si l'IA détecte une configuration dangereuse

---

## Table des matières

1. [Vision produit & positionnement](#1-vision-produit--positionnement)
2. [Cible utilisateur](#2-cible-utilisateur)
3. [Proposition de valeur différenciante](#3-proposition-de-valeur-différenciante)
4. [Les 4 différenciants clés](#4-les-4-différenciants-clés)
5. [Périmètre MVP](#5-périmètre-mvp)
6. [Architecture technique](#6-architecture-technique)
7. [Structure du monorepo](#7-structure-du-monorepo)
8. [Services microservices](#8-services-microservices)
9. [Communication inter-services gRPC](#9-communication-inter-services-grpc)
10. [Flux utilisateurs complets](#10-flux-utilisateurs-complets)
11. [Stack technique détaillée](#11-stack-technique-détaillée)
12. [Dépendances par service](#12-dépendances-par-service)
13. [Infrastructure & Observabilité](#13-infrastructure--observabilité)
14. [Variables d'environnement](#14-variables-denvironnement)
15. [Schéma de base de données](#15-schéma-de-base-de-données)
16. [Prompts IA](#16-prompts-ia)
17. [Format de réponse standardisé](#17-format-de-réponse-standardisé)
18. [Sécurité](#18-sécurité)
19. [Roadmap MVP](#19-roadmap-mvp)
20. [Évolution post-MVP](#20-évolution-post-mvp)
21. [Modèle économique](#21-modèle-économique)
22. [Notes pour Cursor](#22-notes-pour-cursor)

---

## 0. Démarrage rapide

### Prérequis
- Docker + Docker Compose installés
- 16 GB RAM minimum (Ollama + Mistral 7B)
- Copier `.env.example` → `.env` (les valeurs par défaut fonctionnent en dev)

### Lancer toute la stack

```bash
cp .env.example .env
docker compose up -d --build
```

### Vérifier que tout est en ordre

```bash
curl http://localhost:8080/healthz
# → {"status": "ok"}
```

### Tester l'analyse d'incident (sans cluster Kubernetes)

`STUB_MODE=true` dans `.env` fait tourner l'analyzer en mode bouchon : il simule un pod en `CrashLoopBackOff` avec des logs fictifs, sans toucher à Kubernetes.

```bash
# 1. Créer un compte
curl -s -X POST http://localhost:8080/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"mutation { register(email: \"demo@podiq.io\", password: \"pass1234\") { token } }"}' \
  | python3 -m json.tool

# 2. Copier le token puis analyser un pod
TOKEN="<token_obtenu_ci-dessus>"
curl -s -X POST http://localhost:8080/graphql \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"mutation { analyzeIncident(podName: \"test\", namespace: \"default\") { errorType rootCause solution confidence correlatedService correlationExplanation } }"}' \
  | python3 -m json.tool
```

**Résultat attendu :** un objet JSON avec `errorType`, `rootCause`, `solution`, `confidence`, et si un pod voisin est en erreur dans la fenêtre de 15 min : `correlatedService` + `correlationExplanation`.

### Playground GraphQL interactif

Ouvrir **`http://localhost:8080/graphql`** dans le navigateur (header `Authorization: Bearer <token>`).

---

## 1. Vision produit & positionnement

PodIQ est une **plateforme d'intelligence des incidents Kubernetes**.

### Pourquoi PodIQ et pas K8sGPT ?

| Capacité | K8sGPT | Komodor | PodIQ |
|---|---|---|---|
| Analyse d'erreur en temps réel | ✅ | ✅ | ✅ |
| Mémoire des incidents passés | ❌ | Partiel | ✅ |
| Détection de patterns récurrents | ❌ | ❌ | ✅ |
| Analyse pre-deploy (manifest YAML) | ❌ | ❌ | ✅ |
| Corrélation multi-services | ❌ | Partiel | ✅ |
| Intégration CI/CD native (blocage pipeline) | ❌ | ❌ | ✅ |
| IA locale (confidentialité logs) | Optionnel | ❌ | ✅ |

K8sGPT est un excellent outil CLI. PodIQ est une **plateforme intelligente** : elle apprend, anticipe et s'intègre dans le workflow DevOps existant.

---

## 2. Cible utilisateur

**Persona principal :**
- DevOps Engineer / SRE
- Backend Engineer travaillant avec Kubernetes
- Niveau : intermédiaire à senior
- Contexte : équipes de 3 à 50 ingénieurs

**Douleurs actuelles résolues :**
- Perte de temps à analyser des logs manuellement à chaque incident
- Même erreur qui revient sans que personne ne l'ait documentée
- Déploiement cassant la prod à cause d'une mauvaise config YAML
- Crash dans un service causé par un autre — introuvable sans corrélation
- Dépendance à ChatGPT sans contexte cluster ni mémoire

---

## 3. Proposition de valeur différenciante

PodIQ n'est pas un wrapper IA sur `kubectl`. C'est une plateforme qui :

- **Analyse** l'incident actuel avec un contexte Kubernetes complet et automatique
- **Se souvient** des incidents passés et détecte les patterns récurrents
- **Prédit** les problèmes avant le déploiement en lisant les manifests YAML
- **Corrèle** les incidents entre services pour trouver la vraie cause racine
- **Bloque** les pipelines CI/CD quand une configuration dangereuse est détectée

---

## 4. Les 4 différenciants clés

### 4.1 Mémoire des incidents (Incident Memory)

**Problème résolu :** Le même pod crashe pour la même raison 3 fois en 2 semaines. Personne ne s'en souvient.

**Ce que PodIQ fait :**
- Stocke chaque analyse avec son contexte complet
- Détecte automatiquement quand un incident est récurrent
- Affiche : *"Ce pod a crashé 3 fois ce mois pour la même raison."*
- Enrichit chaque nouveau prompt avec les 5 derniers incidents similaires

**Implémentation :**
- Table `incident_patterns` — upsert sur `(pod_name, namespace, error_type)`
- `memory/engine.py` dans `ai-service`

---

### 4.2 Analyse pre-deploy (Pre-Deploy Scanner)

**Problème résolu :** Un `deployment.yaml` mal configuré casse la prod. 30 minutes de rollback perdues.

**Ce que PodIQ fait :**
- Accepte un manifest YAML avant `kubectl apply`
- Détecte : variables manquantes, limites mémoire trop basses, probes absentes, images sans tag fixe
- Croise avec l'historique pour détecter des configs qui ont déjà causé des crashs
- Retourne un rapport : `safe` / `warning` / `block`

**Implémentation :**
- `parsers/yaml_parser.py` dans `analyzer-service`
- Prompt IA spécialisé `predeploy_prompt.py`
- CLI : `podiq scan manifest deployment.yaml`

---

### 4.3 Corrélation multi-services (Cross-Service Correlation)

**Problème résolu :** Service A crashe à cause de Service B en OOMKilled. Sans corrélation, on cherche dans les mauvais logs.

**Ce que PodIQ fait :**
- Collecte l'état de tous les pods du namespace à chaque analyse
- Détecte les causalités temporelles (fenêtre configurable, défaut 15 min)
- Affiche : *"postgres-service was OOMKilled 6 minutes before this crash."*

**Comment ça marche en détail :**

1. L'analyzer scanne **tous les pods** du namespace au moment de l'incident et retourne leur statut, leurs erreurs, et leur dernier `restart_time`.
2. Le gateway construit le **`namespace_context`** : il retire le pod analysé de la liste, puis pour chaque voisin, calcule si son dernier restart tombe **dans la fenêtre de 15 minutes** avant l'incident. Chaque pod reçoit un flag `in_correlation_window`, un champ `seconds_before_reference`, et son statut.
3. Ce contexte enrichi est transmis à l'AI Service dans le prompt. Le modèle peut alors distinguer une panne **isolée** d'une **dégradation simultanée** dans le namespace et proposer un `correlated_service` avec une `correlation_explanation`.

**Résultat attendu dans la réponse GraphQL :**
```json
{
  "correlatedService": "worker-6b8c",
  "correlationExplanation": "worker-6b8c had issues 5 minutes before the incident snapshot"
}
```
Si aucun voisin n'est dans la fenêtre : `correlatedService: null`, `correlationExplanation: null`.

**Variable d'environnement :** `CORRELATION_WINDOW_MINUTES` (défaut `15`).

**Implémentation :**
- `collectors/namespace_scan.py` dans `analyzer-service`
- `app/namespace_correlation.py` dans `gateway` (`build_namespace_context`)
- Table `namespace_snapshots` PostgreSQL (analyzer-service)
- Prompt incident (`namespace_context` section) dans `ai-service`

---

### 4.4 Intégration CI/CD native (Pipeline Gate)

**Problème résolu :** Les analyses post-incident arrivent trop tard. Le déploiement est déjà en prod.

**Ce que PodIQ fait :**
- Endpoint REST dédié : `POST /api/v1/cicd/scan`
- Auth via API Key (adapté aux pipelines)
- Exit codes : 0 = safe, 1 = warning, 2 = block
- Support GitHub Actions et GitLab CI

**Implémentation :**
- `gateway/api/cicd.py`
- `apikeys/` dans `auth-service`
- GitHub Action officielle `podiq/scan-action@v1` (Phase 2)

---

## 5. Périmètre MVP

### Inclus MVP

- Analyse d'incident : logs, events, statut pod, réponse IA < 5s
- **Mémoire** : stockage + détection récurrence + historique par pod dans l'UI
- **Pre-deploy Scanner** : scan YAML via CLI et UI, rapport de risque
- **Corrélation** (simplifié MVP) : état du namespace affiché à chaque analyse
- **Endpoint CI/CD** : `POST /api/v1/cicd/scan` avec API Key

```bash
podiq analyze pod <pod-name> --namespace <namespace>
podiq scan manifest <path/to/deployment.yaml>
```

### Hors scope MVP

- Multi-cluster, OAuth2/SSO, RAG vectoriel, WebSocket temps réel
- GitHub Action packagée (Phase 2)
- Kafka, Elasticsearch, service mesh, Kubernetes local

---

## 6. Architecture technique

### Vue globale

```
[Frontend Angular / CLI]
         ↓ GraphQL + REST (CI/CD)
  [API Gateway Django]       [postgres-gateway]
         ↓ gRPC
   ┌─────┼───────────────────┐
   ↓     ↓                   ↓
[Analyzer]  [AI Service]  [Auth Service]
  Service    Ollama          JWT
 kubectl     Memory          API Keys
 YAML        Correlator
   │              │               │
[postgres-  [postgres-      [postgres-
 analyzer]    ai]             auth]

  Redis (Dramatiq queue + cache)
  Promtail → Loki → Grafana
```

**Principe fondamental :** chaque service est un microservice **entièrement indépendant**.
- Sa propre base PostgreSQL — aucun accès à la base d'un autre service
- Sa propre stack Django ORM + migrations
- Toute communication inter-service passe exclusivement par **gRPC**
- Les références croisées sont des UUIDs applicatifs, sans FK cross-service

### Diagramme microservices

```
                ┌─────────────────┐
                │   Frontend      │
                │   Angular       │
                └────────┬────────┘
                         │ GraphQL (HTTP/WS)
                    ┌────▼────┐
                    │  Nginx  │
                    └────┬────┘
                         │
                ┌────────▼──────────────┐
                │      API Gateway      │
                │  Django + Strawberry  │
                │  + REST /api/v1/      │
                └───┬──────────┬────────┘
                    │          │
              ┌─────┘    ┌─────┘
              │ gRPC      │ gRPC          gRPC
              ▼           ▼               ▼
┌─────────────────┐ ┌──────────────┐ ┌──────────────┐
│   AI Service    │ │   Analyzer   │ │    Auth      │
│  Ollama client  │ │   Service    │ │   Service    │
│  Memory Engine  │ │ kubectl/k8s  │ │  JWT         │
│  Correlator     │ │ YAML Parser  │ │  API Keys    │
│  Django ORM     │ │ Django ORM   │ │  Django ORM  │
└────────┬────────┘ └──────┬───────┘ └──────┬───────┘
         │                 │                 │
         ▼                 ▼                 ▼
  [postgres-ai]   [postgres-analyzer]  [postgres-auth]
  analyses         logs_snapshots       users
  incident_        namespace_           api_keys
  patterns         snapshots

[API Gateway Django ORM]──▶[postgres-gateway]
 (sessions Django uniquement)

┌────────────────┐
│    Ollama      │
│ qwen2.5-coder  │
│     :14b       │
└────────────────┘

┌────────────────┐
│  Redis Queue   │
│  (Dramatiq)    │
└────────────────┘

        Observabilité
┌─────────────────────────────────────┐
│  Promtail → Loki → Grafana          │
└─────────────────────────────────────┘
```

---

## 7. Structure du monorepo

```
podiq/
├── services/
│   ├── gateway/
│   │   ├── app/
│   │   │   ├── graphql/
│   │   │   │   ├── schema.py
│   │   │   │   ├── mutations/
│   │   │   │   │   ├── analyze.py
│   │   │   │   │   └── scan_manifest.py
│   │   │   │   └── queries/
│   │   │   │       ├── analyses.py
│   │   │   │       └── incident_history.py
│   │   │   ├── api/
│   │   │   │   └── cicd.py            # POST /api/v1/cicd/scan
│   │   │   ├── models/
│   │   │   └── workers/               # Dramatiq workers
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── analyzer-service/
│   │   ├── app/
│   │   │   ├── collectors/
│   │   │   │   ├── pod_logs.py
│   │   │   │   ├── pod_events.py
│   │   │   │   └── namespace_scan.py  # différenciant #3
│   │   │   ├── parsers/
│   │   │   │   ├── log_cleaner.py
│   │   │   │   └── yaml_parser.py     # différenciant #2
│   │   │   └── grpc_server.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── ai-service/
│   │   ├── app/
│   │   │   ├── prompts/
│   │   │   │   ├── incident_prompt.py
│   │   │   │   ├── predeploy_prompt.py
│   │   │   │   └── correlation_prompt.py
│   │   │   ├── ollama/
│   │   │   │   └── client.py
│   │   │   ├── memory/
│   │   │   │   ├── engine.py          # différenciant #1
│   │   │   │   └── enricher.py
│   │   │   ├── correlator/
│   │   │   │   └── temporal.py        # différenciant #3
│   │   │   └── grpc_server.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── auth-service/
│       ├── app/
│       │   ├── jwt/
│       │   └── apikeys/               # différenciant #4
│       ├── Dockerfile
│       └── requirements.txt
│
├── proto/
│   ├── ai/ai.proto
│   ├── analyzer/analyzer.proto
│   └── auth/auth.proto
│
├── infra/
│   ├── nginx/nginx.conf
│   ├── grafana/dashboards/podiq-overview.json
│   ├── loki/loki-config.yml
│   └── promtail/promtail-config.yml
│
├── shared/
│   ├── utils/
│   ├── schemas/
│   │   ├── analysis.py
│   │   ├── predeploy.py
│   │   └── pattern.py
│   └── grpc/                          # stubs gRPC générés
│
├── docker-compose.yml
├── docker-compose.override.yml
├── .env.example
├── Makefile
└── README.md
```

---

## 8. Services microservices

> **Principe de lecture :** chaque service est comme un **département indépendant d'un hôpital**. Ils ne se parlent qu'en passant par le couloir principal (gRPC), ne partagent pas leurs dossiers (PostgreSQL séparés), et ont chacun leur propre rôle spécialisé.

### 8.1 Gateway Service

> **Analogie :** La **réceptionniste de l'hôpital**. Elle reçoit le patient (la requête), comprend sa demande, contacte les bons départements dans le bon ordre, et lui remet la réponse finale. Elle ne fait **aucun diagnostic** — elle orchestre et transmet.

**Rôle :** Point d'entrée unique — GraphQL pour l'UI/CLI, REST pour les pipelines CI/CD.

**Base de données :** `postgres-gateway` — sessions Django uniquement

**Responsabilités :**
- Exposer l'API GraphQL (Strawberry) pour UI et CLI
- Exposer `POST /api/v1/cicd/scan` en REST avec auth API Key
- Valider JWT et API Keys via gRPC vers auth-service (jamais en local)
- Orchestrer les appels via gRPC — zéro logique métier, zéro accès aux bases des autres services
- Gérer la file Redis (Dramatiq) — ne jamais bloquer sur l'IA

---

### 8.2 Analyzer Service

> **Analogie :** Le **technicien de terrain** de l'hôpital. Quand un patient arrive, il va sur place collecter tous les examens bruts : prise de sang (logs), radio (events), fiche d'entrée (describe). Il récupère aussi l'état de toute la salle de soins (namespace) pour voir si d'autres patients autour ont eu des problèmes récemment. Il **ne diagnostique pas** — il collecte et nettoie.

**Rôle :** Interaction exclusive avec Kubernetes + parsing YAML.

**Base de données :** `postgres-analyzer` — `logs_snapshots`, `namespace_snapshots`

**Responsabilités :**
- Logs pod (max 2000 lignes), events, describe output
- Scanner l'état de tous les pods du namespace (différenciant #3)
- Parser un manifest YAML (différenciant #2)
- Masquer les secrets dans les logs avant transmission
- Nettoyer et structurer toutes les données
- Stocker les snapshots dans sa propre base

---

### 8.3 AI Service

> **Analogie :** Le **médecin expert** de l'hôpital. Il reçoit tous les examens déjà préparés par le technicien, consulte le dossier médical du patient (mémoire des incidents passés), regarde si d'autres patients dans la même salle ont eu des problèmes récents (corrélation namespace), puis pose un **diagnostic** : cause racine, solution, récurrence, service corrélé.

**Rôle :** Cerveau IA + Memory Engine + Corrélateur temporel.

**Base de données :** `postgres-ai` — `analyses`, `incident_patterns`

**Responsabilités :**
- Analyse incident : prompt enrichi historique → Ollama
- Pre-deploy scan : prompt spécialisé
- Memory Engine : lire historique dans **sa propre base** + enrichir le prompt (5 derniers incidents)
- Corrélateur temporel : détecter causalités inter-services dans la fenêtre de 15 min
- Valider toutes les réponses IA avec Pydantic strict
- Fallback si Ollama est indisponible

---

### 8.4 Auth Service

> **Analogie :** Le **portier de l'hôpital**. Il vérifie les badges (JWT) et les laissez-passer permanents (API Keys pour les pipelines CI/CD). Il ne connaît rien de l'intérieur — son seul rôle est de répondre à la question : *"Est-ce que cette personne a le droit d'entrer ?"*

**Rôle :** Auth utilisateurs + gestion API Keys CI/CD.

**Base de données :** `postgres-auth` — `users`, `api_keys`

**Responsabilités :**
- Login / Register + JWT
- Génération et validation des API Keys pour pipelines
- Révocation d'API Keys
- Seul service autorisé à lire/écrire `users` et `api_keys`

---

## 9. Communication inter-services gRPC

### proto/analyzer/analyzer.proto

```protobuf
syntax = "proto3";
package analyzer;

service AnalyzerService {
  rpc CollectPod (PodRequest) returns (PodData);
  rpc ScanNamespace (NamespaceRequest) returns (NamespaceSnapshot);
  rpc ParseManifest (ManifestRequest) returns (ParsedManifest);
}

message PodRequest {
  string pod_name = 1;
  string namespace = 2;
  int32 log_lines = 3;
}

message PodData {
  string pod_name = 1;
  string namespace = 2;
  string status = 3;
  string logs = 4;
  string events = 5;
  string describe_output = 6;
}

message NamespaceRequest {
  string namespace = 1;
  int64 timestamp = 2;
}

message NamespaceSnapshot {
  string namespace = 1;
  repeated PodSummary pods = 2;
  int64 collected_at = 3;
}

message PodSummary {
  string pod_name = 1;
  string status = 2;
  bool has_errors = 3;
  int64 last_restart_time = 4;
}

message ManifestRequest {
  string yaml_content = 1;
  string manifest_type = 2;
}

message ParsedManifest {
  string manifest_type = 1;
  string name = 2;
  string namespace = 3;
  repeated string env_vars = 4;
  string memory_limit = 5;
  string cpu_limit = 6;
  bool has_liveness_probe = 7;
  bool has_readiness_probe = 8;
  string image = 9;
  bool image_has_fixed_tag = 10;
  string raw_config = 11;
}
```

### proto/ai/ai.proto

```protobuf
syntax = "proto3";
package ai;

service AIService {
  rpc AnalyzeIncident    (IncidentRequest)    returns (AnalysisResult);
  rpc ScanManifest       (ManifestScanRequest) returns (ManifestScanResult);
  rpc GetAnalysisHistory (HistoryRequest)     returns (HistoryResponse);
}

message IncidentRequest {
  string pod_name = 1;
  string namespace = 2;
  string status = 3;
  string logs = 4;
  string events = 5;
  repeated PastIncident history = 6;         // Memory Engine
  repeated PodContext namespace_context = 7; // Corrélation
}

message PastIncident {
  string error_type = 1;
  string root_cause = 2;
  string solution = 3;
  int64 occurred_at = 4;
}

message PodContext {
  string pod_name = 1;
  string status = 2;
  bool had_issues = 3;
  int64 issue_timestamp = 4;
}

message AnalysisResult {
  string error_type = 1;
  string root_cause = 2;
  string explanation = 3;
  string solution = 4;
  string confidence = 5;
  bool is_recurring = 6;
  int32 recurrence_count = 7;
  string correlated_service = 8;
  string correlation_explanation = 9;
}

message ManifestScanRequest {
  string parsed_manifest = 1;
  repeated PastIncident related_history = 2;
}

message ManifestScanResult {
  string risk_level = 1;
  repeated RiskItem risks = 2;
  string summary = 3;
}

message RiskItem {
  string severity = 1;
  string category = 2;
  string description = 3;
  string fix = 4;
}
```

---

## 10. Flux utilisateurs complets

### Flux 1 — Analyse d'incident

```
1. Utilisateur sélectionne pod + namespace dans Angular
2. Mutation GraphQL → Gateway
3. Gateway valide JWT → crée job Dramatiq dans Redis
4. Worker → Analyzer Service : CollectPod
5. Worker → Analyzer Service : ScanNamespace
6. Worker → PostgreSQL : 5 derniers incidents du pod (Memory Engine)
7. Worker → AI Service : AnalyzeIncident
   (prompt enrichi avec historique + contexte namespace)
8. AI Service → Ollama → parse → retourne AnalysisResult
9. Gateway stocke résultat + namespace_snapshot en PostgreSQL
10. Gateway upsert incident_patterns
11. Frontend reçoit le résultat
```

### Flux 2 — Pre-deploy Scan

```
1. Utilisateur upload deployment.yaml (Angular ou CLI)
2. Mutation ScanManifest → Gateway
3. Analyzer Service : ParseManifest
4. PostgreSQL : incidents liés à ce type de config
5. AI Service : ScanManifest (prompt pre-deploy + historique)
6. Retour : rapport de risque avec sévérité et fixes
```

### Flux 3 — Pipeline CI/CD Gate

```
1. Pipeline envoie POST /api/v1/cicd/scan
   Headers: Authorization: ApiKey <key>
   Body: { yaml_content, branch, environment }
2. Gateway valide l'API Key → même logique que Flux 2
3. Retour JSON + exit code :
   "safe"    → exit 0, pipeline continue
   "warning" → exit 1, pipeline continue + Slack
   "block"   → exit 2, pipeline s'arrête
```

### Résultat affiché — Analyse incident

```
❌ Error Type: CrashLoopBackOff

📌 Root Cause:
Application crashes at startup due to missing DATABASE_URL env variable

🔁 Recurring — 3rd time this month
  → 2025-04-28: fixed by adding DATABASE_URL to secret
  → 2025-05-02: secret rotation without deployment update

🔗 Correlated: postgres-service OOMKilled 6 min before this crash
   Probable cause: database unavailability triggered the crash loop

💡 Solution:
1. Verify DATABASE_URL is in your deployment secret
2. Check postgres-service memory limits (256Mi → recommend 512Mi)
3. Add a readiness probe to prevent traffic before DB is ready

🔍 Confidence: High
```

---

## 11. Stack technique détaillée

| Domaine | Technologie | Justification |
|---|---|---|
| API Gateway | Django 5.2 + Strawberry GraphQL | Stack Python cohérente, GraphQL flexible |
| API CI/CD | Django REST Framework (minimal) | REST plus adapté pour pipelines |
| GraphQL | Strawberry | Plus moderne que Graphene, typage Python natif |
| Microservices | Python 3.12 | Perf améliorée, async natif |
| Communication interne | gRPC + protobuf | Rapide, typé, scalable |
| Queue async | Dramatiq + Redis | Plus simple que Celery, moderne |
| Base de données | PostgreSQL + JSONB | JSONB pour historique incidents |
| Cache / Queue | Redis | Jobs async, rate limiting, cache API keys |
| IA locale | Ollama 0.23.2 + qwen2.5-coder:14b | Gratuit, Dockerisable, confidentialité logs — configurable via `OLLAMA_MODEL` |
| Logs centralisés | Grafana Loki | Cohérent avec produit orienté observabilité |
| Agent logs | Promtail | Lit stdout Docker → Loki |
| Visualisation | Grafana | Debug rapide + dashboard incidents |
| Validation | Pydantic v2 | Parsing IA, schemas typés |
| YAML parsing | PyYAML | Pre-deploy scanner |
| Reverse proxy | Nginx | Frontend, GraphQL, REST |
| Conteneurisation | Docker + Docker Compose | Dev local |
| Frontend | Angular | Cohérent avec la stack |

---

## 12. Dépendances par service

### Gateway

```txt
Django==5.2.1
djangorestframework==3.16.0
strawberry-graphql[django] @ https://github.com/strawberry-graphql/strawberry/archive/1eb08b2513798cd42e0f503ab9b430fb0c8b783c.tar.gz
psycopg[binary]==3.2.13
redis==6.0.0
dramatiq[redis]==1.18.0
grpcio==1.80.0
protobuf==6.31.1
python-dotenv==1.1.0
uvicorn==0.34.2
structlog==25.4.0
django-cors-headers==4.7.0
gunicorn==23.0.0
pytest==8.3.5
pytest-django==4.11.1
```

> `grpcio-tools`, `PyJWT` et `httpx` ne sont pas utilisés dans le gateway. Strawberry GraphQL est installé depuis une archive GitHub (commit pinné), comme dans `services/gateway/requirements.txt`, pour la compatibilité Python 3.14 en local.

### Analyzer Service

```txt
Django==5.2.1
psycopg[binary]==3.2.13
grpcio==1.80.0
protobuf==6.31.1
kubernetes==32.0.1
PyYAML==6.0.2
python-dotenv==1.1.0
structlog==25.4.0
pydantic==2.13.4
gunicorn==23.0.0
pytest==8.3.5
```

### AI Service

```txt
Django==5.2.1
psycopg[binary]==3.2.13
grpcio==1.80.0
protobuf==6.31.1
redis==6.0.0
ollama==0.4.8
httpx==0.28.1
python-dotenv==1.1.0
structlog==25.4.0
pydantic==2.13.4
gunicorn==23.0.0
pytest==8.3.5
```

### Auth Service

```txt
Django==5.2.1
psycopg[binary]==3.2.13
PyJWT==2.10.1
grpcio==1.80.0
protobuf==6.31.1
python-dotenv==1.1.0
structlog==25.4.0
pytest==8.3.5
pytest-django==4.11.1
```

> `grpcio-tools` n'est pas dans les `requirements.txt` de service — c'est une dépendance de build uniquement, dans `requirements-dev.txt` à la racine.

### Dev (racine) — `requirements-dev.txt`

```txt
grpcio-tools==1.73.0
black==25.1.0
isort==6.0.1
ruff==0.11.9
mypy==1.15.0
pytest==8.3.5
pytest-django==4.11.1
pytest-asyncio==0.26.0
coverage==7.8.0
pre-commit==4.2.0
```

---

## 13. Infrastructure & Observabilité

### Conteneurs Docker Compose

| Conteneur | Rôle |
|---|---|
| `gateway` | API GraphQL + REST CI/CD |
| `auth-service` | JWT + API Keys |
| `analyzer-service` | Collecte K8s + YAML parser + Namespace scan |
| `ai-service` | IA + Memory Engine + Corrélateur |
| `postgres-gateway` | Base dédiée gateway (sessions Django) |
| `postgres-auth` | Base dédiée auth-service (users, api_keys) |
| `postgres-analyzer` | Base dédiée analyzer-service (logs, snapshots) |
| `postgres-ai` | Base dédiée ai-service (analyses, patterns) |
| `redis` | Queue async Dramatiq + cache |
| `ollama` | Modèle IA local Mistral 7B |
| `grafana` | Visualisation logs + dashboard incidents |
| `loki` | Agrégation logs centralisés |
| `promtail` | Agent collecte logs Docker |
| `nginx` | Reverse proxy |

### Réseaux et volumes

```yaml
networks:
  backend:       # gateway, services, redis, tous les postgres
  observability: # grafana, loki, promtail

volumes:
  postgres_gateway_data:
  postgres_auth_data:
  postgres_analyzer_data:
  postgres_ai_data:
  grafana_data:
  ollama_data:
  loki_data:
```

### Dashboard Grafana PodIQ

Dashboard `podiq-overview.json` configuré pour visualiser :
- Nombre d'analyses par heure / jour
- Distribution des `error_type` détectés
- Top 10 pods les plus incidents (score récurrence)
- Latence des appels Ollama
- Score de risque des scans pre-deploy

### Nginx — Résolution DNS dynamique

Nginx utilise `resolver 127.0.0.11` (DNS interne Docker) avec une variable `$gateway_upstream` pour re-résoudre le hostname `gateway` à chaque requête. Cela garantit que Nginx continue de fonctionner après un redémarrage du container gateway (qui peut changer d'IP dans le réseau Docker). Ne pas utiliser de bloc `upstream` statique — il résout l'IP une seule fois au démarrage et la garde en cache.

### Ressources machine recommandées

| Composant | RAM estimée |
|---|---|
| Ollama (Mistral 7B) | ~8 GB |
| PostgreSQL | ~512 MB |
| Grafana + Loki | ~1 GB |
| Services Python x4 | ~1 GB total |
| **Minimum** | **16 GB RAM** |
| **Recommandé** | **32 GB RAM** |

---

## 13.5 Mode développement sans cluster Kubernetes — STUB_MODE

Par défaut (`STUB_MODE=false`), l'**analyzer-service** appelle le **vrai cluster Kubernetes** via `kubectl`. En développement local sans cluster, mettre **`STUB_MODE=true`** dans `.env`.

**Ce que STUB_MODE fait :**
- `collect_pod()` retourne des **logs et événements fictifs** : un pod en `CrashLoopBackOff`, des erreurs de connexion à Postgres, 7 restarts. Le nom du pod fourni par l'appelant est conservé, le reste est simulé.
- `scan_namespace()` retourne une **liste fictive de 3 pods** dans le namespace demandé :
  - `api-gateway-7d9f` — Running, pas d'erreur
  - `worker-6b8c` — CrashLoopBackOff, `last_restart_time = maintenant − 300s` (dans la fenêtre de corrélation)
  - `redis-0` — Running, pas d'erreur

**Ce qui reste réel même en STUB_MODE :**
- Le gateway orchestre toujours tous les appels dans le bon ordre
- La corrélation namespace est calculée avec les vraies règles (fenêtre, tri, `in_correlation_window`)
- L'AI Service envoie un **vrai prompt** à **Ollama** et reçoit une vraie réponse du modèle
- La mémoire des incidents est lue et écrite en base

**En production / staging :** toujours `STUB_MODE=false` (ou absent). L'analyzer utilise le kubeconfig monté dans le conteneur.

---

## 14. Variables d'environnement

```env
# PostgreSQL — identifiants partagés, chaque service a sa propre instance
POSTGRES_USER=podiq
POSTGRES_PASSWORD=changeme

# Database URLs par service (chaque service lit uniquement la sienne)
GATEWAY_DATABASE_URL=postgresql://podiq:changeme@postgres-gateway:5432/podiq_gateway
AUTH_DATABASE_URL=postgresql://podiq:changeme@postgres-auth:5433/podiq_auth
ANALYZER_DATABASE_URL=postgresql://podiq:changeme@postgres-analyzer:5434/podiq_analyzer
AI_DATABASE_URL=postgresql://podiq:changeme@postgres-ai:5435/podiq_ai

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
JWT_SECRET=supersecret_change_in_production
JWT_EXPIRY_MINUTES=60

# API Keys CI/CD
API_KEY_SALT=changeme_salt

# Ollama
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=mistral

# gRPC ports
ANALYZER_GRPC_HOST=analyzer-service
ANALYZER_GRPC_PORT=50052
AI_GRPC_HOST=ai-service
AI_GRPC_PORT=50053
AUTH_GRPC_HOST=auth-service
AUTH_GRPC_PORT=50051

# Django (par service)
DJANGO_SECRET_KEY=changeme
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Limites
MAX_LOG_LINES=2000
AI_TIMEOUT_SECONDS=30

# Memory Engine
INCIDENT_HISTORY_DEPTH=5

# Corrélation
CORRELATION_WINDOW_MINUTES=15

# Développement — mettre false avec un vrai cluster K8s
STUB_MODE=true

# CI/CD
SLACK_WEBHOOK_URL=
```

**Règle absolue :** Ne jamais hardcoder ces valeurs. Toujours lire depuis `os.environ` via `python-dotenv`.

---

## 15. Schéma de base de données

Chaque service possède ses tables dans sa propre instance PostgreSQL. Aucun FK cross-service — les références croisées sont des UUIDs applicatifs transmis via gRPC.

### postgres-auth — auth-service

#### users
```sql
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMP DEFAULT NOW()
);
```

#### api_keys
```sql
CREATE TABLE api_keys (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL,          -- référence applicative vers users.id
  key_hash   VARCHAR(255) NOT NULL,
  name       VARCHAR(100),           -- ex: "github-actions-prod"
  last_used  TIMESTAMP,
  is_active  BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

### postgres-ai — ai-service

#### analyses
```sql
CREATE TABLE analyses (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            UUID NOT NULL,         -- référence applicative (auth-service)
  analysis_type      VARCHAR(20) NOT NULL,  -- incident | predeploy | cicd
  pod_name           VARCHAR(255),
  namespace          VARCHAR(255),
  status             VARCHAR(100),
  error_type         VARCHAR(255),
  root_cause         TEXT,
  explanation        TEXT,
  solution           TEXT,
  confidence         VARCHAR(20),           -- high | medium | low
  risk_level         VARCHAR(20),           -- safe | warning | block
  is_recurring       BOOLEAN DEFAULT FALSE,
  recurrence_count   INT DEFAULT 0,
  correlated_service VARCHAR(255),
  correlation_type   VARCHAR(50),
  risks              JSONB,
  created_at         TIMESTAMP DEFAULT NOW()
);
```

#### incident_patterns — Memory Engine
```sql
-- Upsert à chaque analyse. Clé du Memory Engine.
CREATE TABLE incident_patterns (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pod_name         VARCHAR(255) NOT NULL,
  namespace        VARCHAR(255) NOT NULL,
  error_type       VARCHAR(255) NOT NULL,
  occurrence_count INT DEFAULT 1,
  first_seen       TIMESTAMP DEFAULT NOW(),
  last_seen        TIMESTAMP DEFAULT NOW(),
  last_solution    TEXT,
  UNIQUE (pod_name, namespace, error_type)
);
```

---

### postgres-analyzer — analyzer-service

#### logs_snapshots
```sql
CREATE TABLE logs_snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id     UUID NOT NULL,    -- référence applicative (ai-service)
  raw_logs        TEXT,
  events          TEXT,
  describe_output TEXT,
  created_at      TIMESTAMP DEFAULT NOW()
);
```

#### namespace_snapshots — Corrélation
```sql
-- État du namespace au moment d'un incident.
CREATE TABLE namespace_snapshots (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id  UUID NOT NULL,       -- référence applicative (ai-service)
  namespace    VARCHAR(255) NOT NULL,
  pods_state   JSONB NOT NULL,      -- [{pod_name, status, has_errors, last_restart_time}]
  collected_at TIMESTAMP DEFAULT NOW()
);
```

---

### postgres-gateway — gateway

Tables Django auto-générées uniquement (sessions, admin, auth Django interne).

---

## 16. Prompts IA

### Prompt 1 — Analyse d'incident (enrichi mémoire + corrélation)

```python
INCIDENT_SYSTEM_PROMPT = """
You are a senior Site Reliability Engineer specialized in Kubernetes with 10+ years of experience.
Analyze Kubernetes pod failures and provide clear, actionable diagnoses.
Always respond ONLY with a valid JSON object. No text outside the JSON.
"""

INCIDENT_USER_PROMPT = """
Analyze the following Kubernetes incident.

Pod: {pod_name} | Namespace: {namespace} | Status: {status}

=== LOGS ===
{logs}

=== EVENTS ===
{events}

=== INCIDENT HISTORY (last {history_count} occurrences) ===
{incident_history}

=== NAMESPACE CONTEXT (other pods at incident time) ===
{namespace_context}

Return ONLY this JSON:
{
  "error_type": "short error category",
  "root_cause": "one sentence — the probable root cause",
  "explanation": "2-3 sentences explaining what happened simply",
  "solution": "step-by-step actionable solution",
  "confidence": "high | medium | low",
  "is_recurring": true | false,
  "correlated_service": "pod name if another pod caused this, else null",
  "correlation_explanation": "one sentence if correlated, else null"
}
"""
```

### Prompt 2 — Pre-deploy Scanner

```python
PREDEPLOY_SYSTEM_PROMPT = """
You are a senior Kubernetes reliability and security expert.
Review Kubernetes manifests BEFORE deployment and identify configuration risks.
Always respond ONLY with a valid JSON object.
"""

PREDEPLOY_USER_PROMPT = """
Review the following Kubernetes manifest for risks before deployment.

Manifest: {manifest_type} | Name: {name} | Namespace: {namespace}

=== CONFIGURATION ===
{parsed_config}

=== RELATED INCIDENT HISTORY ===
{related_history}

Analyze for: missing_env, memory limits, probe config, image tag,
             missing secrets, resource requests, security context.

Return ONLY this JSON:
{
  "risk_level": "safe | warning | block",
  "summary": "one sentence summary of the main risk",
  "risks": [
    {
      "severity": "low | medium | high | critical",
      "category": "category_name",
      "description": "what is wrong",
      "fix": "exact fix to apply"
    }
  ]
}
"""
```

---

## 17. Format de réponse standardisé

### Analyse d'incident

```json
{
  "error_type": "CrashLoopBackOff",
  "root_cause": "Application crashes at startup due to missing DATABASE_URL env variable",
  "explanation": "The pod starts, attempts DB connection using DATABASE_URL which is not defined, and immediately exits. Kubernetes restarts it repeatedly.",
  "solution": "1. Add DATABASE_URL to your deployment secret\n2. Reference it:\n   env:\n     - name: DATABASE_URL\n       valueFrom:\n         secretKeyRef:\n           name: app-secrets\n           key: database-url",
  "confidence": "high",
  "is_recurring": true,
  "recurrence_count": 3,
  "correlated_service": "postgres-service",
  "correlation_explanation": "postgres-service was OOMKilled 6 minutes before this crash"
}
```

### Pre-deploy / CI/CD Scan

```json
{
  "risk_level": "block",
  "summary": "Missing DATABASE_URL — this config caused 3 crashes this month",
  "risks": [
    {
      "severity": "critical",
      "category": "missing_env",
      "description": "DATABASE_URL is not defined. Will cause immediate CrashLoopBackOff.",
      "fix": "Add DATABASE_URL via secretKeyRef in your env section"
    },
    {
      "severity": "medium",
      "category": "probe",
      "description": "No readiness probe. Pod will receive traffic before the app is ready.",
      "fix": "Add readiness probe on /health with initialDelaySeconds: 10"
    }
  ]
}
```

---

## 18. Sécurité

**MVP obligatoire :**
- Masquer les secrets dans les logs avant envoi à Ollama (regex sur `password`, `secret`, `token`, `key`)
- RBAC K8s minimal : `get`, `list` sur pods/logs uniquement
- Validation JWT sur chaque requête GraphQL
- Validation API Key sur endpoint CI/CD (hash bcrypt en base)
- Rate limiting par utilisateur et par API Key (Redis)
- Logs bruts : TTL 30 jours maximum
- Variables sensibles uniquement via `.env` / Docker secrets

**Ne jamais faire :**
- Stocker des logs en clair indéfiniment
- Exposer le kubeconfig publiquement
- Hardcoder des credentials dans le code
- Logger les contenus de prompts en production

---

## 19. Roadmap MVP

### Semaine 1 — Fondation ✅

- [x] Monorepo + Docker Compose complet (4 postgres + tous conteneurs up)
- [x] Django ORM + migrations dans chaque service (chaque service possède ses tables)
  - auth-service : `users`, `api_keys`
  - ai-service : `analyses`, `incident_patterns`
  - analyzer-service : `logs_snapshots`, `namespace_snapshots`
  - gateway : sessions Django uniquement
- [x] Redis + Ollama (pull Mistral 7B)
- [x] proto gRPC → génération stubs Python dans `shared/grpc/`
- [x] Analyzer Service : `CollectPod` + `ScanNamespace` + `ParseManifest`
- [x] AI Service : `AnalyzeIncident` + `ScanManifest` + `GetAnalysisHistory`
- [x] Auth Service : `Register` + `Login` + `ValidateJWT` + `CreateApiKey` + `ValidateApiKey` + `RevokeApiKey`
- [x] Gateway GraphQL complet : `analyzeIncident`, `scanManifest`, `register`, `login`, `analysisHistory`
- [x] Loki + Promtail + Grafana configurés (labels `service`, `namespace`, rétention 7j)
- [x] README.md dans chaque microservice (FR, analogies, gRPC I/O, DB, env vars)

### Semaine 2 — IA & Différenciants

- [x] **Memory Engine** : gateway appelle `GetAnalysisHistory` avant chaque `AnalyzeIncident`, injecte `history[]`
- [ ] **Corrélation temporelle** complète (fenêtre 15 min, `namespace_context` enrichi)
- [ ] **Prompt pre-deploy** flux complet gateway ↔ analyzer ↔ ai
- [ ] Queue Dramatiq + Redis (flux async complet)
- [ ] **Endpoint REST CI/CD** `POST /api/v1/cicd/scan` + Auth API Key

### Semaine 3 — UI, CLI & Finalisation

- [ ] Angular : analyse incident + historique du pod
- [ ] Angular : upload YAML + rapport pre-deploy
- [ ] CLI : `podiq analyze pod` + `podiq scan manifest`
- [ ] Dashboard Grafana `podiq-overview.json`
- [ ] Tests unitaires services core (coverage > 70%)
- [ ] Déploiement staging

---

## 20. Évolution post-MVP

| Feature | Différenciant | Priorité |
|---|---|---|
| GitHub Action officielle `podiq/scan-action@v1` | #4 CI/CD | Haute |
| GitLab CI template natif | #4 CI/CD | Haute |
| Alertes récurrence Slack/Teams | #1 Mémoire | Haute |
| Corrélation avancée (graph de dépendances) | #3 Corrélation | Haute |
| RAG sur historique incidents (embeddings) | #1 Mémoire | Moyenne |
| Analyse YAML élargie (RBAC, NetworkPolicy, HPA) | #2 Pre-deploy | Moyenne |
| Multi-cluster support | — | Moyenne |
| Dashboard santé cluster (scoring global) | — | Basse |
| Migration Docker Compose → Kubernetes | — | Phase 3 |
| SSO / OAuth2 | — | Phase 3 |

---

## 21. Modèle économique

**Gratuit :**
- 10 analyses incident / jour
- Pre-deploy scan illimité (levier d'acquisition principal)
- Historique 7 jours — 1 cluster

**Pro (payant) :**
- Analyses illimitées + Memory Engine complet
- Corrélation multi-services
- Intégration CI/CD native (GitHub Actions, GitLab CI)
- Multi-cluster + notifications Slack/Teams

**Enterprise :**
- Self-hosted (confidentialité totale des logs — argument fort)
- RBAC avancé par namespace + SSO + SLA

> Le pre-deploy scan gratuit et illimité est le levier d'acquisition : c'est la feature la plus facile à tester sans cluster, idéale pour convertir des devs qui découvrent le produit.

---

## 22. Notes pour Cursor

### Conventions de code

- Python 3.12 partout, type hints obligatoires sur toutes les fonctions
- Pydantic v2 pour **tous** les modèles de données inter-services et réponses IA
- `structlog` pour les logs — jamais `print` ni `logging` standard
- Ruff pour le linting, Black pour le formatage
- Tests Pytest, coverage > 70%

### Points d'attention critiques

1. **Ne jamais appeler Ollama depuis la Gateway** — passer obligatoirement par ai-service via gRPC
2. **Truncate à 2000 lignes dans analyzer-service** — jamais dans ai-service
3. **Le job d'analyse est toujours async** — la Gateway ne bloque jamais sur l'IA
4. **La Gateway est légère** — orchestration uniquement, zéro logique métier
5. **Masquer les secrets dans analyzer-service** — avant toute transmission à ai-service
6. **Memory Engine dans ai-service** — lit PostgreSQL directement pour enrichir le prompt
7. **Endpoint CI/CD est REST** — exit codes 0 / 1 / 2, pas GraphQL
8. **`incident_patterns` : upsert à chaque analyse** — clé unique `(pod_name, namespace, error_type)`
9. **`namespace_snapshots` collecté à chaque analyse incident** — même si la corrélation est partielle

### Ordre de développement recommandé

```
1.  Docker Compose complet
2.  Migrations PostgreSQL (toutes les tables dès le début)
3.  proto gRPC → génération stubs
4.  Analyzer Service : CollectPod + ScanNamespace + ParseManifest
5.  AI Service : AnalyzeIncident (prompt basique, valider JSON)
6.  Gateway GraphQL : mutation analyze + query history
7.  Memory Engine (lecture historique + enrichissement prompt)
8.  Namespace scan + corrélation temporelle
9.  Pre-deploy scan : ParseManifest + prompt predeploy
10. Endpoint CI/CD REST + API Keys
11. Redis Queue Dramatiq (flux async complet)
12. Loki + Grafana + Promtail + dashboard
13. Frontend Angular
14. CLI
```