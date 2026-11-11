"""
Quiz business logic. Views stay thin and call these functions.

Always use `now()` from this module instead of `timezone.now()`:
tests patch `quiz.services.now` to control time.
"""

import hashlib
import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status

from .exceptions import QuizError
from .models import Category, QuizSession, SessionQuestion

# OS-level randomness: question picks and choice order should not be predictable.
_rng = random.SystemRandom()


def now():
    return timezone.now()


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def playable_categories():
    """Active categories with enough active questions for a quiz, with `question_count`."""
    needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
    return (
        Category.objects.filter(is_active=True)
        .annotate(question_count=Count("questions", filter=Q(questions__is_active=True)))
        .filter(question_count__gte=needed)
        .order_by("order", "name")
    )


def session_expires_at(session):
    return session.started_at + timedelta(minutes=settings.FAST_QUIZ["SESSION_TTL_MINUTES"])


def start_quiz(category_slug):
    """
    Create a quiz for the category: pick random questions, shuffle each question's choices.
    Returns (session, raw_token). The raw token is shown to the client once and never stored.
    """
    needed = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]

    category = Category.objects.filter(slug=category_slug, is_active=True).first()
    if category is None:
        raise QuizError("CATEGORY_NOT_FOUND", "Böyle bir kategori yok.", status.HTTP_404_NOT_FOUND)

    questions = list(category.questions.filter(is_active=True).prefetch_related("choices"))
    if len(questions) < needed:
        raise QuizError(
            "NOT_ENOUGH_QUESTIONS",
            "Bu kategoride quiz başlatmak için yeterli soru yok.",
            status.HTTP_409_CONFLICT,
        )

    picked = _rng.sample(questions, needed)
    raw_token = secrets.token_urlsafe(32)

    with transaction.atomic():
        session = QuizSession.objects.create(category=category, token_hash=hash_token(raw_token))
        SessionQuestion.objects.bulk_create(
            SessionQuestion(
                session=session,
                question=question,
                position=position,
                choice_order=_shuffled_choice_ids(question),
            )
            for position, question in enumerate(picked)
        )

    return session, raw_token


def _shuffled_choice_ids(question):
    ids = [choice.id for choice in question.choices.all()]
    _rng.shuffle(ids)
    return ids
