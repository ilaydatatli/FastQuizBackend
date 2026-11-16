"""Multi-language support (PROJE.md section 12): tr is the default, en/es are translations."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.cache import cache
from django.core.management import CommandError, call_command
from rest_framework.test import APITestCase

from quiz import services
from quiz.models import Category, Choice, Question, QuizSession, Score

from .factories import make_category, make_question, make_score, make_session


def translate(question, language):
    """Give a question and its choices a translation, e.g. 'Soru? (en)'."""
    setattr(question, f"text_{language}", f"{question.text} ({language})")
    question.save()
    for choice in question.choices.all():
        setattr(choice, f"text_{language}", f"{choice.text} ({language})")
        choice.save()
    return question


def make_questions(category, n, translated_to=(), start=0):
    questions = []
    for i in range(start, start + n):
        question = make_question(category, text=f"{category.slug} sorusu {i + 1}?")
        for language in translated_to:
            translate(question, language)
        questions.append(question)
    return questions


class CategoryLanguageTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.software = make_category("yazilim", name="Yazılım", order=1)
        self.software.name_en, self.software.description_en = "Software", "Code and tools"
        self.software.save()
        make_questions(self.software, 20, translated_to=["en", "es"])

        countries = make_category("ulkeler", name="Ülkeler", color="orange", order=2)
        countries.name_en = "Countries"
        countries.save()
        make_questions(countries, 20)
        make_questions(countries, 5, translated_to=["en"], start=20)  # only 5 in English

    def get(self, query=""):
        return self.client.get(f"/api/v1/categories/{query}")

    def test_default_is_turkish(self):
        body = self.get().json()
        self.assertEqual([(c["name"], c["question_count"]) for c in body], [("Yazılım", 20), ("Ülkeler", 25)])

    def test_english_lists_only_categories_with_enough_english_questions(self):
        body = self.get("?lang=en").json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["slug"], "yazilim")
        self.assertEqual(body[0]["name"], "Software")
        self.assertEqual(body[0]["description"], "Code and tools")
        self.assertEqual(body[0]["question_count"], 20)

    def test_missing_category_translation_falls_back_to_turkish(self):
        body = self.get("?lang=es").json()  # questions exist in Spanish, the name does not
        self.assertEqual(body[0]["name"], "Yazılım")

    def test_unknown_language_is_a_validation_error(self):
        response = self.get("?lang=de")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")


class PlayInLanguageTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.category = make_category("yazilim", name="Yazılım")
        self.category.name_en = "Software"
        self.category.save()
        make_questions(self.category, 22, translated_to=["en"])
        make_questions(self.category, 10, start=22)  # Turkish-only questions

    def start(self, **body):
        return self.client.post("/api/v1/quizzes/", {"category": "yazilim", **body}, format="json")

    def test_language_defaults_to_turkish(self):
        body = self.start().json()
        self.assertEqual(body["language"], "tr")
        self.assertEqual(body["category"]["name"], "Yazılım")

    def test_english_quiz_uses_only_english_questions(self):
        response = self.start(language="en")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["language"], "en")
        self.assertEqual(body["category"]["name"], "Software")

        session = QuizSession.objects.get(id=body["quiz_id"])
        self.assertEqual(session.language, "en")
        picked = [item.question for item in session.items.select_related("question")]
        self.assertEqual(len(picked), 20)
        self.assertTrue(all(q.text_en for q in picked))

    def test_current_question_is_in_the_quiz_language(self):
        body = self.start(language="en").json()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {body['token']}"}
        current = self.client.get(f"/api/v1/quizzes/{body['quiz_id']}/current/", **auth).json()

        self.assertTrue(current["question"]["text"].endswith("(en)"))
        self.assertTrue(all(c["text"].endswith("(en)") for c in current["question"]["choices"]))

    def test_not_enough_questions_in_that_language(self):
        response = self.start(language="es")  # no Spanish questions
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "NOT_ENOUGH_QUESTIONS")

    def test_unknown_language_is_a_validation_error(self):
        response = self.start(language="de")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")


class ResultAndLeaderboardLanguageTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.category = make_category("yazilim", name="Yazılım")
        self.category.name_en = "Software"
        self.category.save()
        make_questions(self.category, 20, translated_to=["en"])

    def finished_quiz(self, language):
        session, token = services.start_quiz("yazilim", language)
        session.status = QuizSession.Status.FINISHED
        session.points, session.correct_count = 2000, 12
        session.finished_at = session.started_at
        session.save()
        return session, {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_result_category_name_is_in_the_quiz_language(self):
        session, auth = self.finished_quiz("en")
        body = self.client.get(f"/api/v1/quizzes/{session.id}/result/", **auth).json()
        self.assertEqual(body["category"]["name"], "Software")

    def test_saved_score_keeps_the_quiz_language(self):
        session, auth = self.finished_quiz("en")
        self.client.post(
            f"/api/v1/quizzes/{session.id}/score/", {"nickname": "neonfox"}, format="json", **auth
        )
        self.assertEqual(Score.objects.get().language, "en")

    def test_leaderboard_is_shared_and_shows_each_language(self):
        make_score(make_session(self.category, status="finished", points=3000, correct_count=15),
                   nickname="ayse")
        english = make_session(self.category, status="finished", points=2500, correct_count=14,
                               language="en")
        make_score(english, nickname="john")
        Score.objects.filter(nickname="john").update(language="en")

        body = self.client.get("/api/v1/leaderboard/yazilim/?lang=en").json()
        self.assertEqual(body["category"]["name"], "Software")
        self.assertEqual(
            [(e["nickname"], e["language"]) for e in body["entries"]], [("ayse", "tr"), ("john", "en")]
        )


class LoadTranslationsTests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def question(self, n, languages=("tr", "en")):
        def text(base):
            return {lang: f"{base} {lang}" for lang in languages}

        return {
            "text": text(f"Soru {n}?"),
            "choices": [{"text": text(f"Şık {n}-{i}"), **({"correct": True} if i == 0 else {})}
                        for i in range(4)],
        }

    def write(self, questions, category_name=None):
        data = {
            "category": {
                "slug": "yazilim", "color": "cyan", "order": 1,
                "name": category_name or {"tr": "Yazılım", "en": "Software"},
                "description": {"tr": "Kod", "en": "Code"},
            },
            "questions": questions,
        }
        (self.dir / "yazilim.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load(self):
        call_command("load_questions", dir=str(self.dir), stdout=StringIO())

    def test_translations_are_stored(self):
        self.write([self.question(1), self.question(2, languages=("tr",))])
        self.load()

        category = Category.objects.get()
        self.assertEqual((category.name_en, category.description_en), ("Software", "Code"))
        translated = Question.objects.get(text="Soru 1? tr")
        self.assertEqual(translated.text_en, "Soru 1? en")
        self.assertEqual(translated.choices.get(is_correct=True).text_en, "Şık 1-0 en")
        self.assertEqual(Question.objects.get(text="Soru 2? tr").text_en, "")  # Turkish only

    def test_half_translated_question_is_an_error(self):
        question = self.question(1)
        del question["choices"][2]["text"]["en"]
        self.write([question])

        with self.assertRaisesMessage(CommandError, "'en' çevirisi eksik"):
            self.load()
        self.assertFalse(Question.objects.exists())

    def test_translated_question_needs_a_translated_category_name(self):
        self.write([self.question(1)], category_name={"tr": "Yazılım"})
        with self.assertRaisesMessage(CommandError, "kategorinin 'en' adı yok"):
            self.load()

    def test_unknown_language_code_is_an_error(self):
        self.write([self.question(1, languages=("tr", "de"))])
        with self.assertRaisesMessage(CommandError, "bilinmeyen dil kodu 'de'"):
            self.load()

    def test_choice_texts_change_when_only_a_translation_changes(self):
        self.write([self.question(1)])
        self.load()
        question = self.question(1)
        question["choices"][1]["text"]["en"] = "Fixed translation"
        self.write([question])
        self.load()

        self.assertTrue(Choice.objects.filter(text_en="Fixed translation").exists())
