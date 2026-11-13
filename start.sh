#!/bin/sh
# Container start: prepare the database, then run the web server.
# Free hosting tiers have no separate pre-deploy job, so these steps run on every start.
# All three commands are safe to repeat (idempotent).
set -e

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py load_questions

# The host provides PORT; default to 8000
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 30 --access-logfile -
