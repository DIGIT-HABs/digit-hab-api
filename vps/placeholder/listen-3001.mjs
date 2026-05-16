/**
 * Placeholder HTTP sur 127.0.0.1:3001 — pour vérifier Caddy sans votre appli finale.
 * Sur le VPS : copier dans /opt/apps/wolof-wifi-pay/ puis
 *   ExecStart=/usr/bin/node /opt/apps/wolof-wifi-pay/listen-3001.mjs
 */
import http from "http";

const host = "127.0.0.1";
const port = 3001;

const server = http.createServer((_req, res) => {
  res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("Wolof WiFi Pay — placeholder OK. Remplacez par votre application.\n");
});

server.listen(port, host, () => {
  console.log(`http://${host}:${port}`);
});
