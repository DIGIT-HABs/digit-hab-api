# Héberger plusieurs projets sur un VPS Ubuntu

Ce dossier fournit une base **Caddy** (HTTPS automatique) + **systemd** pour faire tourner plusieurs applis Node (ou tout ce qui écoute sur un port local).

## Prérequis

- VPS Ubuntu 22.04 avec IP fixe (ex. `31.207.37.80`).
- Les enregistrements **A** (et **AAAA** si vous utilisez l’IPv6 du VPS) des noms ci-dessous doivent pointer vers cette IP.
- Ports **80** et **443** ouverts (pare-feu + hébergeur).

### Vos trois sites (Caddy → port local)

| Hostname | Projet | Port interne |
|----------|--------|----------------|
| `wifi.wolofdigital.site` | Wolof WiFi Pay | `3001` |
| `apisign.wolofdigtal.com` | wolof Sign | `3002` |
| `apie.wolofdigital.com` | e-wolof (éducation) | `3003` |
| `api.digit-hab.wolofdigital.site` | Digit-Hab API (Django) | `3004` |

Les noms d’hôte dans le `Caddyfile` doivent **exactement** correspondre aux enregistrements DNS chez votre registrar (y compris **apisign** si vous corrigez plus tard `wolofdigtal` → `wolofdigital`).

Éditez `email` en tête du `Caddyfile` (adresse réelle pour ACME).

## 0. Mettre le MVP en ligne — **recadrage important pour ce dépôt**

Votre stack VPS (Ubuntu, Node 22, Docker, IP publique, **Caddy** déjà en place) est **très adaptée** aux services annexes (webhooks Wave, petites API, autres sites sur des ports locaux).

**Ce dépôt** est configuré pour **TanStack Start + Nitro + Node** (`npm run build` → `.output/server/index.mjs`, `npm run start`). C’est la voie **VPS** (reverse proxy **Caddy** vers `127.0.0.1:3001`). Détails : **`infra/vps/DEPLOY-NODE.md`**.

| Objectif | Piste |
|----------|--------|
| **MVP sur ce VPS** | `git clone` → `/opt/apps/wolof-wifi-pay` → `npm ci` → `npm run build` → systemd avec `HOST=127.0.0.1` `PORT=3001` et `npm run start` (ou `node .output/server/index.mjs`). |
| **Cloudflare** (optionnel) | Il faudrait réintroduire `@cloudflare/vite-plugin` + entrée Worker ; ce n’est plus la config par défaut du dépôt. |
| **Process manager** | Sur le VPS vous utilisez déjà **systemd** (`wolof-wifi-pay.service`) ; **PM2** est équivalent, pas obligatoire. |
| **Docker Compose** | Utile pour d’autres conteneurs ; `apt install docker-compose-plugin -y` reste valable si vous standardisez plusieurs services. |
| **Sécurité Supabase** | Prioritaire en prod : **RLS**, politiques fines, **accès ticket** (jeton ou lecture serveur), **webhook Wave** vérifié (signature). |

**CHR MikroTik** : à traiter après le MVP en ligne et le paiement réel, comme vous l’indiquez.

## 1. Pare-feu

```bash
sudo apt update && sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 2. Caddy (reverse proxy + TLS)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Copiez `caddy/Caddyfile` vers `/etc/caddy/Caddyfile`, ajustez l’`email` global si besoin, puis :

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
```

**`reload` ne marche que si Caddy tourne déjà.** Si vous voyez `caddy.service is not active, cannot reload`, utilisez `restart` (ou `enable --now` juste après l’installation).

Après chaque modification du `Caddyfile` :

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

Si le service ne démarre pas :

```bash
sudo journalctl -u caddy -e --no-pager
sudo ss -tlnp | grep -E ':80|:443'
```

(`ss` permet de voir si un autre programme occupe déjà 80/443.)

### Port 80 ou 443 déjà utilisé (`bind: address already in use`)

Caddy doit être **le seul** service à écouter sur **80** et **443** (reverse proxy + challenge Let’s Encrypt). Souvent le conflit vient d’**Apache** ou **nginx** préinstallés sur le VPS.

Voir quel processus tient le port :

```bash
sudo ss -tlnp | grep -E ':80 |:443 '
```

Puis arrêter et désactiver le service inutile (exemples) :

```bash
# Si nginx occupe le port
sudo systemctl stop nginx
sudo systemctl disable nginx

# Si apache2 occupe le port
sudo systemctl stop apache2
sudo systemctl disable apache2
```

Ensuite : `sudo systemctl restart caddy` et `sudo systemctl status caddy`.

Lors de `caddy validate`, un avertissement du type *« listening only on the HTTP port, so no automatic HTTPS »* apparaît souvent avec le **Caddyfile par défaut** d’Ubuntu (site sur `:80` seulement). Dès que `/etc/caddy/Caddyfile` contient vos **vrais noms de domaine** (comme dans `infra/vps/caddy/Caddyfile`) et que le DNS pointe vers le VPS, Caddy pourra obtenir les certificats Let’s Encrypt sur le port 443.

### Caddy n’écoute que sur 80 (`ss` ne montre pas `:443`)

Si `sudo ss -tlnp | grep caddy` n’affiche que **`*:80`** et pas **`*:443`**, le HTTPS n’est pas actif : `curl https://...` donnera *connection refused*.

1. Affichez la config réelle : `sudo cat /etc/caddy/Caddyfile`
2. **Supprimez** le bloc par défaut du style **`:80 { root * /usr/share/caddy file_server }`** s’il est encore présent.
3. Le fichier doit commencer par le bloc global `email` puis des **noms d’hôte** (ex. `wifi.wolofdigital.site { ... }`), comme dans `infra/vps/caddy/Caddyfile` du dépôt.
4. `sudo caddy validate --config /etc/caddy/Caddyfile` puis **`sudo systemctl restart caddy`** (un simple `reload` suffit souvent, mais `restart` force la relecture des listeners).
5. Revérifiez : `sudo ss -tlnp | grep -E ':80|:443'` — vous devez voir **caddy sur 80 et 443**.

Les avertissements TLS du type *« looking up info for HTTP challenge »* dans les logs indiquent souvent que **Let’s Encrypt** teste encore un nom dont le **DNS** ne pointe pas vers ce VPS ; corrigez le DNS ou retirez du `Caddyfile` les blocs pour des domaines que vous n’utilisez pas encore.

## 3. Arborescence conseillée

```text
/opt/apps/
  wolof-wifi-pay/   # 127.0.0.1:3001  → wifi.wolofdigital.site
  wolof-sign/       # 127.0.0.1:3002  → apisign.wolofdigtal.com
  e-wolof/          # 127.0.0.1:3003  → apie.wolofdigital.com
  digit-hab-api/    # 127.0.0.1:3004  → api.digit-hab.wolofdigital.site
```

API Django Digit-Hab : voir **`DEPLOY-DJANGO.md`**.

Chaque app doit **écouter sur localhost** (sécurité) : `127.0.0.1:PORT`, pas `0.0.0.0` si vous ne voulez pas l’exposer sans passer par Caddy.

Créez un utilisateur dédié (ex. `deploy`) :

```bash
sudo adduser --disabled-password deploy
sudo mkdir -p /opt/apps
sudo chown deploy:deploy /opt/apps
```

## 4. systemd (une unit par projet)

Le fichier modèle est dans le dépôt : `infra/vps/systemd/node-app-single.service.example`.  
Il **n’existe pas** sur le VPS tant que vous ne l’y avez pas copié (il n’est pas dans `/root`).

**Option A — dépôt déjà cloné sur le VPS** (adaptez le chemin) :

```bash
sudo cp /opt/apps/wolof-wave-connect/infra/vps/systemd/node-app-single.service.example \
  /etc/systemd/system/wolof-wifi-pay.service
sudo nano /etc/systemd/system/wolof-wifi-pay.service
```

**Option B — depuis votre PC** (SCP vers le VPS) :

```bash
scp infra/vps/systemd/node-app-single.service.example root@31.207.37.80:/tmp/
ssh root@31.207.37.80 'sudo mv /tmp/node-app-single.service.example /etc/systemd/system/wolof-wifi-pay.service'
```

Puis sur le VPS : éditer `WorkingDirectory`, `ExecStart` (binaire + chemin), et dupliquer pour chaque projet (`wolof-sign.service` → port 3002, etc.).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wolof-wifi-pay.service
sudo systemctl status wolof-wifi-pay.service
```

### Erreur `status=200/CHDIR` (service qui redémarre en boucle)

Systemd ne peut pas utiliser `WorkingDirectory` : le chemin **n’existe pas** ou **deploy** n’est pas propriétaire / n’a pas le droit d’y entrer.

Créez le répertoire du projet et alignez le `.service` sur ce chemin (exemple pour Wolof WiFi Pay sur le port 3001) :

```bash
sudo mkdir -p /opt/apps/wolof-wifi-pay
sudo chown -R deploy:deploy /opt/apps/wolof-wifi-pay
```

Dans `/etc/systemd/system/wolof-wifi-pay.service`, **ne laissez pas** `/opt/apps/mon-api` si ce dossier n’existe pas : utilisez au minimum :

- `WorkingDirectory=/opt/apps/wolof-wifi-pay`
- `ExecStart=/usr/bin/node /opt/apps/wolof-wifi-pay/listen-3001.mjs` (fichier qui **existe**)

### Placeholder sur le port 3001 (enlever le 502 tout de suite)

Le dépôt contient `infra/vps/placeholder/listen-3001.mjs` (écoute **127.0.0.1:3001**). Sur le VPS :

```bash
sudo mkdir -p /opt/apps/wolof-wifi-pay
sudo chown -R deploy:deploy /opt/apps/wolof-wifi-pay
# Copier listen-3001.mjs depuis votre PC (scp) ou depuis un clone du repo vers ce chemin.
```

Exemple d’unité alignée : `infra/vps/systemd/wolof-wifi-pay.service.example`. Après copie du `.mjs` et du `.service` :

```bash
sudo systemctl daemon-reload
sudo systemctl restart wolof-wifi-pay.service
sudo ss -tlnp | grep 3001
curl -I http://127.0.0.1:3001
```

Quand votre vraie appli est buildée, remplacez `ExecStart` par le chemin vers `dist/server.js` (ou l’entrée réelle).

Voir les logs : `sudo journalctl -u wolof-wifi-pay.service -e --no-pager`.

## 5. Vérification

- `curl -I https://wifi.wolofdigital.site` (et les deux autres hosts) doit répondre via Caddy une fois les services locaux démarrés.
- `ss -tlnp` sur le VPS : ports internes (3001, …) + 443.

## Note sur **wolof-wave-connect**

L’app est buildée avec **Nitro** (`npm run build`) et servie par **Node** (`npm run start` → `.output/server/index.mjs`). Ce dossier `infra/vps` documente **Caddy**, **systemd** et le déploiement sur votre VPS.

## Lab MikroTik (CHR)

Pour simuler un routeur, tester l’API et le hotspot avant la prod : voir **`infra/mikrotik/README.md`**.
