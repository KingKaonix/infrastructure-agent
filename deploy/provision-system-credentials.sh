#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="infrastructure-agent"
TARGET_USER="${SUDO_USER:-kaos}"
TARGET_IP="${1:-192.168.12.229}"
COPY_OPENCODE=1
for argument in "$@"; do
  if [[ "${argument}" == "--no-local-opencode" ]]; then
    COPY_OPENCODE=0
  fi
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname -- "${SCRIPT_DIR}")"
STATE_DIR="/var/lib/${SERVICE_USER}"
SSH_DIR="${STATE_DIR}/.ssh"
ENV_FILE="/etc/${SERVICE_USER}/agent.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [target-ip]" >&2
  exit 1
fi
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Missing ${SERVICE_USER} account; run deploy/install-system-service.sh first." >&2
  exit 1
fi
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
if [[ -z "${TARGET_HOME}" || ! -d "${TARGET_HOME}" ]]; then
  echo "Cannot resolve target user home: ${TARGET_USER}" >&2
  exit 1
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${SSH_DIR}"
chmod 700 "${SSH_DIR}"
KEY_FILE="${SSH_DIR}/id_ed25519"
if [[ ! -s "${KEY_FILE}" ]]; then
  runuser -u "${SERVICE_USER}" -- ssh-keygen -q -t ed25519 -N "" -f "${KEY_FILE}"
fi
chown "${SERVICE_USER}:${SERVICE_USER}" "${KEY_FILE}" "${KEY_FILE}.pub"
chmod 600 "${KEY_FILE}"
chmod 644 "${KEY_FILE}.pub"

KNOWN_HOSTS="${SSH_DIR}/known_hosts"
ssh-keyscan -H "${TARGET_IP}" > "${KNOWN_HOSTS}.new" 2>/dev/null
if [[ ! -s "${KNOWN_HOSTS}.new" ]]; then
  echo "Could not read an SSH host key from ${TARGET_IP}" >&2
  rm -f "${KNOWN_HOSTS}.new"
  exit 1
fi
cat "${KNOWN_HOSTS}.new" >> "${KNOWN_HOSTS}"
sort -u "${KNOWN_HOSTS}" -o "${KNOWN_HOSTS}"
rm -f "${KNOWN_HOSTS}.new"
chown "${SERVICE_USER}:${SERVICE_USER}" "${KNOWN_HOSTS}"
chmod 644 "${KNOWN_HOSTS}"

AUTHORIZED_KEYS="${TARGET_HOME}/.ssh/authorized_keys"
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "${TARGET_HOME}/.ssh"
touch "${AUTHORIZED_KEYS}"
chown "${TARGET_USER}:${TARGET_USER}" "${AUTHORIZED_KEYS}"
chmod 600 "${AUTHORIZED_KEYS}"
grep -qxF "$(cat "${KEY_FILE}.pub")" "${AUTHORIZED_KEYS}" || cat "${KEY_FILE}.pub" >> "${AUTHORIZED_KEYS}"

install -d -o root -g "${SERVICE_USER}" -m 0750 "$(dirname "${ENV_FILE}")"
if [[ ! -e "${ENV_FILE}" ]]; then
  install -o root -g "${SERVICE_USER}" -m 0640 "${REPO_DIR}/deploy/agent.env.example" "${ENV_FILE}"
fi
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}
set_env INFRA_AGENT_SSH_USERNAME "${TARGET_USER}"
set_env INFRA_AGENT_SSH_KEY "${KEY_FILE}"
set_env INFRA_AGENT_SSH_KNOWN_HOSTS "${KNOWN_HOSTS}"

if [[ "${COPY_OPENCODE}" -eq 1 ]]; then
  OPENCODE_SOURCE="$(find "${TARGET_HOME}/.nvm/versions/node" -path '*/@opencode/cli/bin/opencode.exe' -type f -perm -111 -print -quit 2>/dev/null || true)"
  OPENCODE_SERVICE_SOURCE="${TARGET_HOME}/.local/state/opencode/service.json"
  if [[ ! -x "${OPENCODE_SOURCE}" || ! -r "${OPENCODE_SERVICE_SOURCE}" ]]; then
    echo "Could not find the user's OpenCode binary or service metadata." >&2
    exit 1
  fi
  install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_DIR}/bin" \
    "${STATE_DIR}/.local/state/opencode"
  install -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0755 "${OPENCODE_SOURCE}" \
    "${STATE_DIR}/bin/opencode"
  install -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0600 "${OPENCODE_SERVICE_SOURCE}" \
    "${STATE_DIR}/.local/state/opencode/service.json"
  set_env INFRA_AGENT_AI_PROVIDER "opencode_cli"
  set_env INFRA_AGENT_AI_MODEL "opencode/beam-free"
  set_env INFRA_AGENT_OPENCODE_BIN "${STATE_DIR}/bin/opencode"
fi
chown root:"${SERVICE_USER}" "${ENV_FILE}"
chmod 640 "${ENV_FILE}"

systemctl restart infrastructure-agent.service
echo "Provisioned SSH credentials for ${SERVICE_USER}; system service restarted."
if [[ "${COPY_OPENCODE}" -eq 1 ]]; then
  echo "Local OpenCode was provisioned for the system service."
else
  echo "AI credentials were not changed. Configure ${ENV_FILE} if model review is not yet enabled."
fi
