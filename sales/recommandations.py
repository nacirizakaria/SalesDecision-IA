"""Moteur déterministe et explicable de recommandations commerciales.

Le module ne fait aucune prédiction et n'emploie aucun LLM. Il transforme les
ventes déjà filtrées et, facultativement, la validation rétrospective ARIMA en
indicateurs, puis applique des règles métier stables et auditables.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from calendar import monthrange
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import uuid4

from django.conf import settings
from django.db.models import DecimalField, ExpressionWrapper, F, QuerySet
from django.utils import timezone


DEFAULT_THRESHOLDS = {
    # Variations : les seuils sont supérieurs au bruit commercial mensuel usuel.
    "decline_pct": 10.0,
    "strong_decline_pct": 20.0,
    "growth_pct": 20.0,
    "quantity_anomaly_pct": 30.0,
    "margin_rate_low_pct": 10.0,
    "margin_rate_critical_pct": 0.0,
    "high_revenue_share_pct": 20.0,
    # Concentration : au-delà de 40 %, la défaillance d'une entité devient matérielle.
    "product_dependency_pct": 40.0,
    "client_dependency_pct": 35.0,
    "region_concentration_pct": 50.0,
    "region_underperformance_pct": 25.0,
    "important_client_share_pct": 15.0,
    "forecast_gap_pct": 20.0,
    "margin_decline_pct": 10.0,
    # Qualité minimale : deux périodes comparables et un volume non trivial.
    "min_periods": 2,
    "min_rows": 5,
    "min_entity_reference_ca": 100.0,
    "max_recommendations": 8,
}

PRIORITY_RANK = {"critique": 4, "élevée": 3, "moyenne": 2, "faible": 1}


@dataclass(frozen=True)
class Recommendation:
    id: str
    rule_id: str
    title: str
    message: str
    justification: str
    recommended_action: str
    priority: str
    score: int
    confidence: float
    entity_type: str
    entity_name: str
    metric_name: str
    current_value: float | None
    reference_value: float | None
    variation_percent: float | None
    period: str
    triggered_at: str
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "nouvelle"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _thresholds(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = DEFAULT_THRESHOLDS | getattr(settings, "RECOMMENDATION_THRESHOLDS", {})
    return values | (overrides or {})


def _pct(current: float, reference: float) -> float | None:
    if reference == 0:
        return None
    return round((current - reference) / abs(reference) * 100, 2)


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _confidence(row_count: int, completeness: float, periods: int, forecast_confidence: str | None = None) -> float:
    volume = min(1.0, row_count / 30)
    history = min(1.0, periods / 6)
    value = 0.45 * completeness + 0.30 * volume + 0.25 * history
    if forecast_confidence:
        value *= {"haute": 1.0, "moyenne": .85, "basse": .65}.get(forecast_confidence, .7)
    return round(max(0.0, min(1.0, value)), 2)


def calculer_score(
    severity: float,
    financial_impact: float,
    duration: float,
    data_reliability: float,
    confidence: float,
) -> int:
    """Retourne un score 0–100 et conserve ses cinq composantes dans l'evidence.

    Chaque entrée est normalisée entre 0 et 1. La gravité et l'impact financier
    dominent (60 %), sans permettre à des données peu fiables d'obtenir un score
    artificiellement critique.
    """
    components = [severity, financial_impact, duration, data_reliability, confidence]
    components = [max(0.0, min(1.0, float(value))) for value in components]
    score = 100 * (
        .35 * components[0] + .25 * components[1] + .15 * components[2]
        + .15 * components[3] + .10 * components[4]
    )
    return round(score)


def determiner_priorite(score: int) -> str:
    if score >= 80:
        return "critique"
    if score >= 60:
        return "élevée"
    if score >= 40:
        return "moyenne"
    return "faible"


def _recommendation(
    rule_id: str,
    title: str,
    message: str,
    action: str,
    entity_type: str,
    entity_name: str,
    metric: str,
    current: float | None,
    reference: float | None,
    variation: float | None,
    period: str,
    severity: float,
    impact: float,
    duration: float,
    reliability: float,
    confidence: float,
    evidence: dict[str, Any],
) -> Recommendation:
    score = calculer_score(severity, impact, duration, reliability, confidence)
    evidence = {
        **evidence,
        "score_components": {
            "severity": round(severity, 3), "financial_impact": round(impact, 3),
            "duration": round(duration, 3), "data_reliability": round(reliability, 3),
            "confidence": round(confidence, 3),
        },
    }
    return Recommendation(
        id=str(uuid4()), rule_id=rule_id, title=title, message=message,
        justification=message, recommended_action=action,
        priority=determiner_priorite(score), score=score, confidence=confidence,
        entity_type=entity_type, entity_name=entity_name, metric_name=metric,
        current_value=None if current is None else round(current, 2),
        reference_value=None if reference is None else round(reference, 2),
        variation_percent=variation, period=period,
        triggered_at=timezone.now().isoformat(), evidence=evidence,
    )


def calculer_indicateurs(
    ventes: QuerySet | Iterable[dict[str, Any]],
    comparison_mode: str = "previous_month",
) -> dict[str, Any]:
    """Sépare le calcul des indicateurs de l'évaluation des règles."""
    if isinstance(ventes, QuerySet):
        ca_expr = ExpressionWrapper(
            F("quantite") * F("prix_unitaire"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
        cout_expr = ExpressionWrapper(
            F("quantite") * F("cout_unitaire"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
        rows = list(ventes.annotate(_ca=ca_expr, _cout=cout_expr).values(
            "date", "produit", "client", "region", "quantite", "_ca", "_cout"
        ))
    else:
        rows = list(ventes)

    normalized = []
    complete = 0
    for row in rows:
        quantity = float(row.get("quantite") or 0)
        ca = float(row.get("_ca", row.get("ca", quantity * float(row.get("prix_unitaire") or 0))) or 0)
        cost = float(row.get("_cout", row.get("cout", quantity * float(row.get("cout_unitaire") or 0))) or 0)
        date = row.get("date")
        if isinstance(date, datetime):
            date = date.date()
        if date and row.get("produit") and row.get("client") and row.get("region"):
            complete += 1
        normalized.append({
            "date": date, "produit": row.get("produit") or "Non renseigné",
            "client": row.get("client") or "Non renseigné",
            "region": row.get("region") or "Non renseignée",
            "quantite": quantity, "ca": ca, "marge": ca - cost,
        })

    months = sorted({r["date"].replace(day=1) for r in normalized if r["date"]})
    latest_month = months[-1] if months else None
    if comparison_mode == "previous_year":
        bucket_for = lambda value: value.replace(month=1, day=1)
        periods = sorted({bucket_for(r["date"]) for r in normalized if r["date"]})
        current_month = periods[-1] if periods else None
        previous_month = current_month.replace(year=current_month.year - 1) if current_month else None
        period_label = (
            f"{current_month:%Y} vs {previous_month:%Y}"
            if current_month and previous_month else "Comparaison annuelle"
        )
    latest_date = max((r["date"] for r in normalized if r["date"]), default=None)
    previous_year_cutoff = None
    if latest_date and comparison_mode == "previous_year":
        previous_year = latest_date.year - 1
        previous_year_cutoff = latest_date.replace(
            year=previous_year,
            day=min(latest_date.day, monthrange(previous_year, latest_date.month)[1]),
        )
    elif comparison_mode == "same_month_previous_year":
        bucket_for = lambda value: value.replace(day=1)
        periods = months
        current_month = latest_month
        previous_month = current_month.replace(year=current_month.year - 1) if current_month else None
        period_label = (
            f"{current_month:%m/%Y} vs {previous_month:%m/%Y}"
            if current_month and previous_month else "Même mois de l’année précédente"
        )
    else:
        comparison_mode = "previous_month"
        bucket_for = lambda value: value.replace(day=1)
        periods = months
        current_month = latest_month
        previous_month = periods[-2] if len(periods) >= 2 else None
        period_label = (
            f"{current_month:%m/%Y} vs {previous_month:%m/%Y}"
            if current_month and previous_month else "Comparaison mensuelle"
        )
    by_month: dict[Any, dict[str, float]] = {}
    for row in normalized:
        if not row["date"]:
            continue
        if previous_year_cutoff and row["date"].year == previous_year_cutoff.year and row["date"] > previous_year_cutoff:
            continue
        month = bucket_for(row["date"])
        bucket = by_month.setdefault(month, {"ca": 0.0, "marge": 0.0, "quantite": 0.0, "rows": 0})
        for metric in ("ca", "marge", "quantite"):
            bucket[metric] += row[metric]
        bucket["rows"] += 1

    dimensions: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for dimension in ("produit", "client", "region"):
        dimensions[dimension] = {}
        for month in (previous_month, current_month):
            groups: dict[str, dict[str, float]] = {}
            if month:
                for row in normalized:
                    if previous_year_cutoff and row["date"] and row["date"].year == previous_year_cutoff.year and row["date"] > previous_year_cutoff:
                        continue
                    if row["date"] and bucket_for(row["date"]) == month:
                        bucket = groups.setdefault(row[dimension], {"ca": 0.0, "marge": 0.0, "quantite": 0.0, "rows": 0})
                        for metric in ("ca", "marge", "quantite"):
                            bucket[metric] += row[metric]
                        bucket["rows"] += 1
            dimensions[dimension][month] = groups

    return {
        "rows": normalized, "row_count": len(normalized), "months": periods,
        "current_month": current_month, "previous_month": previous_month,
        "by_month": by_month, "dimensions": dimensions,
        "completeness": complete / len(normalized) if normalized else 0.0,
        "comparison_mode": comparison_mode, "period_label": period_label,
        "comparison_available": bool(
            current_month in by_month and previous_month in by_month
        ),
    }


def _period(ind: dict, current: Any | None = None) -> str:
    if current is not None and ind.get("comparison_mode") == "previous_year":
        return f"{current:%Y}"
    return ind.get("period_label") or (
        f"{ind['current_month']:%m/%Y} vs {ind['previous_month']:%m/%Y}"
    )


def evaluer_ca_global(ind: dict, t: dict) -> list[Recommendation]:
    cur, prev = ind["current_month"], ind["previous_month"]
    if not cur or not prev:
        return []
    current, reference = ind["by_month"][cur]["ca"], ind["by_month"][prev]["ca"]
    variation = _pct(current, reference)
    if variation is None or variation > -t["decline_pct"]:
        return []
    loss = max(0.0, reference - current)
    conf = _confidence(ind["row_count"], ind["completeness"], len(ind["months"]))
    text = f"Le chiffre d’affaires global a diminué de {abs(variation):.1f} %, soit {_money(loss)} MAD de moins que le mois précédent."
    return [_recommendation(
        "REC_CA_GLOBAL_BAISSE", "Baisse du chiffre d’affaires global", text,
        "Analyser les pertes par produit, client et région, puis sécuriser les opportunités à court terme.",
        "global", "Entreprise", "chiffre_affaires", current, reference, variation,
        _period(ind), min(1, abs(variation) / 30),
        min(1, loss / max(reference * .25, 1)), .5, ind["completeness"], conf,
        {"loss_mad": round(loss, 2), "threshold_pct": t["decline_pct"]},
    )]


def evaluer_dimensions(ind: dict, t: dict) -> list[Recommendation]:
    results: list[Recommendation] = []
    cur, prev = ind["current_month"], ind["previous_month"]
    if not cur or not prev:
        return results
    current_total = ind["by_month"][cur]["ca"]
    reference_total = ind["by_month"][prev]["ca"]
    conf = _confidence(ind["row_count"], ind["completeness"], len(ind["months"]))
    labels = {"produit": "produit", "client": "client", "region": "région"}
    for dimension in ("produit", "client", "region"):
        current_groups = ind["dimensions"][dimension][cur]
        previous_groups = ind["dimensions"][dimension][prev]
        for name in set(current_groups) | set(previous_groups):
            current = current_groups.get(name, {"ca": 0, "marge": 0, "quantite": 0})
            reference = previous_groups.get(name, {"ca": 0, "marge": 0, "quantite": 0})
            if reference["ca"] < t["min_entity_reference_ca"]:
                continue
            variation = _pct(current["ca"], reference["ca"])
            loss = max(0.0, reference["ca"] - current["ca"])
            share_ref = 100 * reference["ca"] / reference_total if reference_total else 0
            if dimension == "produit" and variation is not None and variation <= -t["strong_decline_pct"]:
                text = f"Le chiffre d’affaires du produit {name} a diminué de {abs(variation):.1f} %, soit une perte estimée de {_money(loss)} MAD."
                results.append(_recommendation(
                    "REC_PRODUIT_BAISSE", f"Forte baisse du produit {name}", text,
                    "Vérifier la demande, le stock et le positionnement prix ; envisager une campagne ciblée si la marge le permet.",
                    dimension, name, "chiffre_affaires", current["ca"], reference["ca"], variation,
                    _period(ind), min(1, abs(variation) / 40),
                    min(1, loss / max(current_total * .15, 1)), .5, ind["completeness"], conf,
                    {"loss_mad": loss, "threshold_pct": t["strong_decline_pct"]},
                ))
            if dimension == "client" and share_ref >= t["important_client_share_pct"] and variation is not None and variation <= -t["decline_pct"]:
                text = f"Les achats du client {name}, qui représentaient {share_ref:.1f} % du CA, ont diminué de {abs(variation):.1f} % ({_money(loss)} MAD)."
                results.append(_recommendation(
                    "REC_CLIENT_IMPORTANT_BAISSE", f"Recul du client important {name}", text,
                    "Contacter le client, qualifier le motif du recul et préparer un plan de rétention documenté.",
                    dimension, name, "chiffre_affaires", current["ca"], reference["ca"], variation,
                    _period(ind), min(1, abs(variation) / 30),
                    min(1, share_ref / 30), .5, ind["completeness"], conf,
                    {"reference_share_pct": round(share_ref, 2), "loss_mad": loss},
                ))
            if dimension == "region" and variation is not None and variation <= -t["region_underperformance_pct"]:
                text = f"Le chiffre d’affaires de la région {name} est inférieur de {abs(variation):.1f} % à son niveau du mois précédent ({_money(loss)} MAD)."
                results.append(_recommendation(
                    "REC_REGION_SOUS_PERFORMANTE", f"Région {name} sous-performante", text,
                    "Comparer pipeline, couverture commerciale et disponibilité produit avec les autres régions.",
                    dimension, name, "chiffre_affaires", current["ca"], reference["ca"], variation,
                    _period(ind), min(1, abs(variation) / 40),
                    min(1, loss / max(current_total * .15, 1)), .5, ind["completeness"], conf,
                    {"loss_mad": loss, "threshold_pct": t["region_underperformance_pct"]},
                ))
            if variation is not None and variation >= t["growth_pct"]:
                gain = current["ca"] - reference["ca"]
                text = f"Le chiffre d’affaires du {labels[dimension]} {name} a progressé de {variation:.1f} %, soit {_money(gain)} MAD supplémentaires."
                results.append(_recommendation(
                    f"REC_{dimension.upper()}_PROGRESSION", f"Forte progression — {name}", text,
                    "Identifier les facteurs reproductibles et vérifier la capacité à soutenir cette progression sans dégrader la marge.",
                    dimension, name, "chiffre_affaires", current["ca"], reference["ca"], variation,
                    _period(ind), min(1, variation / 50),
                    min(1, gain / max(current_total * .15, 1)), .5, ind["completeness"], conf,
                    {"gain_mad": gain, "threshold_pct": t["growth_pct"]},
                ))
            quantity_variation = _pct(current["quantite"], reference["quantite"])
            if dimension == "produit" and quantity_variation is not None and abs(quantity_variation) >= t["quantity_anomaly_pct"]:
                text = f"Les quantités vendues du produit {name} ont varié de {quantity_variation:+.1f} % ({reference['quantite']:.0f} à {current['quantite']:.0f} unités)."
                results.append(_recommendation(
                    "REC_QUANTITE_ANORMALE", f"Variation anormale des quantités — {name}", text,
                    "Contrôler les données, les ruptures, commandes exceptionnelles et promotions avant d'ajuster les approvisionnements.",
                    dimension, name, "quantite", current["quantite"], reference["quantite"], quantity_variation,
                    _period(ind), min(1, abs(quantity_variation) / 60),
                    min(1, current["ca"] / max(current_total * .2, 1)), .5, ind["completeness"], conf,
                    {"threshold_pct": t["quantity_anomaly_pct"]},
                ))
    return results


def evaluer_marges(ind: dict, t: dict) -> list[Recommendation]:
    cur, prev = ind["current_month"], ind["previous_month"]
    if not cur:
        return []
    results = []
    total = ind["by_month"][cur]["ca"]
    conf = _confidence(ind["row_count"], ind["completeness"], len(ind["months"]))
    for name, values in ind["dimensions"]["produit"][cur].items():
        if values["ca"] <= 0:
            continue
        rate = 100 * values["marge"] / values["ca"]
        share = 100 * values["ca"] / total if total else 0
        if rate <= t["margin_rate_low_pct"]:
            rule = "REC_MARGE_NEGATIVE" if rate <= t["margin_rate_critical_pct"] else "REC_MARGE_FAIBLE"
            text = f"La marge du produit {name} est de {_money(values['marge'])} MAD, soit {rate:.1f} % d’un CA de {_money(values['ca'])} MAD."
            results.append(_recommendation(
                rule, f"{'Marge négative' if rate <= 0 else 'Marge faible'} — {name}", text,
                "Revoir coûts, remises et prix ; suspendre les promotions non rentables jusqu'à validation.",
                "produit", name, "taux_marge", rate, t["margin_rate_low_pct"], rate - t["margin_rate_low_pct"],
                _period(ind, cur), min(1, max(0, t["margin_rate_low_pct"] - rate) / 20),
                min(1, values["ca"] / max(total * .2, 1)), .5, ind["completeness"], conf,
                {"margin_mad": values["marge"], "revenue_share_pct": round(share, 2)},
            ))
            if share >= t["high_revenue_share_pct"]:
                results.append(_recommendation(
                    "REC_PRODUIT_CA_ELEVE_MARGE_FAIBLE", f"CA élevé mais marge faible — {name}", text,
                    "Prioriser une analyse prix-coût-remise sur ce produit à fort impact avant toute action de volume.",
                    "produit", name, "taux_marge", rate, t["margin_rate_low_pct"], rate - t["margin_rate_low_pct"],
                    _period(ind, cur), min(1, (t["margin_rate_low_pct"] - rate) / 20),
                    min(1, share / 40), .5, ind["completeness"], conf,
                    {"margin_mad": values["marge"], "revenue_share_pct": round(share, 2)},
                ))
    if prev:
        current, reference = ind["by_month"][cur], ind["by_month"][prev]
        ca_var, margin_var = _pct(current["ca"], reference["ca"]), _pct(current["marge"], reference["marge"])
        if ca_var is not None and margin_var is not None and ca_var > 0 and margin_var <= -t["margin_decline_pct"]:
            text = f"Le CA a progressé de {ca_var:.1f} %, mais la marge a reculé de {abs(margin_var):.1f} % ({_money(reference['marge'])} à {_money(current['marge'])} MAD)."
            results.append(_recommendation(
                "REC_CA_HAUSSE_MARGE_BAISSE", "Croissance non rentable", text,
                "Isoler les produits et remises responsables, puis conditionner la croissance à un plan de marge.",
                "global", "Entreprise", "marge", current["marge"], reference["marge"], margin_var,
                _period(ind), min(1, abs(margin_var) / 30),
                min(1, current["ca"] / max(reference["ca"], 1)), .5, ind["completeness"], conf,
                {"revenue_variation_pct": ca_var},
            ))
    return results


def evaluer_concentrations(ind: dict, t: dict) -> list[Recommendation]:
    cur = ind["current_month"]
    if not cur:
        return []
    total = ind["by_month"][cur]["ca"]
    if total <= 0:
        return []
    results = []
    conf = _confidence(ind["row_count"], ind["completeness"], len(ind["months"]))
    rules = {
        "produit": ("REC_DEPENDANCE_PRODUIT", t["product_dependency_pct"]),
        "client": ("REC_DEPENDANCE_CLIENT", t["client_dependency_pct"]),
        "region": ("REC_CONCENTRATION_REGION", t["region_concentration_pct"]),
    }
    for dimension, (rule, threshold) in rules.items():
        for name, values in ind["dimensions"][dimension][cur].items():
            share = 100 * values["ca"] / total
            if share < threshold:
                continue
            text = f"{share:.1f} % du chiffre d’affaires mensuel dépend du {dimension} {name} ({_money(values['ca'])} MAD sur {_money(total)} MAD)."
            results.append(_recommendation(
                rule, f"Concentration du CA — {name}", text,
                "Établir un plan de diversification et suivre cette concentration chaque mois.",
                dimension, name, "part_chiffre_affaires", share, threshold, share - threshold,
                _period(ind, cur), min(1, share / 70), min(1, share / 60), .5,
                ind["completeness"], conf, {"entity_ca_mad": values["ca"], "total_ca_mad": total},
            ))
    return results


def evaluer_prevision(ind: dict, t: dict, prediction: dict | None) -> list[Recommendation]:
    validation = (prediction or {}).get("validation_retrospective") or {}
    actual, forecast = validation.get("realise"), validation.get("prevu")
    if actual is None or forecast in (None, 0):
        return []
    variation = _pct(float(actual), float(forecast))
    if variation is None or abs(variation) < t["forecast_gap_pct"]:
        return []
    gap = float(actual) - float(forecast)
    conf = _confidence(
        ind["row_count"], ind["completeness"], len(ind["months"]),
        (prediction or {}).get("fiabilite"),
    )
    text = f"Le CA réalisé ({_money(float(actual))} MAD) s’écarte de {abs(variation):.1f} % de la prévision rétrospective ({_money(float(forecast))} MAD)."
    return [_recommendation(
        "REC_ECART_PREVISION_ARIMA", "Écart important entre réalisé et prévision", text,
        "Rechercher un événement non modélisé et réévaluer la prévision avant de l'utiliser pour engager des ressources.",
        "global", "Entreprise", "ecart_prevision", float(actual), float(forecast), variation,
        str(validation.get("mois") or "validation rétrospective"), min(1, abs(variation) / 40),
        min(1, abs(gap) / max(float(actual) * .2, 1)), .5, ind["completeness"], conf,
        {"gap_mad": round(gap, 2), "forecast_method": (prediction or {}).get("methode")},
    )]


def _insufficient(ind: dict, t: dict) -> list[Recommendation]:
    reasons = []
    if ind["row_count"] < t["min_rows"]:
        reasons.append(f"{ind['row_count']} lignes disponibles, minimum {t['min_rows']}")
    if len(ind["months"]) < t["min_periods"]:
        reasons.append(f"{len(ind['months'])} période(s) disponible(s), minimum {t['min_periods']}")
    elif not ind.get("comparison_available"):
        reasons.append("la période de référence sélectionnée est absente")
    if ind["completeness"] < .7:
        reasons.append(f"complétude des dimensions : {ind['completeness'] * 100:.0f} %")
    if not reasons:
        return []
    text = "Analyse non fiable : " + " ; ".join(reasons) + "."
    return [_recommendation(
        "REC_DONNEES_INSUFFISANTES", "Données insuffisantes", text,
        "Importer au moins deux mois et compléter date, produit, client et région avant toute décision.",
        "global", "Jeu de données", "qualite_donnees", ind["row_count"], t["min_rows"], None,
        "Périmètre filtré", .3, 0, 0, ind["completeness"],
        _confidence(ind["row_count"], ind["completeness"], len(ind["months"])),
        {"reasons": reasons},
    )]


def resoudre_contradictions(items: list[Recommendation]) -> list[Recommendation]:
    """Supprime les signaux opposés portant sur la même entité et métrique.

    Les règles de risque priment sur les opportunités à score égal. Une marge
    faible et une forte progression restent compatibles : elles décrivent deux
    métriques différentes et doivent être montrées ensemble.
    """
    decline_rules = {"REC_PRODUIT_BAISSE", "REC_CLIENT_IMPORTANT_BAISSE", "REC_REGION_SOUS_PERFORMANTE"}
    growth_rules = {"REC_PRODUIT_PROGRESSION", "REC_CLIENT_PROGRESSION", "REC_REGION_PROGRESSION"}
    grouped: dict[tuple[str, str, str], list[Recommendation]] = {}
    for item in items:
        grouped.setdefault((item.entity_type, item.entity_name, item.metric_name), []).append(item)
    result = []
    for group in grouped.values():
        declines = [item for item in group if item.rule_id in decline_rules]
        growth = [item for item in group if item.rule_id in growth_rules]
        if declines and growth:
            contradictory = declines + growth
            winner = sorted(contradictory, key=lambda item: (item.score, item.rule_id in decline_rules), reverse=True)[0]
            result.extend(item for item in group if item not in contradictory)
            result.append(winner)
        else:
            result.extend(group)
    return result


def supprimer_doublons(items: list[Recommendation]) -> list[Recommendation]:
    seen, result = set(), []
    for item in items:
        key = (item.rule_id, item.entity_type, item.entity_name, item.period)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def generer_recommandations(
    ventes: QuerySet | Iterable[dict[str, Any]],
    prediction: dict | None = None,
    thresholds: dict[str, Any] | None = None,
    comparison_mode: str = "previous_month",
) -> list[dict[str, Any]]:
    """Point d'entrée Django : calcule, évalue, arbitre, trie et sérialise."""
    t = _thresholds(thresholds)
    indicators = calculer_indicateurs(ventes, comparison_mode)
    insufficient = _insufficient(indicators, t)
    if insufficient:
        return [item.to_dict() for item in insufficient]
    items = (
        evaluer_ca_global(indicators, t)
        + evaluer_dimensions(indicators, t)
        + evaluer_marges(indicators, t)
        + evaluer_concentrations(indicators, t)
        + evaluer_prevision(indicators, t, prediction)
    )
    items = supprimer_doublons(resoudre_contradictions(items))
    items.sort(key=lambda item: (
        -PRIORITY_RANK[item.priority], -item.score,
        -abs(float(item.evidence.get("loss_mad") or item.evidence.get("gap_mad") or 0)),
        item.rule_id, item.entity_name,
    ))
    return [item.to_dict() for item in items[: int(t["max_recommendations"])]]
