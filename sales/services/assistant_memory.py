"""Mémoire conversationnelle compacte, isolée par utilisateur et session."""

from django.conf import settings
from django.core.cache import cache


def _key(user_id, session_key):
    return f'assistant-memory:{user_id}:{session_key}'


def get_memory(user_id, session_key):
    return cache.get(_key(user_id, session_key), {
        'product': None, 'client': None, 'region': None,
        'last_intent': None, 'last_period': None, 'summary': '',
    })


def update_memory(user_id, session_key, plan, result):
    memory = get_memory(user_id, session_key)
    memory.update({
        'product': plan.filters.product or memory.get('product'),
        'client': plan.filters.client or memory.get('client'),
        'region': plan.filters.region or memory.get('region'),
        'last_intent': plan.intent.value,
        'last_period': result.get('period') or result.get('current_period'),
        'summary': (
            f"Dernière intention: {plan.intent.value}; "
            f"entité: {plan.filters.product or plan.filters.client or plan.filters.region or 'globale'}."
        )[:300],
    })
    cache.set(
        _key(user_id, session_key), memory,
        timeout=settings.ASSISTANT_MEMORY_TTL_SECONDS,
    )
    return memory


def clear_memory(user_id, session_key):
    cache.delete(_key(user_id, session_key))
