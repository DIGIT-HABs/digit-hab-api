#!/usr/bin/env bash
# Dossier médias + permissions pour uploads (add_image)
# Usage: sudo bash setup-media.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/apps/digit-hab-api}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
MEDIA_DIR="${MEDIA_DIR:-$APP_DIR/media}"

mkdir -p "$MEDIA_DIR/properties/images" "$MEDIA_DIR/properties/thumbnails"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$MEDIA_DIR"
chmod -R u+rwX,g+rwX "$MEDIA_DIR"

echo "OK — $MEDIA_DIR (owner $DEPLOY_USER)"
ls -la "$MEDIA_DIR"
