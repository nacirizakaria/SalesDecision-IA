"""Mémoire contrôlée des formulations validées par les utilisateurs."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from ..models import ChatInteraction, LearnedChatExample


def normalize_question(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0
    sequence = SequenceMatcher(None, left, right).ratio()
    return round((0.6 * jaccard) + (0.4 * sequence), 4)


def find_validated_examples(question: str, user, limit: int = 3) -> list[dict]:
    normalized = normalize_question(question)
    candidates = (
        LearnedChatExample.objects.filter(active=True, interaction__user=user)
        .select_related('interaction')
        .order_by('-updated_at')[:200]
    )
    ranked = sorted(
        (
            (_similarity(normalized, example.normalized_question), example)
            for example in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        {
            'question': example.interaction.question,
            'answer': example.interaction.answer[:1200],
            'similarity': score,
        }
        for score, example in ranked[:limit]
        if score >= 0.35
    ]


def record_feedback(interaction: ChatInteraction, helpful: bool) -> None:
    interaction.helpful = helpful
    interaction.save(update_fields=['helpful'])
    if helpful:
        LearnedChatExample.objects.update_or_create(
            interaction=interaction,
            defaults={
                'normalized_question': normalize_question(interaction.question),
                'active': True,
            },
        )
    else:
        LearnedChatExample.objects.filter(interaction=interaction).update(active=False)
