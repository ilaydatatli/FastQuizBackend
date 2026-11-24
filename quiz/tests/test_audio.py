"""Sound questions (Faz 26): the sound plays first, then the answer time starts.
Fixed timing (see base.py): 5000 ms to answer + 1000 ms grace."""

from quiz.models import Question

from .base import QuizPlayTestCase

SOUND_MS = 3000


class SoundQuestionTests(QuizPlayTestCase):
    def setUp(self):
        super().setUp()
        Question.objects.filter(category=self.category).update(audio="/sounds/test.mp3", audio_ms=SOUND_MS)

    def test_current_sends_the_sound_and_a_full_timer(self):
        body = self.current(0).json()
        self.assertEqual(
            body["question"]["audio"],
            {"url": "/sounds/test.mp3", "duration_ms": SOUND_MS, "left_ms": SOUND_MS},
        )
        self.assertEqual(body["remaining_ms"], 5000)  # the timer has not started yet

    def test_refresh_during_and_after_the_sound(self):
        self.current(0)
        during = self.current(1200).json()
        self.assertEqual(during["question"]["audio"]["left_ms"], 1800)
        self.assertEqual(during["remaining_ms"], 5000)

        after = self.current(SOUND_MS + 1000).json()
        self.assertEqual(after["question"]["audio"]["left_ms"], 0)
        self.assertEqual(after["remaining_ms"], 4000)

    def test_answer_during_the_sound_gets_the_full_bonus(self):
        body = self.show_and_answer(0, 1000).json()
        self.assertTrue(body["is_correct"])
        self.assertEqual(body["points_awarded"], 200)

    def test_answer_time_is_counted_from_the_end_of_the_sound(self):
        body = self.show_and_answer(0, SOUND_MS + 4900).json()
        self.assertEqual(body["points_awarded"], 102)  # same as 4900 ms on a normal question

    def test_sound_time_does_not_count_as_late(self):
        # 6500 ms after showing would be late on a normal question, not with a 3 s sound.
        body = self.show_and_answer(0, 6500).json()
        self.assertTrue(body["is_correct"])
        self.assertFalse(body["timed_out"])

    def test_late_after_sound_plus_time_plus_grace(self):
        body = self.show_and_answer(0, SOUND_MS + 6001).json()
        self.assertFalse(body["is_correct"])
        self.assertTrue(body["timed_out"])

    def test_unanswered_sound_question_times_out_after_sound_plus_window(self):
        self.current(0)
        self.assertEqual(self.current(SOUND_MS + 6000).json()["position"], 0)
        self.assertEqual(self.current(SOUND_MS + 6001).json()["position"], 1)
