"""
Django settings for the Fast Quiz backend.

All environment-specific values are read from `.env` (see `.env.example`).
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.getenv("SECRET_KEY", "")
DEBUG = env_bool("DEBUG", False)

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "insecure-local-dev-key"
    else:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is False.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Only needed live, for the admin login form (the API itself does not use CSRF).
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "quiz",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves admin CSS/JS in production
    "corsheaders.middleware.CorsMiddleware",  # must be before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: DATABASE_URL, e.g. postgres://localhost:5432/fast_quiz
DATABASE_SSL_REQUIRE = env_bool("DATABASE_SSL_REQUIRE", False)

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://localhost:5432/fast_quiz",
        conn_max_age=60,
        ssl_require=DATABASE_SSL_REQUIRE,
    )
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Hashed + compressed files need `collectstatic` (done in the Docker build).
# Local development and tests (DEBUG=True in .env) use the plain storage.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# CORS: only origins listed in .env may call the API from a browser.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = False  # no cookies; auth is a Bearer token
# CORS_ALLOW_HEADERS default already includes "authorization".


# Production security. DigitalOcean ends HTTPS at its load balancer and forwards
# plain HTTP with X-Forwarded-Proto, so Django must trust that header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_HTTPS = env_bool("USE_HTTPS", False)
if USE_HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600  # short on purpose for a prototype
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

SILENCED_SYSTEM_CHECKS = [
    # SECURE_SSL_REDIRECT stays off: DigitalOcean already redirects HTTP -> HTTPS.
    "security.W008",
    # No HSTS preload for a prototype on a shared *.ondigitalocean.app domain.
    "security.W021",
]


# Throttle counters must be shared by all Gunicorn workers -> database cache
# (no Redis needed). Create the table once with: python manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}


# Log to stdout so DigitalOcean shows it under Runtime Logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}


# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],  # quiz endpoints set their own class explicitly
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "quiz.exceptions.api_exception_handler",
    # Behind one proxy (DigitalOcean): take the real client IP from X-Forwarded-For.
    "NUM_PROXIES": 1,
    "DEFAULT_THROTTLE_RATES": {
        "quiz_start": "30/hour",
        "answer": "120/minute",
        "score": "20/hour",
        "room_create": "10/hour",
    },
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )


# Quiz constants. Always read via settings.FAST_QUIZ[...] so tests can override them.
FAST_QUIZ = {
    "QUESTIONS_PER_QUIZ": 20,
    "TIME_LIMIT_MS": 10000,
    "GRACE_MS": 1000,
    "SESSION_TTL_MINUTES": 15,
    "FEEDBACK_HINT_MS": 700,  # informational only; used by the client
    "LEADERBOARD_SIZE": 10,
    "ROOM_TTL_HOURS": 24,  # challenge rooms: new players can join for this long
    "ROOM_MAX_PLAYERS": 50,
}
