#!/usr/bin/env bash
# Script de build usado pelo Render (blueprint render.yaml).
# Instala dependências, coleta os estáticos e aplica migrações.
#
# As migrações rodam aqui (em vez de um releaseCommand) para simplificar o
# blueprint. Só rodam quando DATABASE_URL estiver definida — assim o primeiro
# build (antes de preencher a variável) não falha sem motivo.
set -e

pip install -r requirements.txt
python manage.py collectstatic --noinput

if [ -n "$DATABASE_URL" ]; then
  echo "DATABASE_URL encontrada — aplicando migrações..."
  python manage.py migrate --noinput
else
  echo "AVISO: DATABASE_URL não definida. Pulando migrações (first deploy)."
fi
