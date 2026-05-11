# Redis Development Guidelines — PodIQ

## Rôle de Redis dans PodIQ

Redis est utilisé dans PodIQ pour deux responsabilités distinctes :

| Rôle | Description | Consommateur |
|------|-------------|--------------|
| **Queue async** | Broker Dramatiq pour les jobs d'analyse | gateway → workers |
| **Cache** | API Keys, rate limiting, résultats temporaires | gateway, auth-service |

Redis n'est **pas** une base de données principale dans PodIQ. Toute donnée persistante va dans PostgreSQL. Redis ne contient que des données reconstituables ou temporaires.

---

## Convention de nommage des clés

Format obligatoire : `podiq:{service}:{type}:{identifiant}`

| Type de clé | Pattern | Exemple |
|-------------|---------|---------|
| Cache API Key | `podiq:auth:apikey:{key_hash}` | `podiq:auth:apikey:sha256abc...` |
| Rate limiting | `podiq:auth:ratelimit:{user_id}` | `podiq:auth:ratelimit:uuid-123` |
| Cache résultat analyse | `podiq:ai:analysis:{analysis_id}` | `podiq:ai:analysis:uuid-456` |
| Lock distribué | `podiq:lock:{resource}:{id}` | `podiq:lock:pod:my-pod-default` |
| Queue Dramatiq | géré par Dramatiq — ne pas manipuler manuellement | — |

**Règles de nommage :**
- Toujours préfixer par `podiq:` — jamais de clé sans namespace
- Utiliser `:` comme séparateur de segments
- Segments en snake_case
- Jamais de données sensibles dans la clé elle-même (hash uniquement)

---

## TTL par type de clé

Toute clé de cache doit avoir un TTL explicite. Pas d'exception.

| Type | TTL | Justification |
|------|-----|---------------|
| Cache API Key validée | 300s (5 min) | Réduit les hits PostgreSQL sans risque sécurité |
| Rate limiting counter | 60s | Fenêtre glissante standard |
| Cache résultat analyse | 3600s (1h) | Résultat stable, Ollama lent |
| Lock distribué | 30s maximum | Prévient les locks orphelins |

**Règles TTL :**
- Ajouter un jitter de ±10% sur les TTL de cache pour éviter les expirations massives simultanées
- Ne jamais persister une donnée critique uniquement dans Redis
- Les données sans TTL dans Redis doivent être explicitement documentées et justifiées

---

## Structures de données à utiliser

### String — valeurs simples et compteurs

```python
# Cache d'une API Key validée
await redis.setex(f"podiq:auth:apikey:{key_hash}", 300, user_id)

# Récupération
user_id = await redis.get(f"podiq:auth:apikey:{key_hash}")
```

### Hash — objets structurés

```python
# Cache d'un résultat d'analyse
await redis.hset(f"podiq:ai:analysis:{analysis_id}", mapping={
    "error_type": result.error_type,
    "root_cause": result.root_cause,
    "confidence": result.confidence,
})
await redis.expire(f"podiq:ai:analysis:{analysis_id}", 3600)
```

### Sorted Set — rate limiting

```python
# Rate limiting par user_id avec fenêtre glissante
now = time.time()
key = f"podiq:auth:ratelimit:{user_id}"
await redis.zremrangebyscore(key, 0, now - 60)
await redis.zadd(key, {str(now): now})
await redis.expire(key, 60)
count = await redis.zcard(key)
if count > MAX_REQUESTS_PER_MINUTE:
    raise RateLimitError()
```

### String + NX — lock distribué

```python
# Evite deux analyses simultanées sur le même pod
lock_key = f"podiq:lock:pod:{pod_name}-{namespace}"
acquired = await redis.set(lock_key, "1", nx=True, ex=30)
if not acquired:
    raise AnalysisAlreadyRunningError()
try:
    # ... traitement
finally:
    await redis.delete(lock_key)
```

---

## Dramatiq — Queue async

Dramatiq gère automatiquement ses clés Redis. Ne pas manipuler les clés Dramatiq manuellement.

```python
# Configuration dans gateway
import dramatiq
from dramatiq.brokers.redis import RedisBroker

broker = RedisBroker(url=settings.REDIS_URL)
dramatiq.set_broker(broker)

# Déclaration d'un actor
@dramatiq.actor(queue_name="analyses", max_retries=3, min_backoff=1000)
def run_analysis(pod_name: str, namespace: str, user_id: str) -> None:
    ...
```

**Règles Dramatiq :**
- Toujours définir `max_retries` — jamais de retry infini
- Toujours définir `queue_name` explicite — pas de queue par défaut non nommée
- Les messages doivent être sérialisables (pas d'objets Python complexes)
- Passer uniquement des IDs dans les messages, jamais des payloads complets

---

## Caching — Règles générales

### Pattern utilisé : Cache-aside

PodIQ utilise exclusivement le pattern cache-aside (lazy loading) :

```
1. Lire dans Redis
2. Si hit → retourner la valeur
3. Si miss → lire dans PostgreSQL → stocker dans Redis avec TTL → retourner
```

### Règles d'invalidation

| Événement | Clé à invalider |
|-----------|-----------------|
| API Key révoquée | `podiq:auth:apikey:{key_hash}` |
| API Key mise à jour | `podiq:auth:apikey:{key_hash}` |
| Analyse terminée | `podiq:ai:analysis:{analysis_id}` (si mise à jour) |

### Comportement en cas d'indisponibilité Redis

Redis n'est **jamais** un point de défaillance bloquant pour les données critiques :
- Si Redis est down → fallback sur PostgreSQL directement
- Logger l'indisponibilité avec structlog
- Ne jamais faire échouer une requête utilisateur à cause de Redis seul

```python
async def get_api_key_user(key_hash: str) -> str | None:
    try:
        cached = await redis.get(f"podiq:auth:apikey:{key_hash}")
        if cached:
            return cached.decode()
    except RedisError:
        logger.warning("redis_unavailable", fallback="postgresql")
    # Fallback PostgreSQL
    return await db.get_user_for_api_key(key_hash)
```

---

## Performance

### Utiliser le pipelining pour les opérations multiples

```python
# Mauvais — 3 round-trips
await redis.get(key1)
await redis.get(key2)
await redis.get(key3)

# Correct — 1 round-trip
async with redis.pipeline() as pipe:
    pipe.get(key1)
    pipe.get(key2)
    pipe.get(key3)
    results = await pipe.execute()
```

### Connection pooling

```python
# Initialiser une fois au démarrage du service
redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=10,
    decode_responses=True,
)
redis = aioredis.Redis(connection_pool=redis_pool)
```

### Commandes interdites en production

| Commande | Alternative |
|----------|-------------|
| `KEYS *` | `SCAN` avec curseur |
| `FLUSHALL` / `FLUSHDB` | Interdit hors environnement contrôlé |
| `SMEMBERS` sur un grand Set | `SSCAN` avec pagination |
| `LRANGE 0 -1` sur une grande List | `LRANGE` avec bornes explicites |

---

## Observabilité

PodIQ utilise Grafana + Loki. Pour Redis, monitorer :

| Métrique | Seuil d'alerte | Comment |
|----------|---------------|---------|
| Hit ratio cache | < 70% → investiguer | `INFO stats` → `keyspace_hits` / `keyspace_misses` |
| Latence commandes | P99 > 10ms | `SLOWLOG GET` |
| Mémoire utilisée | > 80% `maxmemory` | `INFO memory` |
| Connexions actives | pic anormal | `INFO clients` |

```python
# Logger les cache miss pour mesurer le hit ratio
async def get_cached_analysis(analysis_id: str):
    result = await redis.get(f"podiq:ai:analysis:{analysis_id}")
    if result is None:
        logger.info("cache_miss", key_type="analysis", analysis_id=analysis_id)
        return None
    logger.debug("cache_hit", key_type="analysis", analysis_id=analysis_id)
    return result
```

---

## Eviction policy recommandée

```
maxmemory-policy: allkeys-lru
```

Justification : toutes les données Redis dans PodIQ sont des caches ou des queues. En cas de pression mémoire, LRU est la politique la plus sûre — les données chaudes restent, les données froides sont évincées. Les données persistantes sont dans PostgreSQL.

---

## Sécurité

- Ne jamais exposer le port Redis publiquement (pas de `ports:` dans docker-compose en production)
- Utiliser un mot de passe Redis en production (`requirepass` ou ACL)
- Ne jamais stocker de secrets en clair dans Redis — stocker uniquement des hashes
- Les clés contenant des données utilisateur doivent être chiffrées si Redis est partagé
- En dev local, Redis sans auth est acceptable sur le réseau Docker interne uniquement

---

## Ce que Redis ne fait PAS dans PodIQ

| Mauvais usage | Pourquoi interdit | Alternative |
|---------------|-------------------|-------------|
| Stocker les analyses complètes | Données persistantes → PostgreSQL | Table `analyses` dans postgres-ai |
| Stocker les patterns d'incidents | Données persistantes → PostgreSQL | Table `incident_patterns` |
| Remplacer gRPC pour la comm inter-services | Redis Pub/Sub n'est pas fiable pour ce cas | gRPC obligatoire |
| Stocker les logs snapshots | Volume trop important, persistance requise | Table `logs_snapshots` dans postgres-analyzer |

---

## Vector Search (Post-MVP)

Non utilisé dans le MVP. Si ajouté en Phase 2 pour le RAG sur l'historique d'incidents :
- Stocker les embeddings des `incident_patterns` dans Redis avec `VECTOR` field
- Utiliser `COSINE` comme métrique de distance
- Documenter le modèle d'embedding utilisé
- Prévoir une stratégie de réindexation si le modèle change
- Aligner `LIMIT` avec le `top_k` attendu (ex: 5 pour la Memory Engine)
