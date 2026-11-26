#!/usr/bin/env bash
# One-time server setup for Ubuntu 22.04/24.04 (Oracle Cloud Always Free, Hetzner, any VPS).
# Run from the repo root:  bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
    say "Installing Docker"
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER" || true
fi
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# 2. Host firewall (Oracle Ubuntu images ship iptables rules that block 80/443)
if command -v iptables >/dev/null 2>&1; then
    say "Opening ports 80 and 443 in the host firewall"
    for port in 80 443; do
        sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
            || sudo iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
    done
    sudo iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null \
        || sudo iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT
    if command -v netfilter-persistent >/dev/null 2>&1; then
        sudo netfilter-persistent save
    fi
fi

# 3. .env with generated secrets
if [ ! -f .env ]; then
    say "Creating .env from .env.example"
    cp .env.example .env
fi
set_env() {  # set_env KEY VALUE  (replaces or appends)
    if grep -q "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}
current() { grep "^$1=" .env | head -1 | cut -d= -f2- || true; }

case "$(current CRM_JWT_SECRET)" in
    ""|change-this-in-production|vg-digital-falcon-dev-secret-change-in-prod)
        say "Generating CRM_JWT_SECRET"
        set_env CRM_JWT_SECRET "$(openssl rand -hex 32)" ;;
esac
case "$(current POSTGRES_PASSWORD)" in
    ""|change-me|scriptfalcon_local)
        say "Generating POSTGRES_PASSWORD"
        set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)" ;;
esac
set_env CRM_ENV production
chmod 600 .env

missing=()
[ -n "$(current DOMAIN)" ] || missing+=("DOMAIN (e.g. scriptfalcon.duckdns.org)")
key="$(current GEMINI_API_KEY)"
[ -n "$key" ] && [ "$key" != "your_gemini_api_key_here" ] || missing+=("GEMINI_API_KEY")
[ -n "$(current SCRIPTFALCON_CRM_USERS_JSON)" ] || missing+=("SCRIPTFALCON_CRM_USERS_JSON (run: bash deploy/add-user.sh)")
if [ ${#missing[@]} -gt 0 ]; then
    say "Edit .env and set:"
    printf '   - %s\n' "${missing[@]}"
    echo "Then run this script again."
    exit 1
fi

# 4. Daily database backup at 02:30
say "Installing daily Postgres backup cron job"
( crontab -l 2>/dev/null | grep -v 'deploy/backup.sh' ; echo "30 2 * * * cd $(pwd) && bash deploy/backup.sh >> backups/backup.log 2>&1" ) | crontab -

# 5. Start
say "Building and starting ScriptFalcon"
$DOCKER compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
$DOCKER compose -f docker-compose.yml -f docker-compose.prod.yml ps

say "Done. Open https://$(current DOMAIN) (first HTTPS certificate can take ~1 minute)."
