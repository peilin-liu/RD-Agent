#!/usr/bin/env bash
#
# Install RD-Agent user environment:
#   1. Sync config files from <repo>/config/ into ~/.rd-agent/ (never overwrite existing ones).
#   2. Install/refresh a *user-level* systemd service `rdagentd` that runs
#      `RUNNING_TIMEOUT_PERIOD=10800 python -m rdagent.app.cli server_ui`
#      from /data/qunant/rdagent_data (override with RDAGENT_RUN_DIR), loading
#      .env and writing relative runtime files there. Code stays in this repo.
#      Console output goes to ~/.local/state/rdagent/rdagent.log. No root required.
#      Set RDAGENT_PYTHON to select a specific environment's Python executable.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RD_AGENT_HOME="${RD_AGENT_HOME:-$HOME/.rd-agent}"
CONFIG_SRC="${SCRIPT_DIR}/config"
RDAGENT_RUN_DIR="${RDAGENT_RUN_DIR:-/data/qunant/rdagent_data}"

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/rdagent"
LOG_FILE="${LOG_DIR}/rdagent.log"
UNIT_NAME="rdagentd.service"
UNIT_PATH="${SYSTEMD_USER_DIR}/${UNIT_NAME}"

# --- resolve the environment's Python, avoiding stale rdagent shebangs -------
if [[ -n "${RDAGENT_PYTHON:-}" ]]; then
    RDAGENT_PYTHON="$(command -v "${RDAGENT_PYTHON}")"
elif command -v rdagent >/dev/null 2>&1; then
    RDAGENT_BIN="$(command -v rdagent)"
    RDAGENT_PYTHON="$(dirname "${RDAGENT_BIN}")/python"
elif [[ -x "${CONDA_PREFIX:-}/bin/rdagent" ]]; then
    RDAGENT_PYTHON="${CONDA_PREFIX}/bin/python"
else
    echo "ERROR: 'rdagent' not found on PATH (and CONDA_PREFIX/bin/rdagent missing)." >&2
    echo "       Activate the conda env that has rdagent installed, then re-run." >&2
    exit 1
fi
if [[ ! -x "${RDAGENT_PYTHON}" ]]; then
    echo "ERROR: Python executable not found: ${RDAGENT_PYTHON}" >&2
    exit 1
fi
# Keep the environment's bin directory for subprocesses, even when Python is a symlink.
RDAGENT_BIN_DIR="$(cd "$(dirname "${RDAGENT_PYTHON}")" && pwd)"
RDAGENT_PYTHON="${RDAGENT_BIN_DIR}/$(basename "${RDAGENT_PYTHON}")"

if [[ "${RDAGENT_RUN_DIR}" != /* ]]; then
    echo "ERROR: RDAGENT_RUN_DIR must be an absolute path." >&2
    exit 1
fi

echo "==> Using Python: ${RDAGENT_PYTHON}"
echo "==> rd-agent home: ${RD_AGENT_HOME}"
echo "==> Code directory: ${SCRIPT_DIR}"
echo "==> Runtime directory: ${RDAGENT_RUN_DIR}"
echo

# ============================================================================
# Part 1: sync config files into ~/.rd-agent/ (do not overwrite existing)
# ============================================================================
echo "==> [1/2] Syncing config files from ${CONFIG_SRC}"

if [[ ! -d "${CONFIG_SRC}" ]]; then
    echo "   WARN: config source dir not found at ${CONFIG_SRC}; skipping."
else
    mkdir -p "${RD_AGENT_HOME}"
    shopt -s nullglob dotglob
    synced=0
    for src in "${CONFIG_SRC}"/*; do
        [[ -f "${src}" ]] || continue
        name="$(basename "${src}")"
        dst="${RD_AGENT_HOME}/${name}"
        if [[ -e "${dst}" ]]; then
            echo "   - exists, kept: ${name}"
        else
            cp "${src}" "${dst}"
            echo "   + copied:      ${name}"
            synced=$((synced + 1))
        fi
    done
    echo "   Synced ${synced} new file(s); existing files were not modified."
fi
echo

# ============================================================================
# Part 2: install/refresh the user-level systemd service `rdagentd`
# ============================================================================
echo "==> [2/2] Setting up user systemd service ${UNIT_NAME}"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemctl not available; systemd is required." >&2
    exit 1
fi

mkdir -p "${SYSTEMD_USER_DIR}" "${LOG_DIR}" "${RDAGENT_RUN_DIR}"
if [[ ! -w "${RDAGENT_RUN_DIR}" ]]; then
    echo "ERROR: Runtime directory is not writable: ${RDAGENT_RUN_DIR}" >&2
    exit 1
fi

# systemd starts Python directly; make code imports and subprocess tools explicit.
UNIT_CONTENT="$(cat <<EOF
[Unit]
Description=RD-Agent server_ui (user-level)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
Environment=RUNNING_TIMEOUT_PERIOD=10800
Environment=PYTHONUNBUFFERED=1
Environment="PATH=${RDAGENT_BIN_DIR}:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
ExecStart="${RDAGENT_PYTHON}" -m rdagent.app.cli server_ui
WorkingDirectory=${RDAGENT_RUN_DIR}
Restart=on-failure
RestartSec=10
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=default.target
EOF
)"

if [[ -f "${UNIT_PATH}" ]]; then
    if [[ "$(cat "${UNIT_PATH}")" == "${UNIT_CONTENT}" ]]; then
        echo "   Unit already up to date; no rewrite needed."
    else
        printf '%s\n' "${UNIT_CONTENT}" > "${UNIT_PATH}"
        echo "   Updated existing unit: ${UNIT_PATH}"
    fi
else
    printf '%s\n' "${UNIT_CONTENT}" > "${UNIT_PATH}"
    echo "   Created unit: ${UNIT_PATH}"
fi
echo "   Log output: ${LOG_FILE}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT_NAME}"
# enable --now leaves an already-running service on its previous configuration.
systemctl --user restart "${UNIT_NAME}"

# So the service can run before login and survive logout:
if command -v loginctl >/dev/null 2>&1; then
    if loginctl show-user "${USER:-$(whoami)}" 2>/dev/null | grep -q '^Linger=yes'; then
        echo "   Lingering already enabled for ${USER:-$(whoami)}."
    else
        loginctl enable-linger "${USER:-$(whoami)}" 2>/dev/null \
            && echo "   Enabled lingering (service starts at boot, before login)." \
            || echo "   NOTE: could not enable lingering; start service manually after boot if needed."
    fi
fi

echo
echo "==> Done."
echo "    Service status:  systemctl --user status ${UNIT_NAME}"
echo "    Live log:        tail -f ${LOG_FILE}"
echo "    Stop/Restart:    systemctl --user {stop,restart} ${UNIT_NAME}"
