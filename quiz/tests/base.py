from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APITestCase

from quiz import services
from quiz.models import QuizSession

from .factories import make_category, make_question_set


class QuizPlayTestCase(APITestCase):
    """
    Starts a 20-question quiz and offers helpers that call the API at a fake time.
    Times are milliseconds after `self.t0` (1 second after the quiz started).
    """

    def setUp(self):
        cache.clear()  # throttle counters
        self.category = make_category()
        make_question_set(self.category, n=20)
        session, self.token = services.start_quiz(self.category.slug)
        self.quiz_id = session.id
        self.t0 = session.started_at + timedelta(seconds=1)

    def at(self, ms):
        return patch("quiz.services.now", return_value=self.t0 + timedelta(milliseconds=ms))

    def auth(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.token}"}

    def current(self, ms=0, token=None):
        with self.at(ms):
            return self.client.get(f"/api/v1/quizzes/{self.quiz_id}/current/", **self.auth(token))

    def answer(self, ms, question_id, choice_id, token=None):
        with self.at(ms):
            return self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/answers/",
                {"question_id": question_id, "choice_id": choice_id},
                format="json",
                **self.auth(token),
            )

    def session(self):
        return QuizSession.objects.get(id=self.quiz_id)

    def item(self, position):
        return self.session().items.select_related("question").get(position=position)

    def correct_choice_id(self, position):
        return self.item(position).question.choices.get(is_correct=True).id

    def wrong_choice_id(self, position):
        return self.item(position).question.choices.filter(is_correct=False).first().id

    def show_and_answer(self, show_ms, answer_after_ms, correct=True):
        """Show the current question at show_ms, answer it answer_after_ms later."""
        body = self.current(show_ms).json()
        position = body["position"]
        choice = self.correct_choice_id(position) if correct else self.wrong_choice_id(position)
        return self.answer(show_ms + answer_after_ms, body["question"]["id"], choice)
