#!/usr/bin/env bash
# Corrige l'unité systemd si elle pointe encore vers config.wsgi (erreur courante au déploiement)
# Usage sur le VPS : sudo bash fix-systemd-unit.sh

set -euo pipefail

UNIT="/etc/systemd/system/digit-hab-api.service"
EXAMPLE_SOURCE="${EXAMPLE_SOURCE:-/opt/apps/digit-hab-api/Django/vps/systemd/digit-hab-api.service.example}"

if [[ ! -f "$UNIT" ]]; then
  echo "Fichier absent: $UNIT"
  if [[ -f "$EXAMPLE_SOURCE" ]]; then
    cp "$EXAMPLE_SOURCE" "$UNIT"
    echo "Copié depuis $EXAMPLE_SOURCE"
  else
    echo "Copiez manuellement Django/vps/systemd/digit-hab-api.service.example"
    exit 1
  fi
fi

cp "$UNIT" "${UNIT}.bak.$(date +%Y%m%d%H%M%S)"

sed -i 's/config\.wsgi:application/digit_hab_crm.wsgi:application/g' "$UNIT"
sed -i 's/DJANGO_SETTINGS_MODULE=config\.settings/DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod/g' "$UNIT"

if ! grep -q 'digit_hab_crm.wsgi:application' "$UNIT"; then
  echo "ERREUR: ExecStart ne contient pas digit_hab_crm.wsgi:application — éditez $UNIT à la main"
  exit 1
fi

if ! grep -q 'DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod' "$UNIT"; then
  if grep -q '^Environment=DJANGO_SETTINGS_MODULE=' "$UNIT"; then
    sed -i 's/^Environment=DJANGO_SETTINGS_MODULE=.*/Environment=DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod/' "$UNIT"
  else
    sed -i '/^WorkingDirectory=/a Environment=DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod' "$UNIT"
  fi
fi

if ! grep -q 'EnvironmentFile=-/opt/apps/digit-hab-api/.env' "$UNIT"; then
  sed -i '/^Environment=DJANGO_SETTINGS_MODULE=/a EnvironmentFile=-/opt/apps/digit-hab-api/.env' "$UNIT"
fi

systemctl daemon-reload
systemctl restart digit-hab-api.service
sleep 2
systemctl status digit-hab-api.service --no-pager -l | tail -n 20

echo
echo "Test:"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:3004/health/ || true
