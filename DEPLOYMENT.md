# Déploiement sécurisé

1. Copier `.env.example` vers un gestionnaire de secrets de la plateforme.
2. Définir `DJANGO_DEBUG=False`, une clé Django aléatoire et les accès MySQL dédiés.
3. Terminer TLS au niveau du reverse proxy et transmettre `X-Forwarded-Proto: https`.
4. Exécuter `python manage.py migrate` puis `python manage.py collectstatic --noinput`.
5. Superviser `GET /health/` et alerter sur toute réponse différente de HTTP 200.
6. Générer une clé de sauvegarde avec :
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
7. Stocker cette valeur dans `BACKUP_ENCRYPTION_KEY`, hors du dépôt.
8. Planifier `python manage.py backup_database --retention-days 14`.
9. Copier les sauvegardes chiffrées vers un stockage externe avec rétention immuable.
10. Tester régulièrement la restauration dans un environnement isolé.

Cinq échecs de connexion sur quinze minutes entraînent un verrouillage de quinze
minutes; ces valeurs sont configurables par environnement.

## Assistant commercial OpenAI GPT

Définir la clé uniquement dans l'environnement du serveur :

```env
OPENAI_API_KEY=sk-...
```

Installer `requirements.txt`, puis redémarrer Django. Le widget transmet à
OpenAI les agrégats pertinents (client, CA, marge, quantités, périodes et
règles), jamais les lignes de ventes brutes. Cette transmission doit être
couverte par la politique de confidentialité de l'entreprise.

## Variables obligatoires en production

Injecter `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST` et `DB_PORT` depuis le gestionnaire de secrets de
l'hébergeur. Conserver `DJANGO_DEBUG=False`. Le fichier `.env` est réservé au
développement local et ne doit jamais être versionné.

La limite des imports est configurable avec `MAX_UPLOAD_SIZE_MB=10`.

## Recette manuelle des imports

1. Fichier vide : message explicite, aucune vente créée, aucune erreur HTTP 500.
2. CSV avec en-têtes seuls : message indiquant l'absence de données.
3. Fichier supérieur à 10 Mo : message rappelant la limite configurée.
4. Faux fichier `.xlsx` ou fichier corrompu : message fonctionnel sans trace
   Python, détail pandas ou information serveur.

## Assistant local gratuit avec Ollama

Le fournisseur par défaut est local et ne consomme aucun crédit API :

```env
LLM_PROVIDER=ollama
OLLAMA_ASSISTANT_MODEL=qwen3:1.7b
OLLAMA_API_URL=http://127.0.0.1:11434/api/chat
```

Installer Ollama sur la machine qui exécute Django, puis télécharger le modèle
avec `ollama pull qwen3:1.7b`. Ollama doit rester démarré. Les agrégats
commerciaux restent alors sur la machine et ne sont envoyés à aucun fournisseur
LLM distant.
