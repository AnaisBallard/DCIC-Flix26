# Perfil estructural del dataset

## Alcance

Este perfil registra una inspección estructural inicial de los archivos fuente
disponibles durante la revisión:

- `dataset/movies.json.gz`
- `dataset/reviews.json.gz`

La inspección cuenta campos, tipos y relaciones sin mostrar títulos, textos de
críticas, correos, identificadores ni otros valores de registros. **No modifica
los archivos, no cambia MongoDB y no ejecuta limpieza.**

Para repetirla desde la raíz con Python 3:

```powershell
py -3.13 dataset\profile_dataset.py
```

El programa usa solo la biblioteca estándar de Python. Su salida contiene
estadísticas agregadas; evita copiar registros fuente a informes públicos.

## Resultados observados

### Películas

| Indicador | Recuento |
| --- | ---: |
| Documentos examinados | 19 842 |
| `_id` presente | 19 842 |
| `title` ausente, nulo, vacío o no textual | 0 |
| Títulos con espacios al inicio o al final | 417 |
| Grupos con más de un título tras `strip` y `casefold` | 1 349 |
| `year` numérico | 19 408 |
| `year` textual | 321 |
| `year` nulo | 113 |
| `genres` ausente | 43 |
| `genres` representado como texto en vez de arreglo | 378 |
| `genres` representado como arreglo | 19 421 |
| `fullplot` ausente | 297 |
| `cast` ausente | 204 |
| `directors` ausente | 238 |

Un mismo título normalizado **no** significa necesariamente un duplicado:
puede corresponder a remakes, versiones u obras distintas. Un género textual
puede representar un único valor legítimo, pero hay que compararlo con el
contrato y las consultas del catálogo antes de transformar el tipo.
La ausencia de un resumen, reparto o dirección también puede ser una omisión
aceptable de la fuente y no debe rellenarse inventando contenido.

### Críticas

| Indicador | Recuento |
| --- | ---: |
| Documentos examinados | 61 488 |
| `rating` numérico | 59 687 |
| `rating` numérico fuera de 1–5 | 1 211 |
| `rating` nulo | 928 |
| `rating` textual | 873 |
| `date` almacenado como objeto BSON/JSON | 60 578 |
| `date` textual | 733 |
| `date` numérico | 177 |
| Referencias a una película no encontrada en el archivo de películas | 350 |
| Documentos que contienen el campo privado `user_email` | 61 488 |

Las 1 211 valoraciones fuera de 1–5 contradicen el rango de la **nueva API**,
pero no demuestran por sí solas que el dato histórico sea incorrecto: puede
haber otra escala o semántica. Los valores textuales también requieren
clasificación antes de decidir una conversión. Las referencias sin película
pueden resultar de que los dos archivos representen subconjuntos distintos.
Verifica el alcance y las reglas académicas antes de corregir o descartar esos
registros.

El campo `user_email` está presente en todas las críticas históricas. El
catálogo debe seguir excluyéndolo de las respuestas públicas y los logs; no se
incluyó ningún correo en el perfil.

## Método y limitaciones

`dataset/profile_dataset.py` lee las dos fuentes comprimidas, cuenta ausencia,
nulos y tipos de campos seleccionados, compara las referencias
`reviews.movie_id` con los `_id` de películas y normaliza títulos únicamente
para contar grupos coincidentes. El perfil no valida todas las reglas de
negocio, fechas, URL, codificación, duplicados por contenido ni semántica de
cada escala de puntuación.

Los recuentos describen una instantánea del dataset, no una política de
corrección. Antes de implementar una limpieza:

1. acuerda con el equipo qué especificación de origen tiene prioridad;
2. examina localmente muestras representativas, incluyendo valores de cada
   tipo y casos límite, manteniendo privados los campos personales;
3. define reglas deterministas, excepciones y criterios para detenerse;
4. compara el conjunto antes y después y valida las consecuencias en búsquedas,
   páginas de detalle y críticas;
5. conserva una ruta de auditoría y de reversión.

Hasta completar esas verificaciones, la importación del dataset debe
considerarse una carga de datos originales, no un proceso de limpieza.
