from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import path
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.response import Response
from rest_framework.test import APITestCase

from quiz.authentication import QuizTokenAuthentication
from quiz.models import QuizSession, SessionQuestion
from quiz.services import hash_token, start_quiz
from quiz.throttles import QuizStartThrottle

from .factories import make_category, make_question_set

URL = "/api/v1/quizzes/"


class QuizStartTests(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        self.category = make_category(slug="yazilim", name="Yazılım", color="cyan")
        make_question_set(self.category, n=20)

    def start(self, slug="yazilim"):
        return self.client.post(URL, {"category": slug}, format="json")

    def test_start_returns_contract_shape(self):
        response = self.start()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            set(body),
            {"quiz_id", "token", "category", "language", "total_questions", "time_limit_ms", "expires_at", "room"},
        )
        self.assertEqual(body["category"], {"slug": "yazilim", "name": "Yazılım", "color": "cyan"})
        self.assertEqual(body["total_questions"], 20)
        self.assertEqual(body["time_limit_ms"], settings.FAST_QUIZ["TIME_LIMIT_MS"])
        self.assertTrue(body["expires_at"].endswith("+03:00"))  # Europe/Istanbul
        self.assertGreaterEqual(len(body["token"]), 40)

    def test_session_has_20_unique_questions_in_positions_0_to_19(self):
        body = self.start().json()

        session = QuizSession.objects.get(id=body["quiz_id"])
        self.assertEqual(session.status, QuizSession.Status.ACTIVE)
        self.assertEqual(session.current_index, 0)
        items = list(session.items.order_by("position"))
        self.assertEqual([item.position for item in items], list(range(20)))
        self.assertEqual(len({item.question_id for item in items}), 20)
        for item in items:
            self.assertIsNone(item.shown_at)  # time starts only when the question is first sent

    def test_choice_order_is_a_permutation_of_the_questions_choices(self):
        body = self.start().json()

        for item in SessionQuestion.objects.filter(session_id=body["quiz_id"]):
            own_ids = sorted(item.question.choices.values_list("id", flat=True))
            self.assertEqual(sorted(item.choice_order), own_ids)

    def test_raw_token_is_not_stored(self):
        body = self.start().json()

        session = QuizSession.objects.get(id=body["quiz_id"])
        self.assertNotEqual(session.token_hash, body["token"])
        self.assertEqual(session.token_hash, hash_token(body["token"]))
        stored = [str(v) for v in QuizSession.objects.values_list(flat=False).get(id=session.id)]
        self.assertNotIn(body["token"], stored)

    def test_each_quiz_gets_a_different_token(self):
        first, second = self.start().json(), self.start().json()
        self.assertNotEqual(first["token"], second["token"])
        self.assertNotEqual(first["quiz_id"], second["quiz_id"])

    def test_response_never_contains_is_correct(self):
        self.assertNotIn("is_correct", self.start().content.decode())

    def test_expires_at_is_started_at_plus_ttl(self):
        body = self.start().json()
        session = QuizSession.objects.get(id=body["quiz_id"])
        expected = session.started_at + timedelta(minutes=settings.FAST_QUIZ["SESSION_TTL_MINUTES"])
        self.assertEqual(parse_datetime(body["expires_at"]), expected)

    def test_only_active_questions_are_picked_from_a_bigger_pool(self):
        extra = make_question_set(make_category(slug="buyuk", order=2), n=25)
        for question in extra[:5]:
            question.is_active = False
            question.save()

        body = self.start("buyuk").json()

        picked = set(
            SessionQuestion.objects.filter(session_id=body["quiz_id"]).values_list(
                "question_id", flat=True
            )
        )
        self.assertEqual(len(picked), 20)
        self.assertEqual(picked, {q.id for q in extra[5:]})

    def test_unknown_category_returns_404(self):
        response = self.start("yok-boyle")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CATEGORY_NOT_FOUND")

    def test_inactive_category_returns_404(self):
        self.category.is_active = False
        self.category.save()
        response = self.start()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CATEGORY_NOT_FOUND")

    def test_not_enough_questions_returns_409(self):
        make_question_set(make_category(slug="az", order=2), n=19)
        response = self.start("az")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "NOT_ENOUGH_QUESTIONS")
        self.assertEqual(QuizSession.objects.count(), 0)

    def test_missing_category_field_returns_validation_error(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_broken_json_returns_bad_request(self):
        response = self.client.post(URL, "{ bozuk", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "BAD_REQUEST")

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    @override_settings(FAST_QUIZ={**settings.FAST_QUIZ, "QUESTIONS_PER_QUIZ": 5})
    def test_question_count_comes_from_settings(self):
        body = self.start().json()
        self.assertEqual(body["total_questions"], 5)
        self.assertEqual(SessionQuestion.objects.filter(session_id=body["quiz_id"]).count(), 5)

    def test_starting_too_often_is_rate_limited(self):
        with patch.object(QuizStartThrottle, "THROTTLE_RATES", {"quiz_start": "2/hour"}):
            self.assertEqual(self.start().status_code, 201)
            self.assertEqual(self.start().status_code, 201)
            response = self.start()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")
        self.assertEqual(QuizSession.objects.count(), 2)


# A tiny endpoint used only by these tests, until the real quiz endpoints exist (Faz 5).
@api_view(["GET"])
@authentication_classes([QuizTokenAuthentication])
def whoami(request, quiz_id):
    return Response({"quiz_id": str(request.auth.id)})


urlpatterns = [path("test/<uuid:quiz_id>/", whoami)]


@override_settings(ROOT_URLCONF=__name__)
class QuizTokenAuthenticationTests(APITestCase):
    def setUp(self):
        cache.clear()
        category = make_category()
        make_question_set(category, n=20)
        self.session, self.token = start_quiz(category.slug)
        self.other_session, self.other_token = start_quiz(category.slug)

    def get(self, quiz_id, header=None):
        extra = {"HTTP_AUTHORIZATION": header} if header is not None else {}
        return self.client.get(f"/test/{quiz_id}/", **extra)

    def assert_invalid_token(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_TOKEN")

    def test_correct_token_opens_its_own_quiz(self):
        response = self.get(self.session.id, f"Bearer {self.token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"quiz_id": str(self.session.id)})

    def test_missing_header_is_401(self):
        response = self.get(self.session.id)
        self.assert_invalid_token(response)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_wrong_token_is_401(self):
        self.assert_invalid_token(self.get(self.session.id, "Bearer yanlis-token"))

    def test_other_quizs_token_is_401(self):
        self.assert_invalid_token(self.get(self.session.id, f"Bearer {self.other_token}"))

    def test_wrong_scheme_is_401(self):
        self.assert_invalid_token(self.get(self.session.id, f"Token {self.token}"))

    def test_token_hash_itself_does_not_work(self):
        self.assert_invalid_token(self.get(self.session.id, f"Bearer {self.session.token_hash}"))

    def test_unknown_quiz_is_404(self):
        response = self.get("00000000-0000-0000-0000-000000000000", f"Bearer {self.token}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_NOT_FOUND")
