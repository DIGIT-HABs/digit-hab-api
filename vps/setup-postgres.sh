#!/usr/bin/env bash
# Installe PostgreSQL sur Ubuntu et crée la base Digit-Hab depuis /opt/apps/digit-hab-api/.env
# Usage: sudo bash setup-postgres.sh

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/apps/digit-hab-api/.env}"

if [[ $EUID -ne 0 ]]; then
  echo "Lancez avec sudo: sudo bash setup-postgres.sh"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Fichier .env introuvable: $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

DB_NAME="${DB_NAME:-digit_hab_crm_prod}"
DB_USER="${DB_USER:-digit_hab_crm_user}"
DB_PASSWORD="${DB_PASSWORD:?DB_PASSWORD manquant dans .env}"

echo "=== Installation PostgreSQL ==="
apt-get update -qq
apt-get install -y postgresql postgresql-contrib

systemctl enable --now postgresql

echo "=== Création utilisateur et base: $DB_NAME / $DB_USER ==="

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

# PostgreSQL 15+ : droits sur le schéma public
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};
SQL

echo "=== Test connexion ==="
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" -c 'SELECT version();' | head -n 3

echo
echo "OK. Vérifiez .env :"
echo "  DB_HOST=127.0.0.1"
echo "  DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod"
echo
echo "Puis (utilisateur deploy) :"
echo "  cd /opt/apps/digit-hab-api && source venv/bin/activate"
echo "  set -a && source .env && set +a"
echo "  python manage.py migrate --noinput"
echo "  python manage.py collectstatic --noinput"
echo "  sudo systemctl restart digit-hab-api.service"
