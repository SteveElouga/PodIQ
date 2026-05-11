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
- (Futur) Exposer un endpoint **REST** sur `/cicd/scan` pour les pipelines CI/CD

Il ne fait **aucun appel direct à Kubernetes**, **aucun appel à Ollama**, et **n'accède à aucune base de données autre que la sienne** (sessions Django).

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-gateway`** (port 5432).

Elle contient uniquement les tables internes à Django :
- `django_session` — sessions web (si utilisées)
- Tables d'administration Django (si activées)

Aucune donnée métier n'est stockée dans cette base.

---

## Interface GraphQL

Le Gateway expose une API GraphQL sur **`http://localhost:8080/graphql`**.

Le playground interactif est disponible à la même URL (en GET).

---

## Mutations disponibles

### `analyzeIncident` — Analyser un incident Kubernetes

Déclenche une analyse complète d'un pod en échec.

**Entrée :**
```graphql
mutation {
  analyzeIncident(podName: "mon-pod", namespace: "default") {
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
```

**Ce que le Gateway fait en interne, dans l'ordre :**

```
1. analyzer_client.collect_pod(pod_name, namespace)
   └── L'analyzer-service va chercher logs + events dans Kubernetes

2. analyzer_client.scan_namespace(namespace, timestamp)
   └── L'analyzer-service liste tous les pods du namespace

3. Construit le namespace_context
   └── Liste des autres pods du namespace avec leur état (had_issues, issue_timestamp)
   └── Permet à l'IA de détecter si plusieurs services tombent en même temps (corrélation)

4. Memory Engine — ai_client.get_history(pod_name, namespace, limit=5)
   └── Récupère les 5 derniers incidents connus pour ce pod/namespace
   └── Transforme chaque HistoryItem en PastIncident (error_type, root_cause, solution, occurred_at)
   └── Injecte dans le champ history[] de l'IncidentRequest
   └── Si aucun historique → history=[] et l'IA traite comme un premier incident

5. ai_client.analyze_incident(request avec history injecté)
   └── L'AI Service construit le prompt avec l'historique inclus
   └── Ollama voit les incidents passés → peut identifier une récurrence, affiner la cause
   └── Upsert dans incident_patterns (compteur d'occurrences)
   └── Retourne le diagnostic enrichi (is_recurring, recurrence_count)

6. Retourne AnalysisResultType au client GraphQL
```

**Pourquoi le Memory Engine est dans le Gateway et non dans l'AI Service ?**

Le Gateway est responsable de l'orchestration : il décide dans quel ordre appeler les services et quelles données assembler. L'AI Service reste pur — il reçoit toutes les données déjà préparées et se concentre uniquement sur l'analyse. Cette séparation garantit que l'AI Service est testable indépendamment, sans dépendance à son propre historique.

**Sortie :**
```
errorType              : String  — type d'erreur (ex: "CrashLoopBackOff")
rootCause              : String  — cause identifiée
explanation            : String  — explication détaillée
solution               : String  — actions recommandées
confidence             : String  — "high" | "medium" | "low"
isRecurring            : Boolean — pattern déjà connu
recurrenceCount        : Int     — nombre d'occurrences
correlatedService      : String  — service lié (null si aucun)
correlationExplanation : String  — explication de la corrélation (null si aucune)
```

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

2. ai_client.scan_manifest(parsed_manifest, related_history=[])
   └── L'AI Service envoie à Ollama pour détecter les risques

3. Retourne ManifestScanResultType
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

---

## Queries disponibles

### `analysisHistory` — Consulter l'historique d'un pod

**Entrée :**
```graphql
query {
  analysisHistory(podName: "mon-pod", namespace: "default", limit: 10) {
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

**Ce que le Gateway fait en interne :**
```
1. ai_client.get_history(pod_name, namespace, limit)
   └── L'AI Service lit ses analyses en base

2. Convertit les unix timestamps en ISO 8601 (ex: "2026-05-11T14:32:00")

3. Retourne [AnalysisHistoryItem]
```

---

## Schéma GraphQL complet

```
Query
└── analysisHistory(podName, namespace, limit) → [AnalysisHistoryItem]

Mutation
├── analyzeIncident(podName, namespace) → AnalysisResultType
├── scanManifest(yamlContent, manifestType) → ManifestScanResultType
├── register(email, password) → AuthPayload
└── login(email, password) → AuthPayload
```

---

## Clients gRPC internes

Le Gateway maintient un client gRPC léger pour chaque service backend.

| Client               | Service cible     | Port  | Méthodes                                        |
|----------------------|-------------------|-------|-------------------------------------------------|
| `analyzer_client.py` | analyzer-service  | 50052 | `collect_pod`, `scan_namespace`, `parse_manifest`|
| `ai_client.py`       | ai-service        | 50053 | `analyze_incident`, `scan_manifest`, `get_history`|
| `auth_client.py`     | auth-service      | 50051 | `register`, `login`, `validate_api_key`         |

Chaque appel gRPC ouvre un canal dédié (simple, sans pool — à optimiser avec Redis en Étape 11).

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
| `REDIS_URL`            | Non         | —            | `redis://redis:6379/0` (futur — Dramatiq) |
| `CORS_ALLOWED_ORIGINS` | Non         | `*`          | Origins autorisées (CORS)                 |

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

### 5. Tester une analyse

```graphql
mutation {
  analyzeIncident(podName: "crashloop-pod", namespace: "default") {
    errorType
    rootCause
    solution
    confidence
  }
}
```
