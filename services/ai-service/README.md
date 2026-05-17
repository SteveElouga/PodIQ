# AI Service — Le Cerveau Analytique

## Analogie

Imagine un **médecin urgentiste senior dans une unité de soins intensifs**.

- On lui amène un patient en mauvais état (un pod Kubernetes en échec), avec son dossier médical (logs, events, describe).
- Il consulte les **antécédents du patient** (historique des analyses passées) pour savoir si c'est une maladie chronique ou un nouvel incident.
- Il regarde aussi **l'état des autres patients dans la salle** (les autres pods du namespace) pour détecter une épidémie (corrélation inter-services).
- Il pose un **diagnostic structuré** : type d'erreur, cause racine, explication, traitement recommandé, et son niveau de confiance.
- Il remplit le **dossier médical** pour que la prochaine fois, ses collègues sachent que ce patient a déjà eu ce problème.

Pour les manifests Kubernetes, c'est comme un médecin qui examine un **bilan de santé préventif** avant que le patient soit opéré — il détecte les risques avant même le déploiement.

---

## Responsabilité

Ce service est le **seul** responsable de :
- Appeler Ollama (le modèle Mistral 7B local) avec des prompts structurés
- Analyser les incidents Kubernetes et produire un diagnostic JSON
- Scanner les manifests YAML à la recherche de risques de configuration
- Stocker les résultats d'analyse dans sa propre base de données
- Maintenir le **Memory Engine** : détecter les patterns récurrents en comparant avec l'historique
- Exposer l'historique des analyses aux autres services via gRPC

Il n'interagit jamais directement avec Kubernetes, ne gère pas les authentifications, et ne connaît pas le client HTTP.

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-ai`** (port 5435).

### Table `analyses`

Stocke chaque résultat d'analyse (incident, pré-déploiement, CI/CD).

| Colonne              | Type      | `incident`                              | `predeploy`                                      |
|----------------------|-----------|-----------------------------------------|--------------------------------------------------|
| `id`                 | UUID (PK) | —                                       | —                                                |
| `user_id`            | UUID      | uuid4 temporaire (à corriger)           | UUID transmis par le gateway                     |
| `analysis_type`      | string    | `"incident"`                            | `"predeploy"`                                    |
| `pod_name`           | string    | Nom du pod Kubernetes                   | `metadata.name` du manifest                      |
| `namespace`          | string    | Namespace Kubernetes                    | `metadata.namespace` du manifest                 |
| `status`             | string    | Statut du pod (ex: `CrashLoopBackOff`)  | vide                                             |
| `error_type`         | string    | Type d'erreur IA (ex: `CrashLoopBackOff`) | Catégorie du risk le plus critique (ex: `security`) |
| `root_cause`         | text      | Cause racine IA                         | Descriptions agrégées par sévérité décroissante  |
| `explanation`        | text      | Explication détaillée                   | Résumé Ollama (`summary`)                        |
| `solution`           | text      | Action corrective IA                    | Fixes agrégés par sévérité décroissante          |
| `confidence`         | string    | `high` / `medium` / `low`               | Dérivé du `risk_level` : `block`→`high`, `warning`→`medium`, `safe`→`low` |
| `risk_level`         | string    | vide                                    | `safe` / `warning` / `block`                     |
| `is_recurring`       | boolean   | `true` si pattern connu                 | `false`                                          |
| `correlated_service` | string    | Autre service corrélé                   | vide                                             |
| `risks`              | JSON      | `[{severity, category, description, fix}]` synthétique | `[{severity, category, description, fix}]` trié par sévérité |
| `created_at`         | datetime  | —                                       | —                                                |

### Table `incident_patterns`

Le **Memory Engine** : garde une trace des patterns récurrents pour les incidents **et** les scans predeploy/CI/CD.

| Colonne            | Type      | Description                                              |
|--------------------|-----------|----------------------------------------------------------|
| `id`               | UUID (PK) | Identifiant unique du pattern                            |
| `pod_name`         | string    | Nom du pod (incident) ou `metadata.name` du manifest (predeploy) |
| `namespace`        | string    | Namespace                                                |
| `error_type`       | string    | Type d'erreur (incident) ou catégorie du risque le plus critique (predeploy) |
| `occurrence_count` | int       | Nombre de fois que ce pattern a été observé              |
| `first_seen`       | datetime  | Première occurrence                                      |
| `last_seen`        | datetime  | Dernière occurrence (mis à jour automatiquement)         |
| `last_solution`    | text      | Dernière solution proposée                               |

**Contrainte unique** : `(pod_name, namespace, error_type)` — un seul enregistrement par combinaison, mis à jour à chaque nouvelle occurrence (upsert).

> `ScanManifest` appelle aussi `_upsert_predeploy_pattern()` après chaque scan, de sorte que `recurrence_count` s'incrémente à chaque nouvelle analyse du même manifest avec le même type de risque dominant.

---

## Interface gRPC

Ce service implémente le contrat défini dans `proto/ai/ai.proto`.

Il écoute sur le port **50053**.

---

### `AnalyzeIncident` — Analyser un incident Kubernetes

**Entrée :**
```
pod_name          : string         — nom du pod en échec
namespace         : string         — namespace Kubernetes
status            : string         — statut actuel du pod
logs              : string         — logs du conteneur (max 2000 lignes, nettoyés)
events            : string         — événements Kubernetes du pod
history           : PastIncident[] — 5 derniers incidents similaires (Memory Engine)
namespace_context : PodContext[]   — état des autres pods du namespace
```

**Sortie :**
```
error_type              : string  — ex: "CrashLoopBackOff"
root_cause              : string  — ex: "Variable d'environnement DATABASE_URL manquante"
explanation             : string  — explication complète pour l'ingénieur
solution                : string  — ex: "Vérifier le Secret K8s et relancer le pod"
confidence              : string  — "high" | "medium" | "low"
is_recurring            : bool    — true si ce pattern existe déjà en base
recurrence_count        : int     — nombre de fois observé
correlated_service      : string  — autre service lié (vide si aucun)
correlation_explanation : string  — explication de la corrélation (vide si aucune)
```

**Ce qui se passe en interne :**

```
1. Construction du prompt (incident_prompt.py)
   └── Section CONTEXT    : pod_name, namespace, status
   └── Section LOGS       : logs bruts du conteneur (max 2000 lignes, déjà nettoyés par analyzer)
   └── Section EVENTS     : événements Kubernetes du pod
   └── Section HISTORY    : les PastIncident[] injectés par le Gateway
   │     "=== INCIDENT HISTORY (last N occurrences) ==="
   │     "1. [CrashLoopBackOff] Variable manquante — Solution: Vérifier Secret K8s"
   │     Si history=[] → "No previous incidents recorded."
   └── Section NAMESPACE  : état des autres pods (corrélation temporelle)

2. Appel à Ollama (client.py)
   └── POST /api/chat avec format="json" pour forcer une réponse JSON valide
   └── Timeout de 60s

3. Validation Pydantic (schemas/analysis.py)
   └── Vérifie tous les champs requis (error_type, root_cause, solution, confidence, etc.)
   └── coerce_to_str : si le modèle renvoie solution/root_cause/explanation/error_type sous forme de liste, les éléments sont joints en string (le prompt spécifie "single string" mais certains modèles ignorent la consigne)
   └── Si la réponse est invalide → fallback avec confidence="low" et champs par défaut

4. Persistence (core/models.py)
   └── INSERT dans `analyses` avec tous les champs du diagnostic
   └── UPSERT dans `incident_patterns` sur (pod_name, namespace, error_type)
         → Nouveau pattern : occurrence_count=1, first_seen=now
         → Pattern connu  : occurrence_count++, last_seen=now, last_solution=mise à jour

5. Retour du résultat gRPC avec is_recurring=true si occurrence_count > 1
```

---

### `ScanManifest` — Scanner un manifest Kubernetes

Utilisé avant un déploiement (`kubectl apply`) pour détecter les risques de configuration.

**Entrée :**
```
parsed_manifest    : string         — JSON sérialisé du ParsedManifest (vient de l'analyzer-service)
related_history    : PastIncident[] — incidents passés liés à ce type de config
user_id            : string         — UUID de l'utilisateur (auth-service)
manifest_name      : string         — metadata.name du manifest
manifest_namespace : string         — metadata.namespace du manifest
manifest_type      : string         — kind Kubernetes (Deployment, StatefulSet, ...)
```

**Sortie :**
```
risk_level : string     — "safe" | "warning" | "block"
risks      : RiskItem[] — liste des risques détectés
summary    : string     — résumé en langage naturel
```

**Structure d'un `RiskItem` :**
```
severity    : string  — "low" | "medium" | "high" | "critical"
category    : string  — "missing_env" | "probe" | "image_tag" | "memory" | "security"
description : string  — description du risque
fix         : string  — action corrective
```

**Ce qui se passe en interne :**

```
1. Construction du prompt (predeploy_prompt.py)
   └── Le prompt analyse le manifest pour : image :latest, sondes manquantes,
       limites mémoire absentes, variables d'environnement critiques manquantes

2. Appel à Ollama
   └── Même client, même mécanisme

3. Validation Pydantic (schemas/predeploy.py)
   └── Si invalide → risk_level="warning", risks=[]
   └── fix_critical_safe_contradiction : si risk_level="safe" mais qu'un risque "critical" est présent, risk_level est forcé à "block" (incohérence du modèle, pas un jugement nuancé)
   └── Le risk_level est sinon conservé tel quel — l'IA fait une évaluation holistique qui peut diverger de la severity individuelle

4. Persistence dans postgres-ai (`_save_predeploy_analysis`)
   └── Tous les champs mappés : pod_name, namespace, error_type, root_cause,
       explanation, solution, confidence, risk_level, risks (trié par sévérité)
```

---

### `GetAnalysisHistory` — Consulter l'historique

Utilisé par le Gateway pour le Memory Engine et pour la query GraphQL `analysisHistory`.

**Entrée :**
```
pod_name      : string  — filtrer par pod / nom du manifest
namespace     : string  — filtrer par namespace
limit         : int     — nombre maximum de résultats (défaut : 10)
analysis_type : string  — "" = tous | "incident" | "predeploy" (optionnel)
```

**Sortie :**
```
items : HistoryItem[]
```

**Structure d'un `HistoryItem` :**
```
id               : UUID string
pod_name         : string
namespace        : string
error_type       : string
root_cause       : string
solution         : string
confidence       : string
is_recurring     : bool
recurrence_count : int
created_at       : int     — unix timestamp
analysis_type    : string  — "incident" | "predeploy"
risk_level       : string  — "safe" | "warning" | "block" (predeploy uniquement)
```

---

## Le Memory Engine

C'est le mécanisme qui rend PodIQ plus intelligent à chaque analyse. Contrairement à K8sGPT qui traite chaque incident de façon isolée, PodIQ se souvient.

**Principe — flux complet :**

```
Incident détecté sur "mon-pod" (namespace "production")
      │
      ▼
[Gateway] GetAnalysisHistory(pod_name="mon-pod", namespace="production", limit=5)
      │     └── Requête sur la table `analyses` de postgres-ai
      │     └── Triée par created_at DESC — les plus récents en premier
      │
      ▼
[Gateway] Transforme les HistoryItem → PastIncident[]
      │     error_type  : "CrashLoopBackOff"
      │     root_cause  : "Variable DATABASE_URL manquante"
      │     solution    : "Vérifier le Secret K8s"
      │     occurred_at : 1746900000  (unix timestamp)
      │
      ▼
[Gateway] Injecte history=PastIncident[] dans l'IncidentRequest
      │
      ▼
[AI Service] incident_prompt.py construit le prompt avec l'historique :
      │     === INCIDENT HISTORY (last 3 occurrences) ===
      │     1. [CrashLoopBackOff] Variable DATABASE_URL manquante — Solution: Vérifier Secret K8s
      │     2. [OOMKilled] Limite mémoire trop basse — Solution: Augmenter resources.limits.memory
      │     ...
      │
      ▼
[Ollama] Analyse avec contexte historique
      │     → peut identifier : "Ce pod crashe régulièrement, pattern récurrent"
      │     → affine la confidence selon la cohérence avec l'historique
      │     → is_recurring=true si même error_type vu précédemment
      │
      ▼
[AI Service] Sauvegarde dans `analyses` + upsert dans `incident_patterns`
      │     incident_patterns : upsert sur (pod_name, namespace, error_type)
      │     → si existe déjà : occurrence_count++, last_seen=now, last_solution=nouvelle solution
      │     → si nouveau : création avec occurrence_count=1
      │
      ▼
La prochaine analyse de ce pod aura encore plus de contexte
```

**Ce que le Memory Engine permet concrètement :**

| Sans Memory Engine | Avec Memory Engine |
|--------------------|--------------------|
| Chaque incident traité de façon isolée | L'IA sait que ce pod a crashé 5 fois ce mois |
| Confidence toujours incertaine | Confidence plus haute si pattern connu |
| Solution générée sans contexte | Solution affinée en tenant compte des solutions passées |
| `is_recurring` toujours `false` | `is_recurring=true` dès la 2e occurrence |

**Analogie :** C'est comme si le médecin urgentiste avait accès au dossier médical complet du patient avant de poser son diagnostic, au lieu de traiter chaque visite comme un premier rendez-vous.

---

## Comment Ollama est appelé

```python
POST http://ollama:11434/api/chat
{
  "model": "mistral",
  "format": "json",          ← force une réponse JSON valide
  "stream": false,
  "options": {"temperature": 0.1},  ← quasi-déterministe, évite les boucles du greedy pur
  "messages": [
    {"role": "system", "content": "<SYSTEM_PROMPT>"},
    {"role": "user",   "content": "<USER_PROMPT avec les données>"}
  ]
}
```

Le paramètre `format: "json"` guide Ollama vers du JSON, mais certains modèles ajoutent encore du texte ou des blocs Markdown autour du JSON.

### Extraction et validation de la réponse

Après la réponse HTTP, le service **extrait le premier `{` jusqu’au dernier `}`** du corps texte avant `json.loads` et validation Pydantic (`AnalysisResponse`, `ManifestScanResponse`). Cela limite les échecs lorsque le modèle entoure le JSON de prose ou de fences Markdown.

### Choix du modèle (dev local)

- **`mistral`** (tag `mistral` / `mistral:latest`) est le choix documenté pour PodIQ : bon compromis pour des prompts longs (logs + historique + contexte namespace) et le format JSON.
- Les variantes **« thinking »** (ex. certains tags **qwen3**) peuvent générer beaucoup de tokens intermédiaires et provoquer des échecs ou des **HTTP 500** côté Ollama sur les gros prompts, même avec une RAM suffisante. En cas de problème, revenir à **`OLLAMA_MODEL=mistral`** après `ollama pull mistral` dans le conteneur Ollama.

---

## Variables d'environnement

| Variable                  | Obligatoire | Défaut              | Description                             |
|---------------------------|-------------|---------------------|-----------------------------------------|
| `DATABASE_URL`            | Oui         | —                   | `postgresql://user:pass@postgres-ai/db` |
| `DJANGO_SECRET_KEY`       | Oui         | —                   | Clé secrète Django                      |
| `OLLAMA_HOST`             | Non         | `http://ollama:11434`| URL du serveur Ollama                  |
| `OLLAMA_MODEL`            | Non         | `mistral`           | Modèle Ollama (nom tel équivalent `ollama list`) |
| `AI_TIMEOUT_SECONDS`      | Non         | `30`                | Timeout HTTP client vers Ollama (s) — souvent **120** en dev CPU |
| `INCIDENT_HISTORY_DEPTH`  | Non         | `5`                 | Nombre d'incidents passés dans le prompt|
| `GRPC_PORT`               | Non         | `50053`             | Port d'écoute gRPC                      |

---

## Communication avec les autres services

```
Gateway ──gRPC──▶ AI Service ──HTTP──▶ Ollama (Mistral 7B)
                      │
                      └──▶ postgres-ai
```

Ce service est **appelé par** le Gateway.
Ce service **appelle** Ollama (via HTTP) et sa propre base de données.

---

## Comment tester

### Tests unitaires (pytest)

```bash
cd services/ai-service
python3 -m pytest -v
```

Les hooks **pre-commit** du dépôt incluent **mypy** sur ce service lorsque des fichiers Python sous `services/ai-service/` sont stagés ; voir le README racine § « Pré-commit ».

### 1. Démarrer les dépendances

```bash
docker compose up -d postgres-ai ollama ai-service
docker compose logs -f ai-service
```

### 2. Vérifier que les migrations ont tourné

```bash
docker compose exec postgres-ai psql -U podiq -d podiq_ai -c "\dt"
```

Doit afficher les tables `analyses` et `incident_patterns`.

### 3. Tester via le playground GraphQL

Lance l'ensemble de la stack, puis exécute depuis `http://localhost:8080/graphql` :

```graphql
mutation {
  analyzeIncident(podName: "mon-pod", namespace: "default") {
    errorType
    rootCause
    solution
    confidence
    isRecurring
  }
}
```
