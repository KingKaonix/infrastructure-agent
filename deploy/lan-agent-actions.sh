#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
TARGET_IP="${2:-192.168.12.229}"
SERVICE="infrastructure-agent.service"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${INFRA_AGENT_PROVISION_SCRIPT:-}" ]]; then
  PROVISION_SCRIPT="${INFRA_AGENT_PROVISION_SCRIPT}"
elif [[ -x /usr/local/lib/infrastructure-agent/provision-system-credentials.sh ]]; then
  PROVISION_SCRIPT=/usr/local/lib/infrastructure-agent/provision-system-credentials.sh
else
  PROVISION_SCRIPT="${ROOT_DIR}/deploy/provision-system-credentials.sh"
fi
SYSTEM_BIN="/var/lib/infrastructure-agent/.venv/bin/infrastructure-agent"

require_sudo() {
  sudo -n true 2>/dev/null || {
    echo "GitHub Actions runner needs passwordless sudo for the infrastructure-agent action." >&2
    exit 2
  }
}

show_status() {
  systemctl is-enabled "${SERVICE}"
  systemctl is-active "${SERVICE}"
  systemctl show "${SERVICE}" -p User -p Group -p MainPID -p NRestarts -p ExecMainStartTimestamp
}

show_recent_evidence() {
  sudo -n journalctl -u "${SERVICE}" --since "10 minutes ago" --no-pager -o cat \
    | grep -E "Optimization cycle complete|Autonomous AI review|Auth for user|OpenCode|failed|timed out|database is locked" \
    | tail -n 80 || true
}

case "${ACTION}" in
  status)
    show_status
    show_recent_evidence
    ;;
  verify)
    require_sudo
    show_status
    sudo -n "${SYSTEM_BIN}" doctor
    show_recent_evidence
    ;;
  repair)
    require_sudo
    sudo -n "${PROVISION_SCRIPT}" "${TARGET_IP}"
    sleep 45
    show_status
    show_recent_evidence
    ;;
  *)
    echo "Usage: $0 {status|verify|repair} [target-ip]" >&2
    exit 2
    ;;
esac
