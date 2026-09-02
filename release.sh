#!/usr/bin/env bash
# Comando de "release" do Render: roda antes de o novo deploy entrar no ar.
# Aplica as migrações no banco (Supabase/PostgreSQL) de forma idempotente.
set -e

python manage.py migrate --noinput
