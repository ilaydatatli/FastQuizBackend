FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bake admin static files into the image (no database needed; fake SECRET_KEY only for the build)
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --noinput

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# migrate + load questions, then Gunicorn (see start.sh)
CMD ["sh", "start.sh"]
