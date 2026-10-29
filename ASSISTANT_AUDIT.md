# Audit et architecture de l'assistant SalesDecision AI

## Diagnostic de l'existant

### Éléments corrects conservés

- `Vente`, `SeuilAlerte` et le moteur `recommandations.py` calculent les faits
  côté Django.
- `build_sales_context()` agrège les ventes et n'envoie pas les lignes brutes.
- Ollama utilisait déjà `/api/chat`, `qwen3:1.7b`, `think:false`, un schéma de
  réponse JSON, un timeout, `keep_alive` et des métriques.
- L'endpoint était authentifié, protégé par CSRF, limité à 500 caractères et
  soumis à une limite de débit.
- Les réponses structurées étaient contrôlées contre les périodes disponibles.
- Les recommandations contenaient déjà preuve, priorité, action et confiance.

### Défauts et risques corrigés

- Six intentions seulement, détectées par quelques mots-clés : confusion entre
  KPI, classements, comparaisons et analyses d'entités.
- Aucun schéma validé pour le plan d'analyse avant les calculs.
- Pas de catalogue fermé validant les produits, clients et régions du JSON.
- Historique uniquement dans le navigateur, perdu au rechargement et trop
  dépendant de formulations comme « et » ou « cela ».
- Absence de séparation explicite plan / fonction métier / formulation.
- Pas de réparation unique de la réponse JSON finale.
- Aucun endpoint pour effacer le contexte.
- Métriques Ollama présentes, mais pas de durée Django ni de durée totale.
- Absence d'index composites pour les filtres analytiques fréquents.
- Réponse HTTP non progressive.

### Cause mesurée des mauvaises intentions

Un premier benchmark Qwen3 1.7B avec un prompt trop abstrait produisait 100 % de
JSON valides, mais seulement 15,91 % d'intentions correctes et choisissait trop
souvent `clarification` (9,12 s en moyenne). Le pipeline final utilise donc une
classification déterministe par catégories pour les demandes non ambiguës et
réserve Qwen aux demandes ambiguës. Ce compromis est adapté au CPU cible.

## Architecture finale

1. `assistant_intents.py`
   - schéma Pydantic fermé ;
   - 17 intentions autorisées ;
   - catalogue dynamique des entités accessibles ;
   - classification rapide des cas nets ;
   - Qwen3 pour les ambiguïtés, une réparation maximum ;
   - fallback déterministe contrôlé.
2. `assistant_analytics.py`
   - filtre le QuerySet autorisé ;
   - calcule KPI, comparaisons, classements, analyses, anomalies, prévisions et
     recommandations ;
   - gère explicitement la division par zéro et l'absence de données ;
   - retourne les valeurs utilisées.
3. `openai_sales_assistant.py`
   - reçoit l'intention validée et `business_result` ;
   - formule sans recalculer ;
   - valide et répare une fois le JSON de réponse.
4. `assistant_memory.py`
   - mémoire compacte par utilisateur et session ;
   - entités, filtres, dernière intention et résumé court ;
   - expiration de 30 minutes et effacement manuel.
5. Interface
   - indicateur de chargement ;
   - flux NDJSON avec statut immédiat et segments de réponse ;
   - bouton « Effacer ».

## Sécurité

- Aucune exécution de SQL LLM, `eval()` ou `exec()`.
- QuerySet construit côté Django et limité aux filtres de la vue.
- Entités du JSON comparées au catalogue de la base.
- Authentification, CSRF, limite de débit et longueur maximale conservées.
- Prompt injection classée `unsupported`.
- Logs limités aux identifiants techniques, intentions et durées.

## Tests et benchmark

- Jeu : `sales/assistant_question_set.json` (44 formulations).
- Exactitude du pipeline hybride : 100 % sur 44 questions.
- Routage Qwen : 4,55 % des questions ambiguës.
- Succès JSON Qwen sur les questions routées : 100 %.
- Temps moyen du pipeline d'intention : 0,155 s ; maximum : 3,455 s.
- Qwen3 1.7B : 1 296,3 Mo sur disque, premier token médian 1,047 s,
  durée totale médiane 3,147 s, 13,93 tokens/s.
- `qwen3:1.7b-q8_0` et `qwen3:4b` non installés : aucune conclusion de qualité
  ou recommandation de migration n'est faite sans mesure réelle.

## Commandes

```powershell
ollama pull qwen3:1.7b
ollama run qwen3:1.7b
python manage.py migrate
python manage.py test
python scripts\benchmark_ollama_assistant.py
python scripts\benchmark_assistant_intents.py
python manage.py runserver
```
