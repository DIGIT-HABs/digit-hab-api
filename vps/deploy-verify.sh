#!/usr/bin/env bash
# Diagnostic Digit-Hab API sur VPS (port 3004 + Caddy)
# Usage: sudo bash deploy-verify.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/apps/digit-hab-api}"
PORT="${PORT:-3004}"
DOMAIN="${DOMAIN:-api.digit-hab.wolofdigital.site}"

echo "=== Digit-Hab deploy verify ==="
echo "APP_DIR=$APP_DIR PORT=$PORT DOMAIN=$DOMAIN"
echo

echo "--- DNS ---"
dig +short "$DOMAIN" || true
echo

echo "--- systemd digit-hab-api ---"
systemctl is-active digit-hab-api.service 2>/dev/null || echo "service not found or inactive"
systemctl status digit-hab-api.service --no-pager -l 2>/dev/null | tail -n 15 || true
echo

echo "--- Last logs (digit-hab-api) ---"
journalctl -u digit-hab-api.service -n 40 --no-pager 2>/dev/null || true
echo

echo "--- Port $PORT ---"
ss -tlnp | grep ":$PORT " || echo "RIEN n'écoute sur $PORT → Gunicorn arrêté ou mauvais port"
echo

echo "--- Local HTTP ---"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:$PORT/health/" || echo "curl local FAILED"
echo

echo "--- Caddy ---"
systemctl is-active caddy 2>/dev/null || true
grep -n "digit-hab" /etc/caddy/Caddyfile 2>/dev/null || echo "bloc digit-hab absent du Caddyfile"
echo

echo "--- Public HTTPS ---"
curl -sS -o /dev/null -w "HTTPS %{http_code}\n" "https://$DOMAIN/health/" || echo "curl HTTPS FAILED (souvent: backend 3004 down ou cert ACME)"
echo

if [[ -f "$APP_DIR/.env" ]]; then
  echo "--- .env (clés présentes, sans valeurs) ---"
  grep -E '^[A-Z_]+=' "$APP_DIR/.env" | cut -d= -f1 | sort
fi

echo
echo "Test manuel Gunicorn (deploy user):"
echo "  sudo -u deploy bash -lc 'cd $APP_DIR && source venv/bin/activate && set -a && source .env && set +a && gunicorn digit_hab_crm.wsgi:application --bind 127.0.0.1:$PORT'"
