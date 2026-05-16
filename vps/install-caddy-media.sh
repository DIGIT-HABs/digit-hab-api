#!/usr/bin/env bash
# Ajoute le bloc Caddy pour servir /media/ (Digit-Hab API)
# Usage: sudo bash install-caddy-media.sh

set -euo pipefail

CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
DOMAIN="${DOMAIN:-api.digit-hab.wolofdigital.site}"
APP_DIR="${APP_DIR:-/opt/apps/digit-hab-api}"
MARKER="# digit-hab-media"

if [[ ! -f "$CADDYFILE" ]]; then
  echo "Caddyfile introuvable: $CADDYFILE"
  exit 1
fi

if grep -q "$MARKER" "$CADDYFILE"; then
  echo "Bloc media déjà présent ($MARKER)."
  exit 0
fi

if ! grep -q "$DOMAIN" "$CADDYFILE"; then
  echo "Domaine $DOMAIN absent de $CADDYFILE — ajoutez le site manuellement."
  exit 1
fi

BACKUP="${CADDYFILE}.bak.$(date +%Y%m%d%H%M%S)"
cp "$CADDYFILE" "$BACKUP"
echo "Sauvegarde: $BACKUP"

# Remplace le bloc site simple par handle media + reverse_proxy
python3 <<PY
from pathlib import Path
import re

path = Path("$CADDYFILE")
text = path.read_text(encoding="utf-8")
domain = "$DOMAIN"
app_dir = "$APP_DIR"
marker = "$MARKER"

block = f'''{domain} {{
\t{marker}
\thandle /media/* {{
\t\troot * {app_dir}
\t\tfile_server
\t}}
\thandle {{
\t\treverse_proxy 127.0.0.1:3004
\t}}
}}'''

pattern = re.compile(
    rf"{re.escape(domain)}\s*\{{[^{{}}]*\}}",
    re.DOTALL,
)
if not pattern.search(text):
    raise SystemExit(f"Impossible de trouver le bloc pour {domain}")

new_text, n = pattern.subn(block, text, count=1)
if n != 1:
    raise SystemExit("Remplacement du bloc Caddy échoué")
path.write_text(new_text, encoding="utf-8")
print("Caddyfile mis à jour.")
PY

caddy validate --config "$CADDYFILE"
systemctl reload caddy
echo "OK — test: curl -sI https://$DOMAIN/media/properties/images/image.jpg"
