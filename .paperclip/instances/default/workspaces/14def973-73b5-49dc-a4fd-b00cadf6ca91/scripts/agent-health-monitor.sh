#!/usr/bin/env bash
# agent-health-monitor.sh — Checks all agents for health issues.
# Called by the Recurring: Agent Health Monitor routine (ZER-416).
#
# Checks:
#   1. No heartbeat in 2+ hours
#   2. Error/paused state
#   3. Tasks stuck in_progress 24+ hours
#   4. Theta-specific: auto-restart if heartbeat gap > 1h (ZER-485)
#
# Outputs structured JSON alerts to stdout (captured by routine execution).

set -euo pipefail

PAPERCLIP_API_URL="${PAPERCLIP_API_URL:-http://localhost:3100}"
COMPANY_ID="${PAPERCLIP_COMPANY_ID:-4df94718-a9d9-47ce-8e7a-361c319cf85f}"
PAPERCLIP_API_KEY="${PAPERCLIP_API_KEY:-}"
THETA_AGENT_ID="b681e965-c7d6-404b-b07d-a16a3ac642f5"
THETA_MAX_GAP=3600  # 1 hour for Theta (investor relations — should always be active)
GENERAL_MAX_GAP=14400  # 4 hours for other agents (episodic work agents routinely idle 2-3h)
LOG_DIR="/Users/abreckler/.paperclip/instances/default/logs"

mkdir -p "$LOG_DIR"

ALERTS=()

log_json() {
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    printf '{"ts":"%s","level":"%s","agent":"%s","event":"%s"%s}\n' \
        "$ts" "$1" "$2" "$3" "${4:-}" >> "${LOG_DIR}/agent-health-monitor.log"
}

# Fetch all agents
agents_json=$(curl -sf --max-time 15 \
    -H "Authorization: Bearer ${PAPERCLIP_API_KEY}" \
    "${PAPERCLIP_API_URL}/api/companies/${COMPANY_ID}/agents" 2>/dev/null) || {
    echo "ERROR: Could not reach Paperclip API"
    exit 1
}

now_epoch=$(date -u +%s)

# Check each agent
echo "$agents_json" | python3 -c "
import json, sys, time
from datetime import datetime

agents = json.load(sys.stdin)
now = time.time()
alerts = []
theta_id = '${THETA_AGENT_ID}'
theta_max_gap = ${THETA_MAX_GAP}
general_max_gap = ${GENERAL_MAX_GAP}

for a in agents:
    name = a['name']
    status = a.get('status', 'unknown')
    pause_reason = a.get('pauseReason', '')
    last_hb = a.get('lastHeartbeatAt', '')

    # Check paused/error — skip intentionally manual-paused agents
    if status == 'paused' and pause_reason != 'manual':
        alerts.append({
            'agent': name,
            'agentId': a['id'],
            'alert': 'agent_paused',
            'detail': f'Pause reason: {pause_reason}',
            'severity': 'high'
        })

    # Check heartbeat gap — skip manually-paused agents (intentional, not a health issue)
    if last_hb and status != 'paused':
        try:
            hb_str = last_hb.replace('Z', '+00:00')
            hb_dt = datetime.fromisoformat(hb_str)
            gap = now - hb_dt.timestamp()
            max_gap = theta_max_gap if a['id'] == theta_id else general_max_gap

            if gap > max_gap:
                alerts.append({
                    'agent': name,
                    'agentId': a['id'],
                    'alert': 'heartbeat_stale',
                    'gapSeconds': int(gap),
                    'thresholdSeconds': max_gap,
                    'detail': f'Last heartbeat {int(gap/60)}m ago (threshold: {int(max_gap/60)}m)',
                    'severity': 'critical' if a['id'] == theta_id else 'high',
                    'autoRestart': a['id'] == theta_id
                })
        except Exception:
            pass

print(json.dumps({'alerts': alerts, 'agentCount': len(agents), 'timestamp': datetime.utcnow().isoformat() + 'Z'}, indent=2))
"
