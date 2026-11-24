from unittest.mock import patch

from quiz import services
from quiz.models import Choice
from quiz.throttles import AnswerThrottle

from .base import QuizPlayTestCase


class CurrentQuestionTests(QuizPlayTestCase):
    def test_current_returns_contract_shape(self):
        response = self.current(0)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {"status", "position", "total_questions", "points", "question", "time_limit_ms", "remaining_ms"},
        )
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["position"], 0)
        self.assertEqual(body["total_questions"], 20)
        self.assertEqual(body["points"], 0)
        self.assertEqual(body["time_limit_ms"], 5000)
        self.assertEqual(set(body["question"]), {"id", "text", "choices", "audio"})
        self.assertIsNone(body["question"]["audio"])  # no sound on normal questions
        for choice in body["question"]["choices"]:
            self.assertEqual(set(choice), {"id", "text"})

    def test_choices_follow_the_sessions_shuffled_order(self):
        body = self.current(0).json()
        ids = [choice["id"] for choice in body["question"]["choices"]]
        self.assertEqual(ids, self.item(0).choice_order)

    def test_current_and_answer_never_leak_correct_choice_before_answering(self):
        text = self.current(0).content.decode()
        self.assertNotIn("is_correct", text)
        self.assertNotIn("correct", text)

    def test_wrong_answer_reveals_correct_choice_only_afterwards(self):
        body = self.show_and_answer(0, 1000, correct=False).json()
        self.assertFalse(body["is_correct"])
        self.assertEqual(body["correct_choice_id"], self.correct_choice_id(0))
        # The next question still does not leak anything.
        self.assertNotIn("correct", self.current(2000).content.decode())


class AnswerTests(QuizPlayTestCase):
    def test_correct_answer_returns_contract_shape_and_moves_on(self):
        response = self.show_and_answer(0, 1600)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body,
            {
                "question_id": self.item(0).question_id,
                "is_correct": True,
                "timed_out": False,
                "correct_choice_id": self.correct_choice_id(0),
                "points_awarded": 168,
                "points": 168,
                "correct_count": 1,
                "position": 1,
                "finished": False,
            },
        )
        session = self.session()
        self.assertEqual((session.current_index, session.points, session.correct_count), (1, 168, 1))
        self.assertEqual(self.current(2000).json()["position"], 1)

    def test_null_choice_means_time_ran_out(self):
        question_id = self.current(0).json()["question"]["id"]

        body = self.answer(5000, question_id, None).json()

        self.assertTrue(body["timed_out"])
        self.assertFalse(body["is_correct"])
        self.assertEqual(body["points_awarded"], 0)
        self.assertEqual(body["position"], 1)
        self.assertIsNone(self.item(0).selected_choice)

    def test_wrong_question_id_is_mismatch(self):
        self.current(0)
        other_question_id = self.item(5).question_id

        response = self.answer(1000, other_question_id, self.correct_choice_id(5))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "QUESTION_MISMATCH")
        self.assertEqual(self.session().current_index, 0)

    def test_question_not_shown_yet_cannot_be_answered(self):
        response = self.answer(0, self.item(0).question_id, self.correct_choice_id(0))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "QUESTION_NOT_SHOWN")

    def test_second_answer_to_same_question_is_rejected(self):
        question_id = self.current(0).json()["question"]["id"]
        self.answer(1000, question_id, self.correct_choice_id(0))

        response = self.answer(1100, question_id, self.correct_choice_id(0))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ALREADY_ANSWERED")
        self.assertEqual(self.session().points, 180)  # counted once

    def test_choice_from_another_question_is_invalid(self):
        question_id = self.current(0).json()["question"]["id"]
        foreign_choice = Choice.objects.exclude(question_id=question_id).first()

        response = self.answer(1000, question_id, foreign_choice.id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_CHOICE")
        self.assertEqual(self.session().current_index, 0)

    def test_missing_fields_are_a_validation_error(self):
        self.current(0)
        with self.at(1000):
            response = self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/answers/",
                {"question_id": self.item(0).question_id},
                format="json",
                **self.auth(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_client_cannot_send_its_own_points(self):
        question_id = self.current(0).json()["question"]["id"]
        with self.at(4999):
            self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/answers/",
                {"question_id": question_id, "choice_id": self.correct_choice_id(0), "points": 4000},
                format="json",
                **self.auth(),
            )
        self.assertEqual(self.session().points, 100)

    def test_answering_too_often_is_rate_limited(self):
        question_id = self.current(0).json()["question"]["id"]
        with patch.object(AnswerThrottle, "THROTTLE_RATES", {"answer": "1/minute"}):
            self.answer(1000, question_id, self.correct_choice_id(0))
            response = self.answer(1100, question_id, self.correct_choice_id(0))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")


class TokenTests(QuizPlayTestCase):
    def test_wrong_token_is_rejected_on_both_endpoints(self):
        self.assertEqual(self.current(0, token="yanlis").status_code, 401)
        response = self.answer(0, self.item(0).question_id, None, token="yanlis")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_TOKEN")

    def test_token_of_another_quiz_is_rejected(self):
        _, other_token = services.start_quiz(self.category.slug)
        response = self.current(0, token=other_token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "INVALID_TOKEN")

    def test_missing_token_is_rejected(self):
        response = self.client.get(f"/api/v1/quizzes/{self.quiz_id}/current/")
        self.assertEqual(response.status_code, 401)


class FullQuizTests(QuizPlayTestCase):
    def test_play_all_20_questions(self):
        for i in range(20):
            body = self.show_and_answer(i * 1000, 1000).json()
            self.assertEqual(body["position"], i + 1)
            self.assertEqual(body["finished"], i == 19)

        self.assertEqual(body["points"], 20 * 180)
        self.assertEqual(body["correct_count"], 20)
        session = self.session()
        self.assertEqual(session.status, "finished")
        self.assertIsNotNone(session.finished_at)

        current = self.current(30_000).json()
        self.assertEqual(
            current,
            {"status": "finished", "position": 20, "total_questions": 20, "points": 3600, "question": None},
        )

    def test_answer_after_finish_is_rejected(self):
        for i in range(20):
            self.show_and_answer(i * 1000, 500)
        response = self.answer(30_000, self.item(19).question_id, self.correct_choice_id(19))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_FINISHED")

    def test_mixed_quiz_counts_points_and_correct_answers(self):
        self.show_and_answer(0, 0)  # 200
        self.show_and_answer(10_000, 2500, correct=False)  # 0
        question_id = self.current(20_000).json()["question"]["id"]
        self.answer(25_000, question_id, None)  # timed out
        body = self.show_and_answer(30_000, 2500).json()  # 150

        self.assertEqual(body["points"], 350)
        self.assertEqual(body["correct_count"], 2)
        self.assertEqual(body["position"], 4)
