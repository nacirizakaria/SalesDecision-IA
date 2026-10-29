# Guide de soutenance — SalesDecision AI

> **Point à annoncer dès le départ :** le projet comporte **sept livrables fonctionnels**. Si l’énoncé parle de six, je préciserais que le septième est le **pack sécurité et exploitation**, transversal mais bien implémenté et documenté.

## 1. Pitch de 60 secondes

« SalesDecision AI est une application web d’aide à la décision commerciale. Elle permet d’importer des ventes CSV ou Excel, de les centraliser dans une base de données, de visualiser les indicateurs clés, de configurer des alertes métier, de générer des recommandations explicables et de produire des prévisions de chiffre d’affaires. Elle inclut aussi un assistant commercial encadré et un socle de sécurité pour une mise en production. L’objectif n’est pas de remplacer le décideur : il est de réduire le temps de lecture des données et de rendre chaque alerte traçable par une règle, une période et des chiffres. »

## 2. Vue d’ensemble technique

| Couche | Réalisation | Rôle |
|---|---|---|
| Interface | Templates Django, CSS et JavaScript/Chart.js | Import, tableaux de bord, graphiques, configuration et assistant |
| Back-end | Python / Django | Routes, droits, calculs, validation, export PDF |
| Données | MySQL via l’ORM Django | Ventes, seuils, historique des seuils, utilisateurs, audit et interactions assistant |
| Analyse | pandas, statsmodels | Lecture des fichiers, agrégations, prévisions ARIMA ou moyenne mobile |
| IA conversationnelle | Ollama local par défaut ; OpenAI possible | Répondre à partir d’un contexte commercial agrégé et borné |
| Sécurité | Django, Argon2, variables d’environnement, sauvegarde Fernet | Authentification, rôles, protection des secrets, sauvegardes chiffrées |

**Schéma oral à dessiner :**

`Fichier CSV/XLSX → validation pandas → modèle Vente/MySQL → KPI / alertes / recommandations / prévisions → dashboard, PDF et assistant`

### Entités de données essentielles

- `Vente` : date, client, produit, quantité, prix unitaire, coût unitaire, région. Le CA est `quantité × prix unitaire`; la marge est `CA − coût total`.
- `SeuilAlerte` : seuils, couleur, type de comparaison, référence et état actif.
- `HistoriqueConfigurationAlerte` : qui a modifié quel seuil et quand.
- `ChatInteraction` et `LearnedChatExample` : journal de questions/réponses et retours explicites de l’utilisateur.

## 3. Livrable 1 — Import contrôlé des ventes

### Besoin traité

Les données commerciales arrivent généralement sous forme de fichiers hétérogènes. Le premier livrable évite de faire des calculs manuels dans Excel et donne un point d’entrée contrôlé vers l’application.

### Comment je l’ai réalisé

1. J’ai créé la route `/import/`, protégée par la permission `import_sales`.
2. J’accepte les formats CSV et Excel, puis je lis le fichier avec `pandas`.
3. J’ai prévu une phase de normalisation : les noms de colonnes sont harmonisés et les colonnes nécessaires sont complétées lorsque cela est possible depuis des colonnes calculées.
4. Chaque ligne est convertie vers le modèle `Vente`, puis enregistrée dans la base via Django. Les calculs métiers ne dépendent donc pas du fichier une fois importé.
5. J’ai ajouté des garde-fous : taille maximale configurable (10 Mo par défaut), fichier vide, fichier avec en-têtes seuls, extension/fichier Excel invalide ou corrompu. Les erreurs sont présentées comme des messages métier, pas comme une trace technique.
6. Les ventes sont indexées par date et par combinaisons produit/client/région-date afin d’accélérer les filtres et les agrégations les plus fréquents.

### Ce que je peux montrer en démo

- Importer un fichier de ventes valide, puis ouvrir la liste et le dashboard.
- Montrer un fichier vide ou corrompu : l’application refuse proprement le fichier et ne crée pas de ventes.
- Expliquer que les données deviennent requêtables par date, client et produit.

### Formulation courte à dire

« J’ai séparé l’étape d’import de l’analyse : le fichier est d’abord validé et normalisé, ensuite seulement les ventes sont enregistrées. Cela évite que tout le reste de l’application dépende d’un Excel instable. »

### Questions probables

**Pourquoi utiliser pandas ?**  
Pandas est adapté à la lecture de CSV/Excel et aux opérations de nettoyage tabulaire. Django reste responsable de la persistance et des contrôles applicatifs.

**Que se passe-t-il si une colonne est absente ?**  
La phase de normalisation tente d’identifier les colonnes équivalentes et de compléter les valeurs calculables. Si le fichier ne permet pas d’obtenir des données exploitables, l’import est rejeté avec un message explicite.

**Comment évitez-vous les doublons ?**  
La version actuelle contrôle la validité du contenu avant création, mais une clé métier de déduplication (par exemple date-client-produit-document-source) serait une amélioration à ajouter si la source peut être réimportée plusieurs fois. Ne pas dire qu’une déduplication automatique est déjà présente si elle n’a pas été démontrée.

**Pourquoi la limite de 10 Mo ?**  
Elle limite le risque de surcharge et reste configurable par `MAX_UPLOAD_SIZE_MB` selon l’infrastructure.

## 4. Livrable 2 — Tableau de bord commercial et export PDF

### Besoin traité

Un responsable commercial doit voir rapidement le chiffre d’affaires, la marge, les volumes, les répartitions et leur évolution, sans requêtes SQL ni consolidation manuelle.

### Comment je l’ai réalisé

- La vue `dashboard` construit un contexte selon les filtres de date, clients et produits.
- Les KPI sont calculés côté serveur à partir des ventes : CA, coûts, marge et ratios associés. Les expressions sont effectuées dans la base lorsque c’est pertinent, plutôt que de charger inutilement chaque ligne en mémoire.
- Les données sont regroupées par période, produit, client et région ; elles alimentent les cartes KPI et les graphiques Chart.js.
- L’utilisateur peut choisir un horizon de prévision de 3, 6 ou 12 mois et une granularité temporelle.
- La route `/dashboard/export-pdf/` génère un document de synthèse avec WeasyPrint et des graphiques SVG. L’export est donc cohérent avec les filtres du dashboard.
- Toutes les pages concernées sont réservées aux utilisateurs authentifiés.

### Ce qu’il faut savoir expliquer

Le CA ne mesure pas la rentabilité. Deux produits peuvent avoir le même CA mais des marges très différentes. C’est pour cela que le dashboard affiche aussi coûts et marge, et que le moteur de recommandations peut signaler une marge faible ou négative.

### Formulation courte à dire

« Le tableau de bord transforme les lignes de ventes en indicateurs actionnables. J’ai gardé les filtres au niveau de la requête afin que le même périmètre soit utilisé pour les KPI, les graphiques, les recommandations, les prévisions et le PDF. »

### Questions probables

**Comment calculez-vous la marge ?**  
`quantité × prix_unitaire − quantité × coût_unitaire`. Le calcul est donc fondé sur les données élémentaires et non sur un chiffre saisi manuellement.

**Pourquoi générer le PDF côté serveur ?**  
Cela rend l’export reproductible, même sans dépendre de l’état visuel du navigateur, et facilite le partage à la direction.

**Comment gérez-vous un très grand volume de données ?**  
Les index ciblent les dimensions de filtre usuelles. À plus grande échelle, j’ajouterais pagination, agrégats matérialisés ou tables de synthèse, cache et traitement asynchrone pour les imports lourds.

## 5. Livrable 3 — Configuration et traçabilité des alertes

### Besoin traité

Les seuils commerciaux ne sont pas universels : une baisse de 5 % peut être grave dans une activité et normale dans une autre. Les décideurs doivent pouvoir les adapter sans modifier le code.

### Comment je l’ai réalisé

- J’ai créé le modèle `SeuilAlerte` avec le KPI concerné (CA ou volume), les seuils vert/orange/rouge, le type de comparaison et la référence.
- Les références prévues sont le mois précédent, la moyenne mobile des trois mois précédents ou une prévision validée.
- Les comparaisons peuvent porter sur une valeur inférieure/supérieure, une baisse en pourcentage ou un écart en pourcentage.
- Une contrainte base de données et une validation Django imposent qu’un minimum soit inférieur à un maximum quand les deux existent.
- La vue `/alertes/configuration/` est réservée à la permission `configure_thresholds`.
- Chaque changement est mémorisé dans `HistoriqueConfigurationAlerte`, avec l’auteur, les valeurs et la date. C’est un élément d’audit important.

### Formulation courte à dire

« Les alertes ne sont pas une boîte noire. Leur seuil, leur référence de comparaison et leur historique sont visibles. Le métier garde ainsi la maîtrise des règles qui déclenchent une alerte. »

### Questions probables

**Pourquoi une moyenne mobile de trois mois ?**  
Elle lisse les variations ponctuelles et donne souvent une référence plus stable que le seul mois précédent. Si elle n’est pas disponible, l’application peut recourir à la référence disponible.

**Qui est autorisé à modifier les seuils ?**  
Uniquement un utilisateur ayant la permission dédiée. C’est plus sûr que d’ouvrir cette action à tout utilisateur connecté.

**Pourquoi garder l’historique ?**  
Pour expliquer a posteriori pourquoi une alerte est apparue ou a disparu et pour attribuer la modification. Sans historique, l’analyse ne serait pas audit-able.

## 6. Livrable 4 — Moteur de recommandations explicables

### Besoin traité

Au lieu de seulement afficher des graphiques, l’application identifie les situations qui demandent une action : baisse de CA, marge trop faible, concentration de risque, anomalie de quantité ou écart avec la prévision.

### Comment je l’ai réalisé

- Le module `sales/recommandations.py` calcule d’abord les indicateurs sur le périmètre filtré.
- Des règles séparées évaluent : CA global, dimensions (produit/client/région), marges, concentrations et écarts de prévision.
- Chaque signal est une structure `Recommendation` contenant : identifiant de règle (`rule_id`), titre, message, justification, action recommandée, priorité, score, confiance, entité, période et preuves chiffrées.
- Le score combine gravité (35 %), impact financier (25 %), durée (15 %), fiabilité des données (15 %) et confiance d’analyse (10 %).
- La confiance tient notamment compte du nombre de lignes, de la complétude et du nombre de périodes. Les données insuffisantes génèrent un état explicite plutôt qu’une fausse conclusion.
- Avant affichage, je supprime les doublons et résous les recommandations contradictoires, par exemple une croissance et une baisse concurrentes sur le même objet/période.
- Les seuils par défaut sont configurables dans `RECOMMENDATION_THRESHOLDS`; ils doivent être validés par le métier avant décision réelle.

### Exemples de règles à citer

- baisse globale de CA ;
- baisse forte par produit, client ou région ;
- marge négative ;
- produit à CA élevé mais marge faible ;
- dépendance à un client, produit ou région ;
- écart significatif entre réalisé et prévision ARIMA ;
- données insuffisantes.

### Formulation courte à dire

« J’ai préféré un moteur de règles explicables à une recommandation opaque. Chaque recommandation dit quelle règle a été déclenchée, sur quelles valeurs, pour quelle période, avec quel degré de confiance et quelle action est suggérée. »

### Questions probables

**Pourquoi ne pas utiliser directement un modèle de machine learning ?**  
Le besoin initial exige surtout explicabilité, auditabilité et faible volume de données. Les règles sont plus faciles à valider par les responsables métiers. Un modèle ML peut être ajouté plus tard si des données historiques labellisées et une métrique de performance sont disponibles.

**Comment évitez-vous une alerte erronée sur peu de données ?**  
Le moteur mesure la complétude, le nombre de lignes et les périodes. Il produit un avertissement de données insuffisantes au lieu d’un signal métier solide.

**Un score de 80 signifie-t-il 80 % de probabilité ?**  
Non. C’est un score de priorisation de 0 à 100, pas une probabilité statistique. La confiance est une information distincte.

**Comment validez-vous les règles ?**  
Par des tests automatisés de recommandations, des cas d’acceptation chiffrés et une calibration avec les responsables commerciaux. Les seuils initiaux sont des paramètres, pas des vérités universelles.

## 7. Livrable 5 — Module de prévision du chiffre d’affaires

### Besoin traité

Le décideur ne veut pas seulement connaître le passé : il veut anticiper une tendance et repérer un écart entre réalisé et attendu.

### Comment je l’ai réalisé

- Les ventes sont agrégées mensuellement dans `prediction.py` pour former une série temporelle de CA.
- Si l’historique est suffisant, le module détermine l’ordre de différenciation avec le test ADF, teste une petite grille de modèles ARIMA `(p,d,q)` et retient le modèle convergé avec le meilleur AIC.
- Une validation rétrospective évalue le comportement sur l’historique disponible.
- Si l’historique contient moins de six mois, si `statsmodels` est indisponible ou si ARIMA ne converge pas, l’application utilise une moyenne mobile. Un avertissement est présenté : elle ne masque pas la solution de repli.
- Le résultat inclut la méthode utilisée, les prévisions, des indicateurs de fiabilité/avertissements et un cache lié à la série afin d’éviter un recalcul identique.

### Point méthodologique important

ARIMA projette une dynamique observée dans l’historique. Il ne connaît pas automatiquement les promotions, changements de prix, ruptures de stock, saisonnalité exceptionnelle ou événements concurrents. Il faut présenter la prévision comme un **outil d’aide**, non comme une certitude.

### Formulation courte à dire

« J’ai conçu une prévision robuste au manque de données : ARIMA est utilisé quand l’historique le permet; sinon une moyenne mobile est utilisée et clairement signalée. Je préfère une dégradation explicite à une prévision sophistiquée mais trompeuse. »

### Questions probables

**Pourquoi ARIMA ?**  
C’est un modèle classique, interprétable et approprié à une série temporelle univariée de CA, avec un coût de mise en œuvre raisonnable.

**Pourquoi six mois comme seuil minimal ?**  
En dessous, l’estimation ARIMA est fragile. La moyenne mobile est une référence plus prudente. Ce seuil doit être revalidé selon la fréquence et la saisonnalité réelles des données.

**Comment mesurez-vous la qualité ?**  
La validation rétrospective compare des prédictions aux valeurs historiques connues. En production, je suivrais aussi MAE, RMSE et éventuellement MAPE, avec prudence lorsque le CA peut être proche de zéro.

**Que feriez-vous pour améliorer la prévision ?**  
Ajouter davantage d’historique, traiter explicitement la saisonnalité, intégrer des variables externes (promotions, jours fériés, stock) et comparer plusieurs modèles sur une période de test séparée.

## 8. Livrable 6 — Assistant commercial encadré

### Besoin traité

L’utilisateur peut poser une question en langage naturel, par exemple « Quel client a le plus baissé ? », sans devoir naviguer entre plusieurs graphiques.

### Comment je l’ai réalisé

- Les routes de chat sont intégrées au dashboard : envoi, streaming, effacement de la mémoire de session et feedback.
- Une couche d’intentions (`assistant_intents.py`) reconnaît la métrique, l’entité, les filtres et les périodes. Elle comporte une base déterministe et, si activé, une résolution assistée par le LLM avec un schéma Pydantic.
- Les calculs métier sont exécutés localement par `assistant_analytics.py` : KPI, comparaisons, classements, analyse d’entité, anomalies, prévisions et recommandations.
- Le LLM reçoit un contexte structuré et agrégé : métriques, périodes, noms d’entités nécessaires et règles. Il ne reçoit pas les lignes brutes de ventes.
- Le fournisseur par défaut est Ollama local (`qwen3:1.7b`), donc sans coût d’API et sans envoi vers un fournisseur distant. OpenAI peut être configuré par variable d’environnement si l’organisation l’autorise.
- Les interactions gardent le fournisseur, le modèle, l’intention, les durées, volumes de contexte, avertissements et un feedback « utile / non utile ».
- Les exemples validés par feedback peuvent aider à reconnaître les formulations futures, sans inventer de données nouvelles.

### Formulation courte à dire

« L’IA ne calcule pas les chiffres à la place de l’application. Elle reformule une réponse à partir de calculs et d’agrégats contrôlés. Cela réduit le risque d’hallucination et protège les lignes de vente brutes. »

### Questions probables

**Comment limitez-vous les hallucinations ?**  
Les métriques sont calculées par le code applicatif; l’assistant reçoit un contexte borné. La sortie structurée est validée et les réponses peuvent citer la période et la règle. Malgré cela, une réponse LLM doit rester une aide à vérifier, pas une preuve autonome.

**Vos données sont-elles envoyées à OpenAI ?**  
Par défaut non : Ollama est local. Si OpenAI est activé, seuls des agrégats pertinents sont transmis, jamais les lignes brutes; cela doit être autorisé par la politique de confidentialité de l’entreprise.

**Pourquoi stocker le feedback ?**  
Pour mesurer l’utilité, repérer les questions mal comprises et améliorer les intentions sur la base d’exemples explicitement validés.

**Pourquoi avez-vous une logique déterministe en plus du LLM ?**  
Pour les questions commerciales fréquentes, elle est plus rapide, testable et prévisible. Le LLM complète l’interprétation du langage, il ne remplace pas les règles de calcul.

## 9. Livrable 7 — Sécurité et exploitation

### Besoin traité

Un outil qui contient des données commerciales et des comptes utilisateurs doit être exploitable de manière sécurisée, et pas seulement fonctionner en démonstration.

### Comment je l’ai réalisé

- La configuration sensible est lue depuis des variables d’environnement : clé Django, accès base, hôtes autorisés, paramètres du LLM et clé de sauvegarde. Les secrets ne doivent pas être versionnés.
- Quand `DJANGO_DEBUG=False`, Django active redirection HTTPS, cookies sécurisés et HTTP-only, HSTS, protection CSRF, `X-Frame-Options: DENY`, `nosniff` et une politique de référent.
- Les mots de passe utilisent Argon2 en priorité et les règles de Django imposent notamment une longueur minimale de 15 caractères.
- Les permissions séparent import, configuration de seuils et administration des comptes.
- Le provisioning crée des comptes avec un mot de passe temporaire à changer, conserve un audit sans secret et limite les échecs de connexion : cinq tentatives en quinze minutes entraînent un verrouillage de quinze minutes (paramétrable).
- Un endpoint `/health/` permet la supervision.
- La commande `backup_database` chiffre les sauvegardes avec Fernet ; `DEPLOYMENT.md` définit la procédure de migration, collecte des fichiers statiques, TLS, supervision, rétention et test de restauration.

### Formulation courte à dire

« La sécurité est intégrée par défaut : principe de moindre privilège, secrets hors code, chiffrement des sauvegardes, journalisation et configuration renforcée hors développement. »

### Questions probables

**Pourquoi Argon2 ?**  
C’est un hachage de mots de passe moderne, coûteux à attaquer et recommandé pour mieux résister aux attaques par force brute.

**Une sauvegarde chiffrée suffit-elle ?**  
Non. Il faut aussi gérer la clé hors du dépôt, stocker la copie dans un emplacement externe, appliquer une rétention et surtout tester périodiquement une restauration isolée.

**Pourquoi séparer les permissions ?**  
Importer des données, changer une règle qui influence les décisions et administrer des comptes ont des impacts différents. Le moindre privilège limite les erreurs et les abus.

## 10. Validation et démonstration recommandée

### Scénario de démonstration (5 à 7 minutes)

1. Présenter le problème et l’architecture en 30 secondes.
2. Se connecter avec un utilisateur approprié.
3. Importer un petit fichier CSV valide.
4. Ouvrir le dashboard : expliquer CA, marge, filtres, graphiques et horizon de prévision.
5. Montrer une recommandation, son `rule_id`, sa preuve chiffrée, sa priorité et sa confiance.
6. Ouvrir la configuration d’alertes et l’historique de modification.
7. Poser une question à l’assistant sur un chiffre visible dans le dashboard.
8. Montrer l’export PDF ou expliquer la route d’export.
9. Conclure avec sécurité, limites et prochaine étape.

### Tests existants à citer avec honnêteté

Le dépôt contient des tests Django généraux ainsi que `test_recommandations.py` et `test_assistant_pipeline.py`. Les cas documentés d’import couvrent notamment fichier vide, en-têtes seuls, taille excessive et fichier corrompu. Si le jury demande si « tous les tests passent », répondre uniquement avec le résultat d’une exécution récente de `python manage.py test`; ne pas l’affirmer sans l’avoir exécuté.

## 11. Limites à assumer (cela renforce la crédibilité)

- Les seuils initiaux doivent être calibrés avec les responsables commerciaux; ils ne sont pas des règles universelles.
- Une prévision ARIMA est limitée par la quantité, la qualité et la stabilité de l’historique, et ne connaît pas les événements externes.
- Le LLM peut mal interpréter une demande ambiguë; les calculs doivent rester vérifiables dans le dashboard.
- La déduplication métier d’un réimport mérite d’être renforcée si les sources contiennent un identifiant de transaction fiable.
- Avant production, il faut une recette métier, une configuration réelle des secrets/hébergement, une revue des droits et un test de restauration.

## 12. Questions transversales rapides — réponses prêtes

**Quel problème résolvez-vous exactement ?**  
La dispersion des données de ventes et le délai entre constat et décision. L’application centralise, calcule, alerte et explique.

**Quelle est la valeur ajoutée par rapport à Excel ?**  
Des règles centralisées, des droits d’accès, une traçabilité des seuils, des calculs réutilisables, des recommandations explicables, un export cohérent et un assistant encadré.

**Pourquoi Django ?**  
Il apporte ORM, authentification, permissions, protection CSRF, migrations, administration et un cadre robuste pour une application métier Python.

**Pourquoi MySQL ?**  
C’est une base relationnelle adaptée aux données transactionnelles et aux agrégations; Django rend le code largement portable vers une autre base compatible si nécessaire.

**Quelle différence entre alerte et recommandation ?**  
Une alerte qualifie un état par seuil (par exemple orange/rouge). Une recommandation interprète un signal dans un contexte et propose une action, avec justification et priorité.

**Comment garantissez-vous la qualité des données ?**  
Par validation à l’import, normalisation, contrôle de taille/formats, indicateurs de complétude et comportement explicite quand les données sont insuffisantes. La qualité de la source reste une responsabilité partagée avec le métier.

**Comment protégez-vous les données personnelles ?**  
Accès authentifié et autorisé, cookies sécurisés, secrets hors code, minimisation du contexte envoyé au LLM et option locale Ollama. La conformité complète exige aussi une politique de rétention et une analyse juridique propres à l’organisation.

**Quel est votre indicateur de réussite ?**  
À valider avec le sponsor : réduction du temps de production du reporting, taux d’adoption, précision utile des alertes, taux de feedback positif de l’assistant et erreur de prévision suivie dans le temps.

**Quel serait votre premier développement après la soutenance ?**  
Une clé de déduplication métier à l’import, puis une calibration formelle des seuils avec données historiques et mesure continue des performances de prévision.

## 13. Conclusion prête à prononcer

« Le projet ne se limite pas à un dashboard. Il construit une chaîne complète et traçable : des fichiers de ventes validés deviennent des données structurées, puis des KPI, des alertes configurables, des recommandations explicables et des prévisions prudentes. L’assistant améliore l’accès à l’analyse sans prendre le contrôle des calculs. Enfin, les rôles, la protection des secrets et les sauvegardes permettent d’envisager une exploitation responsable. »

## 14. Fichiers de référence dans le dépôt

- `sales/views.py` : import, dashboard, PDF, chat, alertes et administration.
- `sales/models.py` : modèle de ventes, seuils, audit et journal de l’assistant.
- `sales/recommandations.py` et `RECOMMANDATIONS.md` : règles, score, confiance et critères.
- `sales/prediction.py` : ARIMA, moyenne mobile, repli et validation rétrospective.
- `sales/services/assistant_intents.py`, `assistant_analytics.py`, `openai_sales_assistant.py` : intentions, calculs contrôlés et fournisseurs LLM.
- `DecisionIQ/settings.py` et `DEPLOYMENT.md` : configuration et sécurité opérationnelle.
