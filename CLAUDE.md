# Fast Quiz Backend — CLAUDE.md

> Bu repo Fast Quiz'in **Django + DRF + PostgreSQL** API'sidir. Önce ortak dokümanı oku, sonra yalnızca **aktif faz** üzerinde çalış.
> Ortak doküman (konsept, modeller, API sözleşmesi, fazlar):

@../PROJE.md

> Frontend ayrı bir repoda: `../fast-quiz-frontend/`. Bu repoda frontend kodu yazılmaz.
> Bu repodaki fazlar: **1–6**, **10**'un backend kısmı, **11** (Docker) ve **12** (DigitalOcean).

---

## 1. Bağımlılıklar (`requirements.txt`)

```
Django>=5.2,<5.3
djangorestframework>=3.15
django-cors-headers>=4.4
psycopg[binary]>=3.2
dj-database-url>=2.2
python-dotenv>=1.0
# Faz 11'de eklenir (canlı için):
gunicorn>=23.0
whitenoise>=6.7
```
Bunların dışında paket eklemeden önce kullanıcıya sor. (Testlerde saat taklidi için ek paket yok: `unittest.mock.patch` ile `quiz.services.now` taklit edilir.)

---

## 2. Klasör Yapısı (hedef)

```
fast-quiz-backend/
├── CLAUDE.md
├── README.md                 # kurulum + curl örnekleri
├── requirements.txt
├── manage.py
├── .env.example
├── .gitignore                # .venv/, .env, __pycache__/, .DS_Store, staticfiles/
├── Dockerfile                # Faz 11
├── .dockerignore             # Faz 11
├── docker-compose.yml        # Faz 11 — yalnızca canlı imajı lokalde denemek için (db + api)
├── .do/
│   └── app.yaml              # Faz 12 — DigitalOcean App Platform spec'i
├── config/
│   ├── settings.py
│   ├── urls.py               # /admin/ ve /api/v1/ → quiz.urls
│   ├── wsgi.py
│   └── asgi.py
└── quiz/
    ├── models.py             # Category, Question, Choice, QuizSession, SessionQuestion, Score
    ├── admin.py
    ├── serializers.py        # istemciye giden şekiller; is_correct ASLA yok
    ├── views.py              # ince view'lar: doğrula → service çağır → serializer
    ├── urls.py
    ├── services.py           # now(), start_quiz, get_current, submit_answer, calculate_points, save_score
    ├── authentication.py     # QuizTokenAuthentication (Bearer token → QuizSession)
    ├── exceptions.py         # QuizError(code, message, status) + ortak hata işleyici
    ├── throttles.py          # quiz_start, answer, score kapsamları
    ├── data/
    │   └── questions/        # yazilim.json, yapay-zeka.json, ulkeler.json, biyoloji.json, fotografcilik.json
    ├── management/
    │   └── commands/
    │       └── load_questions.py
    ├── migrations/
    └── tests/
        ├── __init__.py
        ├── factories.py      # test verisi yardımcıları (paket değil, düz fonksiyonlar)
        ├── test_models.py
        ├── test_load_questions.py
        ├── test_categories_api.py
        ├── test_quiz_start.py
        ├── test_quiz_flow.py
        ├── test_timing.py
        ├── test_score_leaderboard.py
        └── test_health_cors.py
```
Tek app (`quiz`) yeterli. Ayrı `leaderboard` app'i açma.

---

## 3. Ayarlar (`config/settings.py`)

- `.env`'i `python-dotenv` ile yükle; `DATABASE_URL`'i `dj_database_url.config(conn_max_age=60)` ile oku.
- `LANGUAGE_CODE = "tr"`, `TIME_ZONE = "Europe/Istanbul"`, `USE_TZ = True`.
- `INSTALLED_APPS`: `corsheaders`, `rest_framework`, `quiz` (+ Django'nun admin için gerekenleri).
- `MIDDLEWARE`: `corsheaders.middleware.CorsMiddleware` **en üste yakın** (`CommonMiddleware`'den önce).
- `CORS_ALLOWED_ORIGINS` = `.env`'deki virgülle ayrılmış liste; `CORS_ALLOW_CREDENTIALS = False`; `CORS_ALLOW_HEADERS`'a `authorization` dahil (varsayılanda var).
- DRF:
  ```python
  REST_FRAMEWORK = {
      "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],  # DEBUG'da BrowsableAPIRenderer eklenir
      "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
      "DEFAULT_AUTHENTICATION_CLASSES": [],          # quiz uçları kendi sınıfını açıkça kullanır
      "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
      "UNAUTHENTICATED_USER": None,
      "EXCEPTION_HANDLER": "quiz.exceptions.api_exception_handler",
      "DEFAULT_THROTTLE_RATES": {"quiz_start": "30/hour", "answer": "120/minute", "score": "20/hour"},
  }
  ```
- Quiz sabitleri:
  ```python
  FAST_QUIZ = {
      "QUESTIONS_PER_QUIZ": 20,
      "TIME_LIMIT_MS": 5000,
      "GRACE_MS": 1000,
      "SESSION_TTL_MINUTES": 15,
      "FEEDBACK_HINT_MS": 700,   # yalnızca bilgi; istemci kullanır
      "LEADERBOARD_SIZE": 10,
  }
  ```
- Canlı ayarları (Faz 11):
  - `DATABASES["default"] = dj_database_url.config(conn_max_age=60, ssl_require=DATABASE_SSL_REQUIRE)`
  - WhiteNoise: `whitenoise.middleware.WhiteNoiseMiddleware` `SecurityMiddleware`'den hemen sonra; `STATIC_ROOT = BASE_DIR / "staticfiles"`; `STORAGES["staticfiles"]` → `whitenoise.storage.CompressedManifestStaticFilesStorage`. (Yalnızca admin'in CSS/JS'i için.)
  - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (DO, HTTPS'i yük dengeleyicide sonlandırır).
  - `USE_HTTPS=True` iken: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS = 3600` (prototip için kısa). `SECURE_SSL_REDIRECT` **kapalı** — HTTP→HTTPS yönlendirmesini DigitalOcean yapıyor; `check --deploy`'daki bu uyarı bilinçli olarak kabul edilir.
  - `CSRF_TRUSTED_ORIGINS` env'den (yalnızca admin girişi için; API CSRF kullanmaz).
  - DRF `"NUM_PROXIES": 1` → throttle gerçek istemci IP'sini `X-Forwarded-For`'dan alır (Faz 12'de loglardan doğrula).
  - `CACHES` → `django.core.cache.backends.db.DatabaseCache` (`LOCATION = "django_cache"`). Throttle sayaçları Gunicorn worker'ları arasında paylaşılsın diye; ek paket/Redis gerekmez. Tablo `createcachetable` ile oluşur.
  - `LOGGING`: konsola (stdout) `INFO` — DO panelindeki **Runtime Logs**'ta görünür.
- Kodda sabitleri doğrudan yazma; `settings.FAST_QUIZ[...]`'tan oku (testlerde `override_settings` ile değiştirilebilsin).

---

## 4. Kodlama Kuralları

- Arayüz/hata mesajları (`message`) **Türkçe**; kod, değişken, yorum **İngilizce**.
- **View'lar ince, mantık `services.py`'de.** Süre, puan, sıra kontrolü view'da yazılmaz.
- **Zaman:** her yerde `quiz.services.now()` kullan (içi `django.utils.timezone.now()`); doğrudan `timezone.now()` çağırma. Testlerde bu tek fonksiyon taklit edilir.
- **Serializer güvenliği:** `Choice` için istemciye giden serializer yalnızca `id`, `text`. `fields = "__all__"` **yasak**. `correct_choice_id` yalnızca cevap yanıtında.
- **Hatalar:** `QuizError(code, message, status)` fırlat; ortak işleyici `{"error": {"code", "message"}}` biçimine çevirsin. DRF'in kendi hataları (404, 405, 429, doğrulama) da aynı biçime dönüştürülür. Kod listesi `PROJE.md` Bölüm 6'dadır; yeni kod gerekirse önce `PROJE.md`'yi güncelle.
- **Atomiklik:** `submit_answer` ve `save_score` → `transaction.atomic()` + `QuizSession.objects.select_for_update()`.
- **Token:** `secrets.token_urlsafe(32)`, DB'de `hashlib.sha256(...).hexdigest()`. `QuizTokenAuthentication` URL'deki `quiz_id` ile token'ın eşleştiğini kontrol eder; eşleşmezse `401 INVALID_TOKEN` (başkasının quiz'ini oynayamazsın).
- **Sorgular:** soru getirirken `prefetch_related("choices")`, skor tablosunda tek sorgu + `[:10]`. N+1'den kaçın.
- URL'lerde sondaki `/` kullan (`/api/v1/categories/`).
- Django admin dışında HTML şablon yazma.

---

## 5. Test Yaklaşımı

- DRF `APITestCase` + Django test runner. Test verisi `tests/factories.py` içindeki düz fonksiyonlarla (`make_category(...)`, `make_question_set(category, n=20)`).
- **Zaman testleri:** `with patch("quiz.services.now", return_value=t0 + timedelta(milliseconds=4900)):` şeklinde. Sınır değerleri mutlaka test et: 4999, 5000, 5999, 6000, 6001 ms.
- **Güvenlik testleri:** tüm quiz yanıtlarında JSON metninde `"is_correct"` geçmediğini kontrol et (yalnızca cevap yanıtındaki `is_correct` alanı hariç — o, kullanıcının **kendi** cevabının sonucu); başka quiz'in token'ı ile erişim 401.
- Testler `.env`'deki veritabanına değil, Django'nun oluşturduğu `test_fast_quiz` veritabanına gider (PostgreSQL kullanıcısının `CREATEDB` yetkisi olmalı; Homebrew kurulumunda vardır).
- Her faz sonunda çalıştırılacaklar:
  ```bash
  python manage.py check
  python manage.py makemigrations --check --dry-run
  python manage.py test
  ```

---

## 6. Lokal Kurulum (macOS)

PostgreSQL (bir kez):
```bash
brew install postgresql@16
```
```bash
brew services start postgresql@16
```
```bash
createdb fast_quiz
```
> `createdb` bulunamazsa: `echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc` ve yeni terminal aç. (Intel Mac'te yol `/usr/local/opt/postgresql@16/bin`.)

Proje (Faz 1'den sonra):
```bash
cd ~/Desktop/fast-quiz/fast-quiz-backend
```
```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```
```bash
cp .env.example .env
```
```bash
python manage.py migrate
```
```bash
python manage.py load_questions
```
```bash
python manage.py createsuperuser
```
```bash
python manage.py runserver
```

`.env.example`:
```
SECRET_KEY=change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://localhost:5432/fast_quiz
CORS_ALLOWED_ORIGINS=http://localhost:5173
CSRF_TRUSTED_ORIGINS=
DATABASE_SSL_REQUIRE=False
USE_HTTPS=False
```
> Homebrew PostgreSQL'de varsayılan kullanıcı Mac kullanıcı adındır ve şifre gerekmez; bu yüzden `DATABASE_URL`'de kullanıcı/şifre yok. Farklıysa: `postgres://KULLANICI:SIFRE@localhost:5432/fast_quiz`.

---

## 7. Docker (Faz 11)

Docker **yalnızca canlı imaj** içindir. Günlük geliştirme yine `.venv` + Homebrew PostgreSQL ile yapılır (daha hızlı, öğrenmesi kolay). `docker-compose.yml`, canlıya çıkmadan önce imajı lokalde denemek için.

`Dockerfile` (hedef):
```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Admin statiklerini imaja göm (veritabanı gerekmez; sahte SECRET_KEY yalnızca build için)
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --noinput

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# DigitalOcean PORT değişkenini verir; yoksa 8000
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 30 --access-logfile -"]
```
- `psycopg[binary]` sistem paketi gerektirmez; `apt-get` adımı yok.
- `.dockerignore`: `.venv`, `.env`, `.git`, `__pycache__`, `*.pyc`, `staticfiles`, `.DS_Store`, `docker-compose.yml`, `.do`.

`docker-compose.yml` (hedef):
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: fast_quiz
      POSTGRES_USER: fastquiz
      POSTGRES_PASSWORD: fastquiz
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fastquiz -d fast_quiz"]
      interval: 2s
      retries: 15

  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: local-docker-only
      DEBUG: "False"
      ALLOWED_HOSTS: localhost,127.0.0.1
      DATABASE_URL: postgres://fastquiz:fastquiz@db:5432/fast_quiz
      DATABASE_SSL_REQUIRE: "False"
      USE_HTTPS: "False"
      CORS_ALLOWED_ORIGINS: http://localhost:5173
    # Canlıdaki PRE_DEPLOY job'ını taklit eder, sonra sunucuyu başlatır
    command: >
      sh -c "python manage.py migrate --noinput &&
             python manage.py createcachetable &&
             python manage.py load_questions &&
             exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile -"

volumes:
  pgdata:
```
Komutlar (Docker Desktop kurulu olmalı):
```bash
docker compose up --build
```
```bash
docker compose exec api python manage.py createsuperuser
```
```bash
docker compose down
```
> Lokal PostgreSQL'in de 5432'de çalışması sorun değil: compose'daki `db` portu dışarı açılmıyor.

---

## 8. DigitalOcean App Platform (Faz 12)

### Kaynaklar
| Kaynak | Ad | Not |
|---|---|---|
| App | `fast-quiz-api` | bölge `fra` (Frankfurt), GitHub `fast-quiz-backend` reposu, `main`, push'ta otomatik deploy |
| Web Service | `api` | Dockerfile'dan build; HTTP port 8000; en küçük instance; health check `/api/v1/health/` |
| PRE_DEPLOY Job | `release` | her deploy'dan **önce**: `migrate` → `createcachetable` → `load_questions` |
| Veritabanı | `fast-quiz-db` | Managed PostgreSQL 16, aynı bölge, app'e bağlı ("trusted source") |

- Job başarısız olursa (örn. migration hatası) **yeni sürüm yayına alınmaz**, eski sürüm çalışmaya devam eder. Bu güvenlik ağı; yine de push öncesi lokalde test şart.
- `load_questions` idempotent olduğu için her deploy'da çalışması güvenli: JSON'da düzelttiğin soru push'la canlıya gider.
- Fiyatlar ve instance boyutları değişebilir; seçimden önce DO panelindeki güncel fiyatı kontrol et.

### `.do/app.yaml` (hedef — `GITHUB_KULLANICI` ve frontend adresi doldurulacak)
```yaml
name: fast-quiz-api
region: fra

envs:                      # app düzeyi: hem service hem job görür
  - key: SECRET_KEY
    type: SECRET           # değer panelden girilir, spec'e yazılmaz
    scope: RUN_TIME
  - key: DEBUG
    value: "False"
    scope: RUN_TIME
  - key: ALLOWED_HOSTS
    value: ${APP_DOMAIN}
    scope: RUN_TIME
  - key: CSRF_TRUSTED_ORIGINS
    value: ${APP_URL}
    scope: RUN_TIME
  - key: DATABASE_URL
    value: ${fast-quiz-db.DATABASE_URL}
    scope: RUN_TIME
  - key: DATABASE_SSL_REQUIRE
    value: "True"
    scope: RUN_TIME
  - key: USE_HTTPS
    value: "True"
    scope: RUN_TIME
  - key: CORS_ALLOWED_ORIGINS
    value: https://FRONTEND-ADRESI.ondigitalocean.app   # Faz 13'te gerçek adresle güncellenir
    scope: RUN_TIME

services:
  - name: api
    github:
      repo: GITHUB_KULLANICI/fast-quiz-backend
      branch: main
      deploy_on_push: true
    dockerfile_path: Dockerfile
    http_port: 8000
    instance_count: 1
    instance_size_slug: apps-s-1vcpu-0.5gb   # en küçük boyut; panelde güncel adı kontrol et
    health_check:
      http_path: /api/v1/health/

jobs:
  - name: release
    kind: PRE_DEPLOY
    github:
      repo: GITHUB_KULLANICI/fast-quiz-backend
      branch: main
      deploy_on_push: true
    dockerfile_path: Dockerfile
    instance_size_slug: apps-s-1vcpu-0.5gb
    run_command: sh -c "python manage.py migrate --noinput && python manage.py createcachetable && python manage.py load_questions"

databases:
  - name: fast-quiz-db
    engine: PG
    version: "16"
    production: true
    cluster_name: fast-quiz-db
```
- `${APP_DOMAIN}`, `${APP_URL}`, `${fast-quiz-db.DATABASE_URL}` DigitalOcean'ın kendi doldurduğu değişkenlerdir.
- Spec dosyası **belge ve tek doğru kaynaktır**. Uygulama ya panelden (Create App → GitHub → repo seç, ayarları spec'e göre gir) ya da `doctl` ile oluşturulur:
  ```bash
  doctl apps create --spec .do/app.yaml
  ```
  Panelden yapılan değişiklik spec'e de işlenmeli (panelde **Settings → App Spec**'ten güncel hâli görülebilir).

### İlk kurulum sırası (kullanıcı yapar, Claude tarif eder)
1. GitHub'da `fast-quiz-backend` reposunu oluştur ve push et.
2. DO panelinde **Databases → Create → PostgreSQL 16, Frankfurt**, adı `fast-quiz-db`.
3. **Apps → Create App** → GitHub reposu → Dockerfile algılanır → spec'teki ayarlar, PRE_DEPLOY job, veritabanını bağla.
4. `SECRET_KEY`'i **Encrypted** olarak gir. Üretmek için:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
5. Deploy bitince: `https://<app-adresi>/api/v1/health/`.
6. Süper kullanıcı: panelde **Console** sekmesi → `python manage.py createsuperuser`.

### Bilinen riskler (Faz 12'de kontrol et)
- **Health check 400 dönerse:** DO'nun health check isteği beklenmeyen bir `Host` ile geliyor olabilir → Runtime Logs'ta `DisallowedHost` ara; çözümü kullanıcıyla birlikte seç.
- **Throttle herkesi aynı IP sanıyorsa:** `NUM_PROXIES` değerini loglardaki `X-Forwarded-For` başlığına göre düzelt.
- **Veritabanı bağlantı hatası:** veritabanının "Trusted Sources" listesinde app'in olduğunu ve `DATABASE_SSL_REQUIRE=True` olduğunu kontrol et.

---

## 9. Mobil Uygulama İçin Kurallar (şimdiden)

- Uçların şekli `PROJE.md` Bölüm 6'dan sapmaz; frontend'e özel kısayol uç ekleme.
- Yanıtlarda istemcinin saatine bağlı bilgi yok; süre her zaman `remaining_ms` olarak.
- Çerez, oturum, CSRF'e bağlı hiçbir şey yok — her şey `Authorization: Bearer` ile.
- Kırıcı değişiklik → `/api/v2/`. `v1` alanlarının adı/tipi değiştirilmez; yeni alan eklemek serbesttir.
