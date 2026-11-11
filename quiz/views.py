from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from . import services
from .serializers import CategorySerializer, QuizStartedSerializer, StartQuizSerializer
from .throttles import QuizStartThrottle


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
