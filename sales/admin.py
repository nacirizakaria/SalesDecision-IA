from django.contrib import admin

from .models import ChatInteraction, LearnedChatExample


@admin.register(ChatInteraction)
class ChatInteractionAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'user', 'intent', 'provider', 'model_name',
        'duration_ms', 'prompt_tokens', 'output_tokens', 'helpful',
    )
    list_filter = ('intent', 'provider', 'helpful', 'created_at')
    search_fields = ('question', 'answer', 'user__username')
    readonly_fields = (
        'user', 'question', 'answer', 'provider', 'model_name', 'intent',
        'provider_response_id', 'duration_ms', 'load_duration_ms',
        'prompt_eval_duration_ms', 'eval_duration_ms', 'prompt_tokens',
        'output_tokens', 'context_characters', 'answer_characters',
        'validation_warnings', 'created_at',
    )


@admin.register(LearnedChatExample)
class LearnedChatExampleAdmin(admin.ModelAdmin):
    list_display = ('updated_at', 'interaction', 'active')
    list_filter = ('active', 'updated_at')
    search_fields = ('normalized_question', 'interaction__question')
    readonly_fields = ('interaction', 'normalized_question', 'created_at', 'updated_at')
