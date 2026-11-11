import hmac

from rest_framework import exceptions, status
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from .exceptions import QuizError
from .models import QuizSession
from .services import hash_token


class QuizTokenAuthentication(BaseAuthentication):
    """
    `Authorization: Bearer <token>` for quiz endpoints with a `quiz_id` URL parameter.

    On success `request.auth` is the QuizSession. A token only opens its own quiz:
    another quiz's token gives 401 INVALID_TOKEN.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        raw_token = self._read_token(request)

        quiz_id = request.parser_context.get("kwargs", {}).get("quiz_id")
        session = QuizSession.objects.filter(id=quiz_id).first() if quiz_id else None
        if session is None:
            raise QuizError("QUIZ_NOT_FOUND", "Böyle bir quiz yok.", status.HTTP_404_NOT_FOUND)

        # Constant-time comparison, so response timing reveals nothing about the hash.
        if not hmac.compare_digest(session.token_hash, hash_token(raw_token)):
            raise exceptions.AuthenticationFailed()

        return (None, session)

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) and send `WWW-Authenticate: Bearer`.
        return self.keyword

    def _read_token(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            raise exceptions.NotAuthenticated()
        if len(parts) != 2 or parts[0].decode().lower() != self.keyword.lower():
            raise exceptions.AuthenticationFailed()
        try:
            return parts[1].decode()
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed()
