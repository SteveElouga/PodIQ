# Analyzer Service — Le Lecteur de Plans

## Analogie

Imagine un **expert en normes de construction** qui examine les plans d'une nouvelle machine avant son installation.

Quand un ingénieur lui soumet les **plans d'une nouvelle installation** (un manifeste YAML Kubernetes), il lit les plans, extrait les informations importantes, et les met en forme pour que l'expert en sécurité puisse les analyser. C'est le `ParseManifest`.

Il ne collecte **plus** de données depuis les clusters — ce rôle est désormais assuré par l'**agent PodIQ** déployé directement dans le cluster du client. L'agent envoie ses collectes au Gateway via `agentReportIncident`.

---

## Responsabilité

Ce service est responsable de :
- **Parser les fichiers YAML Kubernetes** et en extraire une structure exploitable pour l'AI Service
- Transmettre cette structure au Gateway (qui la passe à l'AI Service via `ScanManifest`)

Il ne stocke **pas** les résultats d'analyse — uniquement des snapshots bruts pour traçabilité.

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-analyzer`** (port 5434).

### Table `logs_snapshots`

Stocke les données brutes pour traçabilité.

| Colonne      | Type      | Description                                       |
|--------------|-----------|---------------------------------------------------|
| `id`         | UUID (PK) | Identifiant unique du snapshot                    |
| `pod_name`   | string    | Nom du pod inspecté                               |
| `namespace`  | string    | Namespace Kubernetes                              |
| `logs`       | text      | Logs nettoyés (max 2000 lignes, secrets masqués)  |
| `events`     | text      | Événements Kubernetes formatés                    |
| `describe`   | text      | Output complet du `kubectl describe pod`          |
| `created_at` | datetime  | Date de la collecte                               |

### Table `namespace_snapshots`

Stocke l'état du namespace au moment de chaque incident.

| Colonne       | Type      | Description                                          |
|---------------|-----------|------------------------------------------------------|
| `id`          | UUID (PK) | Identifiant unique du snapshot                       |
| `namespace`   | string    | Namespace scanné                                     |
| `snapshot`    | JSON      | Liste des pods avec leur état                        |
| `captured_at` | datetime  | Timestamp de la capture                              |

---

## Interface gRPC

Ce service implémente le contrat défini dans `proto/analyzer/analyzer.proto`.

Il écoute sur le port **50052**.

---

### `ParseManifest` — Parser un fichier YAML Kubernetes

**Entrée :**
```
yaml_content  : string  — contenu brut du fichier YAML
manifest_type : string  — type indicatif (optionnel, ex: "Deployment")
```

**Sortie :**
```
name         : string   — nom de la ressource
namespace    : string   — namespace (si défini)
kind         : string   — type de ressource (Deployment, StatefulSet, etc.)
raw_config   : string   — JSON sérialisé de la structure extraite
image        : string   — image Docker principale
has_fixed_tag: bool     — false si l'image utilise :latest ou pas de tag
env_vars     : string[] — noms des variables d'environnement définies
has_limits   : bool     — true si des resource limits sont définies
has_probes   : bool     — true si liveness ou readiness probes sont définies
```

**Règle sur `has_fixed_tag` :**
- `nginx:1.25` → `true` (tag fixe, c'est bien)
- `nginx:latest` → `false` (dangereux en production)
- `nginx` sans tag → `false` (équivaut à `:latest`)

**Ce qui se passe en interne :**

```
1. Parse le YAML avec PyYAML

2. Détecte le type (Deployment, StatefulSet, Job, Pod...)

3. Navigue dans la structure pour trouver le conteneur principal
   └── Pour un Deployment : spec.template.spec.containers[0]
   └── Pour un Pod simple : spec.containers[0]

4. Extrait image, env, resources, probes

5. Sérialise en JSON (raw_config) pour transmission à l'AI Service

6. Retourne ParsedManifest
```

---

## Variables d'environnement

| Variable             | Obligatoire | Défaut   | Description                                  |
|----------------------|-------------|----------|----------------------------------------------|
| `DATABASE_URL`       | Oui         | —        | URL PostgreSQL vers `postgres-analyzer:5434/podiq_analyzer`         |
| `DJANGO_SECRET_KEY`  | Oui         | —        | Clé secrète Django                           |
| `MAX_LOG_LINES`      | Non         | `2000`   | Nombre maximal de lignes de logs à conserver |
| `GRPC_PORT`          | Non         | `50052`  | Port d'écoute gRPC                           |

> Note : `STUB_MODE` et `KUBECONFIG` sont **supprimés** depuis phase-16. La collecte K8s est assurée par l'agent déployé dans le cluster client.

---

## Communication avec les autres services

```
Gateway ──gRPC──▶ Analyzer Service
                        │
                        └──▶ postgres-analyzer
```

Ce service est **appelé par** le Gateway (uniquement pour `ParseManifest` — scan de manifestes YAML).
Ce service **ne connaît pas** l'AI Service — c'est le Gateway qui orchestre.
La collecte K8s (logs, events, describe) est désormais faite par l'**agent** dans le cluster client.

---

## Comment tester

### Tests unitaires (pytest)

```bash
cd services/analyzer-service
python3 -m pytest -v
```

Les hooks **pre-commit** du dépôt incluent **mypy** sur ce service lorsque des fichiers Python sous `services/analyzer-service/` sont stagés ; configuration à la racine (`pyproject.toml`, `scripts/run_mypy_precommit.py`).

### Démarrer le service

```bash
docker compose up -d postgres-analyzer analyzer-service
docker compose logs -f analyzer-service
```

### Tester via une analyse complète (scan de manifeste)

Depuis le playground GraphQL `http://localhost:8080/graphql` :

```graphql
mutation {
  scanManifest(yamlContent: "apiVersion: apps/v1\nkind: Deployment\n...") {
    errorType
    recommendations
    blockDeployment
  }
}
```

### Vérifier les snapshots en base

```bash
docker compose exec postgres-analyzer psql -U podiq -d podiq_analyzer -c \
  "SELECT pod_name, namespace, created_at FROM logs_snapshots ORDER BY created_at DESC LIMIT 5;"
```
