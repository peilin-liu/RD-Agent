#!/usr/bin/env bash
#
# Install RD-Agent user environment:
#   1. Sync config files from <repo>/config/ into ~/.rd-agent/ (never overwrite existing ones).
#   2. Install/refresh a *user-level* systemd service `rdagentd` that runs
#      `RUNNING_TIMEOUT_PERIOD=10800 rdagent server_ui`, logging to
#      ~/.local/state/rdagent/rdagent.log. No root required.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RD_AGENT_HOME="${RD_AGENT_HOME:-$HOME/.rd-agent}"
CONFIG_SRC="${SCRIPT_DIR}/config"

SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/rdagent"
LOG_FILE="${LOG_DIR}/rdagent.log"
UNIT_NAME="rdagentd.service"
UNIT_PATH="${SYSTEMD_USER_DIR}/${UNIT_NAME}"

# --- resolve absolute path to the rdagent executable -------------------------
if command -v rdagent >/dev/null 2>&1; then
    RDAGENT_BIN="$(command -v rdagent)"
elif [[ -x "${CONDA_PREFIX:-}/bin/rdagent" ]]; then
    RDAGENT_BIN="${CONDA_PREFIX}/bin/rdagent"
else
    echo "ERROR: 'rdagent' not found on PATH (and CONDA_PREFIX/bin/rdagent missing)." >&2
    echo "       Activate the conda env that has rdagent installed, then re-run." >&2
    exit 1
fi
RDAGENT_BIN="$(readlink -f "${RDAGENT_BIN}")"

echo "==> Using rdagent: ${RDAGENT_BIN}"
echo "==> rd-agent home: ${RD_AGENT_HOME}"
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

mkdir -p "${SYSTEMD_USER_DIR}" "${LOG_DIR}"

# Resolve login shell for the service user (systemd Type=simple runs the command
# directly; ExecStart is an absolute path, so no shell profile is loaded).
UNIT_CONTENT="[Unit]
Description=RD-Agent server_ui (user-level)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=RUNNING_TIMEOUT_PERIOD=10800
ExecStart=${RDAGENT_BIN} server_ui
WorkingDirectory=${HOME}
Restart=on-failure
RestartSec=5
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=default.target
"

if [[ -f "${UNIT_PATH}" ]]; then
    if [[ "$(cat "${UNIT_PATH}")" == "${UNIT_CONTENT}" ]]; then
        echo "   Unit already up to date; no rewrite needed."
    else
        printf '%s' "${UNIT_CONTENT}" > "${UNIT_PATH}"
        echo "   Updated existing unit: ${UNIT_PATH}"
    fi
else
    printf '%s' "${UNIT_CONTENT}" > "${UNIT_PATH}"
    echo "   Created unit: ${UNIT_PATH}"
fi
echo "   Log output: ${LOG_FILE}"

systemctl --user daemon-reload
systemctl --user enable --now "${UNIT_NAME}"

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