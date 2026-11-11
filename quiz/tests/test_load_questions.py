import copy
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from quiz.models import Category, Choice, Question


def question(text, correct_index=0):
    return {
        "text": text,
        "choices": [
            {"text": f"{text} şık {i + 1}", **({"correct": True} if i == correct_index else {})}
            for i in range(4)
        ],
    }


def file_data(slug="yazilim", name="Yazılım", n=3, order=1):
    return {
        "category": {"slug": slug, "name": name, "description": "Açıklama", "color": "cyan", "order": order},
        "questions": [question(f"{slug} sorusu {i + 1}?") for i in range(n)],
    }


class LoadQuestionsTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, filename, data):
        (self.dir / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load(self):
        out = StringIO()
        call_command("load_questions", dir=str(self.dir), stdout=out)
        return out.getvalue()

    def test_valid_file_is_loaded(self):
        self.write("yazilim.json", file_data(n=3))

        self.load()

        category = Category.objects.get(slug="yazilim")
        self.assertEqual(category.name, "Yazılım")
        self.assertEqual(category.color, "cyan")
        self.assertEqual(category.questions.count(), 3)
        for q in category.questions.all():
            self.assertEqual(q.choices.count(), 4)
            self.assertEqual(q.choices.filter(is_correct=True).count(), 1)

    def test_second_run_creates_no_duplicates_and_keeps_choice_ids(self):
        self.write("yazilim.json", file_data(n=3))
        self.load()
        choice_ids = set(Choice.objects.values_list("id", flat=True))

        output = self.load()

        self.assertEqual(Category.objects.count(), 1)
        self.assertEqual(Question.objects.count(), 3)
        self.assertEqual(set(Choice.objects.values_list("id", flat=True)), choice_ids)
        self.assertIn("0 yeni, 0 güncellendi", output)

    def test_changed_choices_are_rewritten(self):
        data = file_data(n=1)
        self.write("yazilim.json", data)
        self.load()

        data["questions"][0]["choices"][0]["text"] = "Yeni doğru şık"
        self.write("yazilim.json", data)
        output = self.load()

        q = Question.objects.get()
        self.assertEqual(q.choices.get(is_correct=True).text, "Yeni doğru şık")
        self.assertEqual(q.choices.count(), 4)
        self.assertIn("1 güncellendi", output)

    def test_category_fields_are_updated(self):
        self.write("yazilim.json", file_data())
        self.load()
        data = file_data()
        data["category"]["name"] = "Yazılım Dünyası"
        self.write("yazilim.json", data)

        self.load()

        self.assertEqual(Category.objects.get(slug="yazilim").name, "Yazılım Dünyası")

    def test_question_removed_from_file_is_deactivated_not_deleted(self):
        data = file_data(n=3)
        self.write("yazilim.json", data)
        self.load()

        removed = data["questions"].pop()
        self.write("yazilim.json", data)
        output = self.load()

        q = Question.objects.get(text=removed["text"])
        self.assertFalse(q.is_active)
        self.assertEqual(Question.objects.filter(is_active=True).count(), 2)
        self.assertIn("1 pasifleştirildi", output)

        # Putting it back in the file activates it again.
        data["questions"].append(removed)
        self.write("yazilim.json", data)
        self.load()
        q.refresh_from_db()
        self.assertTrue(q.is_active)

    def test_invalid_file_writes_nothing_at_all(self):
        self.write("biyoloji.json", file_data(slug="biyoloji", name="Biyoloji", order=2))
        bad = file_data()
        bad["questions"][1]["choices"][2]["correct"] = True  # two correct choices
        self.write("yazilim.json", bad)

        with self.assertRaises(CommandError) as ctx:
            self.load()

        self.assertIn("yazilim.json, soru 2", str(ctx.exception))
        self.assertIn("tam 1 doğru şık olmalı (şu an 2)", str(ctx.exception))
        self.assertEqual(Category.objects.count(), 0)  # the valid file was not written either
        self.assertEqual(Question.objects.count(), 0)

    def test_validation_errors(self):
        cases = {
            "three choices": (
                lambda d: d["questions"][0]["choices"].pop(),
                "soru 1: tam 4 şık olmalı (şu an 3)",
            ),
            "no correct choice": (
                lambda d: d["questions"][0]["choices"][0].pop("correct"),
                "soru 1: tam 1 doğru şık olmalı (şu an 0)",
            ),
            "empty question text": (
                lambda d: d["questions"][0].update(text="   "),
                "soru 1: soru metni boş",
            ),
            "empty choice text": (
                lambda d: d["questions"][0]["choices"][1].update(text=""),
                "soru 1, şık B: şık metni boş",
            ),
            "choice too long": (
                lambda d: d["questions"][0]["choices"][1].update(text="x" * 61),
                "soru 1, şık B: 60 karakterden uzun",
            ),
            "question too long": (
                lambda d: d["questions"][0].update(text="x" * 151),
                "soru 1: soru metni 150 karakterden uzun",
            ),
            "duplicate question": (
                lambda d: d["questions"][1].update(text=d["questions"][0]["text"]),
                "soru 2: aynı soru metni dosyada iki kez var",
            ),
            "duplicate choice": (
                lambda d: d["questions"][0]["choices"][1].update(
                    text=d["questions"][0]["choices"][2]["text"]
                ),
                "soru 1: aynı şık metni iki kez var",
            ),
            "missing slug": (
                lambda d: d["category"].pop("slug"),
                "kategori 'slug' alanı boş",
            ),
        }
        for label, (break_it, expected) in cases.items():
            with self.subTest(label):
                data = copy.deepcopy(file_data())
                break_it(data)
                self.write("yazilim.json", data)
                with self.assertRaises(CommandError) as ctx:
                    self.load()
                self.assertIn(expected, str(ctx.exception))
                self.assertEqual(Question.objects.count(), 0)

    def test_broken_json_is_reported(self):
        (self.dir / "yazilim.json").write_text("{ bozuk", encoding="utf-8")
        with self.assertRaises(CommandError) as ctx:
            self.load()
        self.assertIn("yazilim.json: geçerli bir JSON değil", str(ctx.exception))

    def test_same_slug_in_two_files_is_rejected(self):
        self.write("a.json", file_data(slug="yazilim", name="Yazılım"))
        self.write("b.json", file_data(slug="yazilim", name="Başka ad"))
        with self.assertRaises(CommandError) as ctx:
            self.load()
        self.assertIn("'yazilim' a.json dosyasında da var", str(ctx.exception))

    def test_empty_folder_is_an_error(self):
        with self.assertRaises(CommandError):
            self.load()

    def test_warns_when_category_has_too_few_questions(self):
        self.write("yazilim.json", file_data(n=3))
        output = self.load()
        needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
        self.assertIn(f"3 aktif soru var, bir quiz için {needed} gerekiyor", output)

    def test_warns_about_long_question(self):
        data = file_data(n=1)
        data["questions"][0]["text"] = "x" * 95 + "?"
        self.write("yazilim.json", data)
        output = self.load()
        self.assertIn("soru 96 karakter, ~90 önerilir", output)
        self.assertEqual(Question.objects.count(), 1)  # a warning does not block loading

    def test_surrounding_spaces_are_stripped(self):
        data = file_data(n=1)
        data["questions"][0]["text"] = "  Boşluklu soru?  "
        self.write("yazilim.json", data)
        self.load()
        self.assertTrue(Question.objects.filter(text="Boşluklu soru?").exists())


class BundledQuestionFilesTests(TestCase):
    """The real files in quiz/data/questions/ must load cleanly."""

    def test_all_bundled_files_load_without_warnings(self):
        out = StringIO()
        call_command("load_questions", stdout=out)

        self.assertNotIn("Uyarı", out.getvalue())
        slugs = set(Category.objects.values_list("slug", flat=True))
        self.assertEqual(
            slugs, {"yazilim", "yapay-zeka", "ulkeler", "biyoloji", "fotografcilik"}
        )
        needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
        for category in Category.objects.all():
            with self.subTest(category.slug):
                self.assertEqual(category.questions.filter(is_active=True).count(), needed)
