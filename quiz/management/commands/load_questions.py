"""
Load questions from quiz/data/questions/*.json into the database.

    python manage.py load_questions

- Idempotent: categories are matched by slug, questions by (category, text).
- Validates every file first; on any error nothing is written.
- Questions that disappeared from a file are deactivated, not deleted.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from quiz.models import Category, Choice, Question

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "questions"

REQUIRED_CHOICES = 4
REQUIRED_CORRECT = 1

# Hard limits come from the model fields; soft limits keep questions readable in 5 seconds.
MAX_QUESTION_LEN = Question._meta.get_field("text").max_length
MAX_CHOICE_LEN = Choice._meta.get_field("text").max_length
SOFT_QUESTION_LEN = 90
SOFT_CHOICE_LEN = 30

CATEGORY_FIELDS = {
    "slug": Category._meta.get_field("slug").max_length,
    "name": Category._meta.get_field("name").max_length,
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
        category, _ = Category.objects.update_or_create(
            slug=cat["slug"],
            defaults={
                "name": cat["name"],
                "description": cat.get("description", ""),
                "color": cat["color"],
                "order": cat["order"],
                "is_active": True,
            },
        )

        created = updated = 0
        for item in data["questions"]:
            question, was_created = Question.objects.update_or_create(
                category=category, text=item["text"], defaults={"is_active": True}
            )
            changed = sync_choices(question, item["choices"])
            if was_created:
                created += 1
            elif changed:
                updated += 1

        texts = [item["text"] for item in data["questions"]]
        deactivated = (
            category.questions.filter(is_active=True).exclude(text__in=texts).update(is_active=False)
        )

        active = category.questions.filter(is_active=True).count()
        self.stdout.write(
            f"{data['file']}: {created} yeni, {updated} güncellendi, "
            f"{deactivated} pasifleştirildi, {active} aktif soru."
        )
        needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
        if active < needed:
            self.stdout.write(
                self.style.WARNING(
                    f"Uyarı: '{category.name}' kategorisinde {active} aktif soru var, "
                    f"bir quiz için {needed} gerekiyor."
                )
            )


def sync_choices(question, choices):
    """Rewrite the choices only if they differ, so unchanged questions keep their choice ids."""
    wanted = [(c["text"], bool(c.get("correct", False)), i) for i, c in enumerate(choices)]
    current = list(question.choices.values_list("text", "is_correct", "order"))
    if current == wanted:
        return False

    question.choices.all().delete()
    Choice.objects.bulk_create(
        Choice(question=question, text=text, is_correct=correct, order=order)
        for text, correct, order in wanted
    )
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
    validate_category(name, data.get("category"), errors)

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
        text = clean_text(item, "text")
        if not text:
            errors.append(f"{where}: soru metni boş.")
            continue
        if len(text) > MAX_QUESTION_LEN:
            errors.append(f"{where}: soru metni {MAX_QUESTION_LEN} karakterden uzun.")
        elif len(text) > SOFT_QUESTION_LEN:
            warnings.append(f"{where}: soru {len(text)} karakter, ~{SOFT_QUESTION_LEN} önerilir.")
        if text in seen_texts:
            errors.append(f"{where}: aynı soru metni dosyada iki kez var.")
        seen_texts.add(text)
        validate_choices(where, item.get("choices"), errors, warnings)

    return data


def validate_category(name, cat, errors):
    if not isinstance(cat, dict):
        errors.append(f"{name}: 'category' nesnesi eksik.")
        return
    for field, max_len in CATEGORY_FIELDS.items():
        value = clean_text(cat, field)
        if not value:
            errors.append(f"{name}: kategori '{field}' alanı boş.")
        elif len(value) > max_len:
            errors.append(f"{name}: kategori '{field}' alanı {max_len} karakterden uzun.")
    if not isinstance(cat.get("order"), int) or cat["order"] < 0:
        errors.append(f"{name}: kategori 'order' alanı 0 veya pozitif bir tam sayı olmalı.")


def validate_choices(where, choices, errors, warnings):
    if not isinstance(choices, list) or len(choices) != REQUIRED_CHOICES:
        count = len(choices) if isinstance(choices, list) else 0
        errors.append(f"{where}: tam {REQUIRED_CHOICES} şık olmalı (şu an {count}).")
        return

    texts = []
    for letter, choice in zip("ABCD", choices):
        if not isinstance(choice, dict):
            errors.append(f"{where}, şık {letter}: şık bir nesne olmalı.")
            return
        text = clean_text(choice, "text")
        if not text:
            errors.append(f"{where}, şık {letter}: şık metni boş.")
        elif len(text) > MAX_CHOICE_LEN:
            errors.append(f"{where}, şık {letter}: {MAX_CHOICE_LEN} karakterden uzun.")
        elif len(text) > SOFT_CHOICE_LEN:
            warnings.append(f"{where}, şık {letter}: {len(text)} karakter, ~{SOFT_CHOICE_LEN} önerilir.")
        texts.append(text)

    if len(set(texts)) != len(texts):
        errors.append(f"{where}: aynı şık metni iki kez var.")

    correct = sum(1 for c in choices if c.get("correct") is True)
    if correct != REQUIRED_CORRECT:
        errors.append(f"{where}: tam {REQUIRED_CORRECT} doğru şık olmalı (şu an {correct}).")


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
            value = data["category"].get(field) if isinstance(data.get("category"), dict) else None
            if not value:
                continue
            if value in seen:
                errors.append(
                    f"{data['file']}: kategori '{field}' değeri '{value}' {seen[value]} dosyasında da var."
                )
            seen[value] = data["file"]
