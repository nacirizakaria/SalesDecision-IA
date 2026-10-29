from datetime import date

import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import ChatInteraction, LearnedChatExample, Vente
from .recommandations import (
    Recommendation, calculer_score, determiner_priorite,
    generer_recommandations, resoudre_contradictions, supprimer_doublons,
)
from .services.recommendation_chat import answer_recommendation_question
from .services.openai_sales_assistant import (
    _render_structured_answer,
    _safe_history,
    answer_common_sales_question,
    build_sales_context,
    detect_question_intent,
    validate_structured_answer,
)


def sale(month, product="A", client="C1", region="Nord", quantity=10, price=100, cost=70):
    return {
        "date": date(2026, month, 15), "produit": product, "client": client,
        "region": region, "quantite": quantity, "prix_unitaire": price,
        "cout_unitaire": cost,
    }


class RecommendationEngineTests(SimpleTestCase):
    thresholds = {"min_rows": 1, "max_recommendations": 50}

    def ids(self, rows, prediction=None, thresholds=None):
        values = self.thresholds | (thresholds or {})
        return {r["rule_id"] for r in generer_recommandations(rows, prediction, values)}

    def test_global_product_client_region_declines_and_quantity(self):
        rows = [
            sale(1, "A", "Important", "Nord", 100, 100),
            sale(1, "B", "Autre", "Sud", 100, 100),
            sale(2, "A", "Important", "Nord", 40, 100),
            sale(2, "B", "Autre", "Sud", 80, 100),
        ]
        ids = self.ids(rows)
        self.assertIn("REC_CA_GLOBAL_BAISSE", ids)
        self.assertIn("REC_PRODUIT_BAISSE", ids)
        self.assertIn("REC_CLIENT_IMPORTANT_BAISSE", ids)
        self.assertIn("REC_REGION_SOUS_PERFORMANTE", ids)
        self.assertIn("REC_QUANTITE_ANORMALE", ids)

    def test_growth_rules_for_all_dimensions(self):
        rows = [sale(1, quantity=10), sale(2, quantity=20)]
        ids = self.ids(rows)
        self.assertTrue({
            "REC_PRODUIT_PROGRESSION", "REC_CLIENT_PROGRESSION",
            "REC_REGION_PROGRESSION",
        }.issubset(ids))

    def test_same_month_previous_year_comparison(self):
        rows = [
            {**sale(5, quantity=100), "date": date(2025, 5, 15)},
            {**sale(5, quantity=70), "date": date(2026, 5, 15)},
        ]
        result = generer_recommandations(
            rows, thresholds=self.thresholds,
            comparison_mode="same_month_previous_year",
        )
        rec = next(r for r in result if r["rule_id"] == "REC_CA_GLOBAL_BAISSE")
        self.assertEqual(rec["period"], "05/2026 vs 05/2025")
        self.assertEqual(rec["variation_percent"], -30.0)

    def test_previous_year_comparison_is_year_to_date(self):
        rows = [
            {**sale(1, quantity=50), "date": date(2025, 1, 15)},
            {**sale(7, quantity=100), "date": date(2025, 7, 15)},
            {**sale(1, quantity=40), "date": date(2026, 1, 15)},
        ]
        result = generer_recommandations(
            rows, thresholds=self.thresholds,
            comparison_mode="previous_year",
        )
        rec = next(r for r in result if r["rule_id"] == "REC_CA_GLOBAL_BAISSE")
        self.assertEqual(rec["period"], "2026 vs 2025")
        self.assertEqual(rec["reference_value"], 5000.0)

    def test_missing_same_month_reference_is_insufficient(self):
        rows = [
            {**sale(4), "date": date(2025, 4, 15)},
            {**sale(5), "date": date(2026, 5, 15)},
        ]
        result = generer_recommandations(
            rows, thresholds=self.thresholds,
            comparison_mode="same_month_previous_year",
        )
        self.assertEqual(result[0]["rule_id"], "REC_DONNEES_INSUFFISANTES")

    def test_margin_rules_and_revenue_up_margin_down(self):
        rows = [
            sale(1, "A", quantity=10, price=100, cost=50),
            sale(2, "A", quantity=20, price=100, cost=95),
        ]
        ids = self.ids(rows)
        self.assertIn("REC_MARGE_FAIBLE", ids)
        self.assertIn("REC_PRODUIT_CA_ELEVE_MARGE_FAIBLE", ids)
        self.assertIn("REC_CA_HAUSSE_MARGE_BAISSE", ids)

    def test_negative_margin(self):
        ids = self.ids([sale(1), sale(2, cost=120)])
        self.assertIn("REC_MARGE_NEGATIVE", ids)

    def test_concentrations(self):
        rows = [
            sale(1, "A", "C1", "Nord", 10), sale(1, "B", "C2", "Sud", 10),
            sale(2, "A", "C1", "Nord", 90), sale(2, "B", "C2", "Sud", 10),
        ]
        ids = self.ids(rows)
        self.assertTrue({
            "REC_DEPENDANCE_PRODUIT", "REC_DEPENDANCE_CLIENT",
            "REC_CONCENTRATION_REGION",
        }.issubset(ids))

    def test_arima_retrospective_gap(self):
        prediction = {
            "methode": "arima", "fiabilite": "haute",
            "validation_retrospective": {"mois": "2026-02", "prevu": 1000, "realise": 700},
        }
        result = generer_recommandations([sale(1), sale(2)], prediction, self.thresholds)
        rec = next(r for r in result if r["rule_id"] == "REC_ECART_PREVISION_ARIMA")
        self.assertEqual(rec["variation_percent"], -30.0)
        self.assertIn("700,00 MAD", rec["message"])
        self.assertEqual(rec["rule_id"], "REC_ECART_PREVISION_ARIMA")

    def test_no_trigger_at_stable_values(self):
        ids = self.ids(
            [sale(1, quantity=100), sale(2, quantity=95)],
            thresholds={
                "product_dependency_pct": 101, "client_dependency_pct": 101,
                "region_concentration_pct": 101, "margin_rate_low_pct": -100,
            },
        )
        self.assertEqual(ids, set())

    def test_nulls_zero_divisions_and_month_without_sales(self):
        rows = [
            {"date": date(2026, 1, 1), "produit": None, "client": None,
             "region": None, "quantite": 0, "prix_unitaire": 0, "cout_unitaire": 0},
            sale(2, quantity=0, price=0, cost=0),
        ]
        result = generer_recommandations(rows, thresholds=self.thresholds)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0]["rule_id"], "REC_DONNEES_INSUFFISANTES")

    def test_insufficient_history(self):
        result = generer_recommandations([sale(1)], thresholds={"min_rows": 1})
        self.assertEqual(result[0]["rule_id"], "REC_DONNEES_INSUFFISANTES")
        self.assertLess(result[0]["confidence"], 1)

    def test_score_and_priority_boundaries(self):
        self.assertEqual(calculer_score(1, 1, 1, 1, 1), 100)
        self.assertEqual(determiner_priorite(80), "critique")
        self.assertEqual(determiner_priorite(60), "élevée")
        self.assertEqual(determiner_priorite(40), "moyenne")
        self.assertEqual(determiner_priorite(39), "faible")

    def test_sorted_by_priority_then_score(self):
        result = generer_recommandations(
            [sale(1, quantity=100), sale(2, quantity=20)],
            thresholds=self.thresholds | {"max_recommendations": 50},
        )
        ranks = {"critique": 4, "élevée": 3, "moyenne": 2, "faible": 1}
        ordering = [(ranks[r["priority"]], r["score"]) for r in result]
        self.assertEqual(ordering, sorted(ordering, reverse=True))

    def test_deduplication_and_contradiction_resolution(self):
        base = dict(
            id="1", title="T", message="M", justification="M",
            recommended_action="A", priority="moyenne", score=50, confidence=.8,
            entity_type="produit", entity_name="A", metric_name="chiffre_affaires",
            current_value=10, reference_value=20, variation_percent=-50,
            period="02/2026", triggered_at="now", evidence={}, status="nouvelle",
        )
        decline = Recommendation(rule_id="REC_PRODUIT_BAISSE", **base)
        growth = Recommendation(rule_id="REC_PRODUIT_PROGRESSION", **(base | {"id": "2", "score": 40}))
        self.assertEqual(resoudre_contradictions([decline, growth]), [decline])
        self.assertEqual(supprimer_doublons([decline, decline]), [decline])


@override_settings(RECOMMENDATION_THRESHOLDS={"decline_pct": 5, "max_recommendations": 50})
class RecommendationConfigurationTests(SimpleTestCase):
    def test_settings_override_is_used(self):
        ids = {r["rule_id"] for r in generer_recommandations(
            [sale(1, quantity=100), sale(2, quantity=94)],
            thresholds={"min_rows": 1, "product_dependency_pct": 101,
                        "client_dependency_pct": 101, "region_concentration_pct": 101},
        )}
        self.assertIn("REC_CA_GLOBAL_BAISSE", ids)


class RecommendationChatServiceTests(SimpleTestCase):
    recommendation = {
        "rule_id": "REC_CA_GLOBAL_BAISSE", "justification": "Le CA baisse de 20 %.",
        "period": "02/2026 vs 01/2026", "score": 72, "priority": "élevée",
        "recommended_action": "Analyser les pertes.", "current_value": 800,
        "reference_value": 1000, "variation_percent": -20,
        "confidence": .9, "metric_name": "chiffre_affaires",
        "evidence": {"score_components": {
            "severity": .7, "financial_impact": .8, "duration": .5,
            "data_reliability": 1, "confidence": .9,
        }},
    }

    def test_answer_is_grounded_for_common_intents(self):
        self.assertIn("REC_CA_GLOBAL_BAISSE", answer_recommendation_question(self.recommendation, "Pourquoi ?"))
        self.assertIn("72/100", answer_recommendation_question(self.recommendation, "Quel score ?"))
        self.assertIn("Analyser les pertes", answer_recommendation_question(self.recommendation, "Que faire ?"))
        self.assertIn("-20.00 %", answer_recommendation_question(self.recommendation, "Quels chiffres ?"))

    def test_unknown_question_refuses_to_invent(self):
        answer = answer_recommendation_question(self.recommendation, "Qui sera mon meilleur client demain ?")
        self.assertIn("ne peux pas conclure", answer)

    def test_main_problems_question_uses_compact_context(self):
        context = build_sales_context(
            [sale(1), sale(2)], "Quels sont les principaux problèmes ?", [],
        )
        self.assertEqual(context["monthly_global"], {})
        self.assertEqual(context["annual_global"], {})
        self.assertEqual(context["top_clients"], [])

    def test_same_month_answer_refuses_mismatched_months(self):
        context = build_sales_context(
            [sale(5), sale(6)], "Compare le dernier mois au même mois des années précédentes", [],
        )
        answer = answer_common_sales_question(
            "Compare le dernier mois au même mois des années précédentes", context,
        )
        self.assertIn("Comparaison impossible", answer)
        self.assertNotIn("2026-05 :", answer)

    def test_main_problems_answer_uses_active_recommendations(self):
        context = {
            "active_recommendations": [
                {"message": "Concentration produit de 88,1 %.", "action": "Diversifier.", "score": 90},
            ],
        }
        answer = answer_common_sales_question(
            "Quels sont les principaux problèmes ?", context,
        )
        self.assertIn("Concentration produit de 88,1 %.", answer)
        self.assertIn("Action : Diversifier.", answer)

    def test_forecast_decline_question_is_answered_locally(self):
        context = {
            "monthly_global": {
                "2026-04": {"ca": 300000},
                "2026-05": {"ca": 250000},
                "2026-06": {"ca": 200000},
            },
            "forecast": {
                "method": "mmp",
                "last_actual_period": "06/2026",
                "last_actual_ca": 200000,
                "variation_pct": -10,
                "rows": [{
                    "mois": "07/2026", "valeur": 180000,
                    "basse": 160000, "haute": 210000,
                }],
            },
        }
        answer = answer_common_sales_question(
            "Analyse-moi pourquoi le caprevu va diminuer dans 07/2026", context,
        )
        self.assertIn("CA prévu pour 07/2026", answer)
        self.assertIn("moyenne mobile pondérée", answer)
        self.assertNotIn("capital de la révision", answer)

    def test_client_context_materializes_requested_calendar_window(self):
        context = build_sales_context(
            [
                sale(5, client="InfoPlus"),
                sale(6, client="InfoPlus"),
                sale(6, client="Autre"),
            ],
            "Analyse le client InfoPlus sur les 6 derniers mois.",
            [],
        )
        window = context["clients"]["InfoPlus"]["fenetre_demandee"]
        self.assertEqual([item["periode"] for item in window], [
            "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
        ])
        self.assertFalse(window[0]["donnees_disponibles"])
        self.assertTrue(window[-1]["donnees_disponibles"])
        self.assertEqual(context["annual_global"], {})
        self.assertEqual(context["top_clients"], [])

    def test_new_analysis_does_not_reuse_unrelated_history(self):
        history = [
            {"role": "user", "content": "Pourquoi le CA prévu baisse ?"},
            {"role": "assistant", "content": "Prévision globale de juillet."},
        ]
        self.assertEqual(
            _safe_history(history, "Analyse le client InfoPlus sur les 6 derniers mois."),
            [],
        )
        self.assertEqual(len(_safe_history(history, "Et ce point ?")), 2)

    def test_structured_answer_is_rendered_without_table(self):
        answer, warnings = _render_structured_answer(json.dumps({
            "conclusion": "Deux mois disposent de données.",
            "points": [{
                "label": "Mai", "preuve": "199 336,19 MAD",
                "periode": "05/2026", "type_source": "realise",
            }],
            "limite": "Aucune donnée de janvier à avril.",
            "action": "Compléter l’historique.",
        }))
        self.assertIn("- **Mai** : 199 336,19 MAD", answer)
        self.assertIn("**Limite**", answer)
        self.assertNotIn("|", answer)
        self.assertEqual(warnings, [])

    def test_intent_detection_covers_business_scopes(self):
        self.assertEqual(
            detect_question_intent("Analyse le client InfoPlus"),
            "client_analysis",
        )
        self.assertEqual(
            detect_question_intent("Pourquoi le CA prévu baisse ?"),
            "forecast_analysis",
        )
        self.assertEqual(
            detect_question_intent("Compare juin 2026 à juin 2025"),
            "temporal_comparison",
        )

    def test_validation_removes_unsupported_period_and_client_forecast(self):
        data = {
            "conclusion": "Analyse",
            "points": [
                {
                    "label": "Mai", "preuve": "CA observé",
                    "periode": "05/2026", "type_source": "realise",
                },
                {
                    "label": "Juillet", "preuve": "Prévision",
                    "periode": "07/2026", "type_source": "prevision",
                },
            ],
            "limite": "", "action": "",
        }
        context = {
            "request": {"intent": "client_analysis"},
            "clients": {"InfoPlus": {"fenetre_demandee": [{"periode": "2026-05"}]}},
        }
        cleaned, warnings = validate_structured_answer(data, context)
        self.assertEqual(len(cleaned["points"]), 1)
        self.assertIn("periode_non_fondee:2026-07", warnings)


@override_settings(
    RECOMMENDATION_THRESHOLDS={"min_rows": 5, "max_recommendations": 50},
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    ASSISTANT_USE_LLM_INTENT=False,
)
class RecommendationChatEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("decision-maker", password="secret")
        self.client.force_login(self.user)
        for index in range(3):
            Vente.objects.create(
                date=date(2026, 1, 10 + index), produit="A", client="C1", region="Nord",
                quantite=10, prix_unitaire=Decimal("100"), cout_unitaire=Decimal("70"),
            )
            Vente.objects.create(
                date=date(2026, 2, 10 + index), produit="A", client="C1", region="Nord",
                quantite=5, prix_unitaire=Decimal("100"), cout_unitaire=Decimal("70"),
            )

    @patch("sales.views.ask_sales_assistant", return_value=(
        "Analyse locale fondée.", "local_123", "ollama",
        {"duration_ms": 120, "prompt_tokens": 80, "output_tokens": 20},
    ))
    def test_chat_builds_context_and_calls_openai(self, mocked_assistant):
        response = self.client.post(
            reverse("recommendation_chat"),
            data=json.dumps({
                "question": "Quels sont les problèmes du client C1 ?",
                "history": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["grounded"])
        self.assertEqual(response.json()["response_id"], "local_123")
        self.assertEqual(response.json()["provider"], "ollama")
        interaction = ChatInteraction.objects.get(pk=response.json()["interaction_id"])
        self.assertEqual(interaction.intent, "detect_anomalies")
        self.assertEqual(interaction.duration_ms, 120)
        self.assertEqual(interaction.prompt_tokens, 80)
        context = mocked_assistant.call_args.kwargs["context"]
        self.assertIn("C1", context["clients"])
        self.assertEqual(context["clients"]["C1"]["mensuel"]["2026-01"]["ca"], 3000)

    def test_chat_rejects_invalid_history_and_oversized_question(self):
        invalid_history = self.client.post(
            reverse("recommendation_chat"),
            data=json.dumps({
                "question": "Pourquoi ?", "history": "not-a-list",
            }),
            content_type="application/json",
        )
        self.assertEqual(invalid_history.status_code, 400)
        oversized = self.client.post(
            reverse("recommendation_chat"),
            data=json.dumps({"question": "x" * 501}),
            content_type="application/json",
        )
        self.assertEqual(oversized.status_code, 400)

    def test_explicit_year_overrides_dashboard_date_filter(self):
        Vente.objects.create(
            date=date(2025, 4, 12), produit="A", client="C1", region="Nord",
            quantite=8, prix_unitaire=Decimal("100"), cout_unitaire=Decimal("70"),
        )
        response = self.client.post(
            reverse("recommendation_chat") + "?date_debut=2026-01-01&date_fin=2026-12-31",
            data=json.dumps({"question": "Donne-moi le CA de 2025", "history": []}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("2025", response.json()["answer"])
        self.assertIn("800,00 MAD", response.json()["answer"])
        self.assertNotIn("2026", response.json()["answer"])

    def test_positive_feedback_creates_validated_example(self):
        interaction = ChatInteraction.objects.create(
            user=self.user,
            question="Pourquoi le caprevu baisse ?",
            answer="Le CA prévu baisse selon la dynamique récente.",
            provider="local",
        )
        response = self.client.post(
            reverse("recommendation_chat_feedback"),
            data=json.dumps({"interaction_id": interaction.pk, "helpful": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        interaction.refresh_from_db()
        self.assertTrue(interaction.helpful)
        example = LearnedChatExample.objects.get(interaction=interaction)
        self.assertTrue(example.active)
        self.assertEqual(example.normalized_question, "pourquoi le caprevu baisse")

    def test_user_cannot_rate_another_users_interaction(self):
        other_user = get_user_model().objects.create_user("other", password="secret")
        interaction = ChatInteraction.objects.create(
            user=other_user, question="Question privée", answer="Réponse", provider="local",
        )
        response = self.client.post(
            reverse("recommendation_chat_feedback"),
            data=json.dumps({"interaction_id": interaction.pk, "helpful": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_context_compares_same_month_across_years(self):
        Vente.objects.create(
            date=date(2025, 2, 12), produit="A", client="C1", region="Nord",
            quantite=8, prix_unitaire=Decimal("100"), cout_unitaire=Decimal("70"),
        )
        context = build_sales_context(
            Vente.objects.all(), "Compare février 2026 à février 2025", [],
        )
        self.assertEqual(set(context["same_month_across_years"]), {"2025-02", "2026-02"})
