# Guide de Déploiement Manuel - DIGIT-HAB CRM avec AL-TOPPE

## 📋 Prérequis

- ✅ Serveur VPS avec Ubuntu
- ✅ AL-TOPPE déjà déployé sur `/var/www/al-toppe`
- ✅ Docker et Docker Compose installés
- ✅ Accès root ou sudo
- ✅ DNS configurés
sudo -u deploy bash -lc '
  cd /opt/apps/digit-hab-api
  source venv/bin/activate
  set -a && source .env && set +a
  python create_test_data_prod.py
'
---

## 🌐 Étape 1 : Configuration DNS

Ajoutez ces enregistrements dans votre panneau DNS :

```
Type    Nom              Valeur                          TTL
──────────────────────────────────────────────────────────────
A       digit-hab        72.60.189.237                  3600
AAAA    digit-hab        2a02:4780:28:d4f7::1           3600
A       api.digit-hab    72.60.189.237                  3600
AAAA    api.digit-hab    2a02:4780:28:d4f7::1           3600
```

### Vérification

```bash
# Attendre 5-10 minutes, puis :
dig digit-hab.altoppe.sn +short
# Devrait retourner : 72.60.189.237

dig api.digit-hab.altoppe.sn +short
# Devrait retourner : 72.60.189.237
```

---

## 📁 Étape 2 : Préparation des Dossiers

```bash
# Créer le dossier webroot pour Certbot
sudo mkdir -p /var/www/certbot
sudo chown -R $USER:$USER /var/www/certbot

# Créer les dossiers static/media pour DIGIT-HAB
sudo mkdir -p /var/www/digit-hab-crm/staticfiles
sudo mkdir -p /var/www/digit-hab-crm/media
sudo chown -R $USER:$USER /var/www/digit-hab-crm/staticfiles
sudo chown -R $USER:$USER /var/www/digit-hab-crm/media
```

---

## 🔧 Étape 3 : Backup de la Config AL-TOPPE

```bash
cd /var/www/al-toppe

# Backup de la config Nginx
cp nginx.prod.conf nginx.prod.conf.backup.$(date +%Y%m%d_%H%M%S)

# Backup du docker-compose
cp docker-compose.prod.yml docker-compose.prod.yml.backup.$(date +%Y%m%d_%H%M%S)
```

---

## 📝 Étape 4 : Modifier nginx.prod.conf d'AL-TOPPE

Ouvrez `/var/www/al-toppe/nginx.prod.conf` et modifiez :

### 4.1 - Modifier le server block HTTP (port 80)

Remplacer :

```nginx
server {
    listen 80;
    server_name altoppe.sn www.altoppe.sn api.altoppe.sn;
    return 301 https://$server_name$request_uri;
}
```

Par :

```nginx
server {
    listen 80;
    server_name altoppe.sn www.altoppe.sn api.altoppe.sn digit-hab.altoppe.sn api.digit-hab.altoppe.sn;
    
    # Webroot pour Certbot
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    
    # Redirection HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}
```

---

## 🐳 Étape 5 : Modifier docker-compose.prod.yml d'AL-TOPPE

Ouvrez `/var/www/al-toppe/docker-compose.prod.yml` et modifiez le service `nginx` :

```yaml
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx.prod.conf:/etc/nginx/nginx.conf:ro
    - ./staticfiles:/var/www/al-toppe/staticfiles:ro
    - ./media:/var/www/al-toppe/media:ro
    - ./ssl:/etc/nginx/ssl:ro
    # ✅ AJOUTS pour DIGIT-HAB
    - /var/www/digit-hab-crm/staticfiles:/var/www/digit-hab-crm/staticfiles:ro
    - /var/www/digit-hab-crm/media:/var/www/digit-hab-crm/media:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro
    - /var/www/certbot:/var/www/certbot:ro
  depends_on:
    - web
  networks:
    - app-network
  restart: unless-stopped
  # ✅ AJOUT : Communication avec l'hôte
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

---

## 🔄 Étape 6 : Redémarrer Nginx d'AL-TOPPE

```bash
cd /var/www/al-toppe
docker compose -f docker-compose.prod.yml restart nginx

# Vérifier
docker ps | grep nginx
docker compose -f docker-compose.prod.yml logs nginx
```

---

## 🔒 Étape 7 : Obtenir les Certificats SSL

```bash
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d digit-hab.altoppe.sn \
  -d api.digit-hab.altoppe.sn \
  --email souleymane9700@gmail.com \
  --agree-tos \
  --non-interactive

# Vérifier
sudo ls -la /etc/letsencrypt/live/digit-hab.altoppe.sn/
```

---

## 📝 Étape 8 : Ajouter le Server Block DIGIT-HAB dans Nginx

Ouvrez `/var/www/al-toppe/nginx.prod.conf` et **ajoutez à la fin du bloc `http {}`** (avant le dernier `}`) :

```nginx
    # ════════════════════════════════════════════════════════
    # DIGIT-HAB CRM - HTTPS SERVER
    # ════════════════════════════════════════════════════════
    
    upstream digit_hab_backend {
        server host.docker.internal:8001;
    }
    
    server {
        listen 443 ssl;
        server_name digit-hab.altoppe.sn api.digit-hab.altoppe.sn;

        # SSL configuration
        ssl_certificate /etc/letsencrypt/live/digit-hab.altoppe.sn/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/digit-hab.altoppe.sn/privkey.pem;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;

        # Security headers
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        client_max_body_size 20M;

        # Logs séparés
        access_log /var/log/nginx/digit-hab-access.log main;
        error_log /var/log/nginx/digit-hab-error.log warn;

        # Static files
        location /static/ {
            alias /var/www/digit-hab-crm/staticfiles/;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }

        location /media/ {
            alias /var/www/digit-hab-crm/media/;
            expires 30d;
            add_header Cache-Control "public";
        }

        # API endpoints
        location /api/ {
            limit_req zone=api burst=80 nodelay;

            # CORS pour OPTIONS
            if ($request_method = 'OPTIONS') {
                add_header 'Access-Control-Allow-Origin' "$http_origin";
                add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
                add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-CSRFToken, X-Requested-With';
                add_header 'Access-Control-Allow-Credentials' 'true';
                add_header 'Access-Control-Max-Age' 86400;
                add_header 'Content-Length' 0;
                add_header 'Content-Type' 'text/plain; charset=utf-8';
                return 204;
            }

            proxy_pass http://digit_hab_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Admin
        location /admin/ {
            proxy_pass http://digit_hab_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # API Docs
        location /api/docs/ {
            proxy_pass http://digit_hab_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Health Check
        location /health/ {
            proxy_pass http://digit_hab_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            access_log off;
        }

        # Root redirect
        location = / {
            return 301 /api/docs/;
        }

        # Default
        location / {
            if ($request_method = 'OPTIONS') {
                add_header 'Access-Control-Allow-Origin' "$http_origin";
                add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
                add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-CSRFToken, X-Requested-With';
                add_header 'Access-Control-Allow-Credentials' 'true';
                add_header 'Access-Control-Max-Age' 86400;
                add_header 'Content-Length' 0;
                add_header 'Content-Type' 'text/plain; charset=utf-8';
                return 204;
            }

            proxy_pass http://digit_hab_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
```

---

## 🔄 Étape 9 : Redémarrer Nginx avec la Nouvelle Config

```bash
cd /var/www/al-toppe
docker compose -f docker-compose.prod.yml restart nginx

# Vérifier les logs
docker compose -f docker-compose.prod.yml logs nginx
```

---

## 🚀 Étape 10 : Déployer DIGIT-HAB CRM

### 10.1 - Copier les Fichiers

```bash
cd /var/www/digit-hab-crm

# Si vous avez copié via rsync/scp, sinon clonez depuis Git
# rsync -avz --exclude 'venv' --exclude '__pycache__' /local/path/ /var/www/digit-hab-crm/
```

### 10.2 - Configurer .env

```bash
nano /var/www/digit-hab-crm/.env
```

**Contenu minimum pour production** :

```env
# Django
DEBUG=False
SECRET_KEY=your-very-long-secret-key-change-this-in-production-12345
DJANGO_SETTINGS_MODULE=digit_hab_crm.settings.prod

# Allowed Hosts
ALLOWED_HOSTS=digit-hab.altoppe.sn,api.digit-hab.altoppe.sn,localhost,127.0.0.1

# Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=digit_hab_prod
DB_USER=digit_hab_user
DB_PASSWORD=votre-mot-de-passe-fort-ici
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_URL=redis://:digit-hab-redis-password@redis:6379/0
REDIS_PASSWORD=digit-hab-redis-password

# Celery
CELERY_BROKER_URL=redis://:digit-hab-redis-password@redis:6379/0
CELERY_RESULT_BACKEND=redis://:digit-hab-redis-password@redis:6379/0

# Email (à configurer selon votre SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-password

# Security
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### 10.3 - Modifier docker-compose.prod.yml

Assurez-vous que le service `web` expose le port `8001` :

```yaml
services:
  # ... db, redis, etc ...
  
  web:
    build: .
    # ... environment, volumes ...
    ports:
      - "8001:8000"  # ✅ IMPORTANT : port 8001 sur l'hôte
    # ... reste de la config ...
```

### 10.4 - Build et Démarrage

```bash
cd /var/www/digit-hab-crm

# Build
docker compose -f docker-compose.prod.yml build --no-cache

# Démarrer
docker compose -f docker-compose.prod.yml up -d

# Vérifier
docker compose -f docker-compose.prod.yml ps
```

### 10.5 - Migrations et Static

```bash
# Attendre que la DB soit prête (15-20 secondes)
sleep 15

# Migrations
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Collecte des statiques
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Créer un superuser
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

---

## ✅ Étape 11 : Tests Finaux

### 11.1 - Test des Endpoints

```bash
# AL-TOPPE
curl -I https://api.altoppe.sn/health/
# Devrait retourner : HTTP/2 200

# DIGIT-HAB
curl -I https://api.digit-hab.altoppe.sn/health/
# Devrait retourner : HTTP/2 200
```

### 11.2 - Test dans le Navigateur

- **AL-TOPPE Admin** : https://api.altoppe.sn/admin/
- **DIGIT-HAB Admin** : https://api.digit-hab.altoppe.sn/admin/
- **DIGIT-HAB API** : https://api.digit-hab.altoppe.sn/api/docs/

### 11.3 - Vérifier les Logs

```bash
# AL-TOPPE
cd /var/www/al-toppe
docker compose -f docker-compose.prod.yml logs -f --tail=100

# DIGIT-HAB
cd /var/www/digit-hab-crm
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

---

## 🔧 Maintenance

### Renouvellement SSL Automatique

```bash
# Ajouter au crontab
sudo crontab -e

# Ajouter cette ligne :
0 3 * * * certbot renew --quiet --post-hook 'cd /var/www/al-toppe && docker compose -f docker-compose.prod.yml restart nginx'
```

### Mise à Jour de DIGIT-HAB

```bash
cd /var/www/digit-hab-crm

# Pull les changements
git pull origin main

# Rebuild
docker compose -f docker-compose.prod.yml build

# Redémarrer
docker compose -f docker-compose.prod.yml up -d

# Migrations
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Collecte des statiques
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
```

### Backup de la Base de Données

```bash
# DIGIT-HAB
cd /var/www/digit-hab-crm
docker compose -f docker-compose.prod.yml exec db pg_dump -U digit_hab_user digit_hab_prod > backup_$(date +%Y%m%d_%H%M%S).sql

# AL-TOPPE
cd /var/www/al-toppe
docker compose -f docker-compose.prod.yml exec db pg_dump -U altoppe_user altoppe_prod > backup_$(date +%Y%m%d_%H%M%S).sql
```

---

## 🐛 Troubleshooting

### Erreur : "Connection refused" depuis Nginx vers DIGIT-HAB

```bash
# Vérifier que le port 8001 est bien exposé
docker ps | grep digit-hab
# Devrait afficher : 0.0.0.0:8001->8000/tcp

# Vérifier depuis l'hôte
curl http://localhost:8001/health/
```

### Erreur : "502 Bad Gateway"

```bash
# Vérifier les logs du service web
cd /var/www/digit-hab-crm
docker compose -f docker-compose.prod.yml logs web

# Vérifier que le service est UP
docker compose -f docker-compose.prod.yml ps
```

### Erreur : "Static files not found"

```bash
# Recollectez les statiques
cd /var/www/digit-hab-crm
docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Vérifier les permissions
ls -la /var/www/digit-hab-crm/staticfiles/
```

---

## 📝 Checklist Finale

- [ ] DNS configurés et propagés
- [ ] Certificats SSL obtenus
- [ ] AL-TOPPE fonctionne normalement
- [ ] DIGIT-HAB répond sur https://api.digit-hab.altoppe.sn/health/
- [ ] Admin accessible
- [ ] API docs accessibles
- [ ] Logs propres (pas d'erreurs)
- [ ] Cron de renouvellement SSL configuré
- [ ] Backup de la config d'origine effectué

---

## ✨ C'est Terminé !

Vos deux projets tournent maintenant sur le même VPS avec :
- ✅ Nginx partagé
- ✅ SSL/HTTPS pour les deux
- ✅ Isolation complète des services
- ✅ Logs séparés

**Bon développement ! 🚀**
