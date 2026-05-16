# Déployer Wolof WiFi Pay sur le VPS (**Node + Nitro**)

Le projet est buildé avec **Nitro** (cible Node officielle TanStack Start). Après `npm run build`, le serveur HTTP se lance avec :

```bash
npm run start
```

Le point d’entrée est **`.output/server/index.mjs`**. Les variables d’environnement doivent être présentes au **build** et au **runtime** (voir **`.env.example`** à la racine du dépôt).

## Première installation sur le VPS (erreurs courantes)

### `fatal: not a git repository`

Le dossier `/opt/apps/wolof-wifi-pay` ne contient pas encore le projet complet. Il faut **cloner** le dépôt (ou **rsync** depuis votre PC **avec** `package-lock.json`).

**Exemple avec Git** (remplacez l’URL par la vôtre) :

```bash
sudo rm -rf /opt/apps/wolof-wifi-pay
sudo mkdir -p /opt/apps
sudo git clone https://github.com/VOTRE_ORG/wolof-wave-connect.git /opt/apps/wolof-wifi-pay
sudo chown -R deploy:deploy /opt/apps/wolof-wifi-pay
```

### `npm ci` → *package.json and package-lock.json are not in sync*

Le lockfile sur GitHub est **plus ancien** que `package.json` (dépendances manquantes dans le lock).

**Sur votre machine de dev** : `npm install`, puis **commit + push** de `package-lock.json`. Sur le VPS : `git pull` puis `npm ci`.

**Contournement ponctuel sur le VPS** (sans lockfile à jour) :

```bash
sudo -u deploy bash -lc 'cd /opt/apps/wolof-wifi-pay && rm -rf node_modules && npm install && npm run build'
```

Ensuite, corrigez le dépôt avec un lockfile synchronisé pour retrouver `npm ci` propre.

### `npm ci` → *existing package-lock.json* (fichier absent)

`npm ci` **exige** un **`package-lock.json`** à la racine. Après un clone correct, il est en principe présent.

### `MANQUE .env`

Créez **`/opt/apps/wolof-wifi-pay/.env`** (modèle : **`.env.example`**) :

```bash
sudo -u deploy nano /opt/apps/wolof-wifi-pay/.env
sudo chmod 600 /opt/apps/wolof-wifi-pay/.env
```

Renseignez au minimum :

- `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (nécessaires au **`npm run build`**)
- `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (SSR et server functions)

## Build et mise à jour

```bash
sudo -u deploy -H bash -lc 'cd /opt/apps/wolof-wifi-pay && git pull && npm ci && npm run build'
sudo systemctl restart wolof-wifi-pay.service
```

(Si ce n’est pas un dépôt Git, remplacez `git pull` par votre méthode de mise à jour.)

## Écouter sur `127.0.0.1:3001` (Caddy)

Dans l’unité systemd (utilisateur `deploy`) :

```ini
Environment=NITRO_HOST=127.0.0.1
Environment=NITRO_PORT=3001
Environment=NODE_ENV=production
EnvironmentFile=-/opt/apps/wolof-wifi-pay/.env
ExecStart=/usr/bin/node /opt/apps/wolof-wifi-pay/.output/server/index.mjs
WorkingDirectory=/opt/apps/wolof-wifi-pay
```

(Nitro lit **`NITRO_HOST`** / **`NITRO_PORT`** ou **`HOST`** / **`PORT`**.)

Ou **`npm run start`** :

```ini
ExecStart=/usr/bin/npm run start
WorkingDirectory=/opt/apps/wolof-wifi-pay
```

## Ancien déploiement Cloudflare

`wrangler.jsonc` a été retiré du dépôt avec le passage à **Nitro + Node**. Pour un déploiement secondaire Cloudflare, il faudrait réintroduire la config Wrangler et l’entrée Worker adaptée.
