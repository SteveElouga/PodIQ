# Template — Merge Request PodIQ

---

## Avant de soumettre la MR

- [ ] Le titre de la MR suit le format conventionnel (`feat/fix/chore/refactor/docs(scope): description`)
- [ ] La branche cible est correcte (`develop`, pas `main`)
- [ ] Les conflits sont résolus
- [ ] Les `print` et logs de debug temporaires sont supprimés
- [ ] `pre-commit run --all-files` passe sans erreur (Black, Ruff, mypy, detect-secrets)
- [ ] Les tests unitaires passent localement (`./scripts/run_all_tests.sh`)
- [ ] Le lien vers la tâche est ajouté ci-dessous (section Références)

Si un point n'est pas résolu, expliquer pourquoi :

---

## Références

- **Tâche / ticket :** _(lien)_
- **MR(s) dépendantes :** _(lien ou "aucune")_
- **Proto modifié :** _(oui/non — si oui, préciser le fichier `.proto` et le service impacté)_

---

## Contexte

Expliquer brièvement **pourquoi** cette MR existe. Quel problème résout-elle ? Quelle fonctionnalité ajoute-t-elle ?

Éviter les descriptions générées par IA : elles noient les informations importantes et ralentissent la review.

---

## Changements

Détailler les changements par service ou composant. Lister tous les fichiers ou modules significativement impactés.

**Format recommandé :**

- **`auth-service`** : _(ce qui a changé et pourquoi)_
- **`gateway`** : _(ce qui a changé et pourquoi)_
- **`shared/grpc`** : _(nouveaux stubs générés / proto modifié)_
- **`docker-compose.yml`** : _(nouvelle variable d'env, nouveau service, etc.)_

Préciser si des changements annexes ont été réalisés dans la même MR et expliquer pourquoi ils n'ont pas été séparés.

> Exemple de ce qu'il ne faut **PAS** faire :
> *"Ajout de la gestion des API keys dans plusieurs services."*

> Exemple correct :
> - **`auth-service/app/grpc_server.py`** : ajout de `ValidateApiKey` — vérifie la signature SHA-256 + pepper et retourne le `user_id` associé.
> - **`gateway/app/api/cicd.py`** : nouveau endpoint `POST /api/v1/cicd/scan`, auth via header `X-Api-Key`, exit codes 0/1/2.

---

## Impact architectural

Cocher ce qui s'applique :

- [ ] Nouveau message proto / modification d'un `.proto` existant (stubs régénérés)
- [ ] Nouvelle migration Django (`makemigrations` + `migrate` requis au déploiement)
- [ ] Nouvelle variable d'environnement (`.env.example` mis à jour)
- [ ] Nouveau service dans `docker-compose.yml`
- [ ] Modification du schéma Redis (clé, TTL, structure)
- [ ] Modification de l'API GraphQL publique (schema Strawberry)
- [ ] Aucun impact architectural

---

## Comment tester

Décrire les étapes précises pour reproduire le bug corrigé ou valider la feature, en partant d'un état propre.

**Prérequis :**

- Variables d'env nécessaires : _(ex. `STUB_MODE=true`, `AI_TIMEOUT_SECONDS=120`)_
- Services à démarrer : _(ex. `docker compose up -d postgres-auth auth-service gateway nginx`)_
- Données de test : _(ex. utilisateur existant, pod crashé en `OOMKilled`)_

**Étapes :**

1. _(action)_
2. _(action)_
3. Vérifier que : _(résultat attendu)_

**Tests unitaires à cibler :**

```bash
cd services/<service> && python3 -m pytest -v tests/<fichier_test>.py
```

---

## Screenshots / Logs

Joindre si pertinent :

- Réponse GraphQL (playground `http://localhost:8080/graphql`)
- Sortie `docker compose logs -f <service>`
- Requête Loki dans Grafana : `{service="<nom-service>"}`
