SHELL  := /bin/bash
.DEFAULT_GOAL := help

# ─────────────────────────────────────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Afficher l'aide
	@echo ""
	@echo "  PodIQ — commandes disponibles"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Démarrage
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: up
up: ## Démarrer tous les services
	docker compose up -d

.PHONY: up-build
up-build: ## Démarrer avec rebuild des images
	docker compose up -d --build

.PHONY: down
down: ## Arrêter tous les services
	docker compose down

.PHONY: restart
restart: down up ## Redémarrer tous les services

# ─────────────────────────────────────────────────────────────────────────────
# Logs & statut
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: logs
logs: ## Suivre les logs de tous les services
	docker compose logs -f

.PHONY: logs-gateway
logs-gateway: ## Logs gateway
	docker compose logs -f gateway

.PHONY: logs-worker
logs-worker: ## Logs gateway-worker (Dramatiq)
	docker compose logs -f gateway-worker

.PHONY: logs-ai
logs-ai: ## Logs ai-service (Ollama)
	docker compose logs -f ai-service

.PHONY: logs-analyzer
logs-analyzer: ## Logs analyzer-service (ParseManifest)
	docker compose logs -f analyzer-service

.PHONY: ps
ps: ## État des conteneurs
	docker compose ps

# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: build
build: ## Builder toutes les images
	docker compose build

.PHONY: build-no-cache
build-no-cache: ## Builder sans cache (après modification d'un Dockerfile)
	docker compose build --no-cache

# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Lancer tous les tests unitaires (tous les services)
	./scripts/run_all_tests.sh

.PHONY: test-gateway
test-gateway: ## Tests gateway uniquement
	cd services/gateway && python3 -m pytest -v

.PHONY: test-ai
test-ai: ## Tests ai-service uniquement
	cd services/ai-service && python3 -m pytest -v

.PHONY: test-auth
test-auth: ## Tests auth-service uniquement
	cd services/auth-service && python3 -m pytest -v

.PHONY: test-analyzer
test-analyzer: ## Tests analyzer-service uniquement
	cd services/analyzer-service && python3 -m pytest -v

# ─────────────────────────────────────────────────────────────────────────────
# Pods de test K8s (flux agent)
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: agent-pods
agent-pods: ## Déployer les pods de test en échec sur le cluster courant
	kubectl apply -f k8s/test-pods/
	@echo ""
	@echo "  Pods déployés. Attendre ~30s, puis simuler l'agent avec make agent-report."
	@echo "  Vérifier : make agent-status"
	@echo ""

.PHONY: agent-status
agent-status: ## Vérifier l'état des pods de test
	kubectl get pods -n default -l podiq-test=true -o wide

.PHONY: agent-clean
agent-clean: ## Supprimer les pods de test du cluster
	kubectl delete -f k8s/test-pods/ --ignore-not-found

# ─────────────────────────────────────────────────────────────────────────────
# Nettoyage
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Arrêter les services et supprimer les volumes (⚠️ données effacées)
	docker compose down -v

.PHONY: clean-all
clean-all: clean agent-clean ## Tout nettoyer — volumes Docker + pods de test K8s
