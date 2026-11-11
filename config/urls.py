from django.contrib import admin
from django.urls import include, path, re_path

from quiz.exceptions import json_not_found

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("quiz.urls")),
    # Any other /api/... path: JSON 404 (even with DEBUG=True, where Django
    # would otherwise show its HTML debug page).
    re_path(r"^api/", json_not_found),
]

handler404 = "quiz.exceptions.json_not_found"
handler500 = "quiz.exceptions.json_server_error"
