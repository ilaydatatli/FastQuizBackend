"""
Shapes sent to the client. Never use fields = "__all__" and never expose Choice.is_correct.
"""

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
