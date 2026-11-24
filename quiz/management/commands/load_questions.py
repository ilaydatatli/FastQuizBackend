"""
Load questions from quiz/data/questions/*.json into the database.

    python manage.py load_questions

- Idempotent: categories are matched by slug, questions by (category, Turkish text).
- Validates every file first; on any error nothing is written.
- Questions that disappeared from a file are deactivated, not deleted.
- Texts are language dictionaries: {"tr": "...", "en": "...", "nl": "...", "es": "..."}. Turkish is
  required; a missing language means the question is not offered in that language.
  A plain string is accepted as Turkish only.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from quiz.models import DEFAULT_LANGUAGE, LANGUAGES, Category, Choice, Question

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "questions"

REQUIRED_CHOICES = 4
REQUIRED_CORRECT = 1
TRANSLATIONS = [lang for lang in LANGUAGES if lang != DEFAULT_LANGUAGE]  # en, nl, es

# Hard limits come from the model fields; soft limits keep questions quick to read.
MAX_QUESTION_LEN = Question._meta.get_field("text").max_length
MAX_CHOICE_LEN = Choice._meta.get_field("text").max_length
MAX_NAME_LEN = Category._meta.get_field("name").max_length
MAX_DESCRIPTION_LEN = Category._meta.get_field("description").max_length
SOFT_QUESTION_LEN = 90
SOFT_CHOICE_LEN = 30

PLAIN_CATEGORY_FIELDS = {
    "slug": Category._meta.get_field("slug").max_length,
    "color": Category._meta.get_field("color").max_length,
}


class Command(BaseCommand):
    help = "quiz/data/questions/ altındaki JSON dosyalarından soruları yükler."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=str(DEFAULT_DIR),
            help="JSON dosyalarının bulunduğu klasör (varsayılan: quiz/data/questions).",
        )

    def handle(self, *args, **options):
        folder = Path(options["dir"])
        paths = sorted(folder.glob("*.json"))
        if not paths:
            raise CommandError(f"{folder} içinde JSON dosyası bulunamadı.")

        errors, warnings = [], []
        files = [parse_file(path, errors, warnings) for path in paths]
        check_cross_file_duplicates(files, errors)

        if errors:
            raise CommandError(
                "Hiçbir şey yazılmadı, önce şu hataları düzelt:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"Uyarı: {warning}"))

        with transaction.atomic():
            for data in files:
                self.load_file(data)

    def load_file(self, data):
        cat = data["category"]
        name, description = cat["name"], cat.get("description", {})
        category, _ = Category.objects.update_or_create(
            slug=cat["slug"],
            defaults={
                "name": name[DEFAULT_LANGUAGE],
                "description": description.get(DEFAULT_LANGUAGE, ""),
                **{f"name_{lang}": name.get(lang, "") for lang in TRANSLATIONS},
                **{f"description_{lang}": description.get(lang, "") for lang in TRANSLATIONS},
                "color": cat["color"],
                "order": cat["order"],
                "is_active": True,
            },
        )

        created = updated = 0
        for item in data["questions"]:
            text = item["text"]
            question, was_created = Question.objects.update_or_create(
                category=category,
                text=text[DEFAULT_LANGUAGE],
                defaults={
                    "is_active": True,
                    **{f"text_{lang}": text.get(lang, "") for lang in TRANSLATIONS},
                    "audio": item.get("audio", ""),
                    "audio_ms": item.get("audio_ms", 0),
                },
            )
            changed = sync_choices(question, item["choices"])
            if was_created:
                created += 1
            elif changed:
                updated += 1

        texts = [item["text"][DEFAULT_LANGUAGE] for item in data["questions"]]
        deactivated = (
            category.questions.filter(is_active=True).exclude(text__in=texts).update(is_active=False)
        )

        active = category.questions.filter(is_active=True)
        counts = {DEFAULT_LANGUAGE: active.count()}
        for lang in TRANSLATIONS:
            counts[lang] = active.exclude(**{f"text_{lang}": ""}).count()
        per_language = ", ".join(f"{lang}: {count}" for lang, count in counts.items())
        self.stdout.write(
            f"{data['file']}: {created} yeni, {updated} güncellendi, "
            f"{deactivated} pasifleştirildi, aktif soru ({per_language})."
        )
        needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
        for lang, count in counts.items():
            if lang == DEFAULT_LANGUAGE:
                if count < needed:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Uyarı: '{category.name}' kategorisinde {count} aktif soru var, "
                            f"bir quiz için {needed} gerekiyor."
                        )
                    )
            elif 0 < count < needed:
                self.stdout.write(
                    self.style.WARNING(
                        f"Uyarı: '{category.name}' kategorisinde '{lang}' dilinde {count} soru var, "
                        f"bir quiz için {needed} gerekiyor (bu dilde listelenmez)."
                    )
                )


def sync_choices(question, choices):
    """Rewrite the choices only if they differ, so unchanged questions keep their choice ids."""
    fields = ["text", *(f"text_{lang}" for lang in TRANSLATIONS), "is_correct", "order"]
    wanted = [
        (
            c["text"][DEFAULT_LANGUAGE],
            *(c["text"].get(lang, "") for lang in TRANSLATIONS),
            bool(c.get("correct", False)),
            i,
        )
        for i, c in enumerate(choices)
    ]
    current = list(question.choices.values_list(*fields))
    if current == wanted:
        return False

    question.choices.all().delete()
    Choice.objects.bulk_create(Choice(question=question, **dict(zip(fields, row))) for row in wanted)
    return True


def parse_file(path, errors, warnings):
    """Read and validate one file. Appends messages to errors/warnings; returns the data."""
    name = path.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append(f"{name}: geçerli bir JSON değil ({exc}).")
        return {"file": name, "category": {}, "questions": []}

    if not isinstance(data, dict):
        errors.append(f"{name}: en üst düzey bir nesne ({{...}}) olmalı.")
        return {"file": name, "category": {}, "questions": []}

    data["file"] = name
    category_languages = validate_category(name, data.get("category"), errors)

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append(f"{name}: 'questions' boş olmayan bir liste olmalı.")
        data["questions"] = []
        return data

    seen_texts = set()
    for number, item in enumerate(questions, start=1):
        where = f"{name}, soru {number}"
        if not isinstance(item, dict):
            errors.append(f"{where}: soru bir nesne olmalı.")
            continue
        text = translations(item, "text", where, errors)
        if not text.get(DEFAULT_LANGUAGE):
            errors.append(f"{where}: soru metni boş.")
            continue
        for lang, value in text.items():
            label = where if lang == DEFAULT_LANGUAGE else f"{where} [{lang}]"
            if len(value) > MAX_QUESTION_LEN:
                errors.append(f"{label}: soru metni {MAX_QUESTION_LEN} karakterden uzun.")
            elif len(value) > SOFT_QUESTION_LEN:
                warnings.append(f"{label}: soru {len(value)} karakter, ~{SOFT_QUESTION_LEN} önerilir.")
            if lang != DEFAULT_LANGUAGE and lang not in category_languages:
                errors.append(f"{label}: kategorinin '{lang}' adı yok; önce kategori adını çevir.")
        if text[DEFAULT_LANGUAGE] in seen_texts:
            errors.append(f"{where}: aynı soru metni dosyada iki kez var.")
        seen_texts.add(text[DEFAULT_LANGUAGE])
        validate_choices(where, item.get("choices"), set(text), errors, warnings)
        validate_audio(where, item, errors)

    return data


AUDIO_MS_RANGE = (1000, 20000)


def validate_audio(where, item, errors):
    """Optional sound (Faz 26): "audio": "/sounds/x.mp3" and "audio_ms": its length, together."""
    audio, audio_ms = item.get("audio"), item.get("audio_ms")
    if audio is None and audio_ms is None:
        return
    if not isinstance(audio, str) or not audio.startswith("/sounds/") or len(audio) > 200:
        errors.append(f"{where}: 'audio' /sounds/ ile başlayan bir yol olmalı (en fazla 200 karakter).")
    low, high = AUDIO_MS_RANGE
    if not isinstance(audio_ms, int) or isinstance(audio_ms, bool) or not low <= audio_ms <= high:
        errors.append(f"{where}: 'audio_ms' {low}–{high} arası bir tam sayı olmalı (sesin süresi).")


def validate_category(name, cat, errors):
    """Validate the category; returns the languages its name is available in."""
    if not isinstance(cat, dict):
        errors.append(f"{name}: 'category' nesnesi eksik.")
        return set()
    for field, max_len in PLAIN_CATEGORY_FIELDS.items():
        value = clean_text(cat, field)
        if not value:
            errors.append(f"{name}: kategori '{field}' alanı boş.")
        elif len(value) > max_len:
            errors.append(f"{name}: kategori '{field}' alanı {max_len} karakterden uzun.")
    if not isinstance(cat.get("order"), int) or cat["order"] < 0:
        errors.append(f"{name}: kategori 'order' alanı 0 veya pozitif bir tam sayı olmalı.")

    names = translations(cat, "name", f"{name}, kategori", errors)
    if not names.get(DEFAULT_LANGUAGE):
        errors.append(f"{name}: kategori 'name' alanı boş.")
    for lang, value in names.items():
        if len(value) > MAX_NAME_LEN:
            errors.append(f"{name}: kategori 'name' alanı [{lang}] {MAX_NAME_LEN} karakterden uzun.")
    descriptions = translations(cat, "description", f"{name}, kategori", errors)
    for lang, value in descriptions.items():
        if len(value) > MAX_DESCRIPTION_LEN:
            errors.append(
                f"{name}: kategori açıklaması [{lang}] {MAX_DESCRIPTION_LEN} karakterden uzun."
            )
    return set(names)


def validate_choices(where, choices, languages, errors, warnings):
    """4 choices, 1 correct; every choice must exist in every language the question has."""
    if not isinstance(choices, list) or len(choices) != REQUIRED_CHOICES:
        count = len(choices) if isinstance(choices, list) else 0
        errors.append(f"{where}: tam {REQUIRED_CHOICES} şık olmalı (şu an {count}).")
        return

    texts_by_language = {lang: [] for lang in languages}
    for letter, choice in zip("ABCD", choices):
        label = f"{where}, şık {letter}"
        if not isinstance(choice, dict):
            errors.append(f"{label}: şık bir nesne olmalı.")
            return
        text = translations(choice, "text", label, errors)
        extra = set(text) - languages
        if extra:
            errors.append(f"{label}: soruda olmayan dilde metin var ({', '.join(sorted(extra))}).")
        for lang in sorted(languages):
            value = text.get(lang, "")
            if not value:
                if lang == DEFAULT_LANGUAGE:
                    errors.append(f"{label}: şık metni boş.")
                else:
                    errors.append(f"{label}: '{lang}' çevirisi eksik (soru bu dilde çevrilmiş).")
                continue
            tag = label if lang == DEFAULT_LANGUAGE else f"{label} [{lang}]"
            if len(value) > MAX_CHOICE_LEN:
                errors.append(f"{tag}: {MAX_CHOICE_LEN} karakterden uzun.")
            elif len(value) > SOFT_CHOICE_LEN:
                warnings.append(f"{tag}: {len(value)} karakter, ~{SOFT_CHOICE_LEN} önerilir.")
            texts_by_language[lang].append(value)

    for lang, texts in texts_by_language.items():
        if len(set(texts)) != len(texts):
            tag = where if lang == DEFAULT_LANGUAGE else f"{where} [{lang}]"
            errors.append(f"{tag}: aynı şık metni iki kez var.")

    correct = sum(1 for c in choices if c.get("correct") is True)
    if correct != REQUIRED_CORRECT:
        errors.append(f"{where}: tam {REQUIRED_CORRECT} doğru şık olmalı (şu an {correct}).")


def translations(obj, key, where, errors):
    """
    Normalize obj[key] in place to a {language: text} dict without empty values.
    A plain string counts as Turkish. Unknown language codes are errors.
    """
    value = obj.get(key)
    if isinstance(value, str):
        value = {DEFAULT_LANGUAGE: value}
    if not isinstance(value, dict):
        obj[key] = {}
        return obj[key]
    cleaned = {}
    for lang, text in value.items():
        if lang not in LANGUAGES:
            errors.append(f"{where}: bilinmeyen dil kodu '{lang}' (geçerli: {', '.join(LANGUAGES)}).")
            continue
        if isinstance(text, str) and text.strip():
            cleaned[lang] = text.strip()
    obj[key] = cleaned
    return cleaned


def clean_text(obj, key):
    """Strip surrounding spaces in place so the stored text is tidy."""
    value = obj.get(key)
    if not isinstance(value, str):
        return ""
    obj[key] = value.strip()
    return obj[key]


def check_cross_file_duplicates(files, errors):
    for field in ("slug", "name"):
        seen = {}
        for data in files:
            cat = data.get("category")
            value = cat.get(field) if isinstance(cat, dict) else None
            if isinstance(value, dict):
                value = value.get(DEFAULT_LANGUAGE)
            if not value:
                continue
            if value in seen:
                errors.append(
                    f"{data['file']}: kategori '{field}' değeri '{value}' {seen[value]} dosyasında da var."
                )
            seen[value] = data["file"]
