#!/usr/bin/env bash
# Simulate the PodIQ agent against a real cluster.
# Usage: ./scripts/agent_simulate.sh <install_token> <pod_name> [namespace]
# Example: ./scripts/agent_simulate.sh wsk_abc123 podiq-test-crashloop default

set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080/graphql}"
TOKEN="${1:?Usage: $0 <install_token> <pod_name> [namespace] [workspace_jwt]}"
POD="${2:?Usage: $0 <install_token> <pod_name> [namespace] [workspace_jwt]}"
NS="${3:-default}"
JWT="${4:-}"  # workspace-scoped JWT for polling analysisJob (requires auth)

# ── Step 1: collect data from the cluster ─────────────────────────────────────

echo "Collecting data for pod $POD in namespace $NS ..."

K8S_VERSION=$(kubectl version --short 2>/dev/null \
  | awk '/Server Version/{print $3}' || echo "unknown")

LOGS=$(kubectl logs "$POD" -n "$NS" --tail=200 2>&1 || true)
EVENTS=$(kubectl get events -n "$NS" \
  --field-selector="involvedObject.name=$POD" \
  --sort-by='.lastTimestamp' 2>/dev/null || true)
DESCRIBE=$(kubectl describe pod "$POD" -n "$NS" 2>/dev/null || true)

# Collect all pods in the namespace for temporal correlation.
# Produces: [{"name":"svc","status":"CrashLoopBackOff","has_errors":true,"last_restart_time":1716120000},...]
_PODS_JSON=$(kubectl get pods -n "$NS" -o json 2>/dev/null || echo '{"items":[]}')
NS_PODS=$(echo "$_PODS_JSON" | python3 -c '
import json, sys, calendar
from datetime import datetime

ERROR_STATUSES = {"CrashLoopBackOff","Error","OOMKilled","ImagePullBackOff","ErrImagePull"}

data = json.load(sys.stdin)
result = []
for pod in data.get("items", []):
    name = pod["metadata"]["name"]
    phase = pod.get("status", {}).get("phase", "Unknown")
    has_errors = False
    last_restart_ts = 0
    reason = ""

    for cs in pod.get("status", {}).get("containerStatuses", []):
        r = (cs.get("state", {}).get("waiting") or {}).get("reason", "")
        if r in ERROR_STATUSES:
            has_errors = True
            reason = r
        finished = (cs.get("lastState", {}).get("terminated") or {}).get("finishedAt")
        if finished:
            try:
                dt = datetime.strptime(finished, "%Y-%m-%dT%H:%M:%SZ")
                ts = int(calendar.timegm(dt.timetuple()))
                if ts > last_restart_ts:
                    last_restart_ts = ts
            except Exception:
                pass

    status = reason if has_errors else phase
    result.append({"name": name, "status": status,
                   "has_errors": has_errors, "last_restart_time": last_restart_ts})

print(json.dumps(result))
')

echo "  logs:          $(echo "$LOGS"    | wc -l | tr -d ' ') lines"
echo "  events:        $(echo "$EVENTS"  | wc -l | tr -d ' ') lines"
echo "  describe:      $(echo "$DESCRIBE"| wc -l | tr -d ' ') lines"
echo "  namespace pods: $(echo "$NS_PODS" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') pods"

# ── Step 2: heartbeat ──────────────────────────────────────────────────────────

echo ""
echo "Sending heartbeat ..."

HEARTBEAT_PAYLOAD=$(jq -n \
  --arg token "$TOKEN" \
  --arg name  "$(kubectl config current-context 2>/dev/null || echo 'unknown')" \
  --arg ver   "$K8S_VERSION" \
  '{
    query: "mutation($t:String!,$n:String!,$v:String){agentHeartbeat(installToken:$t,clusterName:$n,k8sVersion:$v){id name status}}",
    variables: {t: $token, n: $name, v: $ver}
  }')

curl -sf -X POST "$GATEWAY_URL" \
  -H "Content-Type: application/json" \
  --data "$HEARTBEAT_PAYLOAD" | jq .

# ── Step 3: report incident ────────────────────────────────────────────────────

echo ""
echo "Reporting incident ..."

INCIDENT_PAYLOAD=$(jq -n \
  --arg token    "$TOKEN" \
  --arg pod      "$POD" \
  --arg ns       "$NS" \
  --arg logs     "$LOGS" \
  --arg events   "$EVENTS" \
  --arg desc     "$DESCRIBE" \
  --arg nspods   "$NS_PODS" \
  '{
    query: "mutation($t:String!,$p:String!,$n:String!,$l:String!,$e:String!,$d:String!,$np:String!){agentReportIncident(installToken:$t,podName:$p,namespace:$n,logs:$l,events:$e,describeOutput:$d,namespacePods:$np){jobId status}}",
    variables: {t: $token, p: $pod, n: $ns, l: $logs, e: $events, d: $desc, np: $nspods}
  }')

RESPONSE=$(curl -sf -X POST "$GATEWAY_URL" \
  -H "Content-Type: application/json" \
  --data "$INCIDENT_PAYLOAD")

echo "$RESPONSE" | jq .

JOB_ID=$(echo "$RESPONSE" | jq -r '.data.agentReportIncident.jobId // empty')

if [ -z "$JOB_ID" ]; then
  echo "ERROR: no jobId in response"
  exit 1
fi

# ── Step 4: poll until complete ────────────────────────────────────────────────

echo ""
echo "Polling job $JOB_ID ..."

if [ -z "$JWT" ]; then
  echo ""
  echo "  ⚠️  No workspace JWT provided (4th argument) — skipping poll."
  echo "     To poll the result, run:"
  echo "       curl -s -X POST $GATEWAY_URL \\"
  echo "         -H 'Content-Type: application/json' \\"
  echo "         -H 'Authorization: Bearer <workspace_jwt>' \\"
  echo "         --data '{\"query\":\"query{analysisJob(jobId:\\\"$JOB_ID\\\"){status result{errorType rootCause solution} error}}\"}'"
  exit 0
fi

for i in $(seq 1 72); do
  sleep 5

  POLL_PAYLOAD=$(jq -n --arg id "$JOB_ID" \
    '{query: "query($id:String!){analysisJob(jobId:$id){status result{errorType rootCause solution confidence isRecurring correlatedService correlationExplanation} error}}",
      variables: {id: $id}}')

  STATUS_RESP=$(curl -sf -X POST "$GATEWAY_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $JWT" \
    --data "$POLL_PAYLOAD")

  STATUS=$(echo "$STATUS_RESP" | jq -r '.data.analysisJob.status // "unknown"')
  echo "  [$i] status: $STATUS"

  if [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ]; then
    echo ""
    echo "$STATUS_RESP" | jq '.data.analysisJob'
    exit 0
  fi
done

echo "Timeout — job still running after 360s"
exit 1
