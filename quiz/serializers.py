"""
Shapes sent to the client. Never use fields = "__all__" and never expose Choice.is_correct.
"""

from django.conf import settings
from rest_framework import serializers

from .models import Category


class CategorySerializer(serializers.ModelSerializer):
    question_count = serializers.IntegerField(read_only=True)  # from playable_categories()

    class Meta:
        model = Category
        fields = ["slug", "name", "description", "color", "question_count"]


class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["slug", "name", "color"]


class StartQuizSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=50)


class QuizStartedSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    token = serializers.CharField()
    category = CategoryBriefSerializer()
    total_questions = serializers.IntegerField()
    time_limit_ms = serializers.IntegerField()
    expires_at = serializers.DateTimeField()  # rendered in Europe/Istanbul, e.g. +03:00


class ChoiceSerializer(serializers.Serializer):
    # Only id and text. is_correct must never reach the client before the answer.
    id = serializers.IntegerField()
    text = serializers.CharField()


class QuestionSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="question.id")
    text = serializers.CharField(source="question.text")


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
            data["question"] = {
                **QuestionSerializer(item).data,
                "choices": ChoiceSerializer(result["choices"], many=True).data,
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
