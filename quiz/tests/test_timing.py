from datetime import timedelta

from django.test import SimpleTestCase

from quiz.models import QuizSession
from quiz.services import calculate_points

from .base import QuizPlayTestCase


class CalculatePointsTests(SimpleTestCase):
    def test_points_by_elapsed_time(self):
        cases = {
            0: 200,  # instant: full bonus
            1600: 168,  # remaining 3400 -> bonus 68 (PROJE.md example)
            2500: 150,
            4900: 102,
            4975: 101,  # bonus 0.5 rounds up
            4999: 100,
            5000: 100,
            5999: 100,  # grace: accepted, no bonus
            6000: 100,
        }
        for elapsed, expected in cases.items():
            with self.subTest(elapsed=elapsed):
                self.assertEqual(calculate_points(elapsed), expected)


class AnswerTimingTests(QuizPlayTestCase):
    def assert_answer(self, after_ms, *, correct, timed_out, points):
        response = self.show_and_answer(0, after_ms, correct=True)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["is_correct"], correct)
        self.assertEqual(body["timed_out"], timed_out)
        self.assertEqual(body["points_awarded"], points)
        self.assertEqual(body["points"], points)

    def test_correct_answer_at_4900_ms_gets_speed_bonus(self):
        self.assert_answer(4900, correct=True, timed_out=False, points=102)

    def test_correct_answer_at_4999_ms(self):
        self.assert_answer(4999, correct=True, timed_out=False, points=100)

    def test_correct_answer_at_5000_ms(self):
        self.assert_answer(5000, correct=True, timed_out=False, points=100)

    def test_correct_answer_in_grace_at_5800_ms_gets_no_bonus(self):
        self.assert_answer(5800, correct=True, timed_out=False, points=100)

    def test_correct_answer_at_5999_ms(self):
        self.assert_answer(5999, correct=True, timed_out=False, points=100)

    def test_correct_answer_at_6000_ms_is_last_accepted_moment(self):
        self.assert_answer(6000, correct=True, timed_out=False, points=100)

    def test_answer_at_6001_ms_is_timed_out(self):
        self.assert_answer(6001, correct=False, timed_out=True, points=0)

    def test_answer_at_6100_ms_is_timed_out_even_if_correct(self):
        self.assert_answer(6100, correct=False, timed_out=True, points=0)
        self.assertFalse(self.item(0).is_correct)

    def test_wrong_answer_in_grace_is_wrong_not_timed_out(self):
        response = self.show_and_answer(0, 5800, correct=False)
        body = response.json()
        self.assertFalse(body["is_correct"])
        self.assertFalse(body["timed_out"])
        self.assertEqual(body["points_awarded"], 0)


class ShownAtTests(QuizPlayTestCase):
    def test_first_request_starts_the_clock(self):
        body = self.current(0).json()
        self.assertEqual(body["remaining_ms"], 5000)
        self.assertEqual(self.item(0).shown_at, self.t0)

    def test_refresh_does_not_reset_shown_at(self):
        first = self.current(0).json()
        second = self.current(1200).json()

        self.assertEqual(second["question"]["id"], first["question"]["id"])
        self.assertEqual(second["remaining_ms"], 3800)
        self.assertEqual(self.item(0).shown_at, self.t0)

    def test_remaining_never_goes_below_zero_during_grace(self):
        self.current(0)
        body = self.current(5500).json()
        self.assertEqual(body["position"], 0)  # still the same question
        self.assertEqual(body["remaining_ms"], 0)

    def test_points_are_measured_from_first_show_not_from_refresh(self):
        question_id = self.current(0).json()["question"]["id"]
        self.current(4000)  # refresh does not give extra time
        response = self.answer(4900, question_id, self.correct_choice_id(0))
        self.assertEqual(response.json()["points_awarded"], 102)


class LazyTimeoutTests(QuizPlayTestCase):
    def test_unanswered_question_times_out_on_next_request(self):
        self.current(0)

        body = self.current(6001).json()

        self.assertEqual(body["position"], 1)
        self.assertEqual(body["remaining_ms"], 5000)
        first = self.item(0)
        self.assertTrue(first.timed_out)
        self.assertFalse(first.is_correct)
        self.assertEqual(first.points, 0)
        self.assertIsNone(first.answered_at)
        self.assertEqual(self.item(1).shown_at, self.t0 + timedelta(milliseconds=6001))

    def test_at_exactly_6000_ms_question_is_still_current(self):
        self.current(0)
        self.assertEqual(self.current(6000).json()["position"], 0)

    def test_answering_a_lazily_timed_out_question_is_already_answered(self):
        question_id = self.current(0).json()["question"]["id"]
        self.current(7000)
        response = self.answer(7100, question_id, self.correct_choice_id(0))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ALREADY_ANSWERED")

    def test_lazy_timeout_on_last_question_finishes_quiz(self):
        for i in range(19):
            self.show_and_answer(i * 1000, 500)
        self.current(19_000)

        body = self.current(19_000 + 6001).json()

        self.assertEqual(body["status"], "finished")
        self.assertIsNone(body["question"])
        self.assertEqual(self.session().status, QuizSession.Status.FINISHED)


class ExpiryTests(QuizPlayTestCase):
    ttl_ms = 15 * 60 * 1000

    def test_quiz_expires_after_15_minutes(self):
        self.current(0)

        response = self.current(self.ttl_ms)  # t0 is 1 s after start -> past 15 min

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_EXPIRED")
        self.assertEqual(self.session().status, QuizSession.Status.EXPIRED)

    def test_quiz_just_before_15_minutes_is_still_active(self):
        response = self.current(self.ttl_ms - 1000)
        self.assertEqual(response.status_code, 200)

    def test_answer_after_expiry_is_rejected(self):
        question_id = self.current(0).json()["question"]["id"]
        response = self.answer(self.ttl_ms, question_id, self.correct_choice_id(0))
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_EXPIRED")
        self.assertEqual(self.session().points, 0)

    def test_expired_quiz_stays_expired(self):
        self.current(self.ttl_ms)
        response = self.current(0)  # even if the clock were earlier
        self.assertEqual(response.json()["error"]["code"], "QUIZ_EXPIRED")

    def test_finished_quiz_does_not_expire(self):
        for i in range(20):
            self.show_and_answer(i * 1000, 500)
        response = self.current(self.ttl_ms * 2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "finished")
