"""Réponses conversationnelles contrôlées sur une recommandation existante."""
import re
import unicodedata


def _normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def answer_recommendation_question(recommendation, question):
    """Répond uniquement avec les champs auditables de la recommandation."""
    normalized = _normalize(question)
    evidence = recommendation.get("evidence") or {}
    components = evidence.get("score_components") or {}

    if re.search(r"\b(pourquoi|raison|declenche|constat|explique)\b", normalized):
        return (
            f"{recommendation['justification']} "
            f"Cette conclusion provient exclusivement de la règle "
            f"{recommendation['rule_id']} sur la période {recommendation['period']}."
        )
    if re.search(r"\b(score|priorite|grave|urgence)\b", normalized):
        if components:
            details = ", ".join(
                f"{label} {float(components.get(key, 0)) * 100:.0f}/100"
                for key, label in (
                    ("severity", "gravité"), ("financial_impact", "impact"),
                    ("duration", "durée"), ("data_reliability", "fiabilité des données"),
                    ("confidence", "confiance"),
                )
            )
            return (
                f"Le score est de {recommendation['score']}/100, soit une priorité "
                f"{recommendation['priority']}. Composantes : {details}."
            )
        return f"Le score est de {recommendation['score']}/100 et la priorité est {recommendation['priority']}."
    if re.search(r"\b(action|faire|agir|conseil|recommande)\b", normalized):
        return (
            f"Action recommandée : {recommendation['recommended_action']} "
            "Cette action doit être validée par le décideur avant exécution."
        )
    if re.search(r"\b(preuves?|chiffres?|donnees?|valeurs?|calculs?|seuils?)\b", normalized):
        variation = recommendation.get("variation_percent")
        comparison = (
            f"Valeur observée : {recommendation.get('current_value')}; "
            f"référence : {recommendation.get('reference_value')}"
        )
        if variation is not None:
            comparison += f"; variation : {variation:+.2f} %"
        return f"{comparison}. Période : {recommendation['period']}. Règle : {recommendation['rule_id']}."
    if re.search(r"\b(confiance|fiable|fiabilite)\b", normalized):
        return (
            f"Le niveau de confiance calculé est de "
            f"{float(recommendation['confidence']) * 100:.0f} %. Il dépend du volume, "
            "de la profondeur historique et de la complétude des données."
        )
    if re.search(r"\b(periode|mois|annee|date)\b", normalized):
        return f"La comparaison porte sur {recommendation['period']}."
    if re.search(r"\b(regle|rule)\b", normalized):
        return (
            f"La règle déclenchée est {recommendation['rule_id']}. "
            f"Indicateur contrôlé : {recommendation['metric_name']}."
        )
    return (
        "Je peux expliquer le constat, les chiffres, le score, la confiance, "
        "la période, la règle ou l’action recommandée. Je ne peux pas conclure "
        "au-delà des preuves calculées par le moteur."
    )
