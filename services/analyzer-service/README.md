# Analyzer Service — Le Technicien de Terrain

## Analogie

Imagine un **technicien de maintenance industrielle** envoyé sur le site d'une usine en panne.

- Quand une machine (un pod) tombe en panne, on l'envoie sur place pour **collecter toutes les données** : les journaux de bord (logs), les rapports d'incident (events Kubernetes), et une inspection complète de la machine (describe). Il ne répare rien — il documente. C'est le `CollectPod`.
- En même temps, il fait le tour de **toute l'usine** pour voir quelles autres machines ont des problèmes en ce moment. Il liste leur état pour détecter si la panne est isolée ou généralisée. C'est le `ScanNamespace`.
- Quand un ingénieur lui soumet les **plans d'une nouvelle machine** avant installation, il lit les plans, extrait les informations importantes, et les met en forme pour que l'expert puisse les analyser. C'est le `ParseManifest`.

Le technicien ne pose **aucun diagnostic** — c'est le rôle de l'AI Service. Son rôle est de **collecter et nettoyer** les données brutes de Kubernetes.

---

## Responsabilité

Ce service est le **seul** à interagir directement avec l'API Kubernetes. Il est responsable de :
- Récupérer les logs, events et describe d'un pod via le SDK Kubernetes Python
- Scanner tous les pods d'un namespace et résumer leur état
- Parser les fichiers YAML Kubernetes et en extraire une structure exploitable
- **Nettoyer les logs** : tronquer à 2000 lignes maximum, masquer les secrets
- Transmettre ces données brutes au Gateway (qui les passe à l'AI Service)

Il ne stocke **pas** les résultats d'analyse — uniquement des snapshots bruts pour traçabilité.

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-analyzer`** (port 5434).

### Table `logs_snapshots`

Stocke les données brutes collectées à chaque incident.

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

Stocke l'état du namespace au moment de chaque incident (pour la corrélation temporelle).

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

### `CollectPod` — Collecter les données d'un pod

**Entrée :**
```
pod_name  : string  — nom du pod en échec
namespace : string  — namespace Kubernetes
```

**Sortie :**
```
pod_name  : string  — confirmé
namespace : string  — confirmé
status    : string  — statut actuel du pod (ex: "CrashLoopBackOff")
logs      : string  — dernières 2000 lignes de logs, secrets masqués
events    : string  — événements Kubernetes formatés en texte lisible
```

**Ce qui se passe en interne :**

```
1. Chargement de la config Kubernetes
   └── Essaie d'abord incluster (si déployé dans le cluster)
   └── Puis kubeconfig local (~/.kube/config)

2. Récupération des logs (kubernetes SDK)
   └── client.read_namespaced_pod_log(pod_name, namespace, tail_lines=2000)

3. Récupération des events
   └── client.list_namespaced_event() → filtre sur ce pod

4. Récupération du describe
   └── client.read_namespaced_pod() → formaté manuellement

5. Nettoyage (log_cleaner.py)
   └── Tronque à 2000 lignes (garde les plus récentes)
   └── Masque 9 patterns de secrets :
       password=***  token=***  api_key=***  secret=***
       Authorization: ***  Bearer ***  private_key=***  etc.

6. Sauvegarde du snapshot en base (logs_snapshots)

7. Retour de la structure PodData
```

---

### `ScanNamespace` — Scanner l'état d'un namespace

**Entrée :**
```
namespace : string  — namespace à scanner
timestamp : int64   — unix timestamp du moment de l'incident
```

**Sortie :**
```
namespace : string
pods      : PodSummary[]  — liste de tous les pods du namespace
```

**Structure d'un `PodSummary` :**
```
pod_name         : string  — nom du pod
status           : string  — statut Kubernetes
has_errors       : bool    — true si le pod est en erreur
last_restart_time: int64   — timestamp du dernier redémarrage (0 si aucun)
```

**Détection d'erreurs :** Un pod est marqué `has_errors=true` si son statut contient l'un de ces mots : `CrashLoopBackOff`, `OOMKilled`, `Error`, `ImagePullBackOff`, `ErrImagePull`.

**Ce qui se passe en interne :**

```
1. Liste tous les pods du namespace via Kubernetes API

2. Pour chaque pod → _summarize_pod()
   └── Lit le statut de chaque conteneur
   └── Détecte les erreurs dans les container states
   └── Extrait le timestamp du dernier restart

3. Sauvegarde du snapshot en base (namespace_snapshots)

4. Retour de la liste des PodSummary
```

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

## Le Nettoyage des Logs — Détail

C'est une étape critique pour la sécurité. Le service doit s'assurer que **jamais** un secret n'est transmis à l'IA.

### Troncature

Les 2000 dernières lignes sont conservées (les plus récentes = les plus pertinentes).

**Pourquoi ici et pas dans l'AI Service ?**  
Règle architecturale : les données doivent être nettoyées **avant toute transmission** inter-service. L'AI Service reçoit des données déjà prêtes.

### Masquage des secrets

Les patterns suivants sont détectés et remplacés par `***` :

```
password=<valeur>       → password=***
passwd=<valeur>         → passwd=***
secret=<valeur>         → secret=***
token=<valeur>          → token=***
api_key=<valeur>        → api_key=***
auth=<valeur>           → auth=***
Authorization: <valeur> → Authorization: ***
Bearer <valeur>         → Bearer ***
private_key=<valeur>    → private_key=***
```

---

## Variables d'environnement

| Variable             | Obligatoire | Défaut   | Description                                                             |
|----------------------|-------------|----------|-------------------------------------------------------------------------|
| `DATABASE_URL`       | Oui         | —        | `postgresql://user:pass@postgres-analyzer/db`                           |
| `DJANGO_SECRET_KEY`  | Oui         | —        | Clé secrète Django                                                      |
| `KUBECONFIG`         | Non         | —        | Chemin vers kubeconfig (hors cluster)                                   |
| `MAX_LOG_LINES`      | Non         | `2000`   | Nombre maximal de lignes de logs à conserver                            |
| `GRPC_PORT`          | Non         | `50052`  | Port d'écoute gRPC                                                      |
| `STUB_MODE`          | Non         | `false`  | Si `true`, retourne des données K8s fictives — développement sans cluster |

---

## Communication avec les autres services

```
Gateway ──gRPC──▶ Analyzer Service ──API──▶ Kubernetes (kubectl)
                        │
                        └──▶ postgres-analyzer
```

Ce service est **appelé par** le Gateway.  
Ce service **appelle** l'API Kubernetes (et sa propre base de données).  
Ce service **ne connaît pas** l'AI Service — c'est le Gateway qui orchestre.

---

## Comment tester

### Sans cluster Kubernetes — STUB_MODE

Si tu n'as pas de cluster K8s disponible, active le mode stub dans ton `.env` :

```env
STUB_MODE=true
```

En mode stub, `CollectPod` retourne un pod fictif en `CrashLoopBackOff` (erreur de connexion DB) et `ScanNamespace` retourne un namespace avec 3 pods fictifs. Le reste du pipeline (AI Service → Ollama) s'exécute normalement.

```bash
docker compose up -d --build analyzer-service
```

Vérifie les logs — tu dois voir `collect_pod_stub` ou `scan_namespace_stub` à la place de `collect_pod` :

```bash
docker compose logs analyzer-service | grep "stub"
```

### Avec un vrai cluster Kubernetes

Mets `STUB_MODE=false` dans `.env` et assure-toi que le kubeconfig est accessible.

### 1. Démarrer les dépendances

```bash
docker compose up -d postgres-analyzer analyzer-service
docker compose logs -f analyzer-service
```

### 2. Tester via une analyse complète

```bash
docker compose up -d  # toute la stack
```

Puis depuis le playground GraphQL `http://localhost:8080/graphql` :

```graphql
mutation {
  analyzeIncident(podName: "mon-pod-crashé", namespace: "default") {
    errorType
    rootCause
    solution
  }
}
```

L'analyzer-service sera automatiquement appelé en premier par le gateway.

### 3. Vérifier les snapshots en base

```bash
docker compose exec postgres-analyzer psql -U podiq -d podiq_analyzer -c "SELECT pod_name, namespace, created_at FROM logs_snapshots ORDER BY created_at DESC LIMIT 5;"
```
