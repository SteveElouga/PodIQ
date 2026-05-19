SHELL  := /bin/bash
.DEFAULT_GOAL := help

KUBECONFIG_PATH ?= $(HOME)/.kube/config-podiq-cluster

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

.PHONY: up-mock
up-mock: ## Démarrer en mode mock — STUB_MODE=true, aucun cluster K8s requis
	STUB_MODE=true docker compose up -d

.PHONY: up-cluster
up-cluster: ## Démarrer en mode cluster réel — STUB_MODE=false, kubeconfig monté
	@if [ ! -f "$(KUBECONFIG_PATH)" ]; then \
	  echo ""; \
	  echo "  ❌  Kubeconfig introuvable : $(KUBECONFIG_PATH)"; \
	  echo "      Lance d'abord : make cluster-config"; \
	  echo ""; \
	  exit 1; \
	fi
	STUB_MODE=false KUBECONFIG_PATH=$(KUBECONFIG_PATH) \
	  docker compose \
	    -f docker-compose.yml \
	    -f docker-compose.cluster.yml \
	  up -d --build

.PHONY: down
down: ## Arrêter tous les services
	docker compose down

.PHONY: restart-mock
restart-mock: down up-mock ## Redémarrer en mode mock

.PHONY: restart-cluster
restart-cluster: down up-cluster ## Redémarrer en mode cluster

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
logs-analyzer: ## Logs analyzer-service (kubectl)
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
# Cluster Kubernetes
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: cluster-start
cluster-start: ## Démarrer le cluster minikube
	minikube start --driver=docker --cpus=2 --memory=2048
	@echo ""
	@echo "  ✅  Cluster démarré. Lance ensuite : make cluster-config"
	@echo ""

.PHONY: cluster-stop
cluster-stop: ## Arrêter le cluster minikube
	minikube stop

.PHONY: cluster-config
cluster-config: ## Générer le kubeconfig accessible depuis les conteneurs Docker
	@MINIKUBE_IP=$$(docker inspect minikube \
	  --format='{{.NetworkSettings.Networks.minikube.IPAddress}}' 2>/dev/null); \
	if [ -z "$$MINIKUBE_IP" ]; then \
	  echo ""; \
	  echo "  ❌  Conteneur minikube introuvable. Lance d'abord : make cluster-start"; \
	  echo ""; \
	  exit 1; \
	fi; \
	minikube kubectl -- config view --flatten --minify > $(KUBECONFIG_PATH); \
	sed -i '' "s|https://127\.0\.0\.1:[0-9]*|https://$$MINIKUBE_IP:8443|g" $(KUBECONFIG_PATH); \
	echo ""; \
	echo "  ✅  Kubeconfig généré : $(KUBECONFIG_PATH)"; \
	echo "      API server réécrit → $$MINIKUBE_IP:8443 (réseau Docker minikube)"; \
	echo "      Lance ensuite : make up-cluster"; \
	echo ""

.PHONY: cluster-pods
cluster-pods: ## Déployer les pods de test en échec sur le cluster
	kubectl apply -f k8s/test-pods/
	@echo ""
	@echo "  ✅  Pods déployés. Attendre ~30s, puis analyser depuis le playground GraphQL."
	@echo "      Vérifier : make cluster-status"
	@echo ""

.PHONY: cluster-status
cluster-status: ## Vérifier l'état des pods de test
	kubectl get pods -n default -l podiq-test=true -o wide

.PHONY: cluster-clean
cluster-clean: ## Supprimer les pods de test du cluster
	kubectl delete -f k8s/test-pods/ --ignore-not-found

# ─────────────────────────────────────────────────────────────────────────────
# Nettoyage
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Arrêter les services et supprimer les volumes (⚠️ données effacées)
	docker compose down -v

.PHONY: clean-all
clean-all: clean cluster-clean ## Tout nettoyer — volumes Docker + pods de test K8s
