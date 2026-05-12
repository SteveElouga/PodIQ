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

**Erreur**
```
grpc._channel._InactiveRpcError: StatusCode.INTERNAL
Details: [Errno 111] Connection refused / No such file or directory: ~/.kube/config
```

**Service concerné** : `analyzer-service` → propagé au `gateway`

**Cause**
La mutation `analyzeIncident` appelle `CollectPod` dans l'analyzer-service, qui tente de charger la configuration Kubernetes (`load_incluster_config()` puis `load_kube_config()`). Sans cluster Kubernetes ni fichier `~/.kube/config`, les deux tentatives échouent et le service retourne une erreur gRPC INTERNAL.

**Solution**
Ajouter `STUB_MODE=true` dans `.env`. En mode stub, `collect_pod()` et `scan_namespace()` retournent des données fictives réalistes (pod en CrashLoopBackOff, namespace avec 3 pods) sans appeler Kubernetes. Le reste du pipeline (AI Service → Ollama) s'exécute normalement.

```env
# .env
STUB_MODE=true
```

```bash
docker compose up -d --build analyzer-service
```

Vérifier l'activation :
```bash
docker compose logs analyzer-service | grep "stub"
# → collect_pod_stub ou scan_namespace_stub
```

**Règle à retenir**
`STUB_MODE=true` est réservé au développement local sans cluster. Toujours mettre `STUB_MODE=false` (ou ne pas le définir) en environnement de staging/production avec un vrai cluster.

---

## [2026-05-11] GraphQL — `Unexpected token '<'` / JSON invalide après `analyzeIncident`

**Erreur (navigateur / playground)**

```
Unexpected token '<', "<html>..." is not valid JSON
```

**Service concerné** : `gateway` (réponse HTTP non-JSON)

**Cause fréquente**
Gunicorn tue le worker qui traite la requête après **30 s** par défaut, alors que `analyzeIncident` attend souvent **plus longtemps** la réponse de l’ai-service (Ollama). Le worker plante, Nginx renvoie une page d’erreur **HTML** ; le client GraphQL tente de parser ce HTML comme du JSON.

**Solution**
Le `Dockerfile` du gateway lance Gunicorn avec **`--timeout 180`**. Reconstruire l’image après mise à jour :

```bash
docker compose up -d --build gateway
```

Aligner si besoin `AI_TIMEOUT_SECONDS` dans `.env` (ex. **120**) et vérifier les logs Ollama / ai-service pour d’autres causes de lenteur.

**Règle à retenir**
Le timeout worker Gunicorn doit être **≥** la durée maximale acceptable d’une mutation longue (ici surtout l’inférence IA).

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
