"""Plain helper functions that create test data (no factory library)."""

import hashlib
import secrets

from quiz.models import Category, Choice, Question, QuizSession, Score, SessionQuestion


def make_category(slug="yazilim", name=None, color="cyan", order=1, is_active=True):
    return Category.objects.create(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        color=color,
        order=order,
        is_active=is_active,
    )


def make_question(category, text="Soru?", correct_index=0, n_choices=4):
    """Question with `n_choices` choices; the one at `correct_index` is correct."""
    question = Question.objects.create(category=category, text=text)
    for i in range(n_choices):
        Choice.objects.create(
            question=question, text=f"Şık {i + 1}", is_correct=(i == correct_index), order=i
        )
    return question


def make_question_set(category, n=20):
    return [make_question(category, text=f"{category.slug} sorusu {i + 1}?") for i in range(n)]


def make_session(category, raw_token=None, **fields):
    raw_token = raw_token or secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return QuizSession.objects.create(category=category, token_hash=token_hash, **fields)


def make_session_question(session, question, position=0, **fields):
    return SessionQuestion.objects.create(
        session=session,
        question=question,
        position=position,
        choice_order=[c.id for c in question.choices.all()],
        **fields,
    )


def make_score(session, nickname="ilayda", points=None, correct_count=None):
    return Score.objects.create(
        session=session,
        category=session.category,
        nickname=nickname,
        points=session.points if points is None else points,
        correct_count=session.correct_count if correct_count is None else correct_count,
    )
