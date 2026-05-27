# Auth Service — Le Gardien des Identités

## Analogie

Imagine un **portier de boîte de nuit haut de gamme**.

- Quand quelqu'un veut entrer pour la **première fois**, il prend ses informations, crée un dossier, lui remet un **bracelet d'accès temporaire** (le JWT). C'est le `Register`.
- Quand un habitué revient, le portier vérifie son identité et lui redonne un **bracelet valide**. C'est le `Login`.
- À chaque fois qu'un bracelet est présenté à l'entrée d'une salle VIP, le portier vérifie qu'il n'est pas expiré et qu'il est authentique. C'est le `ValidateJWT`.
- Pour les **systèmes automatiques** (pipelines CI/CD), on ne peut pas utiliser un bracelet temporaire — on leur donne une **carte magnétique permanente** (API Key) qui reste valable jusqu'à révocation.

Le portier ne connaît rien du reste de la boîte (il ne sait pas ce qui se passe dans les salles) — il ne fait **que** gérer les accès.

---

## Responsabilité

Ce service est le **seul** responsable de :
- L'enregistrement et la connexion des utilisateurs humains
- La génération et la validation des tokens JWT
- La création, la validation et la révocation des clés API (pour les pipelines CI/CD)

Il n'a aucune connaissance de Kubernetes, des incidents, ou des analyses. Il répond uniquement aux questions : **"Qui es-tu ? Es-tu autorisé ?"**

---

## Base de données

Ce service possède sa propre instance PostgreSQL : **`postgres-auth`** (port 5433).

### Table `users`

| Colonne         | Type      | Description                                      |
|-----------------|-----------|--------------------------------------------------|
| `id`            | UUID (PK) | Identifiant unique de l'utilisateur              |
| `email`         | string    | Email unique (identifiant de connexion)          |
| `password_hash` | string    | Mot de passe haché avec **Argon2id** (OWASP, sel unique par hash) |
| `created_at`    | datetime  | Date de création du compte                       |

### Table `api_keys`

| Colonne      | Type      | Description                                              |
|--------------|-----------|----------------------------------------------------------|
| `id`         | UUID (PK) | Identifiant unique de la clé                             |
| `user_id`    | UUID      | Référence applicative vers `users.id` (pas de FK réelle) |
| `key_hash`   | string    | Clé API hachée avec SHA-256                              |
| `name`       | string    | Nom lisible (ex: "github-actions-prod")                  |
| `last_used`  | datetime  | Dernière utilisation (mis à jour à chaque validation)    |
| `is_active`  | boolean   | `False` si révoquée                                      |
| `created_at` | datetime  | Date de création                                         |

---

## Interface gRPC

Ce service implémente le contrat défini dans `proto/auth/auth.proto`.

Il écoute sur le port **50051**.

### `Register` — Créer un compte

**Entrée :**
```
email    : string  — ex: "alice@example.com"
password : string  — mot de passe en clair (jamais stocké tel quel)
```

**Sortie :**
```
user_id : UUID string  — identifiant permanent de l'utilisateur
token   : string       — JWT valide pour 24h
email   : string       — email confirmé
```

**Ce qui se passe en interne :**
1. Vérifie que l'email n'existe pas déjà → erreur `ALREADY_EXISTS`
2. Hache le mot de passe avec **Argon2id** (time=2, mem=64 MB, p=2 — sel aléatoire unique)
3. Crée la ligne dans `users`
4. Génère un JWT signé avec `JWT_SECRET`
5. Retourne token + user_id

---

### `Login` — Se connecter

**Entrée :**
```
email    : string
password : string
```

**Sortie :**
```
user_id : UUID string
token   : string  — nouveau JWT valide 24h
email   : string
```

**Ce qui se passe en interne :**
1. Cherche l'utilisateur par email → erreur `NOT_FOUND` si absent
2. Vérifie le mot de passe via `_verify_password` :
   - Hash Argon2id → `argon2.PasswordHasher.verify()` (résistant timing attacks)
   - Hash legacy SHA-256+pepper → `hmac.compare_digest()` (migration transparente)
3. Si le hash est legacy : le rehache en Argon2id et sauvegarde immédiatement (`password_rehashed_argon2id`)
4. Génère un nouveau JWT et le retourne

---

### `ValidateJWT` — Vérifier un token

**Entrée :**
```
token : string  — le JWT à vérifier
```

**Sortie :**
```
valid   : bool    — true si le token est valide et non expiré
user_id : string  — extrait du payload
email   : string  — extrait du payload
error   : string  — erreur si invalid (ex. "Token expired")
```

**Ce qui se passe en interne :**
1. Décode le JWT avec `PyJWT` et `JWT_SECRET`
2. Si expiré → `valid=false, error="Token expired"`
3. Si invalide (mauvaise signature, malformé) → `valid=false, error=...`

---

### `CreateApiKey` — Créer une clé API

**Entrée :**
```
user_id : UUID string  — l'utilisateur propriétaire
name    : string       — nom descriptif (ex: "github-actions-prod")
```

**Sortie :**
```
key_id     : UUID string  — identifiant de la clé en base
raw_key    : string       — la clé brute (retournée UNE SEULE FOIS, à stocker immédiatement)
name       : string
created_at : ISO datetime string
```

**Important :** Le `raw_key` n'est **jamais stocké** en base (seulement son hash). Si perdu, il faut en créer une nouvelle.

---

### `ValidateApiKey` — Vérifier une clé API

**Entrée :**
```
raw_key : string  — la clé brute envoyée par le pipeline CI/CD
```

**Sortie :**
```
valid   : bool
user_id : UUID string
key_id  : UUID string
error   : string
```

**Ce qui se passe en interne :**
1. Hache le `raw_key` reçu
2. Cherche en base par `key_hash` + `is_active=True`
3. Met à jour `last_used`
4. Retourne `valid=true` avec les identifiants

---

### `RevokeApiKey` — Révoquer une clé API

**Entrée :**
```
key_id  : UUID string  — la clé à révoquer
user_id : UUID string  — vérification de propriété
```

**Sortie :**
```
success : bool
```

**Ce qui se passe en interne :**
1. Filtre `ApiKey` par `id + user_id + is_active=True`
2. Fait un `UPDATE SET is_active=False`
3. Si aucune ligne trouvée → erreur `NOT_FOUND`

---

## Sécurité

| Mesure                       | Détail                                                                                    |
|------------------------------|-------------------------------------------------------------------------------------------|
| Mots de passe                | **Argon2id** (time=2, mem=64 MB, p=2, sel 16 octets) — OWASP, NIST SP 800-63B, SOC2 §8.3 |
| Migration legacy             | Hashes SHA-256+pepper détectés au login → rehachés Argon2id automatiquement (`_needs_rehash`) |
| Comparaison hashes Argon2id  | `PasswordHasher.verify()` — résistant aux timing attacks                                  |
| Comparaison hashes legacy    | `hmac.compare_digest()` — résistant aux timing attacks pendant la fenêtre de migration    |
| JWT                          | Algorithme HS256, expiration 24h, signé avec `JWT_SECRET`                                 |
| Clés API                     | `secrets.token_urlsafe(32)` — 256 bits d'entropie                                         |
| Stockage des clés API        | Seul le SHA-256 est en base — la clé brute n'est jamais conservée                         |
| Messages d'erreur génériques | Login retourne `Invalid email or password` (pas de distinction email/mot de passe)        |

---

## Variables d'environnement

| Variable              | Obligatoire | Défaut | Description                              |
|-----------------------|-------------|--------|------------------------------------------|
| `DATABASE_URL`        | Oui         | —      | URL PostgreSQL vers `postgres-auth:5433/podiq_auth`      |
| `DJANGO_SECRET_KEY`   | Oui         | —      | Pepper pour les hashes SHA-256 legacy (migration uniquement) + sécurité Django |
| `JWT_SECRET`          | Oui         | —      | Secret de signature des tokens JWT       |
| `JWT_EXPIRY_MINUTES`  | Non         | `1440` | Durée de vie des JWT (24h par défaut)    |
| `GRPC_PORT`           | Non         | `50051`| Port d'écoute gRPC                       |

---

## Communication avec les autres services

Ce service est **appelé par** :
- Le **Gateway** : pour les mutations `register` et `login` (GraphQL)
- Le **Gateway** : pour les mutations `createApiKey` et `revokeApiKey` (GraphQL, JWT requis)
- Le **Gateway** : pour valider les API Keys sur l'endpoint CI/CD (REST `POST /api/v1/cicd/scan`)

Ce service **n'appelle personne**. Il est terminal dans la chaîne de dépendances.

```
Gateway ──gRPC──▶ Auth Service ──▶ postgres-auth
```

---

## Comment tester

### Tests unitaires (pytest)

Depuis le répertoire du service : SQLite en mémoire (`config.settings_pytest`), stubs gRPC comme sous Docker. Aucune variable d’environnement obligatoire ; `JWT_SECRET` et `DJANGO_SECRET_KEY` ont des valeurs de secours dans `tests/conftest.py`.

```bash
cd services/auth-service
python3 -m pytest -v
```

Les contrôles **pre-commit** du monorepo s’exécutent depuis la **racine du dépôt** ; voir le README racine § « Pré-commit » et `pre-commit install`.

### 1. Démarrer uniquement l'auth-service

```bash
docker compose up -d postgres-auth auth-service
docker compose logs -f auth-service
```

### 2. Tester via le playground GraphQL du Gateway

Lance aussi le gateway :
```bash
docker compose up -d gateway
```

Puis ouvre `http://localhost:8080/graphql` et exécute :

```graphql
mutation {
  register(email: "test@example.com", password: "monmotdepasse") {  # pragma: allowlist secret
    token
    userId
    email
  }
}
```

```graphql
mutation {
  login(email: "test@example.com", password: "monmotdepasse") {  # pragma: allowlist secret
    token
    userId
    email
  }
}
```

**Créer une clé API** (ajouter le header `Authorization: Bearer <token>` dans GraphiQL) :

```graphql
mutation {
  createApiKey(name: "github-actions-prod") {
    keyId
    rawKey
    name
    createdAt
  }
}
```

> `rawKey` est retourné **une seule fois**. Copiez-le immédiatement — si perdu, révoquez et recréez.

**Révoquer une clé API** :

```graphql
mutation {
  revokeApiKey(keyId: "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb")
}
```

### 3. Vérifier en base

```bash
docker compose exec postgres-auth psql -U podiq -d podiq_auth -c "SELECT id, email, created_at FROM users;"
docker compose exec postgres-auth psql -U podiq -d podiq_auth -c "SELECT id, name, is_active, last_used FROM api_keys;"
```
