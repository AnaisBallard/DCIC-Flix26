# Arquitectura y operación

Este documento describe lo que la configuración y el código actuales hacen,
separándolo de las funciones previstas. Antes de cambiar límites o dependencias,
el equipo debe revisar esta propuesta y confirmar las decisiones en
[decisions.md](decisions.md).

## 1. Vista general

```mermaid
flowchart LR
    Browser[Navegador] -->|HTTP :5173| Frontend[React + Vite]
    Frontend -->|HTTP :8000, CORS| Gateway[Gateway FastAPI]
    Gateway -->|HTTP| Catalog[Servicio de catálogo]
    Gateway -->|HTTP| Interaction[Servicio de interacción]
    Gateway -.->|health; recomendaciones aún no implementadas| Recommendation[Servicio de recomendaciones]
    Gateway -.->|health| Consumer[Consumer]
    Catalog -->|lectura| Mongo[(MongoDB)]
    Recommendation -.->|acceso previsto| Mongo
    Interaction -->|evento persistente| Broker[RabbitMQ]
    Broker -->|cola de críticas| Consumer
    Consumer -->|lectura/escritura| Mongo
    Loader[Cargador del dataset] -->|upsert e índices| Mongo
    Broker -.->|cola preparada| Cleaning[Agente de limpieza]
    Cleaning -.->|integración futura| LLM[Proveedor LLM]
```

Las líneas discontinuas indican una relación futura o una comprobación de
estado, no una funcionalidad de negocio terminada. Hoy, el catálogo puede
consultarse y las críticas pueden atravesar la gateway, RabbitMQ, el consumer y
MongoDB. El servicio de recomendaciones y el agente de limpieza son esqueletos
de aplicación: no calculan recomendaciones ni modifican datos.

## 2. Servicios y propiedad de los datos

| Servicio | Responsabilidad actual | Datos/dependencias |
| --- | --- | --- |
| `frontend` | Interfaz española; envía solicitudes HTTP a la gateway | Solo gateway; perfil local sin autenticación |
| `gateway` | Valida las solicitudes públicas, reenvía HTTP y agrega healthchecks | Servicios HTTP internos; no se conecta a MongoDB ni RabbitMQ |
| `catalog-service` | Busca, filtra, pagina y serializa películas y críticas | Cuenta de MongoDB de solo lectura |
| `interaction-service` | Valida y publica críticas como eventos confirmados | RabbitMQ; no escribe en MongoDB |
| `consumer` | Valida mensajes de crítica y los persiste de manera idempotente | MongoDB de lectura/escritura y RabbitMQ |
| `dataset-loader` | Carga archivos admitidos y reconcilia cuentas e índices | Cuenta administrativa de MongoDB; trabajo de inicialización |
| `cleaning-agent` | Endpoint de salud y configuración de contenedor | La lógica LLM/limpieza no está implementada |
| `recommendation-service` | Endpoint de salud y configuración de contenedor | TF-IDF, similitud coseno y acceso de lectura aún no implementados |
| `mongodb` | Almacén persistente del catálogo y las críticas | Solo red `data` |
| `rabbitmq` | Broker, exchange, colas, bindings y colas de mensajes fallidos | Solo red `messaging` |

Cada servicio HTTP tiene un `Dockerfile` y un `requirements.txt` propios. Las
dependencias runtime deben limitarse al código que realmente ejecuta ese
servicio; añade las librerías del LLM y del modelo cuando se implementen y
prueben sus funciones, no solo porque estén previstas.

## 3. Redes y límites de confianza

Compose conecta los contenedores a redes distintas para limitar qué nombres
puede resolver cada servicio:

| Red Compose | Miembros | Finalidad |
| --- | --- | --- |
| `frontend_gateway` (interna) | `frontend`, `gateway` | Comunicación HTTP entre navegador del contenedor y gateway |
| `host_ingress` (no interna) | `frontend`, `gateway` | Publicar los puertos HTTP 5173 y 8000 en el host |
| `backend` (interna) | `gateway`, servicios HTTP internos | Reenvío HTTP entre servicios |
| `data` (interna) | `mongodb`, `dataset-loader`, catálogo, recomendaciones, consumer | Acceso a MongoDB |
| `messaging` (interna) | `rabbitmq`, `rabbitmq-init`, interacción, consumer, cleaning-agent | Acceso a RabbitMQ |
| `llm_egress` (no interna) | `cleaning-agent` | Salida prevista para una futura API LLM |

MongoDB no pertenece a `frontend_gateway`, `host_ingress` ni `backend`; RabbitMQ
tampoco. El frontend comparte con la gateway el segmento de entrada del host,
pero no una red con los servicios de datos. Por eso el navegador usa el puerto
HTTP de la gateway y no el DNS ni el puerto de MongoDB o RabbitMQ.

**Límite importante:** el aislamiento de redes Docker reduce la conectividad,
pero no es autenticación, cifrado TLS ni una política de firewall del host. La
red `host_ingress` y `llm_egress` no son `internal`; el frontend puede necesitar
esa conexión de salida para publicar el servidor de desarrollo. Revisa las
redes y los puertos efectivos con `docker inspect` y `Test-NetConnection`; no
infieras la seguridad únicamente de los nombres en Compose.

Solo se publican los puertos de la gateway y de Vite en el host. Los puertos de
MongoDB y RabbitMQ no tienen asignación `ports:`. El panel de administración de
RabbitMQ tampoco se publica.

## 4. Flujo síncrono: lectura del catálogo

1. El navegador consulta una ruta `/api/...` en el puerto de la gateway.
2. La gateway valida los parámetros y envía la solicitud al servicio adecuado.
3. El catálogo consulta MongoDB con su cuenta de solo lectura, transforma los
   valores no serializables y devuelve la respuesta.
4. La gateway retransmite el resultado sin abrir una conexión de base de datos
   desde el frontend.

La búsqueda textual examina `title`, `plot` y `fullplot`; el filtro por género
compara una entrada del arreglo `genres`. Los resultados usan paginación con
un máximo de 100 elementos por página. Los detalles del contrato público están
en [contracts.md](contracts.md).

La interfaz actual obtiene las opciones de género a partir de una muestra
paginada, pues no existe una ruta de géneros distintos. Por ello, no se debe
presentar esa lista como exhaustiva. El selector de orden actual reordena los
elementos de la página visible en el navegador; el servidor todavía no ordena
globalmente por año o nota. Una implementación global requiere ampliar y probar
el contrato de catálogo.

## 5. Flujo asíncrono: creación de una crítica

1. La interfaz envía `movie_id`, `user_id`, `rating` y `comment` a la gateway.
2. Gateway e interaction-service validan los límites del contrato. Repetir
   validaciones en ambos límites es deliberado: ambos servicios deben poder
   rechazar una solicitud inválida aunque se llamen por separado.
3. Interaction-service publica un mensaje persistente en `dcic.events` con la
   clave `interaction.review.created` y espera la confirmación del broker.
4. RabbitMQ enruta el evento a `interactions.reviews`.
5. El consumer valida de nuevo el evento y hace un upsert en `reviews` con
   `_id = event_id`.
6. El consumer confirma el mensaje solo después de persistir correctamente.
   MongoDB inaccesible produce reencolado; un mensaje inválido se rechaza hacia
   la cola de mensajes fallidos.

La definición del evento se repite en productor y consumidor para que cada
límite pueda validar mensajes de forma independiente. La evolución debe
mantener compatibilidad y sincronizar las pruebas y el contrato, no eliminar
esa validación independiente.

## 6. MongoDB y carga del dataset

### Inicialización

`mongodb` usa la imagen oficial fijada en `docker-compose.yml`, un volumen
persistente y `dataset/mongo-init.sh` montado en
`/docker-entrypoint-initdb.d/`. Mongo ejecuta ese script al crear por primera
vez un volumen vacío. El script crea:

- una cuenta de lectura para el catálogo;
- una cuenta de lectura para el futuro recomendador;
- una cuenta de lectura y escritura para el consumer;
- índices de catálogo y críticas.

Como el punto de entrada de Mongo solo ejecuta esos scripts en la primera
inicialización, `dataset-loader` vuelve a reconciliar cuentas e índices en los
arranques posteriores. La cuenta root queda reservada al bootstrap y la carga;
las contraseñas salen de variables de entorno.

### Formatos e idempotencia

El cargador procesa archivos `.json` y `.json.gz` en la raíz de `dataset/`,
incluyendo JSON Lines, arreglos JSON y Extended JSON de MongoDB según su
implementación actual. Los documentos necesitan `_id`. El archivo de origen se
monta como solo lectura y el cargador compara un hash SHA-256 antes de volver a
procesarlo; aplica upserts por `_id`.

Los archivos suministrados en esta copia son `movies.json.gz` y
`reviews.json.gz`. La carga inicial conocida contiene aproximadamente 19 842
películas y 61 488 críticas; verifica los recuentos en la instancia antes de
usar cifras en una presentación, porque la fuente puede cambiar.

La carga preserva el contenido de origen y **no** equivale a detectar ni
corregir anomalías. Antes de crear un agente de limpieza, el equipo debe perfilar
el dataset real, acordar reglas y registrar los cambios antes/después. El perfil
estructural reproducible está en [data-profile.md](data-profile.md). No
interpretes una importación correcta como una confirmación de calidad.

## 7. RabbitMQ y topología

RabbitMQ usa una imagen oficial fijada, volumen persistente, configuración en
`rabbitmq/rabbitmq.conf` y definiciones declarativas en
`rabbitmq/definitions.json`. Estas últimas crean automáticamente:

- exchange topic durable `dcic.events`;
- exchange durable `dcic.events.dlx` para mensajes fallidos;
- colas `interactions.reviews`, `interactions.votes` y `catalog.cleaning`;
- una cola durable de mensajes fallidos para cada una de esas colas;
- bindings para críticas, votos y solicitudes de limpieza.

La topología preparada para votos y limpieza no implica que sus productores o
consumidores estén implementados. Cuando el volumen conserva credenciales
anteriores, `rabbitmq-init` espera el healthcheck del broker y reconcilia
usuario y permisos antes de iniciar los servicios dependientes. Utiliza el
volumen de datos existente en modo de solo lectura y no reinicializa el broker.

## 8. Healthchecks, dependencias y reinicio

Los servicios HTTP ofrecen `/health`; los healthchecks de Compose comprueban que
el proceso web responda. La gateway consulta el estado de los servicios que
conoce mediante `/api/health`. Un servicio puede responder a `/health` sin tener
implementada toda la lógica de negocio: un estado `ok` significa que el proceso
está disponible, no que la limpieza o las recomendaciones ya funcionen.

`depends_on` con condiciones de salud o de finalización fija el orden inicial;
no sustituye reintentos, recuperación ante fallos ni observabilidad en
producción. La mayoría de servicios persiste con `unless-stopped`; el cargador
y `rabbitmq-init` son tareas puntuales.

## 9. Seguridad, secretos y límites conocidos

- La gateway es el único API que utiliza el frontend. Nunca añadas una
  conexión MongoDB, RabbitMQ o clave del LLM al bundle del navegador.
- Los perfiles del frontend solo generan un identificador local. No hay
  autenticación, autorización, sesiones verificadas ni protección contra
  suplantación; este sistema no es apto para publicar críticas en producción.
- Las credenciales de `.env.example` no son secretos de producción.
- El consumidor de mensajes es dueño de la escritura de críticas; el servicio
  de interacción no obtiene permisos de escritura en MongoDB.
- La red no sustituye TLS, rotación de claves, límites de tasa ni un análisis
  de las imágenes y dependencias.
- El endpoint de salud de recomendaciones no demuestra que exista un motor.
  Los reportes de auditoría tampoco existen hasta que haya contrato y persistencia
  para esas métricas.

## 10. Cómo comprobar y desarrollar cambios

### Comprobaciones de la pila

```powershell
docker compose config -q
docker compose ps
docker compose logs --tail 100 gateway catalog-service interaction-service consumer
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod "http://localhost:8000/api/movies?page_size=1"
```

Comprueba también en Docker que el frontend no resuelve `mongodb` ni
`rabbitmq`, como se muestra en el README. Para comprobar un cambio de flujo,
ejercita la API y confirma que el evento termina en la base de datos; una
respuesta HTTP de éxito por sí sola no prueba persistencia.

### Pruebas automatizadas

Desde la raíz, con Python 3.13:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r gateway\requirements-dev.txt -r catalog-service\requirements-dev.txt -r interaction-service\requirements-dev.txt -r consumer\requirements-dev.txt
python -m pytest -q
```

Para el frontend, desde `frontend/`, ejecuta `npm ci` y `npm run build`.
Describe en el cambio qué criterio mide cada prueba y qué escenario real todavía
no cubre.

### Cambios de arquitectura o contrato

Antes de cambiar un límite, prepara con el equipo un diagrama o secuencia y el
contrato afectado. Actualiza el productor, el consumidor, las pruebas, el
frontend si corresponde, el Compose y esta documentación en el mismo cambio
lógico. Comprueba el diff y pide a otra persona que lo explique antes de
integrarlo; Git por sí solo no garantiza esa revisión.
