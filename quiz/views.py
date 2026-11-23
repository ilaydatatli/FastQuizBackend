from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, throttle_classes
from rest_framework.response import Response

from . import services
from .authentication import QuizTokenAuthentication
from .serializers import (
    AnswerResultSerializer,
    AnswerSerializer,
    CreateRoomSerializer,
    JoinRoomSerializer,
    CategorySerializer,
    CurrentSerializer,
    LanguageQuerySerializer,
    LeaderboardSerializer,
    OverallLeaderboardSerializer,
    QuizStartedSerializer,
    ResultSerializer,
    RoomBoardSerializer,
    RoomSerializer,
    SaveScoreSerializer,
    ScoreSavedSerializer,
    StartQuizSerializer,
)
from .throttles import AnswerThrottle, QuizStartThrottle, RoomCreateThrottle, ScoreThrottle


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "api_version": "v1"})


def query_language(request):
    """?lang=tr|en|es (default tr); anything else is a 400 VALIDATION_ERROR."""
    serializer = LanguageQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["lang"]


@api_view(["GET"])
def categories(request):
    language = query_language(request)
    serializer = CategorySerializer(
        services.playable_categories(language), many=True, context={"language": language}
    )
    return Response(serializer.data)


@api_view(["POST"])
@throttle_classes([QuizStartThrottle])
def start_quiz(request):
    serializer = StartQuizSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    session, raw_token = services.start_quiz(
        serializer.validated_data["category"], serializer.validated_data["language"]
    )
    return _quiz_started(session, raw_token)


def _quiz_started(session, raw_token):
    payload = QuizStartedSerializer(
        {
            "quiz_id": session.id,
            "token": raw_token,
            "category": session.category,
            "language": session.language,
            "total_questions": settings.FAST_QUIZ["QUESTIONS_PER_QUIZ"],
            "time_limit_ms": settings.FAST_QUIZ["TIME_LIMIT_MS"],
            "expires_at": services.session_expires_at(session),
            "room": session.room.code if session.room_id else None,
        },
        context={"language": session.language},
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
    data = services.get_result(request.auth.id)
    return Response(ResultSerializer(data, context={"language": data["language"]}).data)


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
    language = query_language(request)
    data = services.leaderboard(category_slug, language)
    return Response(LeaderboardSerializer(data, context={"language": language}).data)


@api_view(["GET"])
def overall_leaderboard(request):
    # Nicknames and points only, so ?lang changes nothing here.
    return Response(OverallLeaderboardSerializer(services.overall_leaderboard()).data)


# Challenge rooms (Faz 24)


@api_view(["POST"])
@throttle_classes([RoomCreateThrottle])
def create_room(request):
    serializer = CreateRoomSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    room = services.create_room(serializer.validated_data["category"])
    language = query_language(request)
    return Response(
        RoomSerializer(room, context={"language": language}).data, status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
def room(request, code):
    language = query_language(request)
    data = services.room_board(code)
    return Response(RoomBoardSerializer(data, context={"language": language}).data)


@api_view(["POST"])
@throttle_classes([QuizStartThrottle])
def join_room(request, code):
    serializer = JoinRoomSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    session, raw_token = services.start_room_quiz(
        code, serializer.validated_data["nickname"], serializer.validated_data["language"]
    )
    return _quiz_started(session, raw_token)

