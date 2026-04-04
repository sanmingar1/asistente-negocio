#!/bin/bash
# =============================================================================
# update.sh — Despliega una nueva versión a todos los clientes
# Uso: sudo bash scripts/update.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Ejecuta este script como root: sudo bash scripts/update.sh"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLIENTS_DIR="$PROJECT_DIR/clients"

echo "========================================"
echo "  Actualizando Asistente de Negocio"
echo "========================================"
echo ""

# Reconstruir imagen Docker
echo "Construyendo imagen..."
cd "$PROJECT_DIR"
docker build -t asistente-negocio:latest .
echo "Imagen construida."
echo ""

# Reiniciar todos los clientes activos
UPDATED=0
for client_dir in "$CLIENTS_DIR"/*/; do
  client=$(basename "$client_dir")
  [ "$client" = "template" ] && continue
  [ ! -f "$client_dir/docker-compose.yml" ] && continue

  echo "  → Actualizando: $client"
  cd "$client_dir"
  docker compose up -d
  cd "$PROJECT_DIR"
  ((UPDATED++))
done

echo ""
echo "========================================"
echo "  $UPDATED cliente(s) actualizado(s)"
echo "========================================"
