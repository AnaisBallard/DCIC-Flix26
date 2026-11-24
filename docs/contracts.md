# Contratos HTTP y de eventos

Este documento describe los contratos que utilizan hoy el frontend, la
gateway, los servicios y RabbitMQ. Los nombres de campos que aparecen en los
ejemplos son parte del contrato. Antes de cambiarlos, actualiza productor,
consumidor, cliente, pruebas y documentación en el mismo cambio.

## Convenciones

- Los identificadores de película son los ObjectId de MongoDB serializados
  como 24 caracteres hexadecimales.
- Las fechas que se devuelven por HTTP se serializan como texto ISO 8601 cuando
  el documento de origen contiene un valor de fecha.
- Los errores HTTP siguen el formato de FastAPI `{"detail": "..."}`.
- Los datos que se muestran en este documento son ejemplos de la forma del
  contrato, no películas ni críticas que deban insertarse como datos ficticios.
- No existe autenticación de usuario. `user_id` identifica el perfil local del
  navegador, no una identidad verificada.

## API pública de la gateway

El navegador usa la gateway en `http://localhost:8000`; no solicita directamente
al catálogo, RabbitMQ ni MongoDB. La gateway permite, por defecto, el origen
`http://localhost:5173`, los métodos `GET` y `POST`, y los encabezados
`Content-Type` y `Accept`.

| Método y ruta | Función | Destino |
| --- | --- | --- |
| `GET /health` | Salud del proceso gateway para Docker Compose | Gateway |
| `GET /api/health` | Estado agregado de servicios HTTP | Servicios de salud |
| `GET /api/movies` | Buscar, filtrar y paginar películas | Catálogo |
| `GET /api/movies/{movie_id}` | Obtener la ficha de una película | Catálogo |
| `GET /api/movies/{movie_id}/reviews` | Leer críticas existentes | Catálogo |
| `POST /api/interactions/reviews` | Publicar una nueva crítica | Interaction-service |

`GET /health` comprueba la disponibilidad local de la gateway. No garantiza por
sí solo que el catálogo u otros servicios respondan. `/api/health` comprueba
catalog, interaction, recommendation y consumer; devuelve un estado no saludable
si un servicio necesario no está disponible. Que el servicio
`recommendation` responda `ok` solo confirma que su proceso está activo: todavía
no ofrece recomendaciones.

Al llamar a un servicio interno, la gateway conserva la respuesta HTTP del
servicio. Un fallo de conexión upstream se traduce a `503 Service Unavailable`;
un timeout, a `504 Gateway Timeout`.

## Listar y buscar películas

### Solicitud

```http
GET /api/movies?q=iron&genre=Crime&page=1&page_size=20
```

Todos los parámetros son opcionales:

| Parámetro | Restricción | Comportamiento |
| --- | --- | --- |
| `q` | 1–120 caracteres si se envía | Busca sin distinguir mayúsculas en `title`, `plot` y `fullplot` |
| `genre` | 1–60 caracteres si se envía | Coincide con un valor completo del arreglo `genres`, sin distinguir mayúsculas |
| `page` | Entero mayor o igual a 1; predeterminado `1` | Página solicitada |
| `page_size` | Entero de 1 a 100; predeterminado `20` | Máximo de elementos por página |

Un filtro ausente debe omitirse, no enviarse como cadena vacía. Una búsqueda
compuesta por espacios no es válida.

### Respuesta `200 OK`

```json
{
  "items": [
    {
      "_id": "573a13a4f29313caabd10527",
      "title": "Título incluido en el dataset",
      "year": 2000,
      "genres": ["Drama"]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

`items` contiene los documentos reales que coinciden con la consulta y puede
estar vacío. No se crean películas de ejemplo. `total` cuenta los documentos
que coinciden antes de aplicar el desplazamiento y el límite.

## Obtener una película

```http
GET /api/movies/573a13a4f29313caabd10527
```

Con un ObjectId válido y existente, la respuesta `200 OK` contiene los campos
disponibles del documento del dataset. `_id` se representa como cadena; las
fechas y otros tipos BSON no JSON se convierten a representaciones serializables.
El catálogo no inventa campos que falten en la fuente.

- Un ObjectId con formato incorrecto produce un error de validación.
- Un ObjectId válido sin película correspondiente produce `404 Not Found`.

## Leer críticas

```http
GET /api/movies/573a13a4f29313caabd10527/reviews?page=1&page_size=20
```

`page` y `page_size` usan los mismos límites que en la lista de películas.
La respuesta tiene `items`, `total`, `page` y `page_size`. Cada crítica puede
contener su identificador, `movie_id`, `user_id`, `rating`, `comment` y `date`
si existen.

El catálogo no incluye `user_email` ni `user_name` en esta respuesta. Si la
película no existe, la API responde `404 Not Found`. Una página válida sin
críticas devuelve `items: []`, no datos ficticios.

## Crear una crítica

### Solicitud

```http
POST /api/interactions/reviews
Content-Type: application/json
```

```json
{
  "movie_id": "573a13a4f29313caabd10527",
  "user_id": "usr_identificador_local",
  "rating": 4,
  "comment": "Una historia que me sorprendió."
}
```

| Campo | Tipo | Restricción |
| --- | --- | --- |
| `movie_id` | cadena | ObjectId MongoDB de 24 caracteres hexadecimales |
| `user_id` | cadena | 1–128 caracteres; no es una identidad autenticada |
| `rating` | entero | Valor estricto entre 1 y 5 |
| `comment` | cadena | 1–5000 caracteres después de quitar espacios en los extremos |

Los campos adicionales se rechazan. El servicio interaction no escribe en
MongoDB: publica un evento persistente y espera la confirmación del broker.

### Respuesta `202 Accepted`

```json
{
  "status": "accepted",
  "event_id": "uuid-generado-por-el-servicio"
}
```

`202` confirma la aceptación/publicación en RabbitMQ, no que la crítica ya esté
visible en MongoDB. La persistencia ocurre de forma asíncrona en el consumer.
Si el broker no está disponible, la API devuelve un error en lugar de una
respuesta de éxito ficticia.

## Evento de RabbitMQ: crítica creada

El productor publica un mensaje persistente con confirmación en:

- Exchange: `dcic.events` (tipo `topic`, durable).
- Routing key: `interaction.review.created`.
- Cola: `interactions.reviews` (durable).
- Exchange de mensajes fallidos: `dcic.events.dlx`.
- Cola de mensajes fallidos: `dead-letter.interactions.reviews`.

Ejemplo de envoltorio y payload:

```json
{
  "event_id": "uuid-generado-por-el-servicio",
  "event_type": "interaction.review.created",
  "occurred_at": "2026-11-17T17:00:00+00:00",
  "payload": {
    "event_id": "uuid-generado-por-el-servicio",
    "movie_id": "573a13a4f29313caabd10527",
    "user_id": "usr_identificador_local",
    "rating": 4,
    "comment": "Una historia que me sorprendió."
  }
}
```

El identificador en el payload debe ser el mismo que el de la envoltura. El
consumer valida de forma independiente el mensaje recibido; su esquema no debe
confiar en que todos los productores ejecuten las mismas validaciones.

## Persistencia, reintentos y duplicados

Al aceptar el evento, el consumer:

1. valida la estructura, tipo de evento y valores del payload;
2. convierte `movie_id` al tipo ObjectId de MongoDB;
3. hace un upsert con `$setOnInsert` y `_id = event_id`;
4. confirma el mensaje RabbitMQ solo después del éxito de MongoDB.

Si el mismo evento se procesa otra vez, `_id = event_id` evita insertar una
segunda crítica. Si MongoDB falla, el mensaje se rechaza con reencolado. Si el
contenido no pasa la validación, se rechaza sin reencolado para que RabbitMQ lo
envíe a la cola de mensajes fallidos. Los campos históricos `user_name` y
`user_email` no se generan ni se aceptan desde la interfaz.

## Topología preparada y contratos aún pendientes

`rabbitmq/definitions.json` también declara:

| Routing key | Cola | Estado |
| --- | --- | --- |
| `interaction.vote.created` | `interactions.votes` | Topología declarada; API, esquema y consumidor de votos pendientes |
| `catalog.cleaning.requested` | `catalog.cleaning` | Topología declarada; esquema y proceso de limpieza pendientes |

No publiques en esas rutas hasta documentar y probar el contrato completo. La
existencia de una cola no implica que haya un consumidor activo, reintentos
correctos o cambios aplicados al catálogo.

## Códigos de error esperados

| Estado | Significado |
| --- | --- |
| `202` | Crítica aceptada para procesamiento asíncrono |
| `404` | No existe la película solicitada |
| `422` | Parámetros o contenido de solicitud inválidos |
| `503` | Servicio de destino o broker no disponible |
| `504` | Timeout al esperar un servicio interno |

Los errores siguen el formato `{"detail": "..."}` cuando los produce FastAPI.
No registres contraseñas, claves de LLM, direcciones de correo ni comentarios
completos de usuarios en logs de producción.
