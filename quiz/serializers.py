"""
Shapes sent to the client. Never use fields = "__all__" and never expose Choice.is_correct.

Texts are returned in one language. Serializers read it from context["language"]
(nested serializers share the root's context); missing translations fall back to Turkish.
"""

from django.conf import settings
from rest_framework import serializers

from .models import DEFAULT_LANGUAGE, LANGUAGE_CHOICES, localized


def _language(serializer):
    return serializer.context.get("language", DEFAULT_LANGUAGE)


class LanguageQuerySerializer(serializers.Serializer):
    """Optional ?lang=tr|en|es on public GET endpoints."""

    lang = serializers.ChoiceField(choices=LANGUAGE_CHOICES, required=False, default=DEFAULT_LANGUAGE)


class CategorySerializer(serializers.Serializer):
    def to_representation(self, category):
        language = _language(self)
        return {
            "slug": category.slug,
            "name": localized(category, "name", language),
            "description": localized(category, "description", language),
            "color": category.color,
            "question_count": category.question_count,  # from playable_categories()
        }


class CategoryBriefSerializer(serializers.Serializer):
    def to_representation(self, category):
        return {
            "slug": category.slug,
            "name": localized(category, "name", _language(self)),
            "color": category.color,
        }


class StartQuizSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=50)
    language = serializers.ChoiceField(
        choices=LANGUAGE_CHOICES, required=False, default=DEFAULT_LANGUAGE
    )


class QuizStartedSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    token = serializers.CharField()
    category = CategoryBriefSerializer()
    language = serializers.CharField()
    total_questions = serializers.IntegerField()
    time_limit_ms = serializers.IntegerField()
    expires_at = serializers.DateTimeField()  # rendered in Europe/Istanbul, e.g. +03:00
    room = serializers.CharField(allow_null=True)  # room code for room quizzes, else null


class CurrentSerializer(serializers.Serializer):
    """Shape of GET .../current/; built from services.get_current()'s result."""

    def to_representation(self, result):
        session, item = result["session"], result["item"]
        data = {
            "status": session.status,
            "position": session.current_index,
            "total_questions": settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"],
            "points": session.points,
            "question": None,
        }
        if item is not None:
            language = session.language
            data["question"] = {
                "id": item.question.id,
                "text": localized(item.question, "text", language),
                # Only id and text: is_correct must never reach the client before the answer.
                "choices": [
                    {"id": choice.id, "text": localized(choice, "text", language)}
                    for choice in result["choices"]
                ],
                # Sound questions: play `url` first; the timer starts after `left_ms`.
                "audio": (
                    {
                        "url": item.question.audio,
                        "duration_ms": item.question.audio_ms,
                        "left_ms": result["audio_left_ms"],
                    }
                    if item.question.audio
                    else None
                ),
            }
            data["time_limit_ms"] = settings.FAST_QUIZ["TIME_LIMIT_MS"]
            data["remaining_ms"] = result["remaining_ms"]
        return data


class AnswerSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()
    choice_id = serializers.IntegerField(allow_null=True)  # null = time ran out on the client


class AnswerResultSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()
    is_correct = serializers.BooleanField()  # result of the player's OWN answer
    timed_out = serializers.BooleanField()
    correct_choice_id = serializers.IntegerField()
    points_awarded = serializers.IntegerField()
    points = serializers.IntegerField()
    correct_count = serializers.IntegerField()
    position = serializers.IntegerField()
    finished = serializers.BooleanField()


class ResultSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    category = CategoryBriefSerializer()
    points = serializers.IntegerField()
    correct_count = serializers.IntegerField()
    total_questions = serializers.IntegerField()
    timed_out_count = serializers.IntegerField()
    qualifies_for_top10 = serializers.BooleanField()
    score_saved = serializers.BooleanField()
    finished_at = serializers.DateTimeField()
    room = serializers.CharField(allow_null=True)


class SaveScoreSerializer(serializers.Serializer):
    # Format rules (NICKNAME_INVALID) are checked in services.save_score.
    nickname = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ScoreSavedSerializer(serializers.Serializer):
    nickname = serializers.CharField()
    points = serializers.IntegerField()
    correct_count = serializers.IntegerField()
    rank = serializers.IntegerField()
    category = serializers.CharField()  # category slug
    best_points = serializers.IntegerField()  # this nickname's best in the category
    is_new_best = serializers.BooleanField()  # this quiz is now that best
    points_to_top10 = serializers.IntegerField(allow_null=True)  # null when already in the top 10
    room = serializers.CharField(allow_null=True)


class LeaderboardEntrySerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    nickname = serializers.CharField(source="score.nickname")
    points = serializers.IntegerField(source="score.points")
    correct_count = serializers.IntegerField(source="score.correct_count")
    language = serializers.CharField(source="score.language")  # played in; shown as a flag
    created_at = serializers.DateTimeField(source="score.created_at")


class OverallEntrySerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    nickname = serializers.CharField()
    points = serializers.IntegerField()  # sum of the best score in each category
    categories_played = serializers.IntegerField()


class OverallLeaderboardSerializer(serializers.Serializer):
    category_count = serializers.IntegerField()  # active categories: "5 / 9"
    entries = OverallEntrySerializer(many=True)


class LeaderboardSerializer(serializers.Serializer):
    category = CategoryBriefSerializer()
    entries = LeaderboardEntrySerializer(many=True)


class CreateRoomSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=50)


class JoinRoomSerializer(serializers.Serializer):
    # Format rules (NICKNAME_INVALID) are checked in services.start_room_quiz.
    nickname = serializers.CharField(allow_blank=True, trim_whitespace=False)
    language = serializers.ChoiceField(
        choices=LANGUAGE_CHOICES, required=False, default=DEFAULT_LANGUAGE
    )


class RoomSerializer(serializers.Serializer):
    code = serializers.CharField()
    category = CategoryBriefSerializer()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()


class RoomBoardSerializer(serializers.Serializer):
    room = RoomSerializer()
    is_open = serializers.BooleanField()  # false: nobody can join any more, the board stays
    entries = LeaderboardEntrySerializer(many=True)

