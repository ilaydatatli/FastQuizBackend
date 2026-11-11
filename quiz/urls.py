from django.urls import path

from . import views

app_name = "quiz"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("categories/", views.categories, name="categories"),
    path("quizzes/", views.start_quiz, name="start-quiz"),
]
