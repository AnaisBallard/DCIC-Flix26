# DCIC-Flix26

Plataforma universitaria para descubrir películas. El repositorio reúne una
interfaz React, una gateway HTTP, servicios FastAPI, MongoDB, RabbitMQ y
contenedores Docker. El catálogo, las fichas y las críticas están conectados;
el agente de limpieza registra las correcciones y el recomendador precalcula
películas similares y recomendaciones personalizadas cuando el catálogo está
listo.

Esta guía explica cómo ejecutar el proyecto, qué hace cada parte y cómo verificar
los resultados. La arquitectura y los contratos se describen con más detalle en
[docs/architecture.md](docs/architecture.md) y
[docs/contracts.md](docs/contracts.md). Las decisiones y los temas que el equipo
debe confirmar están en [docs/decisions.md](docs/decisions.md).

## Estado actual y límites

| Parte | Estado comprobable |
| --- | --- |
| Interfaz en español | Inicio, catálogo, fichas, críticas y estado de servicios |
| Gateway y catálogo | Búsqueda, filtro, paginación, detalle y críticas históricas |
| Publicación de críticas | Validación en la API y publicación persistente en RabbitMQ |
| Consumer | Validación, escritura idempotente en MongoDB y confirmación del mensaje |
| Carga del dataset | Importación de los archivos `.json` y `.json.gz` admitidos |
| Limpieza con LLM | Normalización determinista, revisión de ratings ambiguos con OpenAI y estado durable; requiere `OPENAI_API_KEY` |
| Recomendación TF-IDF | Índice persistente de vecinos; recomendaciones personalizadas desde las notas del perfil y películas similares |
| Auditoría de datos | `/audit` muestra estado, métricas e historial antes/después reales |
| Autenticación | No implementada. El selector crea perfiles locales para identificar críticas durante el desarrollo |

La topología de RabbitMQ incluye colas de limpieza y el evento durable de
catálogo listo. La disponibilidad del catálogo se publica solo después de
persistir la limpieza y su auditoría; el índice se habilita después de guardar
todos sus vecinos. La interfaz no inventa películas,
recomendaciones, críticas ni resultados de limpieza.

## Requisitos

- Docker Desktop o Docker Engine con Docker Compose v2.
- Node.js y npm con las versiones compatibles con `frontend/package.json` para
  desarrollar el frontend fuera de Docker.
- Python 3.13 para ejecutar los servicios o sus pruebas fuera de Docker.
- Acceso a Internet durante la primera instalación de imágenes o paquetes.

Las versiones JavaScript están fijadas en `frontend/package.json` y en
`frontend/package-lock.json`. Cada servicio Python fija sus dependencias en su
propio `requirements.txt`; sus imágenes base se fijan en los `Dockerfile`.
Antes de actualizar una dependencia, revisa su uso, compatibilidad, avisos de
seguridad y archivo de bloqueo.

La revisión de dependencias encontró cinco avisos npm de nivel alto en Vite,
`@vitejs/plugin-react` y dependencias transitivas. La corrección que propone el
registro cambia versiones mayores y, para Vite, incluso propone una versión
anterior a la fijada. No se aplicó una actualización forzada: investiga cada
aviso, confirma una combinación compatible con Node y Vite, y ejecuta el build
antes de aceptar una actualización.

## Empezar con Docker Compose

Abre PowerShell en la carpeta `DCIC-Flix26`. Crea `.env` una sola vez a partir
de los valores de desarrollo:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs -f frontend gateway
```

Cuando Vite esté listo, abre:

- Aplicación: <http://localhost:5173>
- Gateway pública: <http://localhost:8000>
- Estado agregado: <http://localhost:8000/api/health>
- Estado de negocio: <http://localhost:8000/api/status>

Para detener los contenedores sin borrar los datos, usa `Ctrl+C` si ejecutaste
Compose en primer plano o ejecuta:

```powershell
docker compose down
```

`docker compose down` conserva los volúmenes con los datos de MongoDB y
RabbitMQ. **No** uses `docker compose down -v` salvo que quieras eliminar
deliberadamente esos datos y puedas volver a inicializarlos.

La primera compilación descarga imágenes y dependencias, por lo que puede tardar.
El frontend espera a que la gateway esté sana; la gateway espera a los servicios
HTTP necesarios, y el catálogo, el consumer y el servicio de recomendaciones
esperan al cargador de datos. Consulta `docker compose ps` y los registros con
`docker compose logs <servicio>` cuando un contenedor no llegue al estado
esperado. El cargador y `rabbitmq-init` son tareas de inicialización y es normal
que terminen con código cero. El cleaning-agent espera a ambas tareas, pero la
interfaz no espera a que acabe la limpieza.

## Configuración y secretos

Compose lee la configuración local de `.env`; el archivo `.env.example` enumera
las variables, los valores de desarrollo y su finalidad:

- `MONGO_INITDB_ROOT_*`: cuenta administrativa usada solo para inicialización y
  carga.
- `MONGODB_DATABASE`: base que contiene el catálogo y las críticas.
- `MONGODB_CATALOG_*`, `MONGODB_RECOMMENDATION_*`, `MONGODB_CONSUMER_*` y
  `MONGODB_CLEANER_*`: cuentas separadas para limitar los permisos de cada
  servicio.
- `RABBITMQ_DEFAULT_*`: cuenta usada por los servicios productores y
  consumidores. `rabbitmq-init` sincroniza esa cuenta con el volumen persistente
  cuando se cambia la contraseña.
- `OPENAI_API_KEY` y `OPENAI_MODEL`: usados por el agente solo para inferir
  ratings ausentes o inválidos con comentarios útiles. Sin clave, la limpieza
  queda explícitamente en `failed` y no publica el evento de catálogo listo si
  encuentra casos que requieren inferencia.
- `CLEANER_VERSION`: versión de reglas; al cambiarla, el cargador reimporta el
  origen antes de limpiar de nuevo.
- `RECOMMENDER_VERSION`: versión del algoritmo/representación; cambiarla
  programa un índice nuevo después de que el catálogo esté listo.

Los valores de ejemplo son **solo para desarrollo local**; cámbialos antes de
compartir un entorno. No guardes `.env`, contraseñas ni claves en Git. La clave
del LLM debe permanecer en un servicio del backend: nunca la pongas en variables
`VITE_*`, porque esas variables se incorporan al código enviado al navegador.
MongoDB y RabbitMQ no publican puertos en el host; la aplicación web solo habla
con la gateway.

## Datos del catálogo

El directorio `dataset/` contiene las fuentes universitarias comprimidas. El
servicio `dataset-loader` puede importar archivos `.json` y `.json.gz` de la
raíz de ese directorio; el montaje es de solo lectura y no modifica los
originales. Los documentos deben tener `_id` para poder importarse de forma
idempotente. El cargador reconoce los formatos JSON documentados en
[docs/architecture.md](docs/architecture.md), crea o actualiza los registros
por identificador y evita volver a cargar un archivo cuyo hash no haya
cambiado.

Para explorar la estructura sin imprimir valores personales ni modificar
fuentes o MongoDB, ejecuta `py -3.13 dataset\profile_dataset.py`. Los recuentos,
las limitaciones y las reglas para interpretar sus indicadores están en
[docs/data-profile.md](docs/data-profile.md).

MongoDB ejecuta `dataset/mongo-init.sh` al inicializar un volumen nuevo. Como
los scripts de `/docker-entrypoint-initdb.d/` se ejecutan solamente en una
inicialización limpia, el cargador también reconcilia cuentas e índices en
arranques posteriores. Añadir o cambiar datos debe hacerse en los archivos
originales del dataset y verificarse en MongoDB; el proceso de importación no es
un proceso de limpieza semántica. El cargador persiste la huella y pone el
pipeline en `pending` cuando cambia el dataset o `CLEANER_VERSION`. El agente
registra cambios y métricas en MongoDB, reanuda mediante lease y solo emite
`catalog.cleaning.completed` después de terminar correctamente. Las críticas
nuevas se rechazan temporalmente hasta `ready`; las recomendaciones permanecen
`waiting`/`indexing` hasta que se complete el índice asociado a la huella y las
versiones activas. No ejecutes una
limpieza masiva sobre un volumen que contenga datos importantes sin copia de
seguridad y validación del equipo.

Comprobaciones rápidas en PowerShell (las contraseñas son las del `.env`
generado; adapta los comandos si las cambiaste):

```powershell
docker compose logs dataset-loader
docker compose exec mongodb mongosh --quiet --username flix --password flix_local_dev_only --authenticationDatabase admin --eval 'db.adminCommand({ ping: 1 })'
docker compose exec mongodb mongosh --quiet --username flix_catalog --password catalog_local_dev --authenticationDatabase peliculas-proyectos peliculas-proyectos --eval 'db.movies.countDocuments()'
```

## Aplicación web

La interfaz está escrita en React y TypeScript, se compila con Vite y aplica
Tailwind CSS junto con estilos propios del sistema visual. Todas las etiquetas
de usuario están en español. Las rutas implementadas son:

| Ruta | Uso |
| --- | --- |
| `/` | Portada editorial, selección del catálogo y recomendaciones del perfil |
| `/explorar` | Búsqueda por título o argumento, género, orden de la página visible y paginación |
| `/pelicula/{movie_id}` | Ficha, críticas, películas similares y formulario para enviar una crítica |
| `/audit` | Estado durable del pipeline, métricas e historial antes/después |

El selector de perfil guarda identificadores aleatorios en el almacenamiento
local del navegador; no valida una identidad y no sustituye un sistema de
autenticación. Las notas publicadas se transmiten al backend mediante la
gateway. La lista de géneros se obtiene de una muestra paginada del catálogo;
hasta que exista un endpoint de géneros, no se puede prometer que el selector
incluya todas las categorías del conjunto de datos.

El orden del catálogo se aplica a la página que ya devolvió el servidor, no a
los miles de registros del conjunto completo. Para ofrecer orden global hace
falta añadir y probar el parámetro de orden en la API.

Para desarrollar solo el frontend mientras los servicios están en Docker:

```powershell
Set-Location frontend
npm ci
npm run dev
```

El servidor de desarrollo utiliza `http://localhost:5173` y consulta la gateway
en `http://localhost:8000`. Si ejecutas la gateway en otro origen, configura la
URL permitida de CORS en el backend. Antes de integrar cambios, ejecuta:

```powershell
npm run build
```

`npm ci` restaura exactamente el árbol de dependencias del archivo de bloqueo;
no edites `package-lock.json` manualmente. Si cambias una dependencia directa,
usa npm y revisa ambos archivos del manifiesto.

## Servicios y API pública

La gateway es el único punto de entrada HTTP de la interfaz. Sus rutas públicas
actuales son:

| Método y ruta | Función |
| --- | --- |
| `GET /api/health` | Estado agregado de los servicios consultados |
| `GET /api/movies?q=&genre=&page=1&page_size=20` | Buscar, filtrar y paginar películas |
| `GET /api/movies/{movie_id}` | Consultar la ficha de una película |
| `GET /api/movies/{movie_id}/similar?limit=12` | Consultar películas similares precalculadas |
| `GET /api/movies/{movie_id}/reviews?page=1&page_size=20` | Leer críticas existentes |
| `GET /api/recommendations/{user_id}?limit=12` | Obtener recomendaciones personalizadas del perfil |
| `POST /api/interactions/reviews` | Publicar una nota y una crítica |

Los contratos de parámetros, validación, respuestas, evento y errores se
mantienen en un único documento: [docs/contracts.md](docs/contracts.md). Antes
de cambiar un contrato, actualiza productor, consumidor, frontend, pruebas y
documentación como una misma unidad de trabajo.

## Desarrollo de los servicios Python

Cada servicio mantiene sus dependencias en su propio directorio. Por ejemplo,
para ejecutar localmente la gateway en Windows:

```powershell
Set-Location gateway
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

La gateway local necesita que los servicios destino estén disponibles y que
sus URL estén configuradas para el entorno elegido. Docker Compose ya configura
los nombres DNS y las variables necesarios para la ejecución integrada; no
copies sin revisar las URL internas `http://<servicio>:8000` a una ejecución
fuera de Docker.

## Pruebas y verificaciones

Desde la raíz, crea un entorno de pruebas e instala las dependencias de
desarrollo de los servicios con pruebas:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r gateway\requirements-dev.txt -r catalog-service\requirements-dev.txt -r interaction-service\requirements-dev.txt -r consumer\requirements-dev.txt -r recommendation-service\requirements.txt
python -m pytest -q
```

Las pruebas unitarias comprueban validaciones, consultas del catálogo, datos
privados, publicación, idempotencia, acuse de recibo y confirmación de
persistencia de mensajes, además del manejo de errores.
`gateway/tests/test_service_flow.py` ejercita las aplicaciones HTTP en un flujo
conjunto con adaptadores simulados; no reemplaza una comprobación integrada
contra los contenedores reales.

Para comprobar la infraestructura activa:

```powershell
docker compose ps
docker compose exec rabbitmq rabbitmqctl list_exchanges name type
docker compose exec rabbitmq rabbitmqctl list_queues name durable messages
docker compose exec rabbitmq rabbitmqctl list_bindings source_name destination_name routing_key
```

Verifica la separación de redes: el frontend debe poder resolver la gateway,
pero no `mongodb` ni `rabbitmq`; MongoDB solo debe estar conectado a `data`, y
RabbitMQ solo a `messaging`. Prueba la resolución desde el contenedor:

```powershell
docker compose exec frontend node -e "require('dns').lookup('mongodb',e=>{if(!e){console.error('mongodb es accesible');process.exit(1)}console.log('OK: mongodb aislado')})"
docker compose exec frontend node -e "require('dns').lookup('rabbitmq',e=>{if(!e){console.error('rabbitmq es accesible');process.exit(1)}console.log('OK: rabbitmq aislado')})"
```

Consulta [docs/architecture.md](docs/architecture.md) para entender por qué
estas pruebas son importantes y cuáles son las redes esperadas.

## Estructura del repositorio

| Ruta | Responsabilidad |
| --- | --- |
| `frontend/` | Interfaz, componentes, páginas, cliente API y compilación web |
| `gateway/` | Validación de solicitudes públicas y comunicación con servicios internos |
| `catalog-service/` | Lectura, búsqueda y serialización del catálogo en MongoDB |
| `interaction-service/` | Validación y publicación de interacciones en RabbitMQ |
| `consumer/` | Validación de eventos y persistencia idempotente de críticas |
| `cleaning-agent/` | Esqueleto para limpieza asistida por LLM; lógica todavía pendiente |
| `recommendation-service/` | Índice TF-IDF/coseno persistente y API de recomendaciones |
| `dataset-loader/` | Importación del dataset, cuentas e índices |
| `dataset/` | Archivos fuente, inicialización de MongoDB y perfilador de solo lectura |
| `rabbitmq/` | Configuración del broker, topología y sincronización de credenciales |
| `docs/` | Arquitectura, contratos y decisiones explicadas |
| `docker-compose.yml` | Arranque, redes, dependencias, volúmenes y healthchecks |
| `.env.example` | Lista de variables de desarrollo; no contiene credenciales de producción |

## Flujo de trabajo para contribuir

1. Acordar y dibujar con el equipo el límite del servicio, sus dependencias y el
   contrato antes de pedir o implementar un cambio.
2. Crear una rama y mantener cada cambio pequeño y con un propósito claro.
3. Revisar `git status` y `git diff` antes de aceptar cambios; explicar cada
   archivo modificado y descartar aquello que no sea necesario.
4. Ejecutar las pruebas relevantes y comprobar sus resultados observables; un
   mensaje de éxito del asistente no sustituye la evidencia.
5. Pedir a otra persona del equipo que lea el diff, explique el comportamiento
   y pueda responder preguntas antes de integrar el cambio.
6. Actualizar contratos y documentación cuando cambie el comportamiento.
7. Registrar los commits pequeños con mensajes que expliquen el cambio.

La lista anterior es un proceso recomendado, no una garantía automática:
la aprobación por dos integrantes debe comprobarse en el flujo de revisión de
Git del equipo.

## Documentación

- [Arquitectura](docs/architecture.md): límites, redes, persistencia, secuencias
  de mensajes, estado real y riesgos.
- [Contratos](docs/contracts.md): rutas HTTP, validaciones, esquemas, eventos y
  errores entre productor y consumidor.
- [Perfil de datos](docs/data-profile.md): indicadores estructurales del
  dataset real, sin exponer texto o datos personales ni aplicar correcciones.
- [Decisiones](docs/decisions.md): motivos, límites, consecuencias y preguntas
  que requieren decisión humana.
