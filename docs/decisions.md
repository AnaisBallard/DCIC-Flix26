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
