"""Challenge rooms (Faz 24): same questions for friends, each nickname plays once."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APITestCase

from quiz import services
from quiz.models import QuizSession, Room, Score

from .factories import make_category, make_question


def make_translated_questions(category, n=20):
    """Questions that exist in every language (rooms only pick these)."""
    questions = []
    for i in range(n):
        question = make_question(category, text=f"{category.slug} sorusu {i + 1}?")
        question.text_en = question.text_nl = question.text_es = f"Question {i + 1}?"
        question.save()
        questions.append(question)
    return questions


class RoomTestCase(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters
        self.category = make_category(slug="yazilim", name="Yazılım", color="cyan")
        self.translated = make_translated_questions(self.category, n=25)

    def create(self, category="yazilim"):
        return self.client.post("/api/v1/rooms/", {"category": category}, format="json")

    def room(self):
        return Room.objects.get(code=self.create().json()["code"])

    def join(self, code, nickname="ilayda", language="tr"):
        return self.client.post(
            f"/api/v1/rooms/{code}/quizzes/", {"nickname": nickname, "language": language}, format="json"
        )

    def board(self, code):
        return self.client.get(f"/api/v1/rooms/{code}/")

    def finish(self, quiz_id, points, correct_count=10):
        """Skip playing: mark the quiz finished with these points."""
        QuizSession.objects.filter(id=quiz_id).update(
            status=QuizSession.Status.FINISHED,
            points=points,
            correct_count=correct_count,
            current_index=20,
            finished_at=timezone.now(),
        )

    def play(self, code, nickname, points, correct_count=10, sent_nickname=None):
        """Join, finish and save the score; returns the save response."""
        started = self.join(code, nickname).json()
        self.finish(started["quiz_id"], points, correct_count)
        return self.client.post(
            f"/api/v1/quizzes/{started['quiz_id']}/score/",
            {"nickname": sent_nickname or nickname},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {started['token']}",
        )


class CreateRoomTests(RoomTestCase):
    def test_create_returns_code_category_and_expiry(self):
        before = timezone.now()
        response = self.create()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"code", "category", "created_at", "expires_at"})
        self.assertEqual(len(body["code"]), 6)
        self.assertTrue(set(body["code"]) <= set(services.ROOM_CODE_ALPHABET))
        self.assertEqual(body["category"], {"slug": "yazilim", "name": "Yazılım", "color": "cyan"})
        expires = parse_datetime(body["expires_at"])
        self.assertAlmostEqual(
            (expires - before).total_seconds(), settings.FAST_QUIZ["ROOM_TTL_HOURS"] * 3600, delta=5
        )

    def test_room_picks_20_different_translated_questions(self):
        tr_only = make_question(self.category, text="Sadece Türkçe?")
        room = self.room()
        self.assertEqual(len(room.question_ids), 20)
        self.assertEqual(len(set(room.question_ids)), 20)
        self.assertNotIn(tr_only.id, room.question_ids)

    def test_unknown_category_is_404(self):
        response = self.create("yok-boyle")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CATEGORY_NOT_FOUND")

    def test_not_enough_translated_questions_is_409(self):
        other = make_category(slug="biyoloji", order=2)
        make_translated_questions(other, n=19)
        make_question(other, text="Sadece Türkçe?")
        response = self.create("biyoloji")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "NOT_ENOUGH_QUESTIONS")

    def test_room_creation_is_throttled(self):
        rate = int(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["room_create"].split("/")[0])
        for _ in range(rate):
            self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 429)


class JoinRoomTests(RoomTestCase):
    def test_join_starts_a_quiz_with_the_room_questions_in_order(self):
        room = self.room()
        response = self.join(room.code)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["room"], room.code)
        session = QuizSession.objects.get(id=body["quiz_id"])
        self.assertEqual(list(session.items.values_list("question_id", flat=True)), room.question_ids)
        self.assertEqual(session.room_nickname, "ilayda")

    def test_friends_get_the_same_questions_in_their_own_language(self):
        room = self.room()
        mine = QuizSession.objects.get(id=self.join(room.code, "ilayda", "tr").json()["quiz_id"])
        theirs = QuizSession.objects.get(id=self.join(room.code, "elo", "nl").json()["quiz_id"])

        self.assertEqual(theirs.language, "nl")
        self.assertEqual(
            list(mine.items.values_list("question_id", flat=True)),
            list(theirs.items.values_list("question_id", flat=True)),
        )

    def test_code_is_not_case_sensitive(self):
        room = self.room()
        self.assertEqual(self.join(room.code.lower()).status_code, 201)

    def test_unknown_room_is_404(self):
        for response in (self.join("ZZZZZZ"), self.board("ZZZZZZ")):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], "ROOM_NOT_FOUND")

    def test_invalid_nickname_is_400(self):
        response = self.join(self.room().code, nickname="x")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "NICKNAME_INVALID")

    def test_closed_room_cannot_be_joined(self):
        room = self.room()
        later = room.expires_at + timedelta(seconds=1)
        with patch("quiz.services.now", return_value=later):
            response = self.join(room.code)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "ROOM_CLOSED")

    def test_a_nickname_plays_a_room_only_once(self):
        room = self.room()
        self.assertEqual(self.play(room.code, "ilayda", 2000).status_code, 201)

        response = self.join(room.code, "ilayda")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ROOM_ALREADY_PLAYED")
        self.assertEqual(self.join(room.code, "Ilayda").status_code, 201)  # different spelling

    def test_second_quiz_started_before_saving_cannot_be_saved(self):
        room = self.room()
        first = self.join(room.code, "ilayda").json()
        self.assertEqual(self.play(room.code, "ilayda", 1000).status_code, 201)

        self.finish(first["quiz_id"], 3000)
        response = self.client.post(
            f"/api/v1/quizzes/{first['quiz_id']}/score/",
            {"nickname": "ilayda"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {first['token']}",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ROOM_ALREADY_PLAYED")

    @override_settings(FAST_QUIZ={**settings.FAST_QUIZ, "ROOM_MAX_PLAYERS": 2})
    def test_full_room_is_409_but_known_players_may_retry(self):
        room = self.room()
        self.join(room.code, "ilayda")
        self.join(room.code, "elo")

        response = self.join(room.code, "bilge")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "ROOM_FULL")
        self.assertEqual(self.join(room.code, "elo").status_code, 201)  # unfinished, starts again


class RoomScoreTests(RoomTestCase):
    def test_score_uses_the_room_nickname_and_names_the_room(self):
        room = self.room()
        response = self.play(room.code, "ilayda", 2500, sent_nickname="baskasi")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["nickname"], "ilayda")
        self.assertEqual(response.json()["room"], room.code)

    def test_room_scores_also_count_on_the_category_board(self):
        room = self.room()
        self.play(room.code, "ilayda", 2500)
        entries = self.client.get("/api/v1/leaderboard/yazilim/").json()["entries"]
        self.assertEqual([(e["nickname"], e["points"]) for e in entries], [("ilayda", 2500)])

    def test_result_names_the_room(self):
        room = self.room()
        started = self.join(room.code).json()
        self.finish(started["quiz_id"], 1000)
        result = self.client.get(
            f"/api/v1/quizzes/{started['quiz_id']}/result/",
            HTTP_AUTHORIZATION=f"Bearer {started['token']}",
        ).json()
        self.assertEqual(result["room"], room.code)


class RoomBoardTests(RoomTestCase):
    def test_board_shape_and_order(self):
        room = self.room()
        self.play(room.code, "elo", 2000, correct_count=12)
        self.play(room.code, "ilayda", 3000)
        self.play(room.code, "bilge", 2000, correct_count=14)
        self.join(room.code, "yarim")  # started, never finished: not on the board

        body = self.board(room.code).json()
        self.assertEqual(set(body), {"room", "is_open", "entries"})
        self.assertEqual(body["room"]["code"], room.code)
        self.assertTrue(body["is_open"])
        self.assertEqual(
            [(e["rank"], e["nickname"]) for e in body["entries"]],
            [(1, "ilayda"), (2, "bilge"), (3, "elo")],
        )

    def test_only_this_rooms_scores_are_shown(self):
        first, second = self.room(), self.room()
        self.play(first.code, "ilayda", 2000)
        self.play(second.code, "elo", 2500)
        self.assertEqual([e["nickname"] for e in self.board(first.code).json()["entries"]], ["ilayda"])

    def test_closed_room_board_stays_visible(self):
        room = self.room()
        self.play(room.code, "ilayda", 2000)
        with patch("quiz.services.now", return_value=room.expires_at + timedelta(days=3)):
            body = self.board(room.code).json()
        self.assertFalse(body["is_open"])
        self.assertEqual(len(body["entries"]), 1)

    def test_board_category_name_follows_lang(self):
        self.category.name_en = "Software"
        self.category.save()
        room = self.room()
        body = self.client.get(f"/api/v1/rooms/{room.code}/?lang=en").json()
        self.assertEqual(body["room"]["category"]["name"], "Software")


class RoomModelTests(APITestCase):
    def test_room_codes_are_unique(self):
        category = make_category()
        make_translated_questions(category)
        codes = {services.create_room(category.slug).code for _ in range(30)}
        self.assertEqual(len(codes), 30)
        self.assertEqual(Room.objects.count(), 30)
        self.assertEqual(Score.objects.count(), 0)
