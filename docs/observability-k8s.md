# Observabilité PodIQ — Production Kubernetes (Option B)

> **Contexte** : En développement Docker Compose, PodIQ utilise le **Loki Docker Log Driver** (Option A) — chaque conteneur pousse ses logs directement vers Loki via un plugin Docker, sans monter le socket Docker. Ce document décrit la migration vers l'**Option B** pour la production Kubernetes : collecte de logs via fichiers, sans accès au socket Docker.

---

## Pourquoi passer à l'Option B en production

| Critère | Option A (Log Driver) | Option B (Fichiers K8s) |
|---|---|---|
| Socket Docker (`/var/run/docker.sock`) | ❌ Aucun | ❌ Aucun |
| Plugin à installer par nœud | ✅ Requis | ❌ Non requis |
| Standard Kubernetes | ⚠️ Non officiel | ✅ Recommandé par Grafana |
| Compatible NetworkPolicies strictes | ⚠️ Partiel | ✅ Oui |
| DaemonSet géré par Helm | ❌ | ✅ `grafana/loki-stack` |
| Richesse des labels K8s (`pod`, `namespace`, `node`) | ❌ | ✅ Via `__meta_kubernetes_*` |

---

## Architecture cible (Production K8s)

```
[Pod PodIQ]  stdout/stderr
      │
      ▼ (kubelet — pas de socket)
/var/log/pods/<namespace>/<pod-name>/<container>.log
      │
      ▼ (DaemonSet Promtail — lecture fichiers uniquement)
Loki (StatefulSet ou Grafana Cloud)
      │
      ▼
Grafana (Deployment)
```

Promtail tourne en **DaemonSet** (un pod par nœud K8s), monte `/var/log/pods` et `/var/log/containers` en **lecture seule**, **sans accès au socket Docker**.

---

## Déploiement avec Helm

### 1. Ajouter le repo Grafana

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### 2. Créer `infra/k8s/loki-stack-values.yaml`

```yaml
loki:
  enabled: true
  persistence:
    enabled: true
    storageClassName: standard   # adapter au provider cloud
    size: 50Gi
  config:
    limits_config:
      retention_period: 2160h    # 90 jours — SOC2 §7.3
    compactor:
      working_directory: /loki/compactor
      compaction_interval: 10m

promtail:
  enabled: true
  config:
    clients:
      - url: http://loki:3100/loki/api/v1/push
    snippets:
      pipelineStages:
        - json:
            expressions:
              level: level
              event: event
              service: service
        - labels:
            level:
            event:
            service:
      # Filtrer uniquement les pods PodIQ
      scrapeConfigs: |
        - job_name: podiq-pods
          kubernetes_sd_configs:
            - role: pod
              namespaces:
                names: ["podiq"]
          pipeline_stages:
            - json:
                expressions:
                  level: level
                  service: service
            - labels:
                level:
                service:
          relabel_configs:
            - source_labels: [__meta_kubernetes_pod_label_app]
              target_label: app
            - source_labels: [__meta_kubernetes_namespace]
              target_label: namespace
            - source_labels: [__meta_kubernetes_pod_name]
              target_label: pod
            - source_labels: [__meta_kubernetes_container_name]
              target_label: container
  # IMPORTANT : lecture de fichiers uniquement, pas de socket Docker
  extraVolumes:
    - name: pods-logs
      hostPath:
        path: /var/log/pods
  extraVolumeMounts:
    - name: pods-logs
      mountPath: /var/log/pods
      readOnly: true             # lecture seule — principe du moindre privilège

grafana:
  enabled: true
  adminPassword: "${GRAFANA_ADMIN_PASSWORD}"
  persistence:
    enabled: true
    size: 5Gi
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Loki
          type: loki
          url: http://loki:3100
          isDefault: true
```

### 3. Déployer dans le namespace `podiq`

```bash
kubectl create namespace podiq

helm upgrade --install podiq-observability grafana/loki-stack \
  --namespace podiq \
  --values infra/k8s/loki-stack-values.yaml \
  --set loki.config.limits_config.retention_period=2160h
```

### 4. Vérifier

```bash
kubectl get pods -n podiq -l "app in (loki, promtail, grafana)"
# Attendre que tous soient Running

# Tester l'ingestion
kubectl logs -n podiq -l app=promtail --tail=20
```

---

## Migration depuis l'Option A (Docker Log Driver)

Lors du passage dev → production K8s :

1. **Retirer les blocs `logging:` du `docker-compose.yml`** — ils sont spécifiques à Docker Compose et sans effet en K8s.
2. **Les manifests K8s des services applicatifs n'ont aucune configuration de logs à ajouter** — Promtail collecte automatiquement depuis `/var/log/pods/`.
3. **Labels Grafana maintenus** : Promtail extrait `namespace`, `service`, `pod` depuis les métadonnées K8s via `__meta_kubernetes_*` — les dashboards `podiq-overview.json` continuent de fonctionner sans modification.

---

## Config Promtail de référence (Docker Compose → K8s)

Le fichier `infra/promtail/promtail-config.yml` (ancienne config Docker Compose avec docker.sock) est conservé à titre de référence. La config K8s équivalente est dans `infra/k8s/loki-stack-values.yaml`.

> **Ne pas réutiliser l'ancienne config** `docker_sd_configs` en K8s — remplacer par `kubernetes_sd_configs` + lecture de fichiers.

---

## NetworkPolicy recommandée

```yaml
# infra/k8s/netpol-promtail.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: promtail-egress
  namespace: podiq
spec:
  podSelector:
    matchLabels:
      app: promtail
  policyTypes:
    - Egress
  egress:
    - ports:
        - port: 3100          # Loki uniquement
      to:
        - podSelector:
            matchLabels:
              app: loki
```

---

## Checklist migration

- [ ] Helm repo grafana ajouté
- [ ] `infra/k8s/loki-stack-values.yaml` créé et `retention_period: 2160h` confirmé
- [ ] Namespace `podiq` créé
- [ ] Stack déployée et pods `Running`
- [ ] Logs visibles dans Grafana → Loki (`{namespace="podiq"}`)
- [ ] Dashboard `podiq-overview.json` importé et fonctionnel
- [ ] NetworkPolicy Promtail appliquée
- [ ] Aucun mount `/var/run/docker.sock` dans le DaemonSet Promtail (`kubectl describe ds promtail -n podiq`)

---

*Référence : [Grafana Loki — Best practices](https://grafana.com/docs/loki/latest/best-practices/) | [Promtail Kubernetes](https://grafana.com/docs/loki/latest/clients/promtail/configuration/#kubernetes_sd_configs)*
