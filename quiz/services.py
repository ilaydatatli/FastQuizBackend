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


# ---------------------------------------------------------------------------
# Playing: current question, answers, time and points
# ---------------------------------------------------------------------------


def calculate_points(elapsed_ms):
    """Correct answer: 100 + speed bonus (0-100). The grace period never adds bonus."""
    limit = settings.FAST_QUIZ["TIME_LIMIT_MS"]
    remaining = max(0, limit - elapsed_ms)
    # round(100 * remaining / limit), rounding halves up, with integers only
    bonus = (200 * remaining + limit) // (2 * limit)
    return 100 + bonus


def elapsed_ms(since, until):
    return int((until - since) / timedelta(milliseconds=1))


def get_current(session_id):
    """
    The question the player should see now. The first call for a question writes `shown_at`
    (the 5 seconds start); later calls (page refresh) never move it.
    Questions whose time (including grace) ran out are timed out here, lazily.

    Returns {"session", "item", "choices", "remaining_ms"}; item is None when finished.
    """
    t = now()
    with transaction.atomic():
        session = _lock(session_id)
        expired = _expire_if_needed(session, t)
        if not expired:
            result = _advance_to_current(session, t)
    if expired:  # raised outside the transaction so the "expired" status is saved
        raise _quiz_expired()
    return result


def submit_answer(session_id, question_id, choice_id):
    """Check and score the answer for the current question. choice_id=None means 'time ran out'."""
    t = now()
    with transaction.atomic():
        session = _lock(session_id)
        expired = _expire_if_needed(session, t)
        if not expired:
            result = _answer(session, question_id, choice_id, t)
    if expired:
        raise _quiz_expired()
    return result


def _lock(session_id):
    # select_for_update: two parallel requests (double click) are handled one after another.
    return QuizSession.objects.select_for_update().get(pk=session_id)


def _expire_if_needed(session, t):
    if session.status == QuizSession.Status.EXPIRED:
        return True
    if session.status == QuizSession.Status.ACTIVE and t > session_expires_at(session):
        session.status = QuizSession.Status.EXPIRED
        session.save(update_fields=["status"])
        return True
    return False


def _quiz_expired():
    return QuizError(
        "QUIZ_EXPIRED", "Bu quiz'in süresi doldu. Yeni bir quiz başlat.", status.HTTP_410_GONE
    )


def _current_item(session):
    return (
        SessionQuestion.objects.select_related("question")
        .prefetch_related("question__choices")
        .get(session=session, position=session.current_index)
    )


def _window_ms():
    return settings.FAST_QUIZ["TIME_LIMIT_MS"] + settings.FAST_QUIZ["GRACE_MS"]


def _advance_to_current(session, t):
    total = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]
    limit = settings.FAST_QUIZ["TIME_LIMIT_MS"]

    while session.status == QuizSession.Status.ACTIVE:
        item = _current_item(session)

        if item.shown_at is None:
            item.shown_at = t
            item.save(update_fields=["shown_at"])
        elif elapsed_ms(item.shown_at, t) > _window_ms():
            # Nobody answered in time (e.g. tab closed): count it as timed out and move on.
            item.timed_out = True
            item.is_correct = False
            item.points = 0
            item.save(update_fields=["timed_out", "is_correct", "points"])
            _move_to_next(session, t, total)
            continue

        remaining = max(0, limit - elapsed_ms(item.shown_at, t))
        return {
            "session": session,
            "item": item,
            "choices": _ordered_choices(item),
            "remaining_ms": remaining,
        }

    return {"session": session, "item": None, "choices": [], "remaining_ms": 0}


def _ordered_choices(item):
    by_id = {choice.id: choice for choice in item.question.choices.all()}
    ordered = [by_id.pop(choice_id) for choice_id in item.choice_order if choice_id in by_id]
    return ordered + list(by_id.values())  # safety net if choices changed after the quiz started


def _move_to_next(session, t, total):
    session.current_index += 1
    if session.current_index >= total:
        session.status = QuizSession.Status.FINISHED
        session.finished_at = t
    session.save(update_fields=["current_index", "status", "finished_at", "points", "correct_count"])


def _answer(session, question_id, choice_id, t):
    total = settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"]

    if session.status == QuizSession.Status.FINISHED:
        raise QuizError("QUIZ_FINISHED", "Bu quiz bitti.", status.HTTP_409_CONFLICT)

    item = _current_item(session)
    if question_id != item.question_id:
        already = session.items.filter(
            question_id=question_id, position__lt=session.current_index
        ).exists()
        if already:
            raise QuizError("ALREADY_ANSWERED", "Bu soruyu zaten cevapladın.", status.HTTP_409_CONFLICT)
        raise QuizError("QUESTION_MISMATCH", "Bu soru şu anki soru değil.", status.HTTP_409_CONFLICT)

    if item.shown_at is None:
        raise QuizError("QUESTION_NOT_SHOWN", "Bu soru henüz gösterilmedi.", status.HTTP_409_CONFLICT)

    choices = {choice.id: choice for choice in item.question.choices.all()}
    if choice_id is not None and choice_id not in choices:
        raise QuizError("INVALID_CHOICE", "Bu şık bu soruya ait değil.", status.HTTP_400_BAD_REQUEST)

    took = elapsed_ms(item.shown_at, t)
    in_time = took <= _window_ms()
    selected = choices.get(choice_id)

    item.answered_at = t
    item.selected_choice = selected
    item.timed_out = selected is None or not in_time
    item.is_correct = bool(selected and selected.is_correct and in_time)
    item.points = calculate_points(took) if item.is_correct else 0
    item.save(update_fields=["answered_at", "selected_choice", "timed_out", "is_correct", "points"])

    session.points += item.points
    session.correct_count += int(item.is_correct)
    _move_to_next(session, t, total)

    correct_choice = next(choice for choice in choices.values() if choice.is_correct)
    return {
        "question_id": item.question_id,
        "is_correct": item.is_correct,
        "timed_out": item.timed_out,
        "correct_choice_id": correct_choice.id,
        "points_awarded": item.points,
        "points": session.points,
        "correct_count": session.correct_count,
        "position": session.current_index,
        "finished": session.status == QuizSession.Status.FINISHED,
    }
