# ERROR_RESOLVE.md

Journal des erreurs rencontrées sur le projet PodIQ, leurs causes et solutions.

---

## [2026-05-11] gRPC version mismatch — gateway crash au démarrage

**Erreur**
```
RuntimeError: The grpc package installed is at version 1.73.0,
but the generated code in analyzer/analyzer_pb2_grpc.py depends on grpcio>=1.80.0.
```

**Service concerné** : `gateway` (et potentiellement tous les services)

**Cause**
Les stubs gRPC dans `shared/grpc/` (`analyzer_pb2_grpc.py`, `ai_pb2_grpc.py`, `auth_pb2_grpc.py`) avaient été générés avec `grpcio-tools==1.80.0`. Chaque fichier `*_pb2_grpc.py` généré embarque une vérification de version à l'import :
```python
GRPC_GENERATED_VERSION = '1.80.0'
# → RuntimeError si grpcio installé < 1.80.0
```
Or tous les `requirements.txt` des services pinaient `grpcio==1.73.0`, créant une incompatibilité détectée dès l'import des stubs, avant même le démarrage de Django.

**Solution**
Mettre à jour `grpcio` à `1.80.0` dans tous les fichiers `requirements.txt` des services, et aligner `requirements-dev.txt` sur `grpcio-tools==1.80.0` :

```
services/gateway/requirements.txt       : grpcio==1.73.0 → 1.80.0
services/auth-service/requirements.txt  : grpcio==1.73.0 → 1.80.0
services/analyzer-service/requirements.txt : grpcio==1.73.0 → 1.80.0, grpcio-tools==1.73.0 → 1.80.0
services/ai-service/requirements.txt    : grpcio==1.73.0 → 1.80.0, grpcio-tools==1.73.0 → 1.80.0
requirements-dev.txt                    : grpcio-tools==1.73.0 → 1.80.0
```

**Règle à retenir**
Toujours régénérer les stubs ET mettre à jour `grpcio` dans les `requirements.txt` en même temps. La version de `grpcio-tools` utilisée pour générer doit correspondre à la version de `grpcio` installée en runtime.

---

## [2026-05-11] AttributeError — HistoryResponse absent des stubs ai_pb2

**Erreur**
```
AttributeError: module 'stubs.ai.ai_pb2' has no attribute 'HistoryResponse'
```

**Service concerné** : `gateway`

**Cause**
Les stubs `shared/grpc/ai/ai_pb2.py` et `ai_pb2_grpc.py` avaient été générés depuis une ancienne version du proto `ai/ai.proto`, avant l'ajout du message `HistoryResponse` (et `HistoryRequest`, `HistoryItem`). Le proto était à jour mais les stubs ne l'étaient pas.

De plus, `grpcio-tools` génère un import absolu `from ai import ai_pb2` au lieu d'un import relatif, ce qui cause une `ImportError` selon le contexte Python.

**Solution**
1. Régénérer les stubs depuis le proto actuel :
```bash
cd proto
python3 -m grpc_tools.protoc -I. --python_out=../shared/grpc --grpc_python_out=../shared/grpc ai/ai.proto
```
2. Corriger l'import dans `shared/grpc/ai/ai_pb2_grpc.py` :
```python
# Avant (généré automatiquement — incorrect)
from ai import ai_pb2 as ai_dot_ai__pb2
# Après (correct)
from . import ai_pb2 as ai_dot_ai__pb2
```

**Règle à retenir**
Après toute modification d'un `.proto`, toujours régénérer les stubs ET corriger l'import relatif dans `*_pb2_grpc.py`. Ne jamais commiter des stubs obsolètes par rapport au proto.

---

## [2026-05-11] ModuleNotFoundError: No module named 'config' — auth-service grpc_server

**Erreur**
```
ModuleNotFoundError: No module named 'config'
  File "/app/app/grpc_server.py", line 11, in <module>
    django.setup()
```

**Service concerné** : `auth-service`

**Cause**
Le Dockerfile lançait `python app/grpc_server.py`. Quand Python exécute un fichier script directement, il ajoute le **répertoire du script** (`/app/app/`) à `sys.path[0]`, pas le répertoire de travail (`/app`). Le module `config` se trouve à `/app/config/` mais n'est donc pas trouvé.

À noter aussi : les `Meta.indexes` du model `ApiKey` n'avaient pas de noms explicites, alors que la migration les avait générés avec des noms (`apikey_user_idx`, `apikey_hash_idx`). Django détectait une dérive et émettait un warning à chaque démarrage.

**Solution**
1. Changer la commande dans le Dockerfile :
```dockerfile
# Avant
CMD ["sh", "-c", "python manage.py migrate --noinput && python app/grpc_server.py"]
# Après
CMD ["sh", "-c", "python manage.py migrate --noinput && python -m app.grpc_server"]
```
Avec `-m`, Python ajoute le répertoire courant (`/app`) à `sys.path`, rendant `config` importable.

2. Ajouter les noms d'index dans `core/models.py` pour aligner avec la migration :
```python
indexes = [
    models.Index(fields=["user_id"], name="apikey_user_idx"),
    models.Index(fields=["key_hash"], name="apikey_hash_idx"),
]
```

**Règle à retenir**
Ne jamais lancer un module Django avec `python path/to/script.py` — toujours utiliser `python -m package.module` depuis le WORKDIR pour que `sys.path` inclue le répertoire racine du projet.

---

## [2026-05-11] AttributeError: module 'hashlib' has no attribute 'compare_digest'

**Erreur**
```
AttributeError: module 'hashlib' has no attribute 'compare_digest'
  in _verify_password() — app/grpc_server.py
```

**Service concerné** : `auth-service`

**Cause**
`compare_digest` est dans le module `hmac`, pas `hashlib`. Mauvais module utilisé.

**Solution**
```python
# Avant
import hashlib
return hashlib.compare_digest(...)

# Après
import hmac
return hmac.compare_digest(...)
```

**Règle à retenir**
`hmac.compare_digest(a, b)` pour la comparaison en temps constant. `hashlib` sert uniquement à hacher (sha256, etc.).

---

## [2026-05-11] GraphQL Playground — "The string did not match the expected pattern"

**Erreur**
```json
{
  "errors": [
    {
      "message": "The string did not match the expected pattern.",
      "stack": "json@[native code]\n@https://unpkg.com/graphiql@3.0.9/graphiql.min.js:71272:61"
    }
  ]
}
```

**Service concerné** : `gateway` (visible dans le playground GraphiQL)

**Cause**
Erreur trompeuse — elle vient du navigateur qui tente de parser la réponse HTTP en JSON. En réalité le serveur retournait un **502 Bad Gateway** (page HTML), pas du JSON.

Nginx retournait 502 car il essayait de contacter le gateway à une ancienne adresse IP (`172.19.0.9`) qui n'existait plus. Après un redémarrage du container gateway, Docker lui avait attribué une nouvelle IP (`172.19.0.12`), mais Nginx gardait l'IP résolue au démarrage en cache (comportement du bloc `upstream` statique).

**Solution**
Remplacer le bloc `upstream` statique par une résolution DNS dynamique via le resolver Docker interne dans `infra/nginx/default.conf` :

```nginx
# Avant — résolution DNS unique au démarrage de Nginx
upstream gateway_upstream {
    server gateway:8000;
    keepalive 32;
}
location / {
    proxy_pass http://gateway_upstream;
}

# Après — re-résolution à chaque requête via le DNS Docker
resolver 127.0.0.11 valid=10s ipv6=off;
set $gateway_upstream http://gateway:8000;
location / {
    proxy_pass $gateway_upstream;
}
```

Puis redémarrer Nginx pour appliquer :
```bash
docker compose restart nginx
```

**Règle à retenir**
Dans Docker Compose, ne jamais utiliser un bloc `upstream` Nginx avec un hostname de service — l'IP est résolue une seule fois et mise en cache. Toujours utiliser `resolver 127.0.0.11` avec une variable pour forcer la re-résolution dynamique, ce qui garantit la résilience aux redémarrages de containers.

---

## [2026-05-11] analyzeIncident échoue sans cluster Kubernetes

> ⚠️ **ARCHITECTURE SUPERSEDED — Phase 16** : `STUB_MODE` et `CollectPod`/`ScanNamespace` ont été **supprimés** de l'analyzer-service. La collecte K8s est désormais assurée par l'**agent PodIQ** déployé dans le cluster client. L'agent envoie les données via `agentReportIncident` (logs, events, describe, namespace_pods). Pour tester sans vrai agent, utiliser `scripts/agent_simulate.sh`. Cette erreur ne peut plus se produire.

**Erreur (historique)**
```
grpc._channel._InactiveRpcError: StatusCode.INTERNAL
Details: [Errno 111] Connection refused / No such file or directory: ~/.kube/config
```

**Service concerné** : `analyzer-service` → propagé au `gateway`

**Cause (historique)**
La mutation `analyzeIncident` appelait `CollectPod` dans l'analyzer-service, qui tentait de charger la configuration Kubernetes (`load_incluster_config()` puis `load_kube_config()`). Sans cluster Kubernetes ni fichier `~/.kube/config`, les deux tentatives échouaient et le service retournait une erreur gRPC INTERNAL.

**Solution actuelle (Phase 16+)**
L'agent PodIQ collecte les données dans le cluster et les envoie via `agentReportIncident`. Pour simuler sans vrai agent :
```bash
./scripts/agent_simulate.sh wsk_xxx <pod_name> <namespace> <workspace-jwt>
```

**Règle à retenir**
Depuis Phase 16, `analyzer-service` ne se connecte plus à Kubernetes. Toute la collecte K8s est dans l'agent.

---

## [2026-05-11] GraphQL — `Unexpected token '<'` / JSON invalide après `analyzeIncident`

**Erreur (navigateur / playground)**

```
Unexpected token '<', "<html>..." is not valid JSON
```

**Service concerné** : `gateway` (réponse HTTP non-JSON)

**Cause fréquente**
Gunicorn tue le worker qui traite la requête après **30 s** par défaut, alors que `analyzeIncident` attend souvent **plus longtemps** la réponse de l’ai-service (Ollama). Le worker plante, Nginx renvoie une page d’erreur **HTML** ; le client GraphQL tente de parser ce HTML comme du JSON.

**Solution actuelle (Phase 16+ — Uvicorn ASGI)**

> ℹ️ Depuis Phase 16, le gateway utilise **Uvicorn ASGI** (plus Gunicorn). Ce problème de timeout Gunicorn ne se produit plus. Le timeout pertinent est maintenant `AI_TIMEOUT_SECONDS` (côté ai-service → Ollama), à mettre à **300** en dev CPU.

**Solution historique (pré-Phase 16)**
Le `Dockerfile` du gateway lançait Gunicorn avec **`--timeout 180`**. Reconstruire l’image après mise à jour.

Aligner si besoin `AI_TIMEOUT_SECONDS` dans `.env` (ex. **300** en dev CPU) et vérifier les logs Ollama / ai-service pour d’autres causes de lenteur.

**Règle à retenir**
Depuis Phase 16 : Uvicorn ASGI — il n’y a plus de timeout worker. Augmenter `AI_TIMEOUT_SECONDS=300` si Ollama met trop longtemps sur CPU.

---

## [2026-05-11] Ollama — HTTP 500 à ~30 s sur `/api/chat`, logs `ollama_timeout`

**Erreur**
- Logs `ai-service` : `ollama_timeout`, `analyze_incident_failed error='timed out'`
- Logs `ollama` : `POST "/api/chat" ... | 500 | 30.00xs`

**Service concerné** : `ai-service` → `ollama`

**Cause possible (plusieurs)**
1. **`AI_TIMEOUT_SECONDS`** trop bas pour la machine (CPU seul, modèle lourd) — augmenter dans `.env` (ex. **120**) et `docker compose up -d --force-recreate ai-service`.
2. Modèle **« thinking »** ou très bavard sur un **prompt volumineux** (logs + historique + namespace) : Ollama peut échouer ou dépasser des limites internes avant la fin de la génération utile.
3. Mémoire Docker insuffisante pour le modèle (moins fréquent si `ollama list` montre le modèle chargé et des `/api/chat` **200** sur de petits tests).

**Solution**
- Utiliser **`OLLAMA_MODEL=mistral`** (après `docker compose exec ollama ollama pull mistral`), cohérent avec le tag listé par `ollama list` (`mistral:latest`).
- Augmenter **`AI_TIMEOUT_SECONDS`** pour le dev sur CPU.

**Règle à retenir**
Pour valider le pipeline incident, privilégier **mistral** ; documenter tout autre modèle avec ses contraintes (taille de contexte, « thinking », temps de réponse).

---

## [2026-05-11] analyzeIncident — `errorType: "Unknown"`, rootCause « AI response could not be parsed »

**Erreur** — réponse GraphQL valide mais diagnostic de repli.

**Service concerné** : `ai-service` (`_parse_incident` dans `app/grpc_server.py`)

**Cause**
Le modèle renvoie du JSON entouré de texte ou de Markdown (malgré `format: "json"`), ce qui faisait échouer `json.loads` sur la chaîne brute.

**Solution**
Le code extrait le sous-texte du **premier `{` au dernier `}`** avant parse et validation Pydantic. Si le message persiste, consulter les logs `incident_parse_failed` et la réponse brute Ollama.

**Règle à retenir**
Ne pas supposer une réponse JSON « pure » de tous les modèles Ollama ; prévoir une extraction tolérante ou un log explicite.

---

## [2026-05-27] pre-commit — `Django==5.2.1` incompatible avec Python 3.9 dans les hooks locaux

**Erreur**
```
ERROR: Could not find a version that satisfies the requirement Django==5.2.1
ERROR: No matching distribution found for Django==5.2.1
```

**Service concerné** : hook `mypy-services` (local) dans `.pre-commit-config.yaml`

**Cause**
Le hook `mypy-services` utilise `language: python` sans `language_version` explicite. Pre-commit prend alors le premier `python3` résolvable dans le PATH, qui était Python 3.9 (Python système macOS). Django 5.x requiert **Python ≥ 3.10** — l'installation échoue dans l'environnement isolé que pre-commit crée pour le hook.

Symptômes typiques menant à ce problème :
1. Présence d'un `venv/` cassé créé avec une version Python désinstallée (ex. Python 3.14) — pre-commit l'active et hérite du mauvais interpréteur.
2. PATH ne contenant pas `/opt/homebrew/bin` ou `/opt/homebrew/opt/python@3.12/libexec/bin` → `python3` pointe vers le Python système Apple (3.9.6).

**Solution**
1. Installer Python 3.12 via Homebrew (une seule fois par machine) :
```bash
brew install python@3.12
```

2. Ajouter `language_version: python3.12` **explicitement** aux deux hooks locaux dans `.pre-commit-config.yaml` :
```yaml
- id: hadolint-dockerfiles
  language: python
  language_version: python3.12          # ← ajouté
  ...

- id: mypy-services
  language: python
  language_version: python3.12          # ← ajouté
  ...
```
Pre-commit cherche `python3.12` dans le PATH système (pas dans le venv courant). `/opt/homebrew/bin/python3.12` est trouvé directement.

3. Purger le cache pre-commit (envs créés avec Python 3.9) et réinstaller :
```bash
pre-commit clean
pre-commit install
```

**Règle à retenir**
Dès qu'un hook `language: python` installe des dépendances qui requièrent Python ≥ 3.10 (Django 5.x, psycopg 3.x…), toujours préciser `language_version: python3.12` (ou supérieur). Ne pas compter sur `python3` du PATH — sa résolution dépend de l'environnement shell et peut pointer vers le Python système macOS (3.9).

---

## [2026-05-27] mypy (pre-commit) — `Cannot find implementation or library stub for module named "argon2"`

**Erreur**
```
app/grpc_server.py:11: error: Cannot find implementation or library stub for module named "argon2"  [import-not-found]
app/grpc_server.py:12: error: Cannot find implementation or library stub for module named "argon2.exceptions"  [import-not-found]
Found 2 errors in 1 file (checked 13 source files)
```

**Service concerné** : hook `mypy-services` (pre-commit) → `auth-service/app/grpc_server.py`

**Cause**
Le hook mypy tourne dans un environnement isolé créé par pre-commit. Cet environnement n'installe que les paquets listés dans `additional_dependencies`. `argon2-cffi` (qui fournit le module `argon2`) avait été ajouté au `requirements.txt` de l'auth-service mais pas à la liste `additional_dependencies` du hook dans `.pre-commit-config.yaml`.

**Solution**
Ajouter `argon2-cffi==23.1.0` aux `additional_dependencies` du hook `mypy-services` dans `.pre-commit-config.yaml` :

```yaml
- id: mypy-services
  additional_dependencies:
    ...
    - PyYAML==6.0.2
    - argon2-cffi==23.1.0    # ← ajouté
```

**Règle à retenir**
Chaque nouvelle dépendance ajoutée à un `requirements.txt` de service doit être **également ajoutée** aux `additional_dependencies` du hook `mypy-services` dans `.pre-commit-config.yaml`. Le hook mypy est isolé — il ne lit pas les `requirements.txt` des services. Sans cette synchronisation, mypy échoue avec `import-not-found` dès que le module est importé dans un fichier analysé.

---

## [2026-05-12] pre-commit — « no files to check » ou secrets / baseline

**Symptôme**
- `pre-commit run` affiche « Skipped » / « no files to check » pour Black, Ruff, etc.

**Cause**
Sans **`--all-files`**, pre-commit ne traite **que les fichiers déjà stagés** (`git add`). Index vide ⇒ aucun fichier à passer aux hooks.

**Solution**
- Avant un commit : **`git add`** les fichiers concernés puis **`pre-commit run`** (ou laisser le hook au **`git commit`** le faire).
- Pour tout le dépôt : **`pre-commit run --all-files`**.

**Symptôme**
- Hook **detect-secrets** : message indiquant que **`.secrets.baseline`** a été mis à jour (souvent après déplacement de lignes dans un fichier déjà référencé).

**Solution**
- Vérifier les entrées, **`git add .secrets.baseline`**, recommitter. En cas de **nouveau** secret réel, le retirer du code ou l’auditer selon la procédure Yelp detect-secrets ; ne pas valider à l’aveugle une baseline élargie.

**Symptôme**
- Premier **`pre-commit run --all-files`** long : installation des environnements isolés (dont dépendances agrégées pour **mypy**).

**Cause**
Normal ; les environnements sont mis en cache sous `~/.cache/pre-commit`.

---

## [2026-05-17] Loki — HTTP 500 `at least 1 live replicas required`

**Erreur**
```
level=warn caller=client.go:419 component=client host=loki:3100
msg="error sending batch, will retry" status=500
error="at least 1 live replicas required, could only find 0
       unhealthy instances: 127.0.0.1:9096"
```

**Service concerné** : `promtail` → `loki` (logs vides dans Grafana)

**Cause**
Loki 3.x démarre en mode single-binary mais tente d'utiliser un ring distribué pour l'ingester. La section `common.ring` ne propage pas automatiquement la configuration à tous les sous-composants internes. L'ingester n'a pas de ring explicite, se marque `unhealthy`, et Loki refuse tout batch entrant avec HTTP 500.

**Solution**
Ajouter une section `ingester` explicite dans `infra/loki/loki-config.yml` :

```yaml
ingester:
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
    final_sleep: 0s
  chunk_idle_period: 1m
  chunk_retain_period: 30s
  max_chunk_age: 2h
```

Puis redémarrer Loki :
```bash
docker compose restart loki
```

**Règle à retenir**
En Loki 3.x, `common.ring` ne suffit pas pour le mode single-binary — chaque composant (ingester, distributor) doit avoir son ring configuré explicitement. Le warning `zone not set` résiduel est bénin et n'empêche pas l'ingestion.

---

## [2026-05-17] kubeconfig — `File does not exist: /Users/apple/.minikube/ca.crt`

> ⚠️ **ARCHITECTURE SUPERSEDED — Phase 16** : L'analyzer-service ne se connecte plus à Kubernetes. La collecte K8s est assurée par l'agent PodIQ dans le cluster client. Les erreurs kubeconfig de ce type ne peuvent plus se produire dans l'analyzer-service.

**Erreur**
```json
{
  "error": "File does not exist: /Users/apple/.minikube/ca.crt"
}
```

**Service concerné** : `analyzer-service` (connexion à l'API K8s depuis le conteneur)

**Cause**
`minikube kubectl -- config view --raw` génère un kubeconfig avec des **chemins absolus** vers les certificats sur la machine hôte (`certificate-authority: /Users/apple/.minikube/ca.crt`, etc.). Ces chemins n'existent pas dans le conteneur Docker.

**Solution**
Utiliser le flag `--flatten` qui embarque les contenus des fichiers `.crt`/`.key` en base64 directement dans le YAML, supprimant toute référence au système de fichiers hôte :

```bash
# Dans make cluster-config (Makefile)
minikube kubectl -- config view --flatten --minify > $(KUBECONFIG_PATH)
```

`--minify` limite au contexte actif uniquement.

**Règle à retenir**
Toujours utiliser `--flatten` lors de l'export d'un kubeconfig destiné à être monté dans un conteneur. Sans `--flatten`, les chemins de certificats sont copiés tels quels et invalides dans tout environnement autre que la machine d'origine.

---

## [2026-05-17] kubeconfig — `Connection refused` sur `172.17.0.1:PORT` (minikube Docker driver)

> ⚠️ **ARCHITECTURE SUPERSEDED — Phase 16** : Même raison que l'entrée précédente. L'analyzer-service ne se connecte plus à Kubernetes.

**Erreur**
```
HTTPSConnectionPool(host='172.17.0.1', port=59782): Max retries exceeded
Caused by NewConnectionError: Failed to establish a new connection: [Errno 111] Connection refused
```

**Service concerné** : `analyzer-service` → API server minikube

**Cause**
Lors de la génération du kubeconfig, l'IP `172.17.0.1` (gateway du bridge Docker, obtenue via `docker network inspect bridge`) était substituée à `127.0.0.1`. Mais sur **macOS avec Docker Desktop**, les conteneurs tournent dans une VM Linux : `172.17.0.1` est la gateway interne de cette VM, pas le Mac hôte. Le port minikube (`59782`) est mappé sur `127.0.0.1` du Mac, inaccessible depuis la VM.

**Solution**
Faire parler `analyzer-service` **directement au conteneur minikube** via le réseau Docker `minikube`, en contournant le port-mapping hôte :

1. Récupérer l'IP du conteneur minikube sur son réseau Docker :
```bash
MINIKUBE_IP=$(docker inspect minikube \
  --format='{{.NetworkSettings.Networks.minikube.IPAddress}}')
# ex: 192.168.49.2
```

2. Réécrire l'adresse API server dans le kubeconfig (port 8443 = port interne K8s) :
```bash
sed -i '' "s|https://127\.0\.0\.1:[0-9]*|https://$MINIKUBE_IP:8443|g" kubeconfig
```

3. Connecter `analyzer-service` au réseau Docker `minikube` dans `docker-compose.cluster.yml` :
```yaml
services:
  analyzer-service:
    networks:
      - backend
      - minikube

networks:
  minikube:
    external: true
    name: minikube
```

Tout cela est géré automatiquement par `make cluster-config` + `make up-cluster`.

**Règle à retenir**
Sur macOS Docker Desktop, ne jamais utiliser la gateway du bridge Docker (`172.17.0.x`) pour joindre des services hôte depuis un conteneur — utiliser `host.docker.internal` ou, mieux, mettre les conteneurs sur le même réseau Docker et communiquer directement (IP container + port interne).

---

## [2026-05-17] `analyses.recurrence_count` toujours à 0

**Symptôme**
Le champ `recurrenceCount` retourné par `analysisJob` est toujours `0` même après plusieurs analyses du même pod.

**Service concerné** : `ai-service` (`app/grpc_server.py`)

**Cause**
Dans `AnalyzeIncident`, l'ordre des opérations était incorrect :
```python
# Ordre incorrect
_save_analysis(request, result)    # INSERT analyses avec recurrence_count=0 (valeur défaut)
_upsert_pattern(request, result)   # UPSERT incident_patterns (occurrence_count++)
recurrence_count = _get_recurrence_count(...)  # lu trop tard, jamais passé à _save_analysis
```
`_save_analysis()` ne recevait pas `recurrence_count` et ne le passait pas au modèle — `analyses.recurrence_count` restait à sa valeur par défaut (0).

**Solution**
Inverser l'ordre et passer `recurrence_count` à `_save_analysis()` :
```python
# Ordre correct
_upsert_pattern(request, result)              # UPSERT en premier
recurrence_count = _get_recurrence_count(...) # lire après l'upsert
_save_analysis(request, result, recurrence_count)  # persister la bonne valeur
```

Et mettre à jour la signature de `_save_analysis()` :
```python
def _save_analysis(request, result, recurrence_count: int = 0) -> Analysis:
    ...
    Analysis.objects.create(..., recurrence_count=recurrence_count, ...)
```

**Règle à retenir**
`analyses.recurrence_count` est une **dénormalisation** de `incident_patterns.occurrence_count` au moment de l'analyse. Pour qu'elle soit correcte, le pattern doit être upsert **avant** que l'analyse soit sauvegardée.

---

## [2026-05-19] agent_simulate.sh — `status: unknown` lors du poll `analysisJob`

**Symptôme**
```bash
[1] status: unknown
[2] status: unknown
...
Timeout — job still running after 150s
```

**Service concerné** : `scripts/agent_simulate.sh` (poll GraphQL)

**Cause**
La query de poll dans le script utilisait `query($id: ID!)` mais le schéma Strawberry déclare `job_id: str` → type GraphQL `String!` (pas `ID!`). GraphQL rejetait silencieusement la variable avec une erreur de type :
```
Variable '$id' of type 'ID!' used in position expecting type 'String!'.
```
Le gateway retournait `{"data": {"analysisJob": null}}`. `jq` décodait `null` comme `"unknown"`.

**Solution**
Changer `ID!` en `String!` dans la query de poll :
```bash
# Avant (incorrect)
'{query: "query($id:ID!){analysisJob(jobId:$id){status ...}}", variables: {id: $id}}'

# Après (correct)
'{query: "query($id:String!){analysisJob(jobId:$id){status ...}}", variables: {id: $id}}'
```

**Vérification**
```bash
# Tester manuellement avec String! — doit retourner status réel
JOB_ID="<uuid>"
curl -s -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <workspace-jwt>" \
  -d "{\"query\":\"query(\$id:String!){analysisJob(jobId:\$id){status}}\",\"variables\":{\"id\":\"$JOB_ID\"}}"
```

**Règle à retenir**
Strawberry GraphQL mappe `str` Python → `String!` GraphQL, **pas** `ID!`. Ne jamais utiliser `ID!` dans les queries de poll de jobs PodIQ — tous les IDs internes sont des `String!` dans le schéma Strawberry généré.

---

## [2026-05-19] agent_simulate.sh — `status: unknown` avec UUID comme 4e argument

**Symptôme**
```
[1] status: unknown
```

**Service concerné** : `scripts/agent_simulate.sh` — usage incorrect

**Cause**
L'utilisateur passe le `workspace_id` (UUID format `5665e7b7-...`) comme 4e argument au lieu du **workspace-JWT** (`eyJhbGci...`). `require_auth()` ne peut pas décoder un UUID comme JWT → la query `analysisJob` échoue avec une erreur d'authentification → retourne `null` → `jq` déduit `"unknown"`.

**Solution**
Le 4e argument doit être un **workspace-JWT** commençant par `eyJ`, obtenu via :
```graphql
mutation {
  selectWorkspace(workspaceId: "uuid-du-workspace") {
    token    # ← c'est ce token à passer comme 4e argument
  }
}
```

Puis :
```bash
./scripts/agent_simulate.sh wsk_xxx pod-name default eyJhbGci...
#                                                    ^^^^^^^^^ JWT, pas UUID
```

**Règle à retenir**
Le 4e argument de `agent_simulate.sh` est un **JWT workspace-scoped** (commence par `eyJ`), pas un workspace UUID. Si vous n'avez que le UUID, appeler d'abord `mutation { selectWorkspace(...) { token } }`.

---

## [2026-05-25] Docker Desktop macOS — `operation not permitted` sur bind mounts vers `~/Documents`

**Erreur**
```
Error response from daemon: error while creating mount source path
'/host_mnt/Users/apple/Documents/PodIQ/infra/loki/loki-config.yml':
mkdir /host_mnt/Users/apple/Documents: operation not permitted
```

Et avec `configs: file:` (Compose v5) :
```
Error response from daemon: invalid mount config for type "bind":
stat /host_mnt/Users/apple/Documents/PodIQ/infra/loki/loki-config.yml:
operation not permitted
```

**Services concernés** : `loki`, `promtail`, `grafana`, `nginx` (tout service avec un bind mount vers `./infra/`)

**Cause**
Docker Desktop sur macOS gère le partage de fichiers via une VM Linux interne. Par défaut, seuls certains chemins hôte sont accessibles (typiquement `/Users/<user>`, `/tmp`, `/var/folders`). Si Docker Desktop n'a pas explicitement `/Users/apple/Documents` dans ses répertoires autorisés, toute tentative de bind mount depuis ce chemin échoue avec `operation not permitted`.

La directive `configs: file:` de Docker Compose est trompeuse : elle crée **également** un bind mount en coulisses et souffre du même blocage — l'erreur devient `invalid mount config for type "bind"` au lieu de `error while creating mount source path`, mais la cause est identique.

**Ce qui ne fonctionne pas**
```yaml
# Tentative 1 — bind mount classique (échoue)
volumes:
  - ./infra/loki/loki-config.yml:/etc/loki/config.yml:ro

# Tentative 2 — configs: file: (échoue aussi, bind mount interne)
configs:
  loki_config:
    file: ./infra/loki/loki-config.yml
services:
  loki:
    configs:
      - source: loki_config
        target: /etc/loki/config.yml
```

**Solution retenue — Dockerfiles dédiés par service d'infra**

Créer un `Dockerfile` minimal dans chaque répertoire `infra/<service>/` qui `COPY` la config au moment du build. Docker lit les fichiers via le **build context** (mécanisme build, pas bind mount runtime) — pas de restriction macOS.

```
infra/
  loki/
    Dockerfile          ← FROM grafana/loki:3.1.1 + COPY loki-config.yml
    loki-config.yml
  promtail/
    Dockerfile          ← FROM grafana/promtail:3.1.1 + COPY promtail-config.yml
    promtail-config.yml
  nginx/
    Dockerfile          ← FROM nginx:1.27-alpine + COPY default.conf
    default.conf
  grafana/
    Dockerfile          ← FROM grafana/grafana:11.3.1 + COPY provisioning/...
    provisioning/
```

Contenu type (ex. `infra/loki/Dockerfile`) :
```dockerfile
FROM grafana/loki:3.1.1
COPY loki-config.yml /etc/loki/config.yml
```

Dans `docker-compose.yml`, remplacer `image:` par `build:` pour ces services :
```yaml
# Avant
loki:
  image: grafana/loki:3.1.1
  volumes:
    - ./infra/loki/loki-config.yml:/etc/loki/config.yml:ro  # ← échoue

# Après
loki:
  build:
    context: ./infra/loki
    dockerfile: Dockerfile
  # plus de volumes pour la config — COPY l'a embarquée dans l'image
```

**Mettre à jour une config** : modifier le fichier source dans `infra/<service>/` puis :
```bash
docker compose up -d --build loki   # rebuild rapide (couche COPY en cache si pas modifiée)
```

**Alternative si Docker Desktop est configurable**
Ouvrir Docker Desktop → ⚙️ Settings → Resources → File Sharing → ajouter `/Users/apple/Documents` → Apply & Restart. Le projet repasse alors aux bind mounts classiques sans modification de code.

**Règle à retenir**
Sur macOS Docker Desktop avec un projet dans `~/Documents`, ne jamais utiliser de bind mounts vers des fichiers de config statiques. Embarquer ces fichiers dans des images via `COPY` (Dockerfile dédié) : pas de restriction file sharing, rebuild rapide grâce au cache Docker, les sources restent dans le repo à leur emplacement naturel.

---

## [2026-05-25] SOC2 — Suppression du mount docker.sock (Promtail → Loki Docker Log Driver)

**Contexte**
Promtail utilisait `docker_sd_configs` avec `/var/run/docker.sock:/var/run/docker.sock:ro` pour collecter les logs. Via `docker inspect`, ce socket permettait de lire les variables d'environnement de tous les conteneurs (JWT_SECRET, POSTGRES_PASSWORD, etc.) — risque R-11 de la politique SOC2.

**Solution**
Remplacer Promtail par le **Loki Docker Log Driver** (Option A) :

1. Installer le plugin une fois par machine dev :
```bash
docker plugin install grafana/loki-docker-driver:latest --alias loki --grant-all-permissions
```

2. Exposer Loki sur `127.0.0.1:3100` (requis par le driver qui tourne hors réseau Docker) :
```yaml
loki:
  ports:
    - "127.0.0.1:3100:3100"
```

3. Ajouter un YAML anchor commun et un bloc `logging:` par service :
```yaml
x-loki-options: &loki-options
  loki-url: "http://host.docker.internal:3100/loki/api/v1/push"
  loki-retries: "5"
  loki-batch-size: "400"
  loki-timeout: "10s"

services:
  gateway:
    logging:
      driver: loki
      options:
        <<: *loki-options
        loki-external-labels: "namespace=podiq,service=gateway"
```

4. Supprimer le service `promtail` du `docker-compose.yml`.

5. **Ne pas appliquer le driver à `loki` et `grafana`** (risque de boucle si Loki redémarre).

**Vérification post-déploiement**
```bash
# Aucun docker.sock monté
docker ps -q | xargs docker inspect --format '{{.Name}} → {{range .Mounts}}{{if eq .Source "/var/run/docker.sock"}}SOCKET{{end}}{{end}}'
# → toutes les lignes doivent être vides après le nom

# Log driver Loki actif
docker inspect podiq-gateway --format '{{.HostConfig.LogConfig.Type}}'
# → loki
```

**Règle à retenir**
Ne jamais monter `/var/run/docker.sock` dans un conteneur de collecte de logs en production. Utiliser le log driver Loki (Docker Compose) ou un DaemonSet Promtail sur fichiers (Kubernetes). Voir `docs/observability-k8s.md` pour la migration K8s.

---

## [2026-05-25] SOC2 — Rétention Loki corrigée (168h → 2160h)

**Contexte**
`infra/loki/loki-config.yml` avait `retention_period: 168h` (7 jours). La politique SOC2 §7.3 exige **90 jours minimum en production**.

**Solution**
```yaml
# infra/loki/loki-config.yml
limits_config:
  retention_period: 2160h    # 90 jours — conforme SOC2 §7.3
```

Puis rebuild de l'image Loki (la config est baked via `infra/loki/Dockerfile`) :
```bash
docker compose up -d --build loki
```

**Règle à retenir**
La config Loki est embarquée dans l'image Docker (pas de bind mount). Tout changement de config = modification du fichier source + `docker compose up -d --build loki`. Ne pas oublier de vérifier la retention après rebuild :
```bash
docker exec podiq-loki grep retention_period /etc/loki/config.yml
```

---

## [2026-05-25] SOC2 §8.3 — Hachage passwords SHA-256 → Argon2id

**Problème (sécurité)**
Le hachage des mots de passe utilisait SHA-256+pepper (`hashlib.sha256(f"{pepper}{password}".encode()).hexdigest()`). SHA-256 est un algorithme de hash général, non conçu pour les mots de passe :
- Pas de sel unique par appel → vulnérable aux attaques rainbow table
- Trop rapide (milliards d'itérations/seconde sur GPU) → brute-force réaliste
- Non conforme OWASP, NIST SP 800-63B, SOC 2 §8.3

**Solution**
Migration vers **Argon2id** avec paramètres OWASP (time=2, mem=64 MB, parallelism=2) via `argon2-cffi==23.1.0` :

```python
# services/auth-service/app/grpc_server.py
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

def _hash_password(password: str) -> str:
    return _ph.hash(password)  # sel aléatoire unique à chaque appel

def _needs_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith("$argon2")  # True = legacy SHA-256

def _verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$argon2"):
        try:
            return _ph.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    # Legacy path — SHA-256+pepper
    pepper = os.environ.get("DJANGO_SECRET_KEY", "")
    legacy = hashlib.sha256(f"{pepper}{password}".encode()).hexdigest()
    return hmac.compare_digest(legacy, stored_hash)
```

**Migration transparente** : dans `Login`, après vérification réussie :
```python
if _needs_rehash(user.password_hash):
    user.password_hash = _hash_password(request.password)
    user.save(update_fields=["password_hash"])
    logger.info("password_rehashed_argon2id", user_id=str(user.id))
```

**Tests ajoutés**
- `test_hash_password_is_argon2id_format` — format `$argon2id$`
- `test_hash_password_uses_unique_salts` — 2 appels = 2 hashes différents
- `test_needs_rehash_legacy_sha256_returns_true`
- `test_needs_rehash_argon2id_returns_false`
- `test_verify_legacy_sha256_correct_password` — compatibilité ascendante
- `test_login_upgrades_legacy_sha256_to_argon2id` — migration effective
- `test_login_does_not_rehash_already_argon2id`

Résultat : **47/47 tests verts**.

**Règle à retenir**
Ne jamais utiliser SHA-1, SHA-256, MD5 pour les mots de passe. Utiliser exclusivement Argon2id (ou bcrypt/scrypt en second recours). Ajouter `argon2-cffi` aux `requirements.txt` du service, rebuilder l'image Docker après ajout.

---
