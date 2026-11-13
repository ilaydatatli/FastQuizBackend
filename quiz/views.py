from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, throttle_classes
from rest_framework.response import Response

from . import services
from .authentication import QuizTokenAuthentication
from .serializers import (
    AnswerResultSerializer,
    AnswerSerializer,
    CategorySerializer,
    CurrentSerializer,
    LeaderboardSerializer,
    QuizStartedSerializer,
    ResultSerializer,
    SaveScoreSerializer,
    ScoreSavedSerializer,
    StartQuizSerializer,
)
from .throttles import AnswerThrottle, QuizStartThrottle, ScoreThrottle


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "api_version": "v1"})


@api_view(["GET"])
def categories(request):
    return Response(CategorySerializer(services.playable_categories(), many=True).data)


@api_view(["POST"])
@throttle_classes([QuizStartThrottle])
def start_quiz(request):
    serializer = StartQuizSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    session, raw_token = services.start_quiz(serializer.validated_data["category"])

    payload = QuizStartedSerializer(
        {
            "quiz_id": session.id,
            "token": raw_token,
            "category": session.category,
            "total_questions": settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"],
            "time_limit_ms": settings.FAST_QUIZ["TIME_LIMIT_MS"],
            "expires_at": services.session_expires_at(session),
        }
    )
    return Response(payload.data, status=status.HTTP_201_CREATED)


# Quiz endpoints below: QuizTokenAuthentication puts the QuizSession into request.auth.


@api_view(["GET"])
@authentication_classes([QuizTokenAuthentication])
def current_question(request, quiz_id):
    result = services.get_current(request.auth.id)
    return Response(CurrentSerializer(result).data)


@api_view(["POST"])
@authentication_classes([QuizTokenAuthentication])
@throttle_classes([AnswerThrottle])
def answer(request, quiz_id):
    serializer = AnswerSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = services.submit_answer(
        request.auth.id,
        serializer.validated_data["question_id"],
        serializer.validated_data["choice_id"],
    )
    return Response(AnswerResultSerializer(result).data)


@api_view(["GET"])
@authentication_classes([QuizTokenAuthentication])
def result(request, quiz_id):
    return Response(ResultSerializer(services.get_result(request.auth.id)).data)


@api_view(["POST"])
@authentication_classes([QuizTokenAuthentication])
@throttle_classes([ScoreThrottle])
def save_score(request, quiz_id):
    serializer = SaveScoreSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    saved = services.save_score(request.auth.id, serializer.validated_data["nickname"])
    return Response(ScoreSavedSerializer(saved).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def leaderboard(request, category_slug):
    return Response(LeaderboardSerializer(services.leaderboard(category_slug)).data)
