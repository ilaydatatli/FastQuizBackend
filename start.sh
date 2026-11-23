#!/bin/sh
# Container start: prepare the database, then run the web server.
# Free hosting tiers have no separate pre-deploy job, so these steps run on every start.
# Every step is safe to repeat (idempotent).
set -e

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py load_questions

# Optional admin account (Render Free has no console). Set DJANGO_SUPERUSER_USERNAME,
# DJANGO_SUPERUSER_PASSWORD and DJANGO_SUPERUSER_EMAIL (all three required) in the host's
# environment; Django reads them itself. If the user already exists, Django refuses
# and we just carry on, so this is safe on every start too.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python manage.py createsuperuser --noinput \
    && echo "Admin user created." \
    || echo "Admin user not created (it probably exists already)."
fi

# The host provides PORT; default to 8000
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 30 --access-logfile -
