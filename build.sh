#!/usr/bin/env bash
# Script de build usado pelo Render (blueprint render.yaml).
# Instala dependências e coleta os arquivos estáticos para produção.
set -e

pip install -r requirements.txt
python manage.py collectstatic --noinput
