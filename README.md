# DCIC-Flix26

Socle d’une plateforme universitaire de cinéma en microservices. Ce dépôt fournit
la structure, les environnements et l’infrastructure de développement; les
fonctionnalités métier restent à construire.

## Prérequis

- Docker avec Docker Compose v2
- Node.js 24 et npm 11 pour le développement frontend hors conteneur
- Python 3.13 pour le développement des services hors conteneur

## Démarrage avec Docker Compose

Depuis `DCIC-Flix26/` :

```powershell
Copy-Item .env.example .env
docker compose up --build
```

- Frontend Vite : <http://localhost:5173>
- Gateway : <http://localhost:8000>; état global : <http://localhost:8000/api/health>
- MongoDB et RabbitMQ ne publient aucun port sur l’hôte; ils sont accessibles
  uniquement depuis les réseaux internes et les commandes `docker compose exec`.

Compose initialise MongoDB sur son volume neuf, crée des comptes applicatifs
séparés et importe automatiquement les fichiers `*.json` et `*.json.gz` du
dataset présent au démarrage. Le chargement est idempotent par empreinte de
fichier; les documents source doivent inclure `_id`. Un dossier sans données est
signalé dans les logs, sans génération de données artificielles.

RabbitMQ importe exchanges, queues, bindings et files de lettres mortes depuis
`rabbitmq/definitions.json`. La gateway transmet les requêtes catalogue et
critiques aux services dédiés; les interactions ne sont stockées dans MongoDB
qu’après publication RabbitMQ et consommation par le consumer. Les contrats
HTTP et événements sont décrits dans [docs/contracts.md](docs/contracts.md).
Le nettoyage et les recommandations ne sont pas implémentés.

Routes principales :

| Route | Fonction |
| --- | --- |
| `GET /api/movies?q=&genre=&page=1&page_size=20` | Rechercher et filtrer le catalogue |
| `GET /api/movies/{movie_id}` | Consulter un film |
| `GET /api/movies/{movie_id}/reviews` | Lire les critiques historiques |
| `POST /api/interactions/reviews` | Publier une note et un commentaire |
| `GET /api/health` | Vérifier les services aval, dont MongoDB et RabbitMQ via leurs services |

La recherche catalogue porte sur le titre, le résumé et le synopsis. Les
identifiants de film sont les ObjectId MongoDB du dataset (24 caractères
hexadécimaux). La lecture des critiques n’expose pas les adresses e-mail.

Les identifiants de `.env.example` sont réservés au développement local.
Remplacez-les avant tout déploiement partagé. Gardez les identifiants MongoDB
compatibles avec les URI (caractères alphanumériques, `_` et `-`) ou encodez-les
en URL. La clé `OPENAI_API_KEY` est facultative tant que le nettoyage LLM n’est
pas développé.

### Contrôles d’infrastructure (PowerShell)

```powershell
docker compose ps
docker compose logs dataset-loader

# MongoDB : ping root, puis accès en lecture avec le compte du catalogue.
docker compose exec mongodb mongosh --quiet --username flix --password flix_local_dev_only --authenticationDatabase admin --eval 'db.adminCommand({ ping: 1 })'
docker compose exec mongodb mongosh --quiet --username flix_catalog --password catalog_local_dev --authenticationDatabase peliculas-proyectos peliculas-proyectos --eval 'db.movies.countDocuments()'

# RabbitMQ : vérifier les exchanges, files et bindings provisionnés au démarrage.
docker compose exec rabbitmq rabbitmqctl list_exchanges name type
docker compose exec rabbitmq rabbitmqctl list_queues name durable messages
docker compose exec rabbitmq rabbitmqctl list_bindings source_name destination_name routing_key

# Le frontend ne doit pas pouvoir résoudre les services de données.
docker compose exec frontend node -e "require('dns').lookup('mongodb',e=>{if(!e){console.error('ERREUR: mongodb est resolvable');process.exit(1)}console.log('OK: mongodb non resolvable ('+e.code+')')})"
docker compose exec frontend node -e "require('dns').lookup('rabbitmq',e=>{if(!e){console.error('ERREUR: rabbitmq est resolvable');process.exit(1)}console.log('OK: rabbitmq non resolvable ('+e.code+')')})"

# Inspecter les réseaux réellement attachés aux conteneurs.
$frontendId = docker compose ps -q frontend
$mongoId = docker compose ps -q mongodb
docker inspect --format '{{json .NetworkSettings.Networks}}' $frontendId
docker inspect --format '{{json .NetworkSettings.Networks}}' $mongoId

# MongoDB et RabbitMQ ne doivent pas écouter sur des ports de l’hôte.
Test-NetConnection localhost -Port 27017 -InformationLevel Quiet
Test-NetConnection localhost -Port 5672 -InformationLevel Quiet

# Le service catalogue, lui, doit résoudre MongoDB sur le réseau data.
docker compose exec catalog-service python -c "import socket; print('MongoDB:', socket.gethostbyname('mongodb'))"
```

Les deux tests de port doivent retourner `False`; l’inspection réseau doit
montrer uniquement `frontend_gateway` pour le frontend et `data` pour MongoDB.
Les recherches DNS du frontend vers `mongodb` et `rabbitmq` doivent échouer.
Les commandes avec identifiants utilisent les valeurs d’exemple; adaptez-les à
votre `.env` si vous les avez remplacées.

## Développement local

Frontend :

```powershell
Set-Location frontend
npm ci
npm run dev
```

Chaque service Python possède son propre `requirements.txt` et son propre
`Dockerfile`. Pour créer un environnement virtuel et installer, par exemple,
celui de la gateway :

```powershell
Set-Location gateway
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Tests backend

Depuis la racine du dépôt, installez les dépendances de test dans un
environnement virtuel Python 3.13, puis lancez toutes les suites :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r gateway\requirements-dev.txt -r catalog-service\requirements-dev.txt -r interaction-service\requirements-dev.txt -r consumer\requirements-dev.txt
python -m pytest -q
```

Les tests couvrent les validations, la recherche/pagination, le filtrage des
champs privés, l’idempotence, l’acquittement après persistance et les erreurs
de broker/base. Le test de flux exerce la gateway et les applications HTTP
réelles des services catalogue et interaction dans le même processus, avec des
adaptateurs simulés pour MongoDB et RabbitMQ. Pour vérifier les conteneurs et
les connexions aux vraies instances MongoDB/RabbitMQ, Docker Desktop doit être
démarré.

## Structure

| Répertoire | Responsabilité prévue |
| --- | --- |
| `frontend/` | Interface React, TypeScript, Vite et Tailwind CSS |
| `gateway/` | Point d’entrée HTTP pour le frontend |
| `catalog-service/` | Accès au catalogue MongoDB |
| `cleaning-agent/` | Nettoyage des données ambiguës avec un LLM |
| `recommendation-service/` | Recommandations TF-IDF et similarité cosinus avec scikit-learn |
| `interaction-service/` | Réception des votes et critiques, publication RabbitMQ |
| `consumer/` | Consommation des événements et persistance MongoDB |
| `dataset-loader/` | Import idempotent du dataset et initialisation des comptes MongoDB |
| `dataset/` | Archives du dataset universitaire fournies avec le projet |
| `docs/` | Documentation d’architecture |

Voir [docs/architecture.md](docs/architecture.md) pour les limites de services
et le flux cible.

## Versions retenues

Les dépendances Python et JavaScript sont épinglées à des versions précises;
`frontend/package-lock.json` verrouille également l’arbre npm transitif. Les
images Docker utilisent des tags précis.

| Composant | Version |
| --- | --- |
| Node.js (frontend) | 24.11.1 |
| React / React DOM | 19.3.1 / 19.3.0 |
| TypeScript | 7.0.2 |
| Vite / plugin React | 8.3.8 / 6.3.0 |
| Tailwind CSS / plugin Vite | 4.3.5 |
| Python (services) | 3.13.7 |
| FastAPI / Uvicorn | 0.163.1 / 0.54.0 |
| PyMongo | 4.20.0 |
| aio-pika | 10.2.3 |
| OpenAI Python SDK | 3.52.0 |
| scikit-learn | 1.9.1 |
| MongoDB / RabbitMQ | 8.0.12 / 4.2.3-management |

Les versions seront réévaluées et mises à jour ensemble au fil du projet.
