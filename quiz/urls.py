from django.urls import path

from . import views

app_name = "quiz"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("categories/", views.categories, name="categories"),
    path("quizzes/", views.start_quiz, name="start-quiz"),
    path("quizzes/<uuid:quiz_id>/current/", views.current_question, name="current-question"),
    path("quizzes/<uuid:quiz_id>/answers/", views.answer, name="answer"),
    path("quizzes/<uuid:quiz_id>/result/", views.result, name="result"),
    path("quizzes/<uuid:quiz_id>/score/", views.save_score, name="score"),
    path("rooms/", views.create_room, name="create-room"),
    path("rooms/<str:code>/", views.room, name="room"),
    path("rooms/<str:code>/quizzes/", views.join_room, name="join-room"),
    path("leaderboard/", views.overall_leaderboard, name="overall-leaderboard"),
    path("leaderboard/<slug:category_slug>/", views.leaderboard, name="leaderboard"),
]
