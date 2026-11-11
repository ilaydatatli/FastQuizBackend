from rest_framework.throttling import SimpleRateThrottle


class IPRateThrottle(SimpleRateThrottle):
    """Limit by client IP (there are no user accounts). Rates live in DEFAULT_THROTTLE_RATES."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class QuizStartThrottle(IPRateThrottle):
    scope = "quiz_start"
