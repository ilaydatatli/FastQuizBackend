"""
N+1 guard: the number of SQL queries per request must not grow with the amount of data
(more categories, more questions, more scores). Each test runs a request on small and
large data and compares the query counts.
"""

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from quiz import services

from .base import QuizPlayTestCase
from .factories import make_category, make_question_set, make_score, make_session


def count_queries(fn):
    with CaptureQueriesContext(connection) as ctx:
        response = fn()
    return response, len(ctx.captured_queries)


class ListQueryCountTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_categories_query_count_is_constant(self):
        make_question_set(make_category("a", order=1), n=20)
        _, few = count_queries(lambda: self.client.get("/api/v1/categories/"))

        for i in range(2, 9):
            make_question_set(make_category(f"c{i}", order=i), n=25)
        response, many = count_queries(lambda: self.client.get("/api/v1/categories/"))

        self.assertEqual(len(response.json()), 8)
        self.assertEqual(few, many)

    def test_leaderboard_query_count_is_constant(self):
        category = make_category()
        make_score(make_session(category, points=100, correct_count=1, status="finished"))
        _, few = count_queries(lambda: self.client.get("/api/v1/leaderboard/yazilim/"))

        for i in range(15):
            session = make_session(category, points=200 + i, correct_count=2, status="finished")
            make_score(session, nickname=f"oyuncu{i}")
        response, many = count_queries(lambda: self.client.get("/api/v1/leaderboard/yazilim/"))

        self.assertEqual(len(response.json()["entries"]), 10)
        self.assertEqual(few, many)

    def test_start_quiz_query_count_does_not_grow_with_pool_size(self):
        small = make_category("small", order=1)
        make_question_set(small, n=20)
        big = make_category("big", order=2)
        make_question_set(big, n=40)

        _, few = count_queries(lambda: services.start_quiz("small"))
        _, many = count_queries(lambda: services.start_quiz("big"))

        self.assertEqual(few, many)


class PlayQueryCountTests(QuizPlayTestCase):
    def test_current_and_answer_query_counts_are_stable_across_questions(self):
        first_current, first_answer = None, None
        for position in range(5):
            show = position * 3000
            response, current_q = count_queries(lambda: self.current(show))
            body = response.json()
            choice = self.correct_choice_id(body["position"])
            response, answer_q = count_queries(
                lambda: self.answer(show + 500, body["question"]["id"], choice)
            )
            self.assertEqual(response.status_code, 200)
            if position == 0:
                first_current, first_answer = current_q, answer_q
            else:
                self.assertEqual(current_q, first_current, f"current at position {position}")
                self.assertEqual(answer_q, first_answer, f"answer at position {position}")
