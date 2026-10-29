"""Convertit la banque PDF en catalogue versionné de tests et d'entraînement.

Usage:
    python scripts/build_assistant_training_catalog.py source.pdf
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DecisionIQ.settings')

import django
from pypdf import PdfReader

django.setup()

from sales.services.assistant_intents import deterministic_intent


THEMES = (
    (1, 20, 'chiffre_affaires'), (21, 40, 'marge_rentabilite'),
    (41, 55, 'volume_panier'), (56, 75, 'clients'), (76, 90, 'produits'),
    (91, 105, 'regions'), (106, 120, 'previsions'), (121, 135, 'alertes'),
    (136, 150, 'recommandations'), (151, 160, 'comparaisons_temporelles'),
    (161, 170, 'import_donnees'), (171, 180, 'dashboard_navigation'),
    (181, 195, 'analyse_ouverte'), (196, 205, 'multi_entites'),
    (206, 215, 'objectifs'), (216, 225, 'diagnostic'),
    (226, 235, 'prise_en_main'), (236, 250, 'requetes_courtes'),
    (251, 260, 'simulations'), (261, 270, 'suivi_conversationnel'),
    (271, 280, 'reporting_direction'), (281, 290, 'gestion_erreurs'),
    (291, 300, 'preferences'),
)

SECTION_TITLES = {
    "Chiffre d'affaires (CA)", 'Marge et rentabilité',
    'Volume des ventes et panier moyen', 'Analyse clients', 'Analyse produits',
    'Analyse régionale', 'Prévisions (forecasting)', 'Alertes',
    'Recommandations commerciales', 'Comparaisons temporelles',
    'Import et gestion des données', 'Tableau de bord et navigation',
    'Questions analytiques ouvertes (assistant conversationnel)',
    'Questions comparatives multi-entités', 'Objectifs et suivi de performance',
    'Questions de diagnostic avancé', 'Questions simples / prise en main',
    'Requêtes chiffrées précises (format court)', 'Scénarios de simulation',
    "Questions de suivi et d'itération (contexte conversationnel)",
    'Questions transverses direction / reporting',
    'Cas limites et gestion des erreurs',
    'Personnalisation et préférences utilisateur',
}

CATALOG = {
    'products': ['Produit X', 'Produit A', 'Produit B'],
    'clients': ['Client X', 'Client Y', 'Client Z'],
    'regions': ['Nord', 'Sud', 'Région X', 'Région Y'],
}


def theme_for(number):
    return next(theme for start, end, theme in THEMES if start <= number <= end)


def answer_mode(number):
    if 122 <= number <= 135:
        return 'alert_management'
    if 161 <= number <= 180 or 226 <= number <= 235 or 281 <= number <= 290:
        return 'product_help'
    if 206 <= number <= 215:
        return 'requires_objective_data'
    if 251 <= number <= 260:
        return 'simulation'
    if 291 <= number <= 300:
        return 'user_preference'
    return 'calculate_from_database'


def extract_questions(pdf_path):
    text = '\n'.join(page.extract_text() or '' for page in PdfReader(pdf_path).pages)
    text = text.translate(str.maketrans({
        'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
    }))
    questions = {}
    current = None
    for raw in text.splitlines():
        line = ' '.join(raw.split())
        if line == "Notes d'utilisation pour l'entraînement":
            break
        match = re.match(r'^(\d{1,3})\.\s+(.+)', line)
        if match:
            number, content = int(match.group(1)), match.group(2).strip()
            if content in SECTION_TITLES or not 1 <= number <= 300:
                current = None
                continue
            if number not in questions:
                questions[number] = content
                current = number
            else:
                current = None
        elif current and line:
            questions[current] += f' {line}'
    missing = sorted(set(range(1, 301)) - set(questions))
    if missing:
        raise ValueError(f'Questions manquantes dans le PDF : {missing}')
    return questions


def main():
    if len(sys.argv) not in {2, 3}:
        raise SystemExit('Usage: build_assistant_training_catalog.py source.pdf [sortie.json]')
    source = Path(sys.argv[1]).resolve()
    destination = (
        Path(sys.argv[2]).resolve() if len(sys.argv) == 3
        else Path(__file__).parents[1] / 'sales' / 'assistant_training_catalog.json'
    )
    questions = extract_questions(source)
    records = []
    for number, question in sorted(questions.items()):
        plan = deterministic_intent(question, CATALOG)
        records.append({
            'id': number,
            'theme': theme_for(number),
            'question': question,
            'answer_mode': answer_mode(number),
            'current_intent': plan.intent.value,
            'review_status': 'pending_reference_answer',
        })
    destination.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    print(f'{len(records)} questions écrites dans {destination}')


if __name__ == '__main__':
    main()
