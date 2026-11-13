import uuid

from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True)
    description = models.CharField(max_length=150, blank=True)
    # Design color key used by the client: cyan, violet, orange, lime, pink, blue, yellow
    color = models.CharField(max_length=20)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "kategori"
        verbose_name_plural = "kategoriler"

    def __str__(self):
        return self.name


class Question(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="questions")
    text = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__order", "id"]
        verbose_name = "soru"
        verbose_name_plural = "sorular"
        constraints = [
            # Lets load_questions find the same question again (idempotent loading).
            models.UniqueConstraint(
                fields=["category", "text"], name="unique_question_text_per_category"
            ),
        ]

    def __str__(self):
        return self.text


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=60)
    is_correct = models.BooleanField(default=False)
    # Only for ordering in the admin; the client receives choices shuffled.
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "şık"
        verbose_name_plural = "şıklar"

    def __str__(self):
        return self.text


class QuizSession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Devam ediyor"
        FINISHED = "finished", "Bitti"
        EXPIRED = "expired", "Süresi doldu"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # SHA-256 hex digest of the raw token; the raw token is never stored.
    token_hash = models.CharField(max_length=64, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="sessions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    current_index = models.PositiveSmallIntegerField(default=0)
    points = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "quiz oturumu"
        verbose_name_plural = "quiz oturumları"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "finished", "expired"]),
                name="quiz_session_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.category} · {self.get_status_display()} · {self.id}"


class SessionQuestion(models.Model):
    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveSmallIntegerField()
    # Shuffled choice ids for this session, so a page refresh shows the same order.
    choice_order = models.JSONField(default=list)
    # Server time when the question was first sent. Written once, never reset.
    shown_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    selected_choice = models.ForeignKey(
        Choice, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_correct = models.BooleanField(null=True, blank=True)
    timed_out = models.BooleanField(default=False)
    points = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["session", "position"]
        verbose_name = "oturum sorusu"
        verbose_name_plural = "oturum soruları"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "position"], name="unique_position_per_session"
            ),
            models.UniqueConstraint(
                fields=["session", "question"], name="unique_question_per_session"
            ),
        ]

    def __str__(self):
        return f"#{self.position} · {self.question}"


class Score(models.Model):
    # One quiz can be saved to the leaderboard at most once.
    session = models.OneToOneField(QuizSession, on_delete=models.CASCADE, related_name="score")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="scores")
    nickname = models.CharField(max_length=16)
    # Copied from the session on the server; the client never sends these.
    points = models.PositiveIntegerField()
    correct_count = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "-points", "-correct_count", "created_at"]
        verbose_name = "skor"
        verbose_name_plural = "skorlar"
        indexes = [
            # Leaderboard query: one category, best first.
            models.Index(
                fields=["category", "-points", "-correct_count", "created_at"],
                name="score_leaderboard_idx",
            ),
        ]

    def __str__(self):
        return f"{self.nickname} · {self.points}"
