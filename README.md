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

### Bir quiz oynamak

```bash
curl http://localhost:8000/api/v1/categories/
```

Quiz başlat. Yanıttaki `quiz_id` ve `token` değerlerini aşağıda `QUIZ_ID` ve `TOKEN` yerine yaz:

```bash
curl -X POST http://localhost:8000/api/v1/quizzes/ -H "Content-Type: application/json" -d '{"category": "yazilim"}'
```

Şu anki soruyu al (ilk istekte 5 saniye başlar):

```bash
curl http://localhost:8000/api/v1/quizzes/QUIZ_ID/current/ -H "Authorization: Bearer TOKEN"
```

Cevap ver (`question.id` ve şıklardan birinin `id`'si). Cevap 6 saniyeden (5 sn + 1 sn tolerans) geç gelirse `timed_out: true` olur:

```bash
curl -X POST http://localhost:8000/api/v1/quizzes/QUIZ_ID/answers/ -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" -d '{"question_id": 1, "choice_id": 2}'
```

Süre doldu bildirimi için `"choice_id": null` gönderilir. 20 soru cevaplanınca `current` şunu döner: `{"status": "finished", ..., "question": null}`.

> İpucu: değerleri bir kez değişkene kaydet, sonra `$QUIZ` ve `$TOKEN` kullan:
> `QUIZ="..."` ve `TOKEN="..."`

### Sonuç, skor ve skor tablosu

Bitmiş quiz'in sonucu (bitmediyse `409 QUIZ_NOT_FINISHED`):

```bash
curl http://localhost:8000/api/v1/quizzes/$QUIZ/result/ -H "Authorization: Bearer $TOKEN"
```

Takma adla skor tablosuna kaydet (bir quiz yalnızca bir kez; takma ad 2–16 karakter, harf/rakam/boşluk/`_`/`-`):

```bash
curl -X POST http://localhost:8000/api/v1/quizzes/$QUIZ/score/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"nickname": "ilayda_99"}'
```

Bir kategorinin ilk 10'u (token gerekmez):

```bash
curl http://localhost:8000/api/v1/leaderboard/yazilim/
```

### Tüm uçlar

| Metot | Yol | Token |
|---|---|---|
| GET | `/api/v1/health/` | — |
| GET | `/api/v1/categories/` | — |
| POST | `/api/v1/quizzes/` | — |
| GET | `/api/v1/quizzes/{quiz_id}/current/` | ✅ |
| POST | `/api/v1/quizzes/{quiz_id}/answers/` | ✅ |
| GET | `/api/v1/quizzes/{quiz_id}/result/` | ✅ |
| POST | `/api/v1/quizzes/{quiz_id}/score/` | ✅ |
| GET | `/api/v1/leaderboard/{category_slug}/` | — |

Ayrıntılı yanıt şekilleri: `../PROJE.md` Bölüm 6.

## Hata biçimi

Tüm hatalar aynı şekildedir; istemci `code`'a bakar, `message` kullanıcıya gösterilebilir:

```json
{ "error": { "code": "NOT_FOUND", "message": "Aradığın kaynak bulunamadı." } }
```
