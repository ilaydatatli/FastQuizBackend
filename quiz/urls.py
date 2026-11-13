from django.urls import path

from . import views

app_name = "quiz"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("categories/", views.categories, name="categories"),
    path("quizzes/", views.start_quiz, name="start-quiz"),
    path("quizzes/<uuid:quiz_id>/current/", views.current_question, name="current-question"),
    path("quizzes/<uuid:quiz_id>/answers/", views.answer, name="answer"),
]
