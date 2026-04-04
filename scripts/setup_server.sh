#!/bin/bash
# =============================================================================
# setup_server.sh — Configuración inicial del servidor (ejecutar una sola vez)
# Ubuntu 24.04 LTS
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Ejecuta este script como root: sudo bash setup_server.sh"
  exit 1
fi

echo "========================================"
echo "  Configuración del servidor"
echo "========================================"

# --- Sistema ---
echo "[1/6] Actualizando sistema..."
apt-get update -qq && apt-get upgrade -y -qq

# --- Docker ---
echo "[2/6] Instalando Docker..."
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
# Añadir usuario no-root al grupo docker si existe
if [ -n "$SUDO_USER" ]; then
  usermod -aG docker "$SUDO_USER"
fi

# --- Nginx ---
echo "[3/6] Instalando Nginx..."
apt-get install -y -qq nginx apache2-utils

# --- Certbot + plugin DuckDNS ---
echo "[4/6] Instalando Certbot + plugin DuckDNS..."
apt-get install -y -qq python3-pip python3-venv
pip3 install --quiet certbot certbot-dns-duckdns

# --- Firewall ---
echo "[5/6] Configurando firewall (UFW)..."
apt-get install -y -qq ufw
ufw allow OpenSSH
ufw allow "Nginx Full"
ufw --force enable

# --- Estructura de directorios ---
echo "[6/6] Creando estructura de directorios..."
mkdir -p /opt/asistente
mkdir -p /etc/nginx/htpasswd

# Activar Nginx
systemctl enable nginx
systemctl start nginx

echo ""
echo "========================================"
echo "  Servidor listo"
echo "========================================"
echo ""
echo "Pasos siguientes:"
echo "  1. Copia el proyecto al servidor:"
echo "     scp -r . usuario@IP_SERVIDOR:/opt/asistente/"
echo ""
echo "  2. Construye la imagen Docker:"
echo "     cd /opt/asistente && docker build -t asistente-negocio:latest ."
echo ""
echo "  3. Añade tu primer cliente:"
echo "     bash /opt/asistente/scripts/add_client.sh"
echo ""
