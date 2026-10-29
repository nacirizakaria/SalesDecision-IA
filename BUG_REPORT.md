# Rapport QA de pré-démonstration

Date : 30 juillet 2026  
Périmètre : import, KPIs, prévisions ARIMA/MMP, alertes, recommandations, sécurité, export PDF et multi-utilisateurs.

## Résultat de validation

- Bugs bloquants restants : **0**
- Bugs majeurs restants : **0**
- Suite automatisée finale : **86/86 tests réussis**
- Contrôle Django de déploiement avec configuration de production : **aucun avertissement**
- Recette navigateur : aucun débordement horizontal, aucune erreur JavaScript, aucun contrôle sans libellé.

## Bugs priorisés

### QA-001 — Majeur — Corrigé

- Module : alertes / chargement du dashboard.
- Étapes de reproduction :
  1. Ouvrir le dashboard avec un utilisateur authentifié.
  2. Capturer les requêtes SQL exécutées pendant le GET.
  3. Observer une écriture `UPDATE sales_seuilalerte ... ecart_arima` et quatre lectures d’initialisation distinctes.
- Impact : un affichage en lecture seule modifiait l’état de la base à chaque chargement, ajoutait cinq requêtes et pouvait écraser l’état d’une ancienne règle configurée.
- Priorité : majeure.
- Correction :
  - chargement groupé des règles avec `in_bulk` ;
  - création groupée uniquement des règles absentes ;
  - conservation des choix utilisateur existants ;
  - suppression de l’écriture portant sur `ecart_arima` pendant un GET ;
  - ajout d’un test de non-régression garantissant une seule lecture et aucune écriture lors d’une initialisation répétée.
- Mesure après correction : 26 → 22 requêtes ; 1 → 0 écriture SQL par dashboard.

### QA-002 — Mineur — Documenté

- Module : configuration locale de déploiement.
- Étapes de reproduction :
  1. Exécuter `python manage.py check --deploy` avec le `.env` local.
  2. Observer les avertissements liés à `DEBUG=True`, à la clé locale et aux cookies HTTPS.
- Impact : aucun sur la démonstration locale ; cette configuration ne doit pas être utilisée en production.
- Priorité : mineure.
- Justification : le code active correctement HTTPS, HSTS et les cookies sécurisés lorsque `DJANGO_DEBUG=False`. Le contrôle avec une clé de production valide ne remonte aucun avertissement. Les secrets réels relèvent du déploiement et ne doivent pas être inscrits dans le dépôt.

## Tests automatisés

La commande `python manage.py test --keepdb` couvre :

- validation et import CSV/XLSX, fichiers vides, corrompus ou trop volumineux ;
- calculs KPIs, filtres, agrégations temporelles et invalidation du cache ;
- prévisions MMP/ARIMA, intervalles et validation rétrospective ;
- export PDF, filtres et répartitions ;
- alertes et permissions de configuration ;
- recommandations, détection d’intentions, ancrage des réponses et feedback ;
- authentification, verrouillage, rôles, permissions et suppression contrôlée de comptes ;
- création multi-utilisateurs, mot de passe temporaire et activation obligatoire.

Résultat final : **86 tests réussis en 5,9 s** sur la base de test conservée.

## Recette exploratoire

Environnement isolé SQLite, navigateur Chromium headless, viewport 1440 × 1000 :

- connexion administrateur : réussie ;
- import du fichier de démonstration : réussi ;
- dashboard : six cartes KPI, graphiques rendus, aucun débordement ;
- filtres produit : application automatique et paramètres d’URL corrects ;
- liste et recherche : trois lignes trouvées pour Casablanca ;
- ARIMA réel : méthode `arima`, historique de 24 mois, trois prévisions produites ;
- alertes : quatre règles affichées, préréglage et sauvegarde réussis ;
- PDF : HTTP 200, `application/pdf`, document de 65 304 octets ;
- recommandations : réponse déterministe ancrée, HTTP 200 en 45 ms ;
- multi-utilisateurs : compte créé, deux identifiants temporaires générés ;
- première connexion : redirection vers l’activation et changement de mot de passe obligatoire ;
- séparation des rôles : accès à la création d’utilisateur refusé en HTTP 403 pour le compte métier ;
- accessibilité structurelle : zéro identifiant dupliqué, zéro contrôle sans libellé ;
- console navigateur : aucune erreur applicative sur les URL valides.

Artefacts : `artifacts/qa-exploratory/`.

## Performances

- Dashboard avec prévision en cache : **23–25 ms**, 22 requêtes SQL.
- Premier calcul ARIMA sur la série de recette : **335,7 ms** pour le modèle seul.
- Premier dashboard après purge complète du cache et ajustement ARIMA : **environ 1,9 s**.
- Export PDF : **environ 1,1 s**.
- Réponse de recommandation déterministe : **45 ms**.

Les index `date`, `(produit, date)`, `(client, date)` et `(region, date)` sont présents.

### Proposition architecturale non appliquée

Pour des historiques volumineux ou de nombreux utilisateurs simultanés, pré-calculer ARIMA après import dans une tâche asynchrone (Celery/RQ) et servir la dernière prévision validée. Ce changement nécessite un worker, une file de tâches, une politique de reprise et du monitoring ; il n’est donc pas appliqué sans validation.

## Fichiers sans relation directe avec l’exécution de la plateforme

Ces fichiers ne ralentissent pas les requêtes HTTP car ils ne sont pas importés au runtime. Leur impact concerne surtout la taille du dépôt, les déploiements et la maintenance.

### Suppression recommandée en priorité

- `sales/static/img/salesdecision-logo.png` — 910,7 Ko, non référencé.
- `sales/static/img/salesdecision-logo.svg` — non référencé.
- `sales/static/img/salesdecision-prism-source.png` — 48,1 Ko, fichier source non référencé.
- `sales/static/img/salesdecision-prism-transparent.png` — 20,1 Ko, non référencé.
- Tous les dossiers `__pycache__/` — environ 428 Ko cumulés, artefacts générés automatiquement.
- `db.sqlite3` — base locale historique non utilisée lorsque MySQL est configuré ; risque de confusion et de données obsolètes.

Conserver seulement `sales/static/img/salesdecision-prism.png`, effectivement utilisé par la navigation, la connexion et le favicon.

### À déplacer hors du paquet de production

- `test_ventes.csv`, `test_alerte_orange.csv`, `test_alerte_rouge.csv` — jeux de démonstration/recette.
- `sales/tests.py`, `sales/test_recommandations.py`, `sales/test_assistant_pipeline.py` — indispensables à la qualité, mais exclusibles d’une image de production minimale.
- `scripts/playwright_audit.py`, `scripts/benchmark_*.py` — outils QA/benchmark, sans impact runtime.
- `ASSISTANT_AUDIT.md`, `RECOMMANDATIONS.md`, `DEPLOYMENT.md` — documentation, sans impact runtime.
- `artifacts/` — captures, rapports et base isolée de recette ; à exclure de l’image déployée.

Recommandation : les conserver dans le dépôt pour la maintenance, mais les exclure du conteneur ou paquet de production via `.dockerignore`/pipeline de build. La suppression des tests du dépôt source n’est pas recommandée.

## Conclusion

Le critère de validation est satisfait : aucun bug bloquant ou majeur ne reste ouvert. L’application est fonctionnellement complète, stable et prête pour la démonstration.
