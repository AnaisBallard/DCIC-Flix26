# Contrats HTTP et événementiels

Tous les identifiants de films utilisent l’ObjectId MongoDB du dataset (24
caractères hexadécimaux). Les dates sont sérialisées au format ISO 8601. Les
réponses d’erreur FastAPI ont la forme `{"detail": "..."}`.

## Gateway

Seul le port HTTP présenté au navigateur est celui de la gateway. Elle transmet
les appels aux services sur le réseau Compose et ne se connecte ni à MongoDB ni
à RabbitMQ.

| Méthode et route publique | Destination | Contrat |
| --- | --- | --- |
| `GET /api/health` | catalog, interaction, recommendation, consumer `/health` | État global; `503` si un service est indisponible |
| `GET /api/movies?q=&genre=&page=1&page_size=20` | `GET /movies` | Recherche texte et genre, pagination (`page_size` de 1 à 100) |
| `GET /api/movies/{movie_id}` | `GET /movies/{movie_id}` | Détail ou `404` |
| `GET /api/movies/{movie_id}/reviews?page=1&page_size=20` | même route catalogue | Critiques historiques paginées; les courriels sont exclus |
| `POST /api/interactions/reviews` | `POST /interactions/reviews` | Événement accepté (`202`) ou erreur de publication |

Une erreur de connexion amont devient `503`, un timeout `504`. Les erreurs HTTP
du service sont retransmises avec leur statut et leur corps.

## Rechercher le catalogue

`GET /movies` accepte `q` (1–120 caractères), `genre` (1–60), `page` (>= 1) et
`page_size` (1–100). La recherche `q` porte sur `title`, `plot` et `fullplot`;
le genre correspond à une entrée complète du tableau `genres`, sans tenir
compte de la casse.

Réponse :

```json
{
  "items": [{"_id": "573a13a4f29313caabd10527", "title": "A Fish Tale"}],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

Le détail conserve les champs du film; `_id` devient une chaîne et les dates
ISO 8601. Les critiques sélectionnent `movie_id`, `user_id`, `rating`,
`comment` et `date`, sans `user_email` ni `user_name`.

## Création d’une critique

Requête publique et service interaction :

```json
{
  "movie_id": "573a13a4f29313caabd10527",
  "user_id": "usr_0937",
  "rating": 4,
  "comment": "A very compelling watch."
}
```

`rating` est un entier strict de 1 à 5; `comment` contient 1 à 5000 caractères
après suppression des espaces de bord; `user_id` contient 1 à 128 caractères.
Les champs supplémentaires sont refusés. Aucune adresse de courriel n’est
acceptée dans ce contrat.

Réponse `202 Accepted` :

```json
{"status": "accepted", "event_id": "a UUID"}
```

## Événement RabbitMQ

Le producteur publie un message persistant avec confirmation broker dans
l’exchange topic durable `dcic.events`, routing key
`interaction.review.created`, queue durable `interactions.reviews`.

```json
{
  "event_id": "a UUID",
  "event_type": "interaction.review.created",
  "occurred_at": "2026-11-17T17:00:00+00:00",
  "payload": {
    "event_id": "le même UUID",
    "movie_id": "573a13a4f29313caabd10527",
    "user_id": "usr_0937",
    "rating": 4,
    "comment": "A very compelling watch."
  }
}
```

Le consumer valide l’enveloppe et le payload, puis fait un upsert `$setOnInsert`
dans `reviews` avec `_id = event_id`. Le `movie_id` devient un BSON ObjectId; les
champs historiques `user_name` et `user_email` ne sont pas inventés. Le message
est acquitté uniquement après le succès de MongoDB. Un événement invalide est
rejeté sans requeue et envoyé à la dead-letter queue; une erreur MongoDB est
nackée avec requeue. Le même événement peut donc être rejoué sans créer de
doublon.
