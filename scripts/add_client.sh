#!/bin/bash
# =============================================================================
# add_client.sh — Añade un nuevo cliente al servidor
# Uso: sudo bash scripts/add_client.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Ejecuta este script como root: sudo bash scripts/add_client.sh"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLIENTS_DIR="$PROJECT_DIR/clients"
BASE_PORT=8001

echo "========================================"
echo "  Añadir nuevo cliente"
echo "========================================"
echo ""

# ── Encontrar siguiente puerto libre ─────────────────────────────────────────
next_free_port() {
  local port=$BASE_PORT
  while true; do
    if ! grep -rq "\"$port:8000\"" "$CLIENTS_DIR"/*/docker-compose.yml 2>/dev/null; then
      echo "$port"
      return
    fi
    ((port++))
  done
}

# ── Recoger datos ─────────────────────────────────────────────────────────────
read -p "Identificador del cliente (sin espacios, ej: acme_inmobiliaria): " CLIENT_SLUG
CLIENT_SLUG=$(echo "$CLIENT_SLUG" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr '-' '_')

if [ -d "$CLIENTS_DIR/$CLIENT_SLUG" ]; then
  echo "ERROR: El cliente '$CLIENT_SLUG' ya existe en $CLIENTS_DIR/$CLIENT_SLUG"
  exit 1
fi

read -p "Nombre del negocio (ej: Inmobiliaria García): " BUSINESS_NAME

echo ""
echo "--- DuckDNS ---"
echo "Ve a https://www.duckdns.org, crea una cuenta y añade un subdominio."
echo "Ese subdominio apuntará a la IP de este servidor."
echo ""
read -p "Subdominio DuckDNS (ej: acme  →  acme.duckdns.org): " DUCKDNS_SUB
read -p "Token DuckDNS (lo ves en la página principal de duckdns.org): " DUCKDNS_TOKEN
DOMAIN="${DUCKDNS_SUB}.duckdns.org"

echo ""
echo "--- Acceso a la web ---"
read -p "Usuario para acceder a la app: " AUTH_USER
read -s -p "Contraseña: " AUTH_PASS
echo ""

# ── Crear directorio del cliente ──────────────────────────────────────────────
PORT=$(next_free_port)
CLIENT_DIR="$CLIENTS_DIR/$CLIENT_SLUG"
mkdir -p "$CLIENT_DIR/data"

echo ""
echo "Configurando '$CLIENT_SLUG' → https://$DOMAIN (puerto interno: $PORT)"

# Config YAML (reemplaza el placeholder del nombre)
cp "$CLIENTS_DIR/template/config.yaml" "$CLIENT_DIR/config.yaml"
sed -i "s/NOMBRE_DEL_NEGOCIO/$(echo "$BUSINESS_NAME" | sed 's/[\/&]/\\&/g')/" "$CLIENT_DIR/config.yaml"

# .env
cp "$CLIENTS_DIR/template/.env.example" "$CLIENT_DIR/.env"

# Docker Compose
cat > "$CLIENT_DIR/docker-compose.yml" << COMPOSE
services:
  app:
    image: asistente-negocio:latest
    restart: unless-stopped
    ports:
      - "$PORT:8000"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./.env:/app/.env:ro
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json
      - ./data:/app/data
COMPOSE

# ── Credenciales web (HTTP Basic Auth) ───────────────────────────────────────
mkdir -p /etc/nginx/htpasswd
htpasswd -bc "/etc/nginx/htpasswd/$CLIENT_SLUG" "$AUTH_USER" "$AUTH_PASS"

# ── Certificado SSL via DuckDNS ───────────────────────────────────────────────
echo ""
echo "Obteniendo certificado SSL para $DOMAIN..."
certbot certonly \
  --non-interactive \
  --agree-tos \
  --email "admin@$DOMAIN" \
  --authenticator dns-duckdns \
  --dns-duckdns-token "$DUCKDNS_TOKEN" \
  --dns-duckdns-propagation-seconds 60 \
  -d "$DOMAIN"

# ── Config Nginx ──────────────────────────────────────────────────────────────
cat > "/etc/nginx/sites-available/$CLIENT_SLUG" << NGINX
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    auth_basic "Acceso restringido";
    auth_basic_user_file /etc/nginx/htpasswd/$CLIENT_SLUG;

    location / {
        proxy_pass         http://localhost:$PORT;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX

ln -sf "/etc/nginx/sites-available/$CLIENT_SLUG" "/etc/nginx/sites-enabled/$CLIENT_SLUG"
nginx -t && systemctl reload nginx

# ── Instrucciones finales ─────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Estructura creada para '$CLIENT_SLUG'"
echo "========================================"
echo ""
echo "FALTA completar 3 pasos manuales:"
echo ""
echo "  1. Edita las API keys del cliente:"
echo "     nano $CLIENT_DIR/.env"
echo ""
echo "  2. Autoriza Gmail (hazlo en tu máquina local):"
echo "     a) Copia credentials.json del cliente a una carpeta local"
echo "     b) Ejecuta en local:"
echo "        python3 -c \"from app.gmail_client import GmailClient; GmailClient()\""
echo "        (se abrirá el navegador para autorizar la cuenta Gmail)"
echo "     c) Sube el token.json generado al servidor:"
echo "        scp token.json root@IP_SERVIDOR:$CLIENT_DIR/"
echo ""
echo "  3. Arranca el contenedor:"
echo "     cd $CLIENT_DIR && docker compose up -d"
echo ""
echo "  La app estará en: https://$DOMAIN"
echo "  Usuario: $AUTH_USER"
echo ""
