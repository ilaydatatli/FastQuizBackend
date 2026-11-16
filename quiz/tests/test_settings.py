from django.conf import settings
from django.test import SimpleTestCase

from quiz.services import calculate_points


class GameSettingsTests(SimpleTestCase):
    """The real game values (other tests pin their own timing on purpose)."""

    def test_each_question_has_10_seconds(self):
        self.assertEqual(settings.FAST_QUIZ["TIME_LIMIT_MS"], 10000)
        self.assertEqual(settings.FAST_QUIZ["GRACE_MS"], 1000)

    def test_speed_bonus_scales_to_10_seconds(self):
        self.assertEqual(calculate_points(0), 200)
        self.assertEqual(calculate_points(5000), 150)  # half the time left -> half bonus
        self.assertEqual(calculate_points(9900), 101)
        self.assertEqual(calculate_points(10000), 100)
        self.assertEqual(calculate_points(10999), 100)  # grace: accepted, no bonus
