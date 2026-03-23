#!/usr/bin/env bash
# Full-stack smoke (curl). Requires compose stack running.
# Usage: ./scripts/e2e_smoke.sh [BASE_URL] [ACCESSION]

set -euo pipefail
BASE_URL="${1:-http://localhost:8000}"
ACCESSION="${2:-P01308}"
TIMEOUT="${E2E_TIMEOUT:-900}"
POLL="${E2E_POLL:-5}"

started=$(date +%s)

echo "Waiting for API at ${BASE_URL}..."
while true; do
  if curl -sf "${BASE_URL}/openapi.json" >/dev/null; then break; fi
  now=$(date +%s)
  if (( now - started > TIMEOUT )); then echo "API not reachable"; exit 1; fi
  sleep 2
done

echo "POST /jobs accession=${ACCESSION}"
resp=$(curl -sf -X POST "${BASE_URL}/jobs" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"protein_analysis\",\"accession\":\"${ACCESSION}\"}")
job_id=$(echo "$resp" | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job id: ${job_id}"

poll_start=$(date +%s)
while true; do
  st=$(curl -sf "${BASE_URL}/jobs/${job_id}" | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "  status: ${st}"
  if [[ "$st" == "completed" ]]; then
    curl -sf "${BASE_URL}/jobs/${job_id}/result" | python -c "import sys,json; r=json.load(sys.stdin); print('pockets' in r and 'OK: pockets present' or 'warn: no pockets key')"
    exit 0
  fi
  if [[ "$st" == "failed" ]]; then
    curl -sf "${BASE_URL}/jobs/${job_id}/logs" || true
    exit 1
  fi
  now=$(date +%s)
  if (( now - poll_start > TIMEOUT )); then echo "Timeout"; exit 1; fi
  sleep "$POLL"
done
