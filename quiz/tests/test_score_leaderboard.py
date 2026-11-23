import itertools
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from quiz.models import QuizSession, Score
from quiz.throttles import ScoreThrottle

from .base import QuizPlayTestCase
from .factories import make_category, make_score, make_session


def finished_session(category, points, correct_count):
    return make_session(
        category,
        status=QuizSession.Status.FINISHED,
        points=points,
        correct_count=correct_count,
        current_index=20,
        finished_at=timezone.now(),
    )


_player_numbers = itertools.count(1)


def fill_board(category, n, points=3000, correct_count=15):
    """n different players (unique nicknames), all with the same score."""
    for _ in range(n):
        nickname = f"oyuncu{next(_player_numbers)}"
        make_score(finished_session(category, points, correct_count), nickname=nickname)


class FinishedQuizTestCase(QuizPlayTestCase):
    """Plays the whole quiz: 18 correct at 1 s (180 each), 1 wrong, 1 timed out."""

    def finish_quiz(self):
        for i in range(18):
            self.show_and_answer(i * 10_000, 1000)
        self.show_and_answer(180_000, 1000, correct=False)
        question_id = self.current(190_000).json()["question"]["id"]
        self.answer(190_500, question_id, None)

    def result(self, token=None):
        return self.client.get(f"/api/v1/quizzes/{self.quiz_id}/result/", **self.auth(token))

    def save(self, nickname="ilayda_99", **extra):
        with self.at(200_000):
            return self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/score/",
                {"nickname": nickname, **extra},
                format="json",
                **self.auth(),
            )


class ResultTests(FinishedQuizTestCase):
    def test_result_of_unfinished_quiz_is_409(self):
        self.current(0)
        response = self.result()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_NOT_FINISHED")

    def test_result_returns_contract_shape(self):
        self.finish_quiz()

        response = self.result()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "quiz_id",
                "category",
                "points",
                "correct_count",
                "total_questions",
                "timed_out_count",
                "qualifies_for_top10",
                "score_saved",
                "finished_at",
            },
        )
        self.assertEqual(body["quiz_id"], str(self.quiz_id))
        self.assertEqual(set(body["category"]), {"slug", "name", "color"})
        self.assertEqual(body["points"], 18 * 180)
        self.assertEqual(body["correct_count"], 18)
        self.assertEqual(body["total_questions"], 20)
        self.assertEqual(body["timed_out_count"], 1)
        self.assertTrue(body["qualifies_for_top10"])  # empty board
        self.assertFalse(body["score_saved"])
        self.assertTrue(body["finished_at"].endswith("+03:00"))

    def test_score_saved_becomes_true_after_saving(self):
        self.finish_quiz()
        self.save()
        self.assertTrue(self.result().json()["score_saved"])

    def test_does_not_qualify_behind_ten_better_scores(self):
        self.finish_quiz()
        fill_board(self.category, 10, points=4000, correct_count=20)
        self.assertFalse(self.result().json()["qualifies_for_top10"])

    def test_equal_scores_saved_earlier_stay_ahead(self):
        self.finish_quiz()
        fill_board(self.category, 10, points=18 * 180, correct_count=18)
        self.assertFalse(self.result().json()["qualifies_for_top10"])

    def test_qualifies_with_nine_better_scores(self):
        self.finish_quiz()
        fill_board(self.category, 9, points=4000, correct_count=20)
        fill_board(self.category, 5, points=100, correct_count=1)
        self.assertTrue(self.result().json()["qualifies_for_top10"])

    def test_scores_of_other_categories_do_not_count(self):
        self.finish_quiz()
        fill_board(make_category(slug="biyoloji", order=2), 10, points=4000, correct_count=20)
        self.assertTrue(self.result().json()["qualifies_for_top10"])

    def test_result_needs_the_right_token(self):
        self.finish_quiz()
        self.assertEqual(self.result(token="yanlis").status_code, 401)


class SaveScoreTests(FinishedQuizTestCase):
    def test_save_score_returns_contract_shape(self):
        self.finish_quiz()

        response = self.save()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "nickname": "ilayda_99",
                "points": 18 * 180,
                "correct_count": 18,
                "rank": 1,
                "category": self.category.slug,
                "best_points": 18 * 180,
                "is_new_best": True,
                "points_to_top10": None,
            },
        )
        score = Score.objects.get()
        self.assertEqual(score.session_id, self.quiz_id)
        self.assertEqual(score.category_id, self.category.id)

    def test_rank_counts_better_scores(self):
        self.finish_quiz()
        fill_board(self.category, 3, points=4000, correct_count=20)
        fill_board(self.category, 2, points=100, correct_count=1)
        self.assertEqual(self.save().json()["rank"], 4)

    def test_rank_can_be_beyond_ten(self):
        self.finish_quiz()
        fill_board(self.category, 12, points=4000, correct_count=20)
        response = self.save()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["rank"], 13)

    def test_points_come_from_the_server_not_the_client(self):
        self.finish_quiz()
        body = self.save(points=4000, correct_count=20).json()
        self.assertEqual(body["points"], 18 * 180)
        self.assertEqual(Score.objects.get().points, 18 * 180)

    def test_second_save_is_rejected(self):
        self.finish_quiz()
        self.save()
        response = self.save(nickname="ikinci")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "SCORE_ALREADY_SAVED")
        self.assertEqual(Score.objects.count(), 1)

    def test_unfinished_quiz_cannot_be_saved(self):
        self.current(0)
        response = self.save()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_NOT_FINISHED")

    def test_expired_quiz_cannot_be_saved(self):
        self.current(0)
        with self.at(15 * 60 * 1000):
            response = self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/score/",
                {"nickname": "gec_kalan"},
                format="json",
                **self.auth(),
            )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"]["code"], "QUIZ_EXPIRED")
        self.assertEqual(Score.objects.count(), 0)

    def test_valid_nicknames(self):
        self.finish_quiz()
        for nickname, stored in [
            ("İlayda", "İlayda"),
            ("çağrı-ş", "çağrı-ş"),
            ("Ali Veli", "Ali Veli"),
            ("ab", "ab"),
            ("x" * 16, "x" * 16),
            ("  ilayda_99  ", "ilayda_99"),  # surrounding spaces are trimmed
        ]:
            with self.subTest(nickname=nickname):
                Score.objects.all().delete()
                response = self.save(nickname=nickname)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(Score.objects.get().nickname, stored)

    def test_invalid_nicknames(self):
        self.finish_quiz()
        for nickname in ["", "a", "   ", "  a  ", "x" * 17, "ab!", "<script>", "a.b", "emoji😀", "a\nb"]:
            with self.subTest(nickname=nickname):
                response = self.save(nickname=nickname)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "NICKNAME_INVALID")
        self.assertEqual(Score.objects.count(), 0)

    def test_missing_nickname_is_a_validation_error(self):
        self.finish_quiz()
        with self.at(200_000):
            response = self.client.post(
                f"/api/v1/quizzes/{self.quiz_id}/score/", {}, format="json", **self.auth()
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_saving_too_often_is_rate_limited(self):
        self.finish_quiz()
        with patch.object(ScoreThrottle, "THROTTLE_RATES", {"score": "1/hour"}):
            self.save(nickname="a!")  # invalid, but still counts
            response = self.save()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "RATE_LIMITED")


class LeaderboardTests(APITestCase):
    def setUp(self):
        self.category = make_category(slug="yazilim", name="Yazılım", color="cyan")

    def get(self, slug="yazilim"):
        return self.client.get(f"/api/v1/leaderboard/{slug}/")

    def add(self, nickname, points, correct_count, category=None):
        session = finished_session(category or self.category, points, correct_count)
        return make_score(session, nickname=nickname)

    def test_unknown_category_is_404(self):
        response = self.get("yok-boyle")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CATEGORY_NOT_FOUND")

    def test_empty_board(self):
        self.assertEqual(
            self.get().json(),
            {"category": {"slug": "yazilim", "name": "Yazılım", "color": "cyan"}, "entries": []},
        )

    def test_entry_shape(self):
        self.add("neonfox", 3640, 20)
        entry = self.get().json()["entries"][0]
        self.assertEqual(set(entry), {"rank", "nickname", "points", "correct_count", "language", "created_at"})
        self.assertEqual(entry["rank"], 1)
        self.assertEqual(entry["nickname"], "neonfox")
        self.assertTrue(entry["created_at"].endswith("+03:00"))

    def test_order_points_then_correct_count_then_earlier_save(self):
        self.add("ucuncu", 2000, 10)
        self.add("erken", 2000, 12)
        self.add("birinci", 3000, 15)
        self.add("gec", 2000, 12)  # same as "erken" but saved later

        names = [entry["nickname"] for entry in self.get().json()["entries"]]

        self.assertEqual(names, ["birinci", "erken", "gec", "ucuncu"])
        ranks = [entry["rank"] for entry in self.get().json()["entries"]]
        self.assertEqual(ranks, [1, 2, 3, 4])

    def test_only_top_ten_are_shown(self):
        for i in range(12):
            self.add(f"oyuncu{i}", 1000 + i, 5)
        entries = self.get().json()["entries"]
        self.assertEqual(len(entries), 10)
        self.assertEqual(entries[0]["nickname"], "oyuncu11")
        self.assertEqual(entries[-1]["nickname"], "oyuncu2")

    @override_settings(FAST_QUIZ={**settings.FAST_QUIZ, "LEADERBOARD_SIZE": 3})
    def test_board_size_comes_from_settings(self):
        for i in range(5):
            self.add(f"oyuncu{i}", 1000 + i, 5)
        self.assertEqual(len(self.get().json()["entries"]), 3)

    def test_categories_are_separate(self):
        other = make_category(slug="biyoloji", name="Biyoloji", order=2)
        self.add("yazilimci", 2000, 10)
        self.add("biyolog", 3000, 15, category=other)

        self.assertEqual([e["nickname"] for e in self.get().json()["entries"]], ["yazilimci"])
        self.assertEqual([e["nickname"] for e in self.get("biyoloji").json()["entries"]], ["biyolog"])

    def test_leaderboard_uses_a_fixed_number_of_queries(self):
        for i in range(10):
            self.add(f"oyuncu{i}", 1000 + i, 5)
        with self.assertNumQueries(2):  # category + scores
            self.get()


class OneRowPerNicknameTests(APITestCase):
    """The same nickname (exact spelling) appears once, with its best score."""

    def setUp(self):
        self.category = make_category(slug="yazilim", name="Yazılım", color="cyan")

    def add(self, nickname, points, correct_count=10, category=None):
        session = finished_session(category or self.category, points, correct_count)
        return make_score(session, nickname=nickname)

    def board(self):
        entries = self.client.get("/api/v1/leaderboard/yazilim/").json()["entries"]
        return [(e["rank"], e["nickname"], e["points"]) for e in entries]

    def test_same_nickname_shows_only_its_best_score(self):
        self.add("ilayda", 1200)
        self.add("ilayda", 2500)
        self.add("ilayda", 1800)
        self.add("neonfox", 2000)

        self.assertEqual(self.board(), [(1, "ilayda", 2500), (2, "neonfox", 2000)])

    def test_different_spelling_is_a_different_player(self):
        self.add("ilayda", 2000)
        self.add("Ilayda", 1500)

        self.assertEqual(self.board(), [(1, "ilayda", 2000), (2, "Ilayda", 1500)])

    def test_top_ten_counts_players_not_scores(self):
        for i in range(10):
            self.add(f"oyuncu{i}", 1000 + i)
        for _ in range(5):
            self.add("tekrarci", 3000)  # one player saving many times

        board = self.board()
        self.assertEqual(len(board), 10)
        self.assertEqual(board[0], (1, "tekrarci", 3000))
        self.assertEqual([nickname for _, nickname, _ in board].count("tekrarci"), 1)

    def test_other_category_scores_do_not_merge(self):
        self.add("ilayda", 1000)
        self.add("ilayda", 3900, category=make_category(slug="biyoloji", order=2))

        self.assertEqual(self.board(), [(1, "ilayda", 1000)])


class RankWithRepeatedNicknamesTests(FinishedQuizTestCase):
    """Saved quiz: 18 x 180 = 3240 points (see FinishedQuizTestCase)."""

    def add(self, nickname, points, correct_count=10):
        make_score(finished_session(self.category, points, correct_count), nickname=nickname)

    def test_rank_counts_players_not_their_extra_scores(self):
        for _ in range(4):
            self.add("rakip", 4000, 20)  # one player, four saves
        self.finish_quiz()

        self.assertEqual(self.save(nickname="ilayda").json()["rank"], 2)

    def test_lower_new_score_returns_the_rank_of_the_best_row(self):
        self.add("ilayda", 3900, 20)  # earlier, better score of the same player
        self.add("rakip", 3500, 19)
        self.finish_quiz()

        body = self.save(nickname="ilayda").json()
        self.assertEqual(body["points"], 18 * 180)  # this quiz's points
        self.assertEqual(body["rank"], 1)  # the row shown on the board is the 3900 one

    def test_qualifies_for_top10_counts_players(self):
        for _ in range(12):
            self.add("rakip", 4000, 20)  # 12 saves, but only one player
        self.finish_quiz()

        self.assertTrue(self.result().json()["qualifies_for_top10"])


class RecordAndTopTenTests(FinishedQuizTestCase):
    """Fields for the result screen's motivation messages. This quiz: 3240 points."""

    def add(self, nickname, points, correct_count=10):
        make_score(finished_session(self.category, points, correct_count), nickname=nickname)

    def test_first_score_is_a_new_best(self):
        self.finish_quiz()
        body = self.save(nickname="ilayda").json()
        self.assertEqual((body["best_points"], body["is_new_best"]), (3240, True))

    def test_beating_the_old_record(self):
        self.add("ilayda", 3000)
        self.finish_quiz()
        body = self.save(nickname="ilayda").json()
        self.assertEqual((body["best_points"], body["is_new_best"]), (3240, True))

    def test_lower_score_keeps_the_old_record(self):
        self.add("ilayda", 3500, 19)
        self.finish_quiz()
        body = self.save(nickname="ilayda").json()
        self.assertEqual((body["points"], body["best_points"], body["is_new_best"]), (3240, 3500, False))

    def test_points_needed_to_pass_the_tenth_player(self):
        for i in range(10):
            self.add(f"rakip{i}", 4000 - i * 10)  # 10th player: 3910
        self.finish_quiz()
        body = self.save(nickname="ilayda").json()
        self.assertEqual(body["rank"], 11)
        self.assertEqual(body["points_to_top10"], 3910 - 3240 + 1)

    def test_top10_gap_uses_the_players_best_not_this_quiz(self):
        for i in range(10):
            self.add(f"rakip{i}", 4000 - i * 10)
        self.add("ilayda", 3800)  # older best, still outside the top 10
        self.finish_quiz()
        body = self.save(nickname="ilayda").json()
        self.assertEqual(body["points_to_top10"], 3910 - 3800 + 1)

    def test_no_gap_inside_the_top_10(self):
        for i in range(5):
            self.add(f"rakip{i}", 4000)
        self.finish_quiz()
        self.assertIsNone(self.save(nickname="ilayda").json()["points_to_top10"])
