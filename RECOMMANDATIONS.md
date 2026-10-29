# Moteur de recommandations commerciales — conception validable

## 1. Architecture fonctionnelle

Le flux est strictement unidirectionnel :

`QuerySet Vente filtré → indicateurs mensuels → règles → score → arbitrage/déduplication → tri → dictionnaires → dashboard`.

`sales/recommandations.py` contient quatre couches séparées : `calculer_indicateurs`
(calcul), `evaluer_*` (règles), `_recommendation` (construction) et
`generer_recommandations` (orchestration/présentation). Le moteur reçoit le même
QuerySet que le dashboard : les filtres de date, clients et produits sont donc
appliqués avant l'analyse. Il est sans état, ne modifie pas la base et n'emploie
ni LLM ni modèle appris.

## 2. Spécification complète des règles métier

Trois référentiels sont sélectionnables dans le dashboard : dernier mois contre
mois précédent, même mois contre le même mois de l’année précédente
(`05/2026 vs 05/2025`), et année en cours à date contre année précédente à la
même date (`2026 vs 2025`). Cette dernière règle évite de comparer une année
partielle à une année complète.
Une entité n'est comparée que si son CA de référence atteint 100 MAD, afin d'éviter
les pourcentages spectaculaires sur un montant négligeable. Les seuils sont des
valeurs initiales configurables dans `settings.RECOMMENDATION_THRESHOLDS`.

| ID / nom | Objectif et indicateurs | Condition exacte / seuil initial | Priorité et texte/action | Incompatibilités, limites, confiance | Exemple |
|---|---|---|---|---|---|
| `REC_CA_GLOBAL_BAISSE` — baisse globale | Détecter une contraction; CA courant/référence, perte | variation CA ≤ −10 % | Score calculé; analyser les pertes par dimension | Pas de comparaison si référence nulle; incompatible avec hausse globale (non émise); confiance volume/historique/complétude | 800 k vs 1 M MAD = −20 %, perte 200 k |
| `REC_PRODUIT_BAISSE` — forte baisse produit | Identifier un produit en recul; CA et quantité produit | CA produit ≤ −20 %, référence ≥100 MAD | Vérifier demande, stock, prix et campagne ciblée | Une progression opposée de même période est arbitrée; produit absent vaut CA 0 | X: 108 k vs 132,5 k = −18,5 % ne déclenche pas; à −20 % oui |
| `REC_REGION_SOUS_PERFORMANTE` | Repérer une zone en décrochage; CA région | variation ≤ −25 % | Comparer pipeline, couverture et disponibilité | Région absente regroupée « Non renseignée », mais baisse fiable seulement si complétude suffisante | Sud: 300 k vs 420 k = −28,6 % |
| `REC_CLIENT_IMPORTANT_BAISSE` | Prévenir un risque de rétention; CA et part du client | part de référence ≥15 % et baisse ≤−10 % | Contacter, qualifier, plan de rétention | Client nouveau sans référence ignoré | Atlas: part 22 %, 180 k vs 240 k = −25 % |
| `REC_MARGE_FAIBLE` | Éviter une activité peu rentable; marge/CA produit | 0 % < taux marge ≤10 % | Revoir coûts, remises et prix | CA nul ignoré; compatible avec progression | Marge 8 k / CA 100 k = 8 % |
| `REC_MARGE_NEGATIVE` | Stopper la destruction de valeur | taux marge ≤0 % | Suspendre promotions non rentables et auditer | Coûts manquants peuvent gonfler la marge : confiance dépend de complétude | Marge −5 k / CA 80 k = −6,25 % |
| `REC_PRODUIT_CA_ELEVE_MARGE_FAIBLE` | Prioriser les marges à fort impact | taux marge ≤10 % et part CA ≥20 % | Analyse prix-coût-remise prioritaire | Compatible avec `REC_MARGE_FAIBLE`; ce sont deux niveaux d'action | X = 35 % du CA, marge 6 % |
| `REC_DEPENDANCE_PRODUIT` | Réduire le risque portefeuille | part CA produit ≥40 % | Plan de diversification | Total CA nul : non calculable | X = 460 k / 1 M = 46 % |
| `REC_DEPENDANCE_CLIENT` | Réduire le risque de contrepartie | part CA client ≥35 % | Diversification/prospection | Même limite sur total nul | Atlas = 380 k / 1 M = 38 % |
| `REC_CONCENTRATION_REGION` | Réduire le risque géographique | part CA région ≥50 % | Diversifier régions/canaux | « Non renseignée » signale aussi un enjeu qualité | Nord = 560 k / 1 M = 56 % |
| `REC_*_PROGRESSION` — produit/client/région | Capitaliser sur une dynamique démontrée | hausse CA ≥20 %, référence ≥100 MAD | Identifier les facteurs reproductibles et la capacité | Incompatible avec baisse de la même entité/métrique/période; compatible avec marge faible | Produit X: 150 k vs 120 k = +25 % |
| `REC_ECART_PREVISION_ARIMA` | Contrôler l'usage de la prévision | \|réalisé−prévu\| / \|prévu\| ≥20 % | Rechercher événement non modélisé, réévaluer | Utilise uniquement la validation rétrospective; prévu nul ignoré; confiance pénalisée si prévision faible | Réalisé 700 k, prévu 1 M = −30 % |
| `REC_QUANTITE_ANORMALE` | Détecter rupture, commande exceptionnelle ou erreur | variation absolue quantité produit ≥30 % | Contrôler données/stock/promotion | Référence quantité nulle ignorée; signal non causal | 1 400 vs 1 000 unités = +40 % |
| `REC_CA_HAUSSE_MARGE_BAISSE` | Détecter une croissance non rentable | variation CA >0 et variation marge ≤−10 % | Isoler produits/remises responsables | Marge de référence nulle : non calculable | CA +12 %, marge −18 % |
| `REC_DONNEES_INSUFFISANTES` | Empêcher une conclusion fragile | lignes <5, périodes <2 ou complétude <70 % | Importer/compléter les données | Exclusive : le moteur ne produit aucune autre recommandation | 3 lignes sur un seul mois |

La priorité n'est pas fixée arbitrairement par règle : elle découle du score et
donc de la matérialité observée. Les seuils de déclenchement correspondent à un
écart mensuel suffisamment supérieur à une fluctuation mineure; les seuils de
concentration expriment le niveau auquel la perte d'une seule entité affecterait
substantiellement le CA. Ils doivent être recalibrés après trois à six mois de
retour métier, sans modifier le code.

## 3. Choix concernant scikit-learn

| Approche | Atouts | Limites | Décision V1 |
|---|---|---|---|
| Règles déterministes | Totalement auditables, stables, efficaces avec peu de données | Seuils à calibrer | Oui, pour le déclenchement |
| Score pondéré sans apprentissage | Classe les signaux, détaille chaque contribution | Poids définis par gouvernance | Oui, pour la priorité |
| Régression logistique | Probabilité calibrable si une cible historique existe | Nécessite des décisions labellisées et suivi de dérive | Non en V1 |
| Arbre de décision | Règles visualisables | Instable sur petit échantillon, surapprentissage | Non en V1 |

Scikit-learn n'apporte pas de valeur nette tant qu'il n'existe pas un historique
fiable du type « recommandation suivie → résultat obtenu ». Une V2 pourrait
apprendre la probabilité d'impact, mais ne devrait jamais remplacer la preuve
métier qui déclenche la recommandation.

## 4. Méthode de scoring

Toutes les composantes sont bornées à `[0,1]` :

`score = 100 × (0,35 gravité + 0,25 impact financier + 0,15 durée + 0,15 fiabilité données + 0,10 confiance analyse)`.

- Gravité : écart observé rapporté à un écart de saturation propre à la règle.
- Impact : perte/gain ou part de CA rapportée à une matérialité du périmètre.
- Durée : 0,5 pour un signal sur une comparaison; pourra atteindre 1 après
  ajout d'un compteur de répétition persistant.
- Fiabilité : taux de lignes avec date, produit, client et région.
- Confiance : 45 % complétude, 30 % volume (saturé à 30 lignes), 25 % profondeur
  (saturée à six mois), puis facteur 1/0,85/0,65 pour ARIMA haute/moyenne/basse.

Priorités : `0–39 faible`, `40–59 moyenne`, `60–79 élevée`, `80–100 critique`.
Le détail des cinq composantes est conservé dans `evidence.score_components`.

## 5. Format standard et exemples de sortie

`Recommendation` impose les champs demandés et `to_dict()` produit du JSON
sérialisable. Cinq sorties représentatives (UUID et horodatages abrégés) :

```json
[
  {"id":"…","rule_id":"REC_CA_GLOBAL_BAISSE","title":"Baisse du chiffre d’affaires global","message":"Le chiffre d’affaires global a diminué de 20,0 %, soit 200 000,00 MAD de moins que le mois précédent.","justification":"Même constat chiffré","recommended_action":"Analyser les pertes par produit, client et région, puis sécuriser les opportunités à court terme.","priority":"élevée","score":72,"confidence":0.91,"entity_type":"global","entity_name":"Entreprise","metric_name":"chiffre_affaires","current_value":800000,"reference_value":1000000,"variation_percent":-20,"period":"06/2026 vs 05/2026","triggered_at":"…","evidence":{"loss_mad":200000,"threshold_pct":10},"status":"nouvelle"},
  {"id":"…","rule_id":"REC_PRODUIT_BAISSE","title":"Forte baisse du produit X","message":"Le chiffre d’affaires du produit X a diminué de 25,0 %, soit une perte estimée de 25 000,00 MAD.","justification":"Même constat chiffré","recommended_action":"Vérifier la demande, le stock et le positionnement prix ; envisager une campagne ciblée si la marge le permet.","priority":"moyenne","score":58,"confidence":0.88,"entity_type":"produit","entity_name":"X","metric_name":"chiffre_affaires","current_value":75000,"reference_value":100000,"variation_percent":-25,"period":"06/2026 vs 05/2026","triggered_at":"…","evidence":{"loss_mad":25000},"status":"nouvelle"},
  {"id":"…","rule_id":"REC_MARGE_NEGATIVE","title":"Marge négative — Y","message":"La marge du produit Y est de -5 000,00 MAD, soit -6,3 % d’un CA de 80 000,00 MAD.","justification":"Même constat chiffré","recommended_action":"Revoir coûts, remises et prix ; suspendre les promotions non rentables jusqu'à validation.","priority":"élevée","score":65,"confidence":0.9,"entity_type":"produit","entity_name":"Y","metric_name":"taux_marge","current_value":-6.25,"reference_value":10,"variation_percent":-16.25,"period":"06/2026","triggered_at":"…","evidence":{"margin_mad":-5000},"status":"nouvelle"},
  {"id":"…","rule_id":"REC_DEPENDANCE_CLIENT","title":"Concentration du CA — Atlas","message":"38,0 % du chiffre d’affaires mensuel dépend du client Atlas (380 000,00 MAD sur 1 000 000,00 MAD).","justification":"Même constat chiffré","recommended_action":"Établir un plan de diversification et suivre cette concentration chaque mois.","priority":"moyenne","score":55,"confidence":0.92,"entity_type":"client","entity_name":"Atlas","metric_name":"part_chiffre_affaires","current_value":38,"reference_value":35,"variation_percent":3,"period":"06/2026","triggered_at":"…","evidence":{"entity_ca_mad":380000},"status":"nouvelle"},
  {"id":"…","rule_id":"REC_ECART_PREVISION_ARIMA","title":"Écart important entre réalisé et prévision","message":"Le CA réalisé (700 000,00 MAD) s’écarte de 30,0 % de la prévision rétrospective (1 000 000,00 MAD).","justification":"Même constat chiffré","recommended_action":"Rechercher un événement non modélisé et réévaluer la prévision avant de l'utiliser pour engager des ressources.","priority":"élevée","score":70,"confidence":0.85,"entity_type":"global","entity_name":"Entreprise","metric_name":"ecart_prevision","current_value":700000,"reference_value":1000000,"variation_percent":-30,"period":"06/2026","triggered_at":"…","evidence":{"gap_mad":-300000,"forecast_method":"arima"},"status":"nouvelle"}
]
```

## 6. Code Python complet

Le code exécutable complet est dans `sales/recommandations.py`. Les seuils
centralisés y ont des valeurs de repli et sont surchargés dans
`DecisionIQ/settings.py`.

## 7. Intégration Django

`construire_contexte_dashboard` applique déjà `date_debut`, `date_fin`,
`clients_selectionnes` et `produits_selectionnes` au QuerySet. Ce même
`ventes_filtrees` est transmis à :

```python
prediction_ca = predire_ca_pour_ventes(ventes_filtrees, nb_mois=horizon_prevision)
recommandations = generer_recommandations(ventes_filtrees, prediction_ca)
context["recommandations"] = recommandations
```

Le module annote chaque `Vente` avec `quantite * prix_unitaire` et
`quantite * cout_unitaire` via ORM, sans modifier le modèle. La vue reste
`dashboard`; aucune URL ni migration n'est nécessaire.

## 8. Interface HTML/CSS

La section complète se trouve dans `sales/templates/sales/dashboard.html`.
Elle montre titre, priorité, score, entité, constat, action, règle, confiance,
période et détails. Les bordures combinent couleur et libellé (la couleur n'est
jamais le seul signal), les filtres sont accessibles, la grille passe à une
colonne sur mobile, un état vide et un état « données insuffisantes » sont
produits par le moteur. `max_recommendations=8` limite la charge cognitive.

## 9. Tests automatisés

`sales/test_recommandations.py` couvre déclenchements, non-déclenchement,
valeurs nulles, divisions par zéro, période sans CA, historique insuffisant,
contradictions, doublons, classement, `rule_id`, cohérence message/preuves,
écart ARIMA et surcharge de configuration.

## 10. Validation manuelle

| Données de test | Règle attendue | Résultat / priorité indicative | Vérifications |
|---|---|---|---|
| CA mai 1 M; juin 800 k | `REC_CA_GLOBAL_BAISSE` | −20 %, priorité selon score | Perte 200 k, périodes correctes |
| X: 100 k puis 75 k | `REC_PRODUIT_BAISSE` | −25 % | Nom X, perte 25 k, action ciblée |
| Y: CA 80 k, coût 85 k | `REC_MARGE_NEGATIVE` | taux −6,25 % | Marge −5 k, pas de division zéro |
| Atlas = 38 % du CA | `REC_DEPENDANCE_CLIENT` | part 38 % | Référence seuil 35 % |
| Nord = 56 % du CA | `REC_CONCENTRATION_REGION` | part 56 % | Total et CA région concordants |
| CA +12 %, marge −18 % | `REC_CA_HAUSSE_MARGE_BAISSE` | croissance non rentable | Deux variations dans la preuve |
| Prévu 1 M, réalisé 700 k | `REC_ECART_PREVISION_ARIMA` | −30 % | Validation rétrospective, pas futur |
| 3 lignes sur un mois | `REC_DONNEES_INSUFFISANTES` seule | faible | Motifs explicites |

Procédure : charger chaque jeu isolément, ouvrir le dashboard sans filtre puis
avec filtres, comparer les valeurs à une agrégation SQL/Excel indépendante,
ouvrir les détails, vérifier l'ordre, les filtres UI et la vue mobile.

## 11. Critères d'acceptation

La conception est validée lorsque : tous les tests passent; 100 % des cartes ont
un `rule_id` et des preuves reproductibles; aucune recommandation autre que
« données insuffisantes » n'est émise sans deux périodes fiables; les montants
rejoués à partir de `Vente` concordent au centime; l'écart ARIMA utilise une
observation rétrospective; les seuils sont modifiables sans changer les règles;
aucun doublon ou signal opposé ne survit; l'ordre priorité/score est stable; le
dashboard est utilisable clavier/mobile et ne présente jamais une causalité non
démontrée.

## 12. Assistant commercial LLM

Le widget flottant utilise par défaut Ollama et le modèle local gratuit
`qwen3:1.7b`. OpenAI reste un fournisseur optionnel avec
`LLM_PROVIDER=openai`. Le modèle n'accède pas à la base : le serveur
sélectionne le client mentionné, calcule ses agrégats mensuels, les comparaisons
du même mois entre années et les recommandations actives, puis envoie ce dossier
analytique borné.

Le prompt impose de distinguer faits et hypothèses, de signaler toute donnée
absente et de ne jamais inventer de causalité. Les filtres actifs, l'authentification,
CSRF, une limite de 30 questions par minute et un historique court s'appliquent.
