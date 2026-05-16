# Déployer l’API Django Digit-Hab sur le même VPS que Wolof WiFi Pay

**Domaine public :** `https://api.digit-hab.wolofdigital.site`  
**Port local (Gunicorn) :** `127.0.0.1:3004` (Caddy fait le HTTPS et le reverse proxy).

Wolof WiFi Pay reste sur **3001** ; Digit-Hab utilise **3004** pour éviter tout conflit.

**Dépôt :** [DIGIT-HABs/digit-hab-api](https://github.com/DIGIT-HABs/digit-hab-api)  
**WSGI :** `digit_hab_crm.wsgi:application` (pas `config.wsgi`)  
**Settings prod :** `digit_hab_crm.settings.prod`  
L’ancien VPS utilisait **Docker Compose** (Postgres + Redis + Gunicorn). Sans Postgres/Redis, Gunicorn plante → `Connection refused` sur 3004.

## Dépannage rapide (`Connection refused` sur 3004)

```bash
sudo systemctl status digit-hab-api.service --no-pager
sudo journalctl -u digit-hab-api.service -n 80 --no-pager
sudo ss -tlnp | grep 3004
```

Causes fréquentes :

1. **Service arrêté ou en échec** → lire `journalctl` (mauvais module WSGI, DB, Redis).
2. **`config.wsgi` dans l’unité** → erreur exacte : `ModuleNotFoundError: No module named 'config'`.  
   Corriger :

```bash
sudo sed -i 's/config\.wsgi:application/digit_hab_crm.wsgi:application/g' /etc/systemd/system/digit-hab-api.service
sudo sed -i 's/DJANGO_SETTINGS_MODULE=config\.settings/DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod/g' /etc/systemd/system/digit-hab-api.service
# ou : sudo bash /opt/apps/digit-hab-api/Django/vps/fix-systemd-unit.sh
sudo systemctl daemon-reload
sudo systemctl restart digit-hab-api.service
curl -I http://127.0.0.1:3004/health/
```
3. **Pas de PostgreSQL / Redis** → voir § Docker (recommandé) ou installer Postgres + Redis et mettre `DB_HOST=127.0.0.1` dans `.env`.
4. **HTTPS `tlsv1 alert internal error`** → souvent Caddy sans backend ; corriger d’abord le port 3004, puis `sudo systemctl reload caddy`.

Test manuel (utilisateur `deploy`) :

```bash
sudo -u deploy bash -lc '
  cd /opt/apps/digit-hab-api
  source venv/bin/activate
  export DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod
  set -a && source .env && set +a
  gunicorn digit_hab_crm.wsgi:application --bind 127.0.0.1:3004
'
```

Si ça affiche une erreur Django/DB, c’est la même cause que systemd.

## 1. DNS

Chez votre registrar, créez un enregistrement **A** :

| Nom | Type | Valeur |
|-----|------|--------|
| `api.digit-hab` (zone `wolofdigital.site`) | A | IP du VPS (la même que `wifi.wolofdigital.site`) |

Vérifiez : `dig +short api.digit-hab.wolofdigital.site`

## 2. Caddy (sur le VPS)

Ajoutez le bloc (déjà dans `infra/vps/caddy/Caddyfile` du dépôt) :

```caddy
api.digit-hab.wolofdigital.site {
	reverse_proxy 127.0.0.1:3004
}
```

Puis :

Depuis le dépôt **DIGIT-HAB CRM** (dossier `Django/vps/caddy/Caddyfile`) :

```bash
# Fusionner à la main dans /etc/caddy/Caddyfile, ou :
sudo cp /opt/apps/digit-hab-api/Django/vps/caddy/Caddyfile /etc/caddy/Caddyfile
# (selon où vous avez cloné le repo CRM)

sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Si HTTPS échoue alors que le port 3004 répond : `sudo journalctl -u caddy -n 50` (certificat ACME / DNS).

## 3. Code Django sur le VPS

```bash
sudo mkdir -p /opt/apps/digit-hab-api
sudo chown deploy:deploy /opt/apps/digit-hab-api
```

**Depuis l’autre VPS** (rsync) ou **depuis Git** :

```bash
sudo -u deploy bash -lc '
  cd /opt/apps
  git clone https://github.com/DIGIT-HABs/digit-hab-api.git digit-hab-api
  cd digit-hab-api
  python3 -m venv venv
  source venv/bin/activate
  pip install -U pip wheel
  pip install -r requirements.txt gunicorn
'
```

## 3b. Option recommandée — Docker Compose (comme l’ancien VPS)

Sur l’ancien serveur le projet tournait avec `docker-compose.prod.yml` (web sur **8001**). Sur ce VPS :

```bash
cd /opt/apps/digit-hab-api
# .env avec SECRET_KEY, DB_PASSWORD, REDIS_PASSWORD, ALLOWED_HOSTS, etc.
# Voir Django/vps/.env.example
sudo -u deploy docker compose -f docker-compose.prod.yml -f docker-compose.vps.yml up -d --build
```

Le fichier `docker-compose.vps.yml` mappe **127.0.0.1:3004 → 8000** (aligné avec Caddy).  
Pas besoin de `digit-hab-api.service` systemd si tout est dans Docker.

Test : `curl -I http://127.0.0.1:3004/health/`

## 4. Fichier `.env` Django (systemd sans Docker)

```bash
sudo -u deploy nano /opt/apps/digit-hab-api/.env
sudo chmod 600 /opt/apps/digit-hab-api/.env
```

Exemple (à adapter) :

```env
DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=api.digit-hab.wolofdigital.site,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://api.digit-hab.wolofdigital.site
DB_NAME=digit_hab_crm_prod
DB_USER=digit_hab_crm_user
DB_PASSWORD=...
DB_HOST=127.0.0.1
DB_PORT=5432
REDIS_URL=redis://:MOT_DE_PASSE_REDIS@127.0.0.1:6379/0
CELERY_BROKER_URL=redis://:MOT_DE_PASSE_REDIS@127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://:MOT_DE_PASSE_REDIS@127.0.0.1:6379/0
```

Puis migrations et fichiers statiques :

```bash
sudo -u deploy bash -lc '
  cd /opt/apps/digit-hab-api
  source venv/bin/activate
  set -a && source .env && set +a
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
'
```

## 5. systemd (Gunicorn)

```bash
sudo cp /opt/apps/digit-hab-api/Django/vps/systemd/digit-hab-api.service.example \
  /etc/systemd/system/digit-hab-api.service
sudo nano /etc/systemd/system/digit-hab-api.service
```

Script de diagnostic sur le VPS :

```bash
sudo bash /opt/apps/digit-hab-api/Django/vps/deploy-verify.sh
```

Vérifiez surtout :

- `WorkingDirectory=/opt/apps/digit-hab-api`
- `ExecStart=.../gunicorn digit_hab_crm.wsgi:application --bind 127.0.0.1:3004 ...`
- `Environment=DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod`

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now digit-hab-api.service
sudo systemctl status digit-hab-api.service --no-pager
```

Test local :

```bash
curl -I http://127.0.0.1:3004/
curl -I https://api.digit-hab.wolofdigital.site/
```

Logs : `sudo journalctl -u digit-hab-api.service -f`

## 6. Mise à jour (comme sur l’autre VPS)

```bash
sudo -u deploy bash -lc '
  cd /opt/apps/digit-hab-api
  git pull
  source venv/bin/activate
  pip install -r requirements.txt
  set -a && source .env && set +a
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
'
sudo systemctl restart digit-hab-api.service
```

## 7. Reprendre la config de l’ancien VPS

Si l’API tourne déjà ailleurs, sur **l’ancien serveur** notez :

- Chemin du projet et commande Gunicorn/uWSGI (`systemctl cat …`)
- Variables `.env` / base PostgreSQL
- Version Python (`python3 --version`)

Copiez le dépôt + `.env` (sans le commiter), recréez le venv sur ce VPS, puis utilisez le port **3004** et le domaine ci-dessus. Si la base reste sur l’ancien VPS, ouvrez le pare-feu PostgreSQL ou migrez la DB vers ce VPS.

## 8. Option PostgreSQL / Redis sur le même VPS

Si Digit-Hab utilisait Docker sur l’autre machine, vous pouvez lancer les mêmes services en local (ports non exposés publiquement) ou un conteneur :

```bash
# Exemple : Postgres uniquement en local
# DATABASE_URL=postgres://user:pass@127.0.0.1:5432/digit_hab
```

Ne exposez pas Postgres sur `0.0.0.0` ; l’app Django se connecte en `127.0.0.1`.

## Récap des ports sur ce VPS

| Port | Service |
|------|---------|
| 3001 | Wolof WiFi Pay (Node) |
| 3002 | wolof Sign |
| 3003 | e-wolof |
| **3004** | **Digit-Hab API (Django)** |
| 443 | Caddy (HTTPS public) |
