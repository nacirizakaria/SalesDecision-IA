"""Fonctions métier autorisées pour l'assistant.

Tous les chiffres sont calculés par Python/Django à partir du QuerySet déjà
filtré et autorisé par la vue. Aucun texte produit par le LLM n'est exécuté.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from .assistant_intents import IntentName, SalesIntent
from ..recommandations import calculer_indicateurs, generer_recommandations


def percentage_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def _metric_value(values, metric):
    if metric == 'margin':
        return values['marge']
    if metric == 'quantity':
        return values['quantite']
    if metric == 'average_basket':
        return values['ca'] / values['rows'] if values['rows'] else 0
    if metric == 'margin_rate':
        return values['marge'] / values['ca'] * 100 if values['ca'] else None
    return values['ca']


def _scope(ventes, plan: SalesIntent):
    filters = plan.filters
    if filters.start_date:
        ventes = ventes.filter(date__gte=filters.start_date)
    if filters.end_date:
        ventes = ventes.filter(date__lte=filters.end_date)
    if filters.product:
        ventes = ventes.filter(produit=filters.product)
    if filters.client:
        ventes = ventes.filter(client=filters.client)
    if filters.region:
        ventes = ventes.filter(region=filters.region)
    return ventes


def _kpi_period_label(rows) -> str:
    dates = sorted(row['date'] for row in rows if isinstance(row.get('date'), date))
    if not dates:
        return 'Période non datée'
    first, last = dates[0], dates[-1]
    if first.year == last.year and first.month == 1 and last.month == 12:
        return str(first.year)
    if first.year == last.year and first.month == last.month:
        return f'{first:%m/%Y}'
    return f'{first:%d/%m/%Y} — {last:%d/%m/%Y}'


def calculate_kpi(ventes, metric='revenue') -> dict[str, Any]:
    ind = calculer_indicateurs(ventes)
    if not ind['row_count']:
        return {
            'available': False,
            'reason': 'Aucune vente ne correspond à la période et aux filtres demandés.',
            'metric': metric,
            'value': None,
            'values_used': {},
            'row_count': 0,
            'period': ind['period_label'],
        }
    total = {'ca': 0.0, 'marge': 0.0, 'quantite': 0.0, 'rows': 0}
    for row in ind['rows']:
        for key in total:
            total[key] += row[key] if key != 'rows' else 1
    return {
        'available': True,
        'metric': metric,
        'value': _metric_value(total, metric),
        'values_used': total,
        'row_count': ind['row_count'],
        'period': _kpi_period_label(ind['rows']),
    }


def compare_periods(ventes, metric='revenue') -> dict[str, Any]:
    ind = calculer_indicateurs(ventes)
    current, previous = ind['current_month'], ind['previous_month']
    if not current or not previous or not ind['comparison_available']:
        return {'available': False, 'reason': 'Deux périodes comparables sont nécessaires.'}
    current_value = _metric_value(ind['by_month'][current], metric)
    previous_value = _metric_value(ind['by_month'][previous], metric)
    return {
        'available': True, 'metric': metric,
        'current_period': current.isoformat(), 'previous_period': previous.isoformat(),
        'current_value': current_value, 'previous_value': previous_value,
        'absolute_change': current_value - previous_value,
        'percentage_change': percentage_change(current_value, previous_value),
        'values_used': {
            'current': ind['by_month'][current],
            'previous': ind['by_month'][previous],
        },
    }


def rank_dimension(ventes, dimension, metric='revenue', limit=10) -> dict[str, Any]:
    ind = calculer_indicateurs(ventes)
    groups = defaultdict(lambda: {'ca': 0.0, 'marge': 0.0, 'quantite': 0.0, 'rows': 0})
    for row in ind['rows']:
        name = row[dimension]
        for key in ('ca', 'marge', 'quantite'):
            groups[name][key] += row[key]
        groups[name]['rows'] += 1
    ranking = sorted(
        ({'entity': name, **values, 'value': _metric_value(values, metric)}
         for name, values in groups.items()),
        key=lambda item: item['value'] if item['value'] is not None else float('-inf'),
        reverse=True,
    )[:limit]
    return {
        'dimension': dimension, 'metric': metric, 'ranking': ranking,
        'period': ind['period_label'], 'row_count': ind['row_count'],
    }


def analyze_entity(ventes, dimension, entity, metric='revenue') -> dict[str, Any]:
    if not entity:
        return {'available': False, 'reason': f'Précisez le {dimension} à analyser.'}
    field = {'produit': 'produit', 'client': 'client', 'region': 'region'}[dimension]
    scoped = ventes.filter(**{field: entity})
    kpi = calculate_kpi(scoped, metric)
    comparison = compare_periods(scoped, metric)
    return {
        'available': bool(kpi['row_count']), 'dimension': dimension,
        'entity': entity, 'kpi': kpi, 'comparison': comparison,
    }


def detect_sales_anomalies(ventes, forecast=None) -> dict[str, Any]:
    items = generer_recommandations(ventes, prediction=forecast)
    return {
        'anomalies': [
            {
                'type': item['rule_id'], 'priority': item['priority'],
                'entity': item['entity_name'], 'period': item['period'],
                'current_value': item['current_value'],
                'previous_value': item['reference_value'],
                'percentage_change': item['variation_percent'],
                'evidence': [item['justification']],
            }
            for item in items
            if item['rule_id'] != 'REC_DONNEES_INSUFFISANTES'
        ],
        'warnings': [
            item['justification'] for item in items
            if item['rule_id'] == 'REC_DONNEES_INSUFFISANTES'
        ],
    }


def get_arima_forecast(forecast) -> dict[str, Any]:
    return {
        'available': bool((forecast or {}).get('rows')),
        'source': 'forecast', 'forecast': forecast or {},
        'warning': 'Une prévision est une estimation, pas une certitude.',
    }


def generate_business_recommendations(ventes, forecast=None) -> dict[str, Any]:
    return {'recommendations': generer_recommandations(ventes, prediction=forecast)}


def get_executive_summary(ventes, forecast=None) -> dict[str, Any]:
    """Assemble une vue dirigeante courte à partir des calculs métier validés."""
    return {
        'kpi': calculate_kpi(ventes, 'revenue'),
        'comparison': compare_periods(ventes, 'revenue'),
        **detect_sales_anomalies(ventes, forecast),
    }


def execute_intent(plan: SalesIntent, ventes, forecast=None) -> dict[str, Any]:
    scoped = _scope(ventes, plan)
    intent, metric = plan.intent, plan.metric or 'revenue'
    if intent == IntentName.GET_EXECUTIVE_SUMMARY:
        return get_executive_summary(scoped, forecast)
    if intent == IntentName.GET_KPI:
        result = calculate_kpi(scoped, metric)
        start, end = plan.filters.start_date, plan.filters.end_date
        if (
            result.get('available') and start and end
            and start.month == 1 and start.day == 1
            and end == date(start.year, 12, 31)
        ):
            result['period'] = str(start.year)
        return result
    if intent == IntentName.COMPARE_PERIODS:
        return compare_periods(scoped, metric)
    if intent in {IntentName.RANK_PRODUCTS, IntentName.COMPARE_PRODUCTS}:
        return rank_dimension(scoped, 'produit', metric)
    if intent in {IntentName.RANK_CLIENTS, IntentName.COMPARE_CLIENTS}:
        return rank_dimension(scoped, 'client', metric)
    if intent in {IntentName.RANK_REGIONS, IntentName.COMPARE_REGIONS}:
        return rank_dimension(scoped, 'region', metric)
    if intent == IntentName.ANALYZE_PRODUCT:
        return analyze_entity(scoped, 'produit', plan.filters.product, metric)
    if intent == IntentName.ANALYZE_CUSTOMER:
        return analyze_entity(scoped, 'client', plan.filters.client, metric)
    if intent == IntentName.ANALYZE_REGION:
        return analyze_entity(scoped, 'region', plan.filters.region, metric)
    if intent == IntentName.DETECT_ANOMALIES:
        return detect_sales_anomalies(scoped, forecast)
    if intent in {IntentName.GET_FORECAST, IntentName.COMPARE_ACTUAL_FORECAST}:
        return get_arima_forecast(forecast)
    if intent == IntentName.GET_RECOMMENDATIONS:
        return generate_business_recommendations(scoped, forecast)
    return {'available': False, 'reason': plan.clarification_question or 'Demande non prise en charge.'}
