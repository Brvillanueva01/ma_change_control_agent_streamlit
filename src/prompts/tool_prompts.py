
STRUCTURED_SPECS_PROC_PROMPT_TOOL_DESC = """

"""

EXTRACT_LEGACY_SECTIONS_PROMPT_TOOL_DESC = """
Extrae información clave de métodos analíticos legados (PDF o DOCX) y prepara una lista de tareas (pruebas) para el procesamiento en paralelo.

## Cuándo usar
- Cuando se pide "extraer", "procesar", "analizar" o "leer" el método analítico en su versión legada.
- Esta es la **primera herramienta** que se debe llamar en el flujo de trabajo de migración.
- El agente **debe** determinar el tipo de documento del que se trata para poder seleccionar el `extract_model` correcto.

## Buenas Prácticas
- **Selección del Modelo:** La decisión más importante es elegir el `extract_model` correcto. El agente debe inferir esto basándose en el contexto.
- **Manejo de Archivos:** La herramienta maneja automáticamente la conversión de DOCX a PDF y la división (chunking). El agente no necesita preocuparse por esto.
- **Llamada Única:** No llames a esta herramienta varias veces para el mismo archivo.

## Parámetros
- `dir_legacy_method (str)`: La ruta completa (path) al archivo DOCX o PDF que se va a procesar.
- `extract_model (Literal)`: El tipo de modelo de extracción a utilizar. Debe ser **exactamente** uno de los siguientes valores:
    - `"legacy_method"`: Para métodos analíticos de legado.
    - `"change_control"`: Para documentos de control de cambios.
    - `"annex_documents"`: Para documentos de anexos.

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** La herramienta devuelve un `ToolMessage` que contiene un **resumen** en lenguaje natural del contenido extraído. El agente debe usar este resumen para informar al usuario que la tarea se completó.
- **Actualización del Estado (State):** Esta herramienta tiene un **doble efecto** en el estado `state['files']`:
    1.  **JSON Completo:** Guarda la extracción completa (el objeto Pydantic) en su ruta principal (ej. `legacy_method.json`). El agente **no** debe leer este archivo gigante directamente en su contexto.
    2.  **Lista de Tareas (Fan-Out):** Guarda un **nuevo** archivo en `/legacy/summary_and_tests.json`. Este archivo SÍ es pequeño y contiene la `lista_pruebas` (una lista de strings con los nombres de todas las pruebas a procesar).

## Siguiente Paso Esperado
- Después de ejecutar esta herramienta, el **siguiente paso lógico** del agente es:
    1.  Llamar a `read_file(path='/legacy/summary_and_tests.json')` para obtener la `lista_pruebas`.
    2.  Usar esa lista para lanzar el 'fan-out' (llamadas en paralelo) a la herramienta `structure_specs_procs`, una llamada por cada prueba en la lista.
"""

SUMMARIZE_EXTRACTED_LEGACY_METHOD = """
Estas creando un resumen del metodo analitico extraido. Tu objetivo es ayudar a un agente a saber que informacion se ha extraido, NO debes preservar todos los detalles.

Crea un resumen muy conciso enfocandote en:

1. El tipo de metodo analitico (metodo de materia prima, producto terminado).
2. El nombre del producto.
3. Menciona cuántas pruebas (tests) se encontraron en total.

El agente necesita saber lo que contiene este archivo para decidir si debe buscar mas informacion o usar esta fuente.

Genera un nombre de archivo que sea descriptivo y que indique el contenido del metodo analitico, enfocandote en si es metodo de materia prima, producto terminado y el nombre del producto (por ejemplo: "MP_GLICERINA_USP.md", "PT_CBG Acetaminofen.md").

Formato de salida:
```json
{{
    "filename": "nombre_descriptivo.md",
    "summary": "Resumen muy conciso enfocandose en el tipo de metodo analitico, el nombre del producto y la cantidad de pruebas.",
    "lista_pruebas": []
}}
```

NOTA IMPORTANTE: La lista_pruebas en el JSON de salida debe ser una LISTA VACÍA ([]). Esta lista se llenará programáticamente después.

Entrada:

<metadata_content>
{metadata_content}
</metadata_content>
"""

GENERATE_STRUCTURED_CONTENT_TEST = """
Eres un asistente experto en migración de datos de métodos analíticos. Tu tarea es transformar un objeto JSON de un esquema de "Prueba Legada" a un "Nuevo Esquema de Prueba".

Debes generar un JSON que se ajuste perfectamente al nuevo modelo de datos.

## 1. Mapeo Directo (Copiar 1:1)

Los siguientes campos deben copiarse **exactamente** como están del JSON de entrada al JSON de salida. Si el campo de entrada es `null`, el campo de salida también debe ser `null`.

* `prueba`
* `procedimientos`
* `equipos`
* `condiciones_cromatograficas`
* `reactivos`
* `soluciones`

## 2. Transformación Clave (La Tarea Principal)

La transformación más importante es convertir el campo `criterio_aceptacion` (antiguo) en el campo `especificaciones` (nuevo).

**Esquema Antiguo (Entrada):**
```json
{{
  "prueba": "Nombre de la Prueba A",
  ...
  "criterio_aceptacion": "Texto del criterio de aceptación."
}}
```

**Esquema Nuevo (Salida):**

```json
{{
  "prueba": "Nombre de la Prueba A",
  ...
  "especificaciones": [
    {{
      "prueba": "Nombre de la Prueba A",
      "texto_especificacion": "Texto del criterio de aceptación.",
      "subespecificacion": []
    }}
  ]
}}
```

### Reglas para la transformación de `especificaciones`:

1.  El nuevo campo `especificaciones` **debe ser una LISTA**.
2.  Si el campo `criterio_aceptacion` de entrada es `null` o un string vacío (`""`), el campo `especificaciones` debe ser una lista vacía (`[]`).
3.  Si `criterio_aceptacion` contiene texto, el campo `especificaciones` debe ser una lista que contenga **un solo objeto** `Especificacion`.
4.  Este objeto `Especificacion` debe poblarse de la siguiente manera:
      * `prueba`: Copia el valor del campo `prueba` de la raíz del JSON de entrada.
      * `texto_especificacion`: Copia el valor del campo `criterio_aceptacion` del JSON de entrada.
      * `subespecificacion`: Debe ser una lista vacía (`[]`) o `null`.

## 3. Campos a Ignorar

**NO** incluyas el campo `id_prueba` del JSON de entrada en tu salida.
**NO** incluyas el campo `criterio_aceptacion` original en tu salida (ya que se transforma en `especificaciones`).

## JSON de Entrada

<extracted_content>
{extracted_content}
</extracted_content>

Genera el JSON transformado.
"""


EXTRACT_STRUCTURED_DATA_PROMPT_TOOL_DESC = """
Extraer de forma estructurada el contenido del documento dependiendo el tipo de documento que sea
"""

STRUCTURED_EXTRACTION_CHANGE_CONTROL = """
Extraer un listado de cambios del método analítico del documento de control de cambios

## JSON de Entrada

<descripcion_detallada_cambio>
{metadata_content}
</descripcion_detallada_cambio>

"""

STRUCTURED_EXTRACTION_SIDE_BY_SIDE = """
Extraer información específica que será insertada en el método analítico modificado a partir de la información extraída de un documento side by side. Debe ser estructurada acorde al formato del método analítico.

## JSON de Entrada

<descripcion_side_by_side>
{metadata_content}
</descripcion_side_by_side>

"""

STRUCTURED_EXTRACTION_REFERENCE_METHODS = """
Extraer información específica que será insertada en el método analítico modificado a partir de la información extraída de diferentes métodos analíticos de referencia. Debe ser estructurada acorde al formato del método analítico.

## JSON de Entrada

<datos_metodo_referencia>
{metadata_content}
</datos_metodo_referencia>

"""