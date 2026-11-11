from django.conf import settings
from django.test import override_settings
from rest_framework.test import APITestCase

from quiz.models import Question

from .factories import make_category, make_question_set

URL = "/api/v1/categories/"


class CategoriesApiTests(APITestCase):
    def test_lists_playable_categories_in_order_with_contract_fields(self):
        second = make_category(slug="biyoloji", name="Biyoloji", color="lime", order=2)
        first = make_category(slug="yazilim", name="Yazılım", color="cyan", order=1)
        first.description = "Kod, araçlar, kavramlar"
        first.save()
        make_question_set(first, n=20)
        make_question_set(second, n=20)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "slug": "yazilim",
                    "name": "Yazılım",
                    "description": "Kod, araçlar, kavramlar",
                    "color": "cyan",
                    "question_count": 20,
                },
                {
                    "slug": "biyoloji",
                    "name": "Biyoloji",
                    "description": "",
                    "color": "lime",
                    "question_count": 20,
                },
            ],
        )

    def test_category_with_too_few_questions_is_hidden(self):
        make_question_set(make_category(slug="az"), n=19)
        self.assertEqual(self.client.get(URL).json(), [])

    def test_inactive_questions_are_not_counted(self):
        category = make_category()
        make_question_set(category, n=20)
        Question.objects.filter(id=category.questions.first().id).update(is_active=False)
        self.assertEqual(self.client.get(URL).json(), [])

    def test_extra_questions_are_counted(self):
        make_question_set(make_category(), n=25)
        self.assertEqual(self.client.get(URL).json()[0]["question_count"], 25)

    def test_inactive_category_is_hidden(self):
        make_question_set(make_category(is_active=False), n=20)
        self.assertEqual(self.client.get(URL).json(), [])

    @override_settings(FAST_QUIZ={**settings.FAST_QUIZ, "QUESTIONS_PER_QUIZ": 3})
    def test_needed_question_count_comes_from_settings(self):
        make_question_set(make_category(), n=3)
        self.assertEqual(len(self.client.get(URL).json()), 1)

    def test_post_is_not_allowed(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "METHOD_NOT_ALLOWED")
