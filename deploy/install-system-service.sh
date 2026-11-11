#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-$(pwd)}"
SERVICE_USER="infrastructure-agent"
STATE_DIR="/var/lib/${SERVICE_USER}"
ENV_DIR="/etc/${SERVICE_USER}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root, for example: sudo $0 /path/to/infrastructure-agent" >&2
  exit 1
fi
if [[ ! -f "${REPO_DIR}/pyproject.toml" ]]; then
  echo "Not an infrastructure-agent checkout: ${REPO_DIR}" >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${STATE_DIR}" --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 "${STATE_DIR}"
install -d -o root -g "${SERVICE_USER}" -m 0750 "${ENV_DIR}"

if [[ ! -x "${STATE_DIR}/.venv/bin/python" ]]; then
  UV_BIN="$(command -v uv || true)"
  if [[ -z "${UV_BIN}" && -x /home/kaos/.local/bin/uv ]]; then
    UV_BIN=/home/kaos/.local/bin/uv
  fi
  if [[ -n "${UV_BIN}" ]]; then
    "${UV_BIN}" venv --python python3 "${STATE_DIR}/.venv"
    "${UV_BIN}" pip install --python "${STATE_DIR}/.venv/bin/python" "${REPO_DIR}"
  else
    python3 -m venv "${STATE_DIR}/.venv"
    "${STATE_DIR}/.venv/bin/python" -m pip install --upgrade pip
    "${STATE_DIR}/.venv/bin/python" -m pip install "${REPO_DIR}"
  fi
else
  "${STATE_DIR}/.venv/bin/python" -m pip install "${REPO_DIR}"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}"

if [[ ! -e "${ENV_DIR}/agent.env" ]]; then
  install -o root -g "${SERVICE_USER}" -m 0640 "${REPO_DIR}/deploy/agent.env.example" "${ENV_DIR}/agent.env"
fi
install -o root -g root -m 0644 "${REPO_DIR}/deploy/infrastructure-agent.service" \
  /etc/systemd/system/infrastructure-agent.service

systemctl daemon-reload
systemctl enable --now infrastructure-agent.service
echo "Installed infrastructure-agent.service as ${SERVICE_USER}."
echo "Edit ${ENV_DIR}/agent.env and provision ${STATE_DIR}/.ssh before enabling remote actions."
