# Fast Quiz — Backend

Django 5.2 + Django REST Framework + PostgreSQL API'si. Tüm uçlar `/api/v1/` altında ve yalnızca JSON döner.
Proje dokümanı: [`../PROJE.md`](../PROJE.md) · Çalışma kuralları: [`CLAUDE.md`](CLAUDE.md)

## Kurulum (macOS)

PostgreSQL (bir kez):

```bash
brew install postgresql@16
brew services start postgresql@16
createdb fast_quiz
```

Proje:

```bash
cd ~/Desktop/fast-quiz/fast-quiz-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

## Ortam değişkenleri (`.env`)

| Değişken | Açıklama | Lokal örnek |
|---|---|---|
| `SECRET_KEY` | Django gizli anahtarı | `change-me` |
| `DEBUG` | Geliştirme modu (browsable API açılır) | `True` |
| `ALLOWED_HOSTS` | Virgülle ayrılmış host listesi | `localhost,127.0.0.1` |
| `DATABASE_URL` | PostgreSQL adresi | `postgres://localhost:5432/fast_quiz` |
| `DATABASE_SSL_REQUIRE` | Veritabanına SSL zorunlu mu | `False` (canlıda `True`) |
| `CORS_ALLOWED_ORIGINS` | API'yi tarayıcıdan çağırabilecek origin'ler | `http://localhost:5173` |
| `CSRF_TRUSTED_ORIGINS` | Yalnızca canlıda admin girişi için | boş |
| `USE_HTTPS` | Güvenli çerez + HSTS (Faz 11) | `False` |

## Testler

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

## curl örnekleri

```bash
curl -i http://localhost:8000/api/v1/health/
# {"status": "ok", "api_version": "v1"}

curl -i http://localhost:8000/api/v1/olmayan-uc/
# 404 {"error": {"code": "NOT_FOUND", "message": "Aradığın kaynak bulunamadı."}}

curl -i -H "Origin: http://localhost:5173" http://localhost:8000/api/v1/health/
# Access-Control-Allow-Origin: http://localhost:5173
```

## Hata biçimi

Tüm hatalar aynı şekildedir; istemci `code`'a bakar, `message` kullanıcıya gösterilebilir:

```json
{ "error": { "code": "NOT_FOUND", "message": "Aradığın kaynak bulunamadı." } }
```
