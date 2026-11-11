"""
Shared error format for the whole API:

    {"error": {"code": "SOME_CODE", "message": "Türkçe açıklama"}}
"""

from django.http import JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class QuizError(exceptions.APIException):
    """Domain error raised from services/views: QuizError(code, message, status)."""

    def __init__(self, code, message, status_code=status.HTTP_400_BAD_REQUEST):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(detail=message, code=code)


def error_payload(code, message):
    return {"error": {"code": code, "message": message}}


# DRF exception class -> (code, Turkish message)
_DRF_ERRORS = [
    (exceptions.NotFound, "NOT_FOUND", "Aradığın kaynak bulunamadı."),
    (exceptions.MethodNotAllowed, "METHOD_NOT_ALLOWED", "Bu istek yöntemine izin verilmiyor."),
    (exceptions.Throttled, "RATE_LIMITED", "Çok fazla istek gönderdin. Biraz bekleyip tekrar dene."),
    (exceptions.ParseError, "BAD_REQUEST", "İstek gövdesi geçerli bir JSON değil."),
    (exceptions.UnsupportedMediaType, "UNSUPPORTED_MEDIA_TYPE", "İstek gövdesi JSON olmalı."),
    (exceptions.NotAcceptable, "NOT_ACCEPTABLE", "İstenen yanıt biçimi desteklenmiyor."),
    (exceptions.NotAuthenticated, "INVALID_TOKEN", "Geçerli bir quiz anahtarı gerekli."),
    (exceptions.AuthenticationFailed, "INVALID_TOKEN", "Quiz anahtarı geçersiz."),
    (exceptions.PermissionDenied, "FORBIDDEN", "Bu işlem için iznin yok."),
    (exceptions.ValidationError, "VALIDATION_ERROR", "Gönderilen veriler geçersiz."),
]


def api_exception_handler(exc, context):
    """Convert every API error into the shared {"error": {...}} shape."""
    if isinstance(exc, QuizError):
        return Response(error_payload(exc.code, exc.message), status=exc.status_code)

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled exception -> let Django produce a 500 (handler500 renders JSON).
        return None

    code, message = "ERROR", "Bir hata oluştu."
    for exc_class, exc_code, exc_message in _DRF_ERRORS:
        if isinstance(exc, exc_class):
            code, message = exc_code, exc_message
            break

    response.data = error_payload(code, message)
    return response


# Plain Django handlers (requests that never reach a DRF view).
def _json_error(code, message, status_code):
    # ensure_ascii=False keeps Turkish characters readable, like DRF's renderer.
    return JsonResponse(
        error_payload(code, message),
        status=status_code,
        json_dumps_params={"ensure_ascii": False},
    )


def json_not_found(request, exception=None):
    return _json_error("NOT_FOUND", "Aradığın kaynak bulunamadı.", 404)


def json_server_error(request):
    return _json_error("SERVER_ERROR", "Sunucuda beklenmeyen bir hata oluştu.", 500)
