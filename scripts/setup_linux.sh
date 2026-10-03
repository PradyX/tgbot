#!/usr/bin/env bash
#
# tgbot — interactive Linux server setup
#
# Walks you through installing and configuring the bot on a fresh Linux server:
# dependencies, virtualenv, database (PostgreSQL or SQLite), configuration
# (env vars or config.py), and an optional systemd service.
#
# Usage:
#   ./scripts/setup_linux.sh            # interactive install
#   ./scripts/setup_linux.sh --dry-run  # show what would be done, change nothing
#
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# ---------------------------------------------------------------- output helpers
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
die()   { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# run a shell command (skipped in dry-run mode)
sh_run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo -e "${YELLOW}[dry-run]${NC} $*"
    else
        bash -c "$*"
    fi
}

# prompt helpers: ask "question" "default" -> $REPLY (default returned on empty input)
ask() {
    local q="$1" d="${2:-}"
    if [[ -n "$d" ]]; then
        read -rp "$q [$d]: " REPLY || die "input closed (EOF) - exiting"
        REPLY="${REPLY:-$d}"
    else
        read -rp "$q: " REPLY || die "input closed (EOF) - exiting"
    fi
}

ask_secret() {
    local q="$1"
    read -rsp "$q: " REPLY || die "input closed (EOF) - exiting"
    echo
}

ask_yn() {
    local q="$1" d="${2:-n}" y n
    if [[ "$d" == "y" ]]; then y="Y"; n="n"; else y="y"; n="N"; fi
    read -rp "$q [$y/$n]: " REPLY || die "input closed (EOF) - exiting"
    REPLY="${REPLY:-$d}"
    [[ "$REPLY" =~ ^[Yy] ]]
}

# strip characters that would break the generated python/shell literals
sanitize() { printf '%s' "$1" | tr -d '"\\$`'; }

gen_password() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 12
    else
        head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

# ---------------------------------------------------------------- preflight
echo
echo "=============================================="
echo "  tgbot — Linux server setup"
echo "=============================================="
echo

[[ $DRY_RUN -eq 1 ]] && warn "DRY RUN: nothing on this system will be modified."

if [[ "$(uname -s)" != "Linux" && $DRY_RUN -eq 0 ]]; then
    die "This installer targets Linux servers. Use --dry-run to preview it elsewhere."
fi

info "Repository: $REPO_DIR"

# python 3.10+
PYTHON_BIN=""
for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PYTHON_BIN="$cand"
        break
    fi
done
[[ -n "$PYTHON_BIN" ]] || die "Python 3.10+ is required. Install it first (e.g. sudo apt install python3 python3-venv)."
ok "Using $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

if [[ $DRY_RUN -eq 0 ]] && ! "$PYTHON_BIN" -c 'import venv' 2>/dev/null; then
    warn "python venv module missing."
    if command -v apt-get >/dev/null 2>&1; then
        sh_run "sudo apt-get update && sudo apt-get install -y python3-venv python3-pip"
    else
        die "Install python3-venv / python3-pip with your package manager, then re-run."
    fi
fi

# ---------------------------------------------------------------- bot configuration
echo
info "--- Bot configuration (from @BotFather / @userinfobot) ---"

BOT_TOKEN=""
while [[ -z "$BOT_TOKEN" ]]; do
    ask_secret "Bot token (from @BotFather)"
    BOT_TOKEN="$(sanitize "$REPLY")"
    [[ -z "$BOT_TOKEN" ]] && warn "Token cannot be empty."
done

OWNER_ID=""
while [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]]; do
    ask "Your Telegram user ID (numeric, from @userinfobot)"
    OWNER_ID="$(sanitize "$REPLY")"
    [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]] && warn "Owner ID must be a number."
done

ask "Your Telegram username (without @)" "owner"
OWNER_USERNAME="$(sanitize "$REPLY")"

ask "Sudo users (space-separated user IDs, blank = just you)" "$OWNER_ID"
SUDO_USERS="$(sanitize "$REPLY")"

ask "Support users (can gban/ungban, space-separated IDs)" ""
SUPPORT_USERS="$(sanitize "$REPLY")"

ask "Whitelisted users (immune to bans, space-separated IDs)" ""
WHITELIST_USERS="$(sanitize "$REPLY")"

# ---------------------------------------------------------------- database
echo
info "--- Database ---"
echo "  1) PostgreSQL (recommended for production)"
echo "  2) SQLite (fine for small/dev deployments)"
DB_CHOICE="1"
ask "Choose database" "1"
DB_CHOICE="$REPLY"

DB_URI=""
if [[ "$DB_CHOICE" == "1" ]]; then
    if ask_yn "Install PostgreSQL on this server?" "y"; then
        INSTALL_PG="y"
    else
        INSTALL_PG="n"
    fi
    ask "Postgres host" "localhost"
    PG_HOST="$(sanitize "$REPLY")"
    ask "Postgres port" "5432"
    PG_PORT="$(sanitize "$REPLY")"
    ask "Database name" "tgbot"
    PG_DB="$(sanitize "$REPLY")"
    ask "Database user" "tgbot"
    PG_USER="$(sanitize "$REPLY")"
    if ask_yn "Generate a strong database password?" "y"; then
        PG_PASS="$(gen_password)"
        info "Generated password: $PG_PASS"
    else
        ask_secret "Database password"
        PG_PASS="$(sanitize "$REPLY")"
    fi
    DB_URI="postgresql://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${PG_DB}"

    if [[ "$INSTALL_PG" == "y" ]]; then
        info "Installing PostgreSQL and creating the database..."
        sh_run "sudo apt-get update && sudo apt-get install -y postgresql"
        sh_run "sudo -u postgres psql -c \"CREATE USER ${PG_USER} WITH PASSWORD '${PG_PASS}';\""
        sh_run "sudo -u postgres psql -c \"CREATE DATABASE ${PG_DB} OWNER ${PG_USER};\""
    else
        info "Skipping Postgres install — make sure '${PG_DB}' and '${PG_USER}' exist on ${PG_HOST}."
    fi
else
    ask "SQLite database file path" "$REPO_DIR/tgbot.db"
    DB_URI="sqlite:///$REPLY"
fi

# ---------------------------------------------------------------- options
echo
info "--- Options ---"
ask_yn "Allow '!' as an alternative command prefix? (ALLOW_EXCL)" "n" && ALLOW_EXCL="True" || ALLOW_EXCL="False"
ask_yn "Enforce gbans in newly joined groups? (STRICT_GBAN)" "n" && STRICT_GBAN="True" || STRICT_GBAN="False"
ask_yn "Ban users flagged by CAS antispam? (USE_CAS)" "n" && USE_CAS="True" || USE_CAS="False"
ask_yn "Delete command messages from unauthorized users? (DEL_CMDS)" "n" && DEL_CMDS="True" || DEL_CMDS="False"
ask "Modules to NOT load (space-separated)" "translation rss sed"
NO_LOAD="$(sanitize "$REPLY")"
ask "Worker threads (WORKERS)" "8"
WORKERS="$(sanitize "$REPLY")"

# ---------------------------------------------------------------- config mode
echo
info "--- Configuration style ---"
echo "  1) Environment file (.env) + systemd  [recommended on servers]"
echo "  2) tg_bot/config.py                    [classic]"
ask "Choose style" "1"
CFG_CHOICE="$REPLY"

if [[ "$CFG_CHOICE" == "2" ]]; then
    CONFIG_MODE="config"
    ENV_FILE=""
else
    CONFIG_MODE="env"
    ENV_FILE="$REPO_DIR/.env"
fi

# space-separated user id lists -> python list literals (1 2 3 -> 1,2,3)
py_list() { tr ' ' ',' <<< "$(xargs <<< "$1")"; }
PY_SUDO_USERS="$(py_list "$SUDO_USERS")"
PY_SUPPORT_USERS="$(py_list "$SUPPORT_USERS")"
PY_WHITELIST_USERS="$(py_list "$WHITELIST_USERS")"

# ---------------------------------------------------------------- install
echo
info "--- Installing ---"

sh_run "cd '$REPO_DIR' && $PYTHON_BIN -m venv .venv"
sh_run "'$REPO_DIR/.venv/bin/pip' install --upgrade pip"
sh_run "'$REPO_DIR/.venv/bin/pip' install -r '$REPO_DIR/requirements.txt'"
ok "Python dependencies installed."

if [[ "$CONFIG_MODE" == "env" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
        echo -e "${YELLOW}[dry-run]${NC} write $ENV_FILE (with the values you entered)"
    else
        cat > "$ENV_FILE" <<EOF
ENV=1
TOKEN=${BOT_TOKEN}
OWNER_ID=${OWNER_ID}
OWNER_USERNAME=${OWNER_USERNAME}
DATABASE_URL=${DB_URI}
SUDO_USERS="${SUDO_USERS}"
SUPPORT_USERS="${SUPPORT_USERS}"
WHITELIST_USERS="${WHITELIST_USERS}"
NO_LOAD="${NO_LOAD}"
ALLOW_EXCL=${ALLOW_EXCL}
STRICT_GBAN=${STRICT_GBAN}
USE_CAS=${USE_CAS}
DEL_CMDS=${DEL_CMDS}
WORKERS=${WORKERS}
EOF
        chmod 600 "$ENV_FILE"
    fi
    ok "Wrote $ENV_FILE (permissions 600)."
else
    if [[ $DRY_RUN -eq 1 ]]; then
        echo -e "${YELLOW}[dry-run]${NC} write $REPO_DIR/tg_bot/config.py (with the values you entered)"
    else
        cat > "$REPO_DIR/tg_bot/config.py" <<EOF
from tg_bot.sample_config import Config


class Development(Config):
    API_KEY = "${BOT_TOKEN}"
    OWNER_ID = ${OWNER_ID}
    OWNER_USERNAME = "${OWNER_USERNAME}"
    SQLALCHEMY_DATABASE_URI = '${DB_URI}'
    SUDO_USERS = [${PY_SUDO_USERS}]
    SUPPORT_USERS = [${PY_SUPPORT_USERS}]
    WHITELIST_USERS = [${PY_WHITELIST_USERS}]
    NO_LOAD = '$NO_LOAD'.split()
    ALLOW_EXCL = ${ALLOW_EXCL}
    STRICT_GBAN = ${STRICT_GBAN}
    USE_CAS = ${USE_CAS}
    DEL_CMDS = ${DEL_CMDS}
    WORKERS = ${WORKERS}
EOF
        chmod 600 "$REPO_DIR/tg_bot/config.py"
    fi
    ok "Wrote tg_bot/config.py (permissions 600)."
fi

# ---------------------------------------------------------------- smoke test
echo
info "--- Smoke test (loads every module; expects an InvalidToken at the end) ---"
if [[ $DRY_RUN -eq 1 ]]; then
    echo -e "${YELLOW}[dry-run]${NC} run 'python -m tg_bot' for 12s and check the startup log"
else
    SMOKE_LOG="$(mktemp)"
    ( cd "$REPO_DIR" && .venv/bin/python -m tg_bot ) > "$SMOKE_LOG" 2>&1 &
    SMOKE_PID=$!
    sleep 12
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true
    if grep -q "Successfully loaded modules" "$SMOKE_LOG"; then
        ok "All modules loaded successfully."
        if grep -q "InvalidToken" "$SMOKE_LOG"; then
            warn "Telegram rejected the token — double-check it if this is unexpected."
        fi
    else
        warn "Startup did not complete — last lines of the log:"
        tail -n 15 "$SMOKE_LOG"
    fi
    rm -f "$SMOKE_LOG"
fi

# ---------------------------------------------------------------- systemd
echo
if ask_yn "Install and start a systemd service (tgbot.service)?" "y"; then
    SERVICE_USER="$(id -un)"
    ENV_LINE=""
    [[ "$CONFIG_MODE" == "env" ]] && ENV_LINE="EnvironmentFile=${ENV_FILE}"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo -e "${YELLOW}[dry-run]${NC} write /etc/systemd/system/tgbot.service and enable it"
    else
        sudo tee /etc/systemd/system/tgbot.service > /dev/null <<EOF
[Unit]
Description=tgbot telegram bot
After=network.target postgresql.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_DIR}
${ENV_LINE}
ExecStart=${REPO_DIR}/.venv/bin/python -m tg_bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable --now tgbot
    fi
    ok "Service 'tgbot' installed and started."
    echo
    info "Useful commands:"
    echo "    sudo systemctl status tgbot"
    echo "    sudo journalctl -u tgbot -f"
else
    info "Start the bot manually with:"
    echo "    cd $REPO_DIR && .venv/bin/python -m tg_bot"
fi

echo
ok "Setup complete. Message your bot /start, add it to a group and promote it as admin."
