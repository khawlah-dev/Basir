#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput
python manage.py collectstatic --noinput

: "${PORT:?PORT environment variable is required}"
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --timeout 120
