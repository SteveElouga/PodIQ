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
