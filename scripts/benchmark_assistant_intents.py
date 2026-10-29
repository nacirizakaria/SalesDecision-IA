"""Mesure réelle de la classification d'intentions avec le modèle configuré."""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DecisionIQ.settings')

import django

django.setup()

from django.conf import settings
from sales.services.assistant_intents import deterministic_intent, resolve_intent


CATALOG = {
    'products': ['A', 'B'],
    'clients': ['Client Alpha', 'Client Beta'],
    'regions': ['Casablanca', 'Rabat'],
}


def main():
    questions = json.loads(
        (Path(__file__).parents[1] / 'sales' / 'assistant_question_set.json')
        .read_text(encoding='utf-8')
    )
    correct = valid = routed = 0
    timings = []
    failures = []
    for case in questions:
        if deterministic_intent(case['question'], CATALOG).intent.value == 'clarification':
            routed += 1
        started = time.perf_counter()
        plan, source = resolve_intent(case['question'], CATALOG, use_llm=True)
        timings.append(time.perf_counter() - started)
        valid += source == 'ollama'
        if plan.intent.value == case['intent']:
            correct += 1
        else:
            failures.append({
                'question': case['question'], 'expected': case['intent'],
                'actual': plan.intent.value, 'source': source,
            })
    total = len(questions)
    print(json.dumps({
        'model': settings.OLLAMA_ASSISTANT_MODEL,
        'questions': total,
        'intent_accuracy_pct': round(correct / total * 100, 2),
        'llm_routed_pct': round(routed / total * 100, 2),
        'llm_json_success_pct': round(valid / routed * 100, 2) if routed else None,
        'mean_seconds': round(sum(timings) / total, 3),
        'max_seconds': round(max(timings), 3),
        'failures': failures,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
