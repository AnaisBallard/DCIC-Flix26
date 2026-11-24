# Registro de decisiones de diseño

Este registro conserva el motivo y las consecuencias de las decisiones que ya
están reflejadas en el repositorio. No reemplaza el diseño del equipo ni una
revisión de dos personas: el equipo debe discutir cada punto, corregir lo que no
represente sus acuerdos y anotar quién valida cualquier decisión nueva.

## Decisiones adoptadas

### D-01 — La gateway es la única API del navegador

**Decisión:** el navegador usa HTTP hacia la gateway; no recibe URI, usuario ni
contraseña de MongoDB o RabbitMQ.

**Motivo:** concentra validación y errores públicos, y mantiene bases y broker
fuera de la superficie web. La red de Compose complementa este límite.

**Consecuencia:** una ruta nueva de frontend debe pasar por gateway y por el
servicio dueño de esa operación. Añadir una API implica acordar primero su
contrato y probar el reenvío.

**Límite:** no hay autenticación ni autorización. El `user_id` de perfil local
puede falsificarse; no se deben tratar las críticas como identidad verificada.

### D-02 — La lectura es HTTP síncrono; la crítica se procesa por eventos

**Decisión:** consultas de catálogo y detalle usan HTTP. La creación de una
crítica se confirma con `202` después de que RabbitMQ acepte el evento; el
consumer realiza la escritura en MongoDB.

**Motivo:** la lectura necesita una respuesta inmediata, mientras que desacoplar
publicación y persistencia de críticas permite reintentos y evita que
interaction-service escriba directamente en la base.

**Consecuencia:** `202 Accepted` no significa que la crítica ya aparezca en la
consulta histórica. El consumer debe validar otra vez, persistir antes del ack
y usar un identificador idempotente.

**Prueba requerida:** además del HTTP, verificar el evento, la entrada
persistida y el comportamiento al repetir el mismo identificador.

### D-03 — Conservar el dataset fuente y separar importación de limpieza

**Decisión:** los originales se montan como solo lectura y el cargador importa
sin reescribir los archivos. No se fabrican películas o críticas para suplir
datos.

**Motivo:** la fuente académica debe seguir siendo auditable. Un import exitoso
solo demuestra que los documentos se cargaron; no demuestra que sus valores
estén limpios.

**Consecuencia:** antes de automatizar correcciones, el equipo debe muestrear y
perfilar anomalías, acordar reglas, medir falsos positivos y conservar un
registro antes/después que permita repetir o revertir el proceso.

### D-04 — Conceder a cada servicio solo el acceso de datos que necesita

**Decisión:** MongoDB tiene cuentas separadas; catálogo y futuro recomendador
leen, consumer escribe y el cargador usa la cuenta administrativa de bootstrap.
RabbitMQ y MongoDB se alojan en redes internas distintas. El frontend no está
conectado a ellas.

**Motivo:** limitar el impacto de una dependencia o servicio comprometido y
hacer explícito quién posee cada escritura.

**Consecuencia:** al incorporar un servicio hay que decidir redes, permisos y
secretos como parte de su diseño, no conectarlo a todas las redes por comodidad.
Los healthchecks de proceso no prueban las autorizaciones de negocio.

**Límite:** `host_ingress` permite publicar HTTP y `llm_egress` permitirá salida
externa. Redes de Docker no sustituyen TLS, reglas de firewall ni autenticación.

### D-05 — Declarar la topología RabbitMQ como configuración versionada

**Decisión:** exchanges, colas, bindings y colas de mensajes fallidos se
declaran en `rabbitmq/definitions.json`; el inicio reconcilia credenciales de
volúmenes existentes.

**Motivo:** que una instalación limpia o persistente no dependa de crear colas
manualmente ni de que el volumen conserve la contraseña inicial.

**Consecuencia:** la topología es explícita y reproducible, pero una cola
declarada para votos o limpieza no implementa por sí misma su API o consumer.
Los cambios deben probarse también contra un broker que ya tenga volumen.

### D-06 — TF-IDF y similitud coseno son una propuesta, no un recomendador activo

**Propuesta para la siguiente etapa:** representar campos textuales seleccionados
de las películas con TF-IDF y comparar vectores mediante similitud coseno.

**Motivo para evaluarla:** es un método de contenido relativamente simple de
explicar: TF-IDF da más peso a términos distintivos y la similitud coseno mide
la orientación relativa de los vectores, no su longitud. Puede servir como
primera línea base sin afirmar que conoce preferencias personales.

**Lo que todavía debe decidir el equipo:** campos y limpieza textual, idioma,
tratamiento de etiquetas frecuentes, umbral/número de resultados, actualización
del corpus, evaluación offline y qué significa «personalizada» sin un historial
de usuario autenticado. La similitud por contenido no constituye por sí sola
una recomendación personalizada.

**Estado:** no hay entrenamiento, vectorización, endpoints de recomendación ni
resultados. No presentar esta propuesta como funcionalidad implementada ni
mostrar puntuaciones ficticias.

### D-07 — Mantener el futuro LLM en el backend

**Decisión de seguridad:** si se integra un proveedor LLM, el agente del backend
será el único responsable de llamarlo. La clave procede del entorno del
servidor y nunca se publica en una variable `VITE_*` ni en el bundle.

**Motivo:** todo valor entregado al navegador puede ser inspeccionado por sus
usuarios.

**Estado:** la variable y la imagen del servicio están preparadas, pero no hay
llamada LLM, instrucción, esquema de aprobación ni corrección automática en
producción. Antes de activar la función, hay que definir anonimización,
validación determinista, revisión humana y límites de coste.

### D-08 — Validar mensajes en ambos lados del límite asíncrono

**Decisión:** interaction-service valida antes de publicar y consumer vuelve a
validar al recibir. Los esquemas se parecen y pueden divergir si no se
mantienen juntos.

**Motivo:** RabbitMQ es una frontera independiente; el consumer puede recibir
eventos antiguos, repetidos o producidos por otro componente.

**Consecuencia:** conservar la validación independiente y añadir pruebas de
paridad para los campos compartidos. No extraer ambos modelos a una librería
común hasta decidir cómo se versiona, publica y despliega esa dependencia entre
servicios.

### D-09 — Las métricas de auditoría requieren una fuente real

**Decisión:** `/audit` enseña el healthcheck disponible y declara expresamente
que faltan datos sobre anomalías, cambios y actividad del LLM.

**Motivo:** una pantalla de cifras ficticias sería difícil de distinguir de un
resultado experimental real y no se podría defender en la evaluación.

**Consecuencia:** diseñar primero el contrato de un informe de limpieza y su
almacenamiento; solo entonces mostrar recuentos, valores antes/después y
trazabilidad.

### D-10 — Las dependencias runtime deben corresponder al código ejecutado

**Decisión:** declarar una librería cuando una ruta o tarea del servicio la use,
no solo porque figure en la arquitectura futura. Durante esta revisión se
retiraron `pydantic-settings`, que no se importaba en los servicios, y las
librerías previstas pero aún no utilizadas de los esqueletos de limpieza y
recomendación.

**Motivo:** instalar SDK de LLM o scikit-learn antes de implementar una función
aumenta tamaño, mantenimiento y superficie de actualización sin producir
capacidad funcional.

**Consecuencia:** al implementar esas etapas, se agrega y fija la dependencia
correspondiente en un cambio pequeño, se verifica que realmente se importe y
se compila la imagen del servicio. No se elimina la validación repetida en los
límites HTTP y de mensajería: es deliberada y debe probarse para evitar que los
contratos diverjan.

**Seguimiento:** npm todavía reporta cinco avisos de nivel alto para la versión
de Vite y su plugin fijadas. El arreglo sugerido implica cambios mayores y no
se aplicó automáticamente; requiere una revisión de compatibilidad separada.

## Decisiones que requieren aprobación del equipo

### Propuesta D-11 — Persistir el estado del pipeline del catálogo

**Fecha:** 2026-11-24

**Estado:** propuesta para discutir; todavía no está implementada ni ratificada.

**Contexto:** `dataset-loader` ya registra el SHA-256 de cada archivo en
`_dataset_imports` y omite la importación si no cambió. No existe todavía un
estado persistente de limpieza; el endpoint de salud de `cleaning-agent` solo
confirma que el proceso HTTP está activo. La topología RabbitMQ preparada para
`catalog.cleaning` tampoco significa que haya un consumidor de limpieza.

**Decisión propuesta:**

1. MongoDB será la fuente de verdad durable en una colección
   `_catalog_pipeline`, con un documento activo `_id: "catalog"` que conserva
   la huella y versión de procesamiento actuales. El volumen `mongo_data`
   conserva ese estado entre reinicios; el informe de auditoría conserva el
   historial de ejecuciones.
2. Después de importar los archivos, `dataset-loader` calculará una huella
   estable del conjunto: SHA-256 del listado ordenado de nombres de archivo y
   sus hashes SHA-256. La versión de las reglas de limpieza también formará
   parte de la versión de procesamiento; cambiar el dataset o las reglas
   requerirá una nueva ejecución deliberada.
3. El documento tendrá como mínimo `source_fingerprint`,
   `cleaner_version`, `cleaning_status`, `attempt`, `lease_until`,
   `ready_event_status`, `updated_at`, `started_at`, `completed_at` y un
   `error_code` seguro, sin secretos. Los estados de limpieza serán `pending`,
   `running`, `ready` y `failed`; `ready_event_status` será `pending` o `sent`.
4. Si la huella y la versión ya están en `ready`, el agente no vuelve a limpiar
   en un arranque posterior. Si no hay estado para esa versión, el dataset
   cambió o el estado anterior es `failed`, se programa una ejecución. Un
   estado `running` solo puede recuperarse cuando vence su lease; el agente
   reclama el trabajo mediante una actualización atómica en MongoDB y renueva
   el lease mientras trabaja para evitar ejecuciones concurrentes.
5. El agente marca `ready` únicamente después de persistir todas las
   correcciones y el informe de auditoría; en esa misma escritura deja
   `ready_event_status: "pending"`. Un fallo conserva `failed`, el motivo
   seguro y el contador de intentos; no se anuncia éxito. La limpieza debe ser
   idempotente para poder reintentar tras una interrupción.
6. Mientras `ready_event_status` sea `pending`, el agente publica con
   confirmación un evento persistente `catalog.cleaning.completed` en
   `dcic.events`, que incluye `event_id`, `source_fingerprint` y
   `cleaner_version`. Solo después de la confirmación lo cambia a `sent`. Si se
   interrumpe entre la publicación y esa escritura, vuelve a publicar el mismo
   `event_id`; el consumidor debe deduplicar por ese identificador. Así, la
   notificación no se pierde aunque MongoDB y RabbitMQ no compartan una
   transacción. El recomendador consume el evento para iniciar o reutilizar su
   índice y mantiene un estado de preparación separado: la salud del proceso
   no equivale a que el índice esté listo.
7. La gateway expondrá `GET /api/status`, separado del healthcheck de liveness.
   Responderá `200` con el estado de negocio, incluso si una etapa está en
   `failed`; los errores se expresan como códigos seguros, no como trazas.
   Forma propuesta:

   ```json
   {
     "catalog": {
       "cleaning_status": "running",
       "source_fingerprint": "sha256:…",
       "updated_at": "2026-11-24T19:00:00Z",
       "error_code": null
     },
     "recommendations": { "status": "waiting" },
     "capabilities": {
       "browse": true,
       "reviews": false,
       "recommendations": false
     }
   }
   ```

   `cleaning_status` admite `pending`, `running`, `ready` y `failed`;
   recomendación admite `waiting`, `indexing`, `ready` y `failed`. La lectura y
   exploración siguen disponibles en todos los estados. `reviews` se habilita
   cuando la limpieza está `ready`; `recommendations` requiere limpieza e
   índice `ready`. Compose no debe retrasar la disponibilidad de la interfaz
   hasta que termine la limpieza.

**Arranque en frío:** la importación deja el estado en `pending`; el agente lo
reclama, lo cambia a `running`, sanea, guarda el informe, pasa a `ready` y
notifica al recomendador.

**Arranque persistente:** si coinciden huella y versión y el estado es `ready`,
se omite la limpieza. Si el contenedor se interrumpió durante `running`, se
espera el vencimiento del lease y se reintenta de forma idempotente. Una nueva
huella o versión invalida el resultado anterior y vuelve a `pending`.

**Consecuencias y puntos que requieren validación:** habría que dar al agente
permisos MongoDB mínimos para leer/escribir su estado y los datos de catálogo,
hacer que espere a que `dataset-loader` termine y declarar en RabbitMQ la cola
durable que recibirá `catalog.cleaning.completed`. La configuración actual no
implementa esos cambios. Además, el cargador actual hace upsert de documentos,
pero no elimina los documentos que ya no aparecen en un archivo fuente; ese
caso debe resolverse antes de tratar la eliminación o sustitución de archivos
como una reconciliación completa.

**Alternativas consideradas:** usar solo healthchecks de Compose (no persisten
el resultado de limpieza); usar solo eventos RabbitMQ (un evento perdido no es
una fuente durable de estado); volver a limpiar en cada arranque (costoso y
contrario al requisito de warm start). Se propone MongoDB como estado canónico
y RabbitMQ como notificación entre etapas.

**Aprobación:** pendiente de discusión y validación del equipo. No registrar
nombres ni aprobación hasta que las personas responsables confirmen la
decisión.

Estas preguntas no se consideran resueltas por el código inicial:

1. ¿Qué subconjunto de servicios y rutas exige la rúbrica y quién es dueño de
   cada contrato?
2. ¿Cómo se autenticará el usuario antes de aceptar críticas reales? ¿Qué
   identificador sustituirá al perfil local?
3. ¿Qué roles y permisos MongoDB hacen falta cuando se implemente el
   recomendador o la limpieza?
4. ¿Qué anomalías existen realmente en `movies.json.gz` y `reviews.json.gz`, y
   qué reglas aprobadas pueden corregirlas sin borrar información válida?
5. ¿Qué experimento demostraría que TF-IDF más coseno es mejor que una línea
   base sencilla? ¿Cómo se evita recomendar solo películas con sinopsis
   completas?
6. ¿Qué versión del evento RabbitMQ se publicará y cómo se migrará un consumer
   sin perder mensajes?
7. ¿Qué evidencia integrada se exigirá para dar por terminados arranque,
   aislamiento, carga, publicación, persistencia y reintentos?
8. ¿Debe exponerse un endpoint de géneros distintos y orden global de
   resultados para que los filtros y el selector de orden cubran todo el
   catálogo y no solo una muestra o página?
9. ¿Qué casos de prueba y criterios de aceptación deben añadirse a dataset
   loader, cleaning-agent y recommendation-service al dejar de ser esqueletos?

## Registro de cambios futuros

Para una decisión que afecte límites, datos o contratos, añade una entrada con:

- identificador y fecha;
- integrantes que la proponen y la revisan;
- contexto y alternativas consideradas;
- decisión y motivo entendible sin leer código;
- consecuencias, riesgos y evidencia de verificación.

No escribas nombres o aprobaciones hasta que las personas correspondientes
hayan revisado y confirmado la decisión.
