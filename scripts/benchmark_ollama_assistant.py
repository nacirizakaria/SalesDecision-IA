"""Benchmark facultatif Ollama, sans téléchargement automatique de modèle."""

import argparse
import json
import statistics
import time
import urllib.request


DEFAULT_MODELS = ['qwen3:1.7b', 'qwen3:1.7b-q8_0', 'qwen3:4b']
QUESTIONS = [
    'Quel est le chiffre d’affaires total ?',
    'Compare les ventes des deux derniers mois.',
    'Quels sont les principaux risques commerciaux ?',
    'Quelle est la fiabilité de la prévision ?',
]


def request_json(url, payload=None, timeout=180):
    data = json.dumps(payload).encode() if payload else None
    request = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'},
        method='POST' if data else 'GET',
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def stream_chat(url, payload, timeout=180):
    payload = {**payload, 'stream': True}
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    started = time.perf_counter()
    first_token = None
    final = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            event = json.loads(raw_line.decode())
            content = (event.get('message') or {}).get('content')
            if content and first_token is None:
                first_token = time.perf_counter() - started
            if event.get('done'):
                final = event
    return final, first_token, time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--models', nargs='*', default=DEFAULT_MODELS)
    args = parser.parse_args()
    installed = {
        model['name']: model for model in request_json(f'{args.base_url}/api/tags').get('models', [])
    }
    results = []
    for model in args.models:
        if model not in installed:
            results.append({'model': model, 'status': 'non_installe'})
            continue
        timings, first_tokens, token_rates = [], [], []
        for question in QUESTIONS:
            response, first_token, elapsed = stream_chat(f'{args.base_url}/api/chat', {
                'model': model, 'think': False, 'keep_alive': '5m',
                'messages': [
                    {'role': 'system', 'content': 'Réponds en français, en 60 mots maximum.'},
                    {'role': 'user', 'content': question},
                ],
                'options': {'temperature': .1, 'num_ctx': 2048, 'num_predict': 120},
            })
            timings.append(elapsed)
            if first_token is not None:
                first_tokens.append(first_token)
            evaluation_seconds = float(response.get('eval_duration') or 0) / 1e9
            if evaluation_seconds:
                token_rates.append(float(response.get('eval_count') or 0) / evaluation_seconds)
        results.append({
            'model': model, 'status': 'ok',
            'disk_size_mb': round(installed[model].get('size', 0) / 1024 / 1024, 1),
            'median_total_seconds': round(statistics.median(timings), 3),
            'median_first_token_seconds': (
                round(statistics.median(first_tokens), 3) if first_tokens else None
            ),
            'mean_tokens_per_second': round(statistics.mean(token_rates), 2) if token_rates else None,
        })
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
