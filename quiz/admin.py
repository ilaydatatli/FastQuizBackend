from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import Category, Choice, Question, QuizSession, Score, SessionQuestion

REQUIRED_CHOICES = 4
REQUIRED_CORRECT = 1


class ChoiceInlineFormSet(BaseInlineFormSet):
    """Every question must have exactly 4 choices and exactly 1 correct one."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return  # show the per-field errors first

        kept = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
        ]
        if len(kept) != REQUIRED_CHOICES:
            raise ValidationError(
                f"Her soruda tam {REQUIRED_CHOICES} şık olmalı (şu an {len(kept)})."
            )

        correct = sum(1 for data in kept if data.get("is_correct"))
        if correct != REQUIRED_CORRECT:
            raise ValidationError(
                f"Her soruda tam {REQUIRED_CORRECT} doğru şık olmalı (şu an {correct})."
            )


class ChoiceInline(admin.TabularInline):
    model = Choice
    formset = ChoiceInlineFormSet
    fields = ["order", "text", "text_en", "text_es", "is_correct"]
    extra = REQUIRED_CHOICES
    max_num = REQUIRED_CHOICES


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "color", "order", "is_active"]
    list_editable = ["order", "is_active"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["text", "category", "is_active", "updated_at"]
    list_filter = ["category", "is_active"]
    search_fields = ["text"]
    list_select_related = ["category"]
    inlines = [ChoiceInline]


class ReadOnlyAdminMixin:
    """Quiz data is written only by the API; the admin can only look at it."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SessionQuestionInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = SessionQuestion
    fields = [
        "position",
        "question",
        "shown_at",
        "answered_at",
        "selected_choice",
        "is_correct",
        "timed_out",
        "points",
    ]
    readonly_fields = fields
    extra = 0


@admin.register(QuizSession)
class QuizSessionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "id",
        "category",
        "status",
        "current_index",
        "points",
        "correct_count",
        "started_at",
    ]
    list_filter = ["category", "status"]
    list_select_related = ["category"]
    exclude = ["token_hash"]  # nothing useful to see; keep it out of sight
    inlines = [SessionQuestionInline]


@admin.register(Score)
class ScoreAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["nickname", "category", "points", "correct_count", "created_at"]
    list_filter = ["category"]
    search_fields = ["nickname"]
    list_select_related = ["category"]
