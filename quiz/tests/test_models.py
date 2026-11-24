from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from quiz.models import Choice, Question, QuizSession, Score

from .factories import (
    make_category,
    make_question,
    make_score,
    make_session,
    make_session_question,
)


class ModelConstraintTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.question = make_question(self.category, text="HTTP 404 nedir?")

    def test_same_question_text_in_same_category_is_rejected(self):
        with self.assertRaises(IntegrityError):
            Question.objects.create(category=self.category, text="HTTP 404 nedir?")

    def test_same_question_text_in_other_category_is_allowed(self):
        other = make_category(slug="biyoloji", order=2)
        Question.objects.create(category=other, text="HTTP 404 nedir?")
        self.assertEqual(Question.objects.filter(text="HTTP 404 nedir?").count(), 2)

    def test_category_slug_and_name_are_unique(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            make_category(slug="yazilim", name="Başka ad")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            make_category(slug="baska", name=self.category.name)

    def test_category_with_questions_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_deleting_question_deletes_its_choices(self):
        self.question.delete()
        self.assertEqual(Choice.objects.count(), 0)

    def test_question_used_in_a_session_cannot_be_deleted(self):
        session = make_session(self.category)
        make_session_question(session, self.question)
        with self.assertRaises(ProtectedError):
            self.question.delete()

    def test_session_defaults(self):
        session = make_session(self.category)
        self.assertEqual(session.status, QuizSession.Status.ACTIVE)
        self.assertEqual(session.current_index, 0)
        self.assertEqual(session.points, 0)
        self.assertIsNotNone(session.started_at)
        self.assertEqual(len(session.token_hash), 64)

    def test_token_hash_is_unique(self):
        make_session(self.category, raw_token="same-token")
        with self.assertRaises(IntegrityError):
            make_session(self.category, raw_token="same-token")

    def test_invalid_session_status_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            make_session(self.category, status="cheating")

    def test_position_is_unique_per_session(self):
        session = make_session(self.category)
        other_question = make_question(self.category, text="Başka soru?")
        make_session_question(session, self.question, position=0)
        with self.assertRaises(IntegrityError):
            make_session_question(session, other_question, position=0)

    def test_question_is_unique_per_session(self):
        session = make_session(self.category)
        make_session_question(session, self.question, position=0)
        with self.assertRaises(IntegrityError):
            make_session_question(session, self.question, position=1)

    def test_same_position_in_different_sessions_is_allowed(self):
        make_session_question(make_session(self.category), self.question, position=0)
        make_session_question(make_session(self.category), self.question, position=0)

    def test_deleting_selected_choice_keeps_the_answer_row(self):
        session = make_session(self.category)
        choice = self.question.choices.first()
        item = make_session_question(session, self.question, selected_choice=choice)
        choice.delete()
        item.refresh_from_db()
        self.assertIsNone(item.selected_choice)

    def test_a_session_can_be_saved_only_once(self):
        session = make_session(self.category, points=1500, correct_count=9)
        make_score(session)
        with self.assertRaises(IntegrityError):
            make_score(session, nickname="ikinci")

    def test_scores_are_ordered_like_the_leaderboard(self):
        def score(points, correct):
            make_score(make_session(self.category), points=points, correct_count=correct)

        score(1000, 5)
        score(2000, 10)
        score(2000, 12)
        score(1000, 5)  # same as first, saved later
        ordered = list(Score.objects.values_list("points", "correct_count", "id"))
        self.assertEqual([(p, c) for p, c, _ in ordered], [(2000, 12), (2000, 10), (1000, 5), (1000, 5)])
        self.assertLess(ordered[2][2], ordered[3][2])  # earlier save comes first


class ChoiceAdminValidationTests(TestCase):
    """The admin's inline formset enforces '4 choices, exactly 1 correct'."""

    add_url = "/admin/quiz/question/add/"

    def setUp(self):
        self.category = make_category()
        admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.force_login(admin)

    def post_question(self, choices, text="Yeni soru?"):
        data = {
            "category": self.category.id,
            "text": text,
            "is_active": "on",
            "audio_ms": "0",  # sound length (Faz 26); 0 = no sound
            "choices-TOTAL_FORMS": str(len(choices)),
            "choices-INITIAL_FORMS": "0",
            "choices-MIN_NUM_FORMS": "0",
            "choices-MAX_NUM_FORMS": "4",
        }
        for i, (choice_text, correct) in enumerate(choices):
            data[f"choices-{i}-text"] = choice_text
            # An untouched extra row keeps the default order 0, like in the real admin.
            data[f"choices-{i}-order"] = str(i) if choice_text else "0"
            if correct:
                data[f"choices-{i}-is_correct"] = "on"
        return self.client.post(self.add_url, data)

    def assert_rejected(self, response, message_part):
        self.assertEqual(response.status_code, 200)  # form shown again with errors
        self.assertContains(response, message_part)
        self.assertEqual(Question.objects.count(), 0)

    def test_four_choices_one_correct_is_saved(self):
        response = self.post_question([("A", True), ("B", False), ("C", False), ("D", False)])
        self.assertEqual(response.status_code, 302)
        question = Question.objects.get()
        self.assertEqual(question.choices.count(), 4)
        self.assertEqual(question.choices.filter(is_correct=True).count(), 1)

    def test_two_correct_choices_are_rejected(self):
        response = self.post_question([("A", True), ("B", True), ("C", False), ("D", False)])
        self.assert_rejected(response, "tam 1 doğru şık olmalı (şu an 2)")

    def test_no_correct_choice_is_rejected(self):
        response = self.post_question([("A", False), ("B", False), ("C", False), ("D", False)])
        self.assert_rejected(response, "tam 1 doğru şık olmalı (şu an 0)")

    def test_three_choices_are_rejected(self):
        response = self.post_question([("A", True), ("B", False), ("C", False)])
        self.assert_rejected(response, "tam 4 şık olmalı (şu an 3)")

    def test_empty_extra_rows_do_not_count_as_choices(self):
        response = self.post_question([("A", True), ("B", False), ("", False), ("", False)])
        self.assert_rejected(response, "tam 4 şık olmalı (şu an 2)")

    def test_deleting_a_choice_on_edit_is_rejected(self):
        question = make_question(self.category, text="Var olan soru?")
        choices = list(question.choices.all())
        data = {
            "category": self.category.id,
            "text": question.text,
            "is_active": "on",
            "audio_ms": "0",  # sound length (Faz 26); 0 = no sound
            "choices-TOTAL_FORMS": "4",
            "choices-INITIAL_FORMS": "4",
            "choices-MIN_NUM_FORMS": "0",
            "choices-MAX_NUM_FORMS": "4",
        }
        for i, choice in enumerate(choices):
            data[f"choices-{i}-id"] = str(choice.id)
            data[f"choices-{i}-question"] = str(question.id)
            data[f"choices-{i}-text"] = choice.text
            data[f"choices-{i}-order"] = str(i)
            if choice.is_correct:
                data[f"choices-{i}-is_correct"] = "on"
        data["choices-3-DELETE"] = "on"

        response = self.client.post(f"/admin/quiz/question/{question.id}/change/", data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tam 4 şık olmalı (şu an 3)")
        self.assertEqual(question.choices.count(), 4)


class ReadOnlyAdminTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.force_login(admin)
        category = make_category()
        self.session = make_session(category, points=1200, correct_count=8)
        make_session_question(self.session, make_question(category))
        self.score = make_score(self.session)

    def test_sessions_and_scores_can_be_viewed(self):
        for url in [
            "/admin/quiz/quizsession/",
            f"/admin/quiz/quizsession/{self.session.id}/change/",
            "/admin/quiz/score/",
            f"/admin/quiz/score/{self.score.id}/change/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_sessions_and_scores_cannot_be_added(self):
        for url in ["/admin/quiz/quizsession/add/", "/admin/quiz/score/add/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_only_the_score_nickname_can_be_changed(self):
        url = f"/admin/quiz/score/{self.score.id}/change/"
        response = self.client.post(url, {"nickname": "  Yeni Ad  ", "points": 4000, "correct_count": 20})
        self.assertEqual(response.status_code, 302)  # saved, back to the list
        self.score.refresh_from_db()
        self.assertEqual(self.score.nickname, "Yeni Ad")  # trimmed, like in the game
        self.assertEqual((self.score.points, self.score.correct_count), (1200, 8))

    def test_invalid_nickname_is_rejected_in_admin(self):
        old = self.score.nickname
        url = f"/admin/quiz/score/{self.score.id}/change/"
        for nickname in ["a", "<script>", "x" * 17]:
            with self.subTest(nickname=nickname):
                response = self.client.post(url, {"nickname": nickname})
                self.assertEqual(response.status_code, 200)  # form shown again, not saved
                self.assertContains(response, 'class="errorlist"')
        self.score.refresh_from_db()
        self.assertEqual(self.score.nickname, old)

    def test_score_cannot_be_deleted(self):
        response = self.client.post(f"/admin/quiz/score/{self.score.id}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Score.objects.filter(id=self.score.id).exists())

    def test_session_cannot_be_changed(self):
        url = f"/admin/quiz/quizsession/{self.session.id}/change/"
        self.client.post(url, {"points": 4000})
        self.session.refresh_from_db()
        self.assertEqual(self.session.points, 1200)

    def test_session_detail_does_not_show_token_hash(self):
        response = self.client.get(f"/admin/quiz/quizsession/{self.session.id}/change/")
        self.assertNotContains(response, self.session.token_hash)
