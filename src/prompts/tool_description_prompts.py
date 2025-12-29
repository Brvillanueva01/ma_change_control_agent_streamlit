# TOOL DESCRIPTIONS
#############################################################################################################
# PDF Metadata + TOC extraction tool description
#############################################################################################################
PDF_DA_METADATA_TOC_TOOL_DESC = """
  Procesa un documento PDF de un método analítico y genera el JSON maestro de metadata + tabla de contenidos usando OCR. El resultado sigue el modelo `MetodoAnaliticoCompleto` e incluye el markdown íntegro del documento.

  ## Cuándo usar
  - Ejecuta esta herramienta como **primer paso** del Structured Extraction Agent cuando recibas la ruta (`dir_method`) a un método analítico en PDF.
  - Úsala cada vez que necesites obtener:
    - Identificadores generales (tipo de método, número, versión, códigos, alcance, etc.).
    - Una tabla de contenidos **completa** con todos los subcapítulos.
    - El markdown consolidado del documento para posteriores extracciones de pruebas/soluciones.

  ## Buenas Prácticas
  - **Modelo fijo:** La extracción se realiza con el modelo Pydantic `MetodoAnaliticoDA` y luego se transforma en `MetodoAnaliticoCompleto` agregando `full_markdown`. No selecciones modelos manualmente.
  - **PDF obligatorio:** Solo acepta archivos con extensión `.pdf`. Valida la ruta antes de llamar la herramienta.
  - **Chunking automático:** El OCR administra la división del PDF y la comunicación con Mistral, no intentes dividirlo manualmente.
  - **TOC exhaustiva:** Siempre busca capturar todos los sub-encabezados numerados (ej. `5.1`, `5.1.1`, etc.) dentro de `tabla_de_contenidos`.

  ## Parámetros
  - `dir_method (str)`: Ruta absoluta al archivo PDF del método analítico.

  ## Salida y efectos en el estado
  - **ToolMessage:** Devuelve un resumen con el número de campos poblados y la longitud del markdown consolidado.
  - **Estado (`state['files']`):**
    - Guarda el JSON estructurado en `/actual_method/method_metadata_TOC.json`.
    - `state['files'][...]['data']` contiene el objeto `MetodoAnaliticoCompleto` (incluyendo `full_markdown`).
    - `state['files'][...]['content']` almacena la misma información serializada como string.

  ## Siguiente paso esperado
  - Tras ejecutar esta herramienta, pasa a las herramientas de limpieza de pruebas/soluciones usando el markdown disponible en `/actual_method/method_metadata_TOC.json`.
  - No vuelvas a ejecutar esta herramienta para el mismo PDF a menos que haya cambios en el documento fuente.
"""

#############################################################################################################
# Test/Solution Clean Markdown tool description
#############################################################################################################
TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC = """
  Lee el archivo `{base_path}/method_metadata_TOC.json`, usa el TOC completo para identificar pruebas y soluciones mediante un LLM y recorta el markdown específico de cada una. El resultado se almacena en `{base_path}/test_solution_markdown.json`, listo para las herramientas posteriores de extracción estructurada.

  ## Cuándo usar
  - Ejecuta esta herramienta inmediatamente después de `pdf_da_metadata_toc`, dentro del Legacy Migration Agent.
  - Úsala siempre que necesites generar el listado de pruebas/soluciones con su markdown para alimentar las herramientas de limpieza y extracción estructurada.

  ## Buenas Prácticas
  - **Precondición:** Asegúrate de que `state['files']` contenga `{base_path}/method_metadata_TOC.json` con `tabla_de_contenidos` (incluida hasta el último subnivel) y `markdown_completo`.
  - **Pre-procesamiento:** Esta herramienta elimina automáticamente la TABLA DE CONTENIDO y extrae SOLO la sección PROCEDIMIENTOS/DESARROLLO para evitar duplicados de ESPECIFICACIONES.
  - **Detección de encabezados:** El LLM (`gpt-5-mini`) produce un objeto `TestMethodsFromChunk`; cada entrada debe tener `raw`, `section_id` y `title`.
  - **Extracción de markdown:** El código compara los encabezados contra el markdown pre-procesado para recortar el texto entre encabezados consecutivos.

  ## Parámetros
  - `base_path (str)`: Ruta base donde se encuentran los archivos. Default: `/actual_method`.

  ## Salida y efectos en el estado
  - **ToolMessage:** Reporta cuántas pruebas/soluciones se generaron y cuántas obtuvieron markdown.
  - **Estado (`state['files']`):** Crea/actualiza `{base_path}/test_solution_markdown.json` con:
    - `full_markdown`: texto consolidado del método.
    - `toc_entries`: TOC usado para la inferencia.
    - `items`: lista de `{raw, title, section_id, markdown}` para cada prueba o solución.

  ## Siguiente Paso Esperado
  - Con este archivo disponible, ejecuta `test_solution_structured_extraction` u otras herramientas que consumen los segmentos de markdown para producir test methods parametrizados o textos limpios.
"""

#############################################################################################################
# Test/Solution Clean Markdown SBS (Side-by-Side) tool description
#############################################################################################################
TEST_SOLUTION_CLEAN_MARKDOWN_SBS_TOOL_DESC = """
  Versión especializada para documentos Side-by-Side. Lee el archivo `{base_path}/method_metadata_TOC.json` generado por `sbs_proposed_column_to_pdf_md` y extrae pruebas/soluciones del markdown de la columna propuesta.

  ## Cuándo usar
  - Ejecuta esta herramienta inmediatamente después de `sbs_proposed_column_to_pdf_md`, dentro del Side-by-Side Agent.
  - Úsala para procesar documentos comparativos donde ya se extrajo la columna del método propuesto.

  ## Diferencias con `test_solution_clean_markdown`
  - **Sin pre-procesamiento de sección PROCEDIMIENTOS:** El markdown ya viene filtrado por columna desde `sbs_proposed_column_to_pdf_md`.
  - **Prompt genérico:** No asume estructura de secciones numeradas (PROCEDIMIENTOS, ESPECIFICACIONES, etc.).
  - **Optimizado para Side-by-Side:** Diseñado para documentos comparativos con formato de tabla.

  ## Buenas Prácticas
  - **Precondición:** Asegúrate de que `state['files']` contenga `{base_path}/method_metadata_TOC.json` con `markdown_completo` (columna propuesta).
  - **Ruta típica:** Usa `base_path="/proposed_method"` para documentos Side-by-Side.

  ## Parámetros
  - `base_path (str)`: Ruta base donde se encuentran los archivos. Default: `/actual_method` (pero típicamente se usa `/proposed_method`).

  ## Salida y efectos en el estado
  - **ToolMessage:** Reporta cuántas pruebas/soluciones se generaron y cuántas obtuvieron markdown.
  - **Estado (`state['files']`):** Crea/actualiza `{base_path}/test_solution_markdown.json` con:
    - `full_markdown`: texto consolidado del método propuesto.
    - `toc_entries`: encabezados identificados.
    - `items`: lista de `{raw, title, section_id, markdown}` para cada prueba o solución.

  ## Siguiente Paso Esperado
  - Con este archivo disponible, ejecuta `test_solution_structured_extraction(base_path="/proposed_method")` para estructurar cada prueba.
"""

#############################################################################################################
# Test/Solution Structured Extraction tool description
#############################################################################################################
TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC = """
  Convierte el markdown de una prueba o solución (generado por `test_solution_clean_markdown`) en un objeto estructurado `TestSolutions` y guarda cada resultado en `/actual_method/test_solution_structured/{{id}}.json`.

  ## Cuándo usar
  - Ejecuta esta herramienta después de tener disponible `/actual_method/test_solution_markdown.json`.
  - Invócala una vez por cada entrada (prueba o solución) que desees estructurar, usando el parámetro `id` que corresponde al consecutivo generado en la herramienta anterior.

  ## Buenas Prácticas
  - **Precondición:** Verifica que `state['files'][TEST_SOLUTION_MARKDOWN_DOC_NAME]['data']['items']` contenga la lista de pruebas/soluciones con el campo `markdown`. Sin este archivo la herramienta no puede operar.
  - **Selección de ítem:** El parámetro `id` debe coincidir con el campo `id` presente en cada objeto de `items`. La herramienta intentará usar ese consecutivo; si no existe, notificará al agente con un mensaje claro.
  - **Acumulación incremental:** Cada ejecución guarda un archivo independiente en `/actual_method/test_solution_structured/{{id}}.json`. Esto permite volver a consolidar las pruebas en cualquier momento ejecutando `consolidate_test_solution_structured`.
  - **Modelo fijo:** El LLM `gpt-5-mini` está configurado con el prompt `TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT` y el esquema Pydantic `TestSolutions`. No necesitas ajustar parámetros adicionales.

  ## Parámetros
  - `id (int)`: Consecutivo asignado a la prueba/solución en `test_solution_markdown.json`.

  ## Salida y efectos en el estado
  - **ToolMessage:** Confirma qué identificador se procesó y recuerda la ruta del archivo de salida.
  - **Estado (`state['files']`):**
    - Crea o actualiza `/actual_method/test_solution_structured/{{id}}.json` con el objeto `TestSolutions` procesado.
    - Cada archivo independiente conserva el `source_id` para rastrear el origen en `test_solution_markdown.json`.

  ## Siguiente Paso Esperado
  - Una vez que hayas generado todos los archivos individuales, ejecuta `consolidate_test_solution_structured` para construir `/actual_method/test_solution_structured_content.json` y alimentar a los agentes de Test Method (determinístico/LLM) o los procesos de parametrización finales.
"""

#############################################################################################################
# Test/Solution Structured Consolidation tool description
#############################################################################################################
TEST_SOLUTION_STRUCTURED_CONSOLIDATION_TOOL_DESC = """
  Une los archivos generados por `test_solution_structured_extraction` (ubicados en `/actual_method/test_solution_structured/{{id}}.json`) dentro del archivo consolidado `/actual_method/test_solution_structured_content.json`.

  ## Cuándo usar
  - Ejecuta esta herramienta después de haber procesado todos los `id` necesarios con `test_solution_structured_extraction`.
  - Vuelve a correrla cuando agregues o modifiques archivos individuales y necesites refrescar el archivo consolidado.

  ## Buenas Prácticas
  - Asegúrate de que el estado contenga los archivos individuales en el prefijo `/actual_method/test_solution_structured/`.
  - No requiere parámetros adicionales; detecta automáticamente todos los archivos `{{id}}.json` de esa carpeta virtual.
  - Si algún archivo no incluye `source_id`, la herramienta lo inferirá con base en el nombre del archivo.

  ## Parámetros
  - No recibe parámetros adicionales. Invócala simplemente como `consolidate_test_solution_structured(state=..., tool_call_id=...)`.

  ## Salida y efectos en el estado
  - **ToolMessage:** Reporta cuántas pruebas/soluciones se consolidaron y la ruta del archivo final.
  - **Estado (`state['files']`):** Crea o actualiza `/actual_method/test_solution_structured_content.json` como una lista ordenada de objetos `TestSolutions`.

  ## Siguiente Paso Esperado
  - Usa el archivo consolidado para alimentar a los agentes de Test Method o a cualquier proceso que requiera todas las pruebas estructuradas en un solo JSON.
"""

EXTRACT_STRUCTURED_DATA_PROMPT_TOOL_DESC = """
  Extrae información clave de documentos de soporte (Controles de Cambio, Comparativos, o Referencias) y prepara un resumen estructurado.

  ## Cuándo usar
  - Cuando se pide "analizar", "procesar", o "extraer" un documento de soporte que NO es el método legado principal.
  - Usar para **Controles de Cambio (CC)**, **comparaciones Side-by-Side**, o **métodos de referencia** (Farmacopea, USP, etc.).
  - Esta herramienta es llamada por subagentes especialistas (como 'change-control-analyst' o 'reference-methods-agent').

  ## Buenas Prácticas
  - **Selección del Modelo:** La decisión más importante es elegir el `document_type` correcto. El agente debe saber su propio rol (ej. 'change_control_analyst') y usar el `document_type` correspondiente ("change_control").
  - **Manejo de Archivos:** La herramienta maneja automáticamente la conversión de DOCX a PDF y la división (chunking). El agente no necesita preocuparse por esto.
  - **Llamada Única:** No llames a esta herramienta varias veces para el mismo archivo.

  ## Parámetros
  - `dir_document (str)`: La ruta completa (path) al archivo DOCX o PDF que se va a procesar.
  - `document_type (Literal)`: El tipo de modelo de extracción a utilizar. Debe ser **exactamente** uno de los siguientes valores:
      - `"change_control"`: Para un documento de Control de Cambios.
      - `"side_by_side"`: Para un documento de comparación "lado a lado".
      - `"reference_methods"`: Para un método de referencia (ej. Farmacopea, USP).

  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** La herramienta devuelve un `ToolMessage` que contiene un **resumen** en lenguaje natural del contenido extraído (ej. "Se extrajeron 5 cambios...").
  - **Actualización del Estado (State):** Esta herramienta tiene un **doble efecto** en el estado `state['files']`:
      1.  **JSON Completo:** Guarda la extracción completa (el objeto Pydantic) en su ruta principal (ej. `/new/change_control.json`). El agente **no** debe leer este archivo gigante.
      2.  **Resumen Estructurado:** Guarda un **nuevo** archivo de resumen pequeño (ej. `/new/change_control_summary.json`). Este archivo SÍ es pequeño y contiene la `lista_cambios` (para CC) u otros datos estructurados listos para usar.

  ## Siguiente Paso Esperado
  - Después de ejecutar esta herramienta, el siguiente paso lógico del agente es:
      1.  Llamar a `read_file()` sobre el archivo de **resumen** (ej. `/new/change_control_summary.json`) para obtener la lista de cambios o los datos estructurados.
      2.  Usar esa lista para informar al supervisor o para el siguiente paso de planificación (ej. 'dictionary-planner').
"""

CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION = """
  Analiza la información estructurada de control de cambios y genera un plan accionable para actualizar el método analítico.

  ## Cuándo usar
  - Después de que existan los archivos procesados por `change_control_agent`, `side_by_side_agent` y/o `reference_methods_agent`.
  - Cuando el supervisor necesita consolidar los cambios propuestos y traducirlos en instrucciones de edición sobre `/new/new_method_final.json`.
  - Úsala una sola vez por ciclo de implementación, una vez que todos los insumos relevantes estén listos.

  ## Buenas Prácticas
  - **Insumos obligatorios:** Siempre debe estar disponible `/new/change_control.json` y contener las descripciones de cambios.
  - **Insumos opcionales:** `/new/side_by_side.json` y `/new/reference_methods.json` pueden no existir; la herramienta manejará su ausencia.
  - **Contexto resumido:** No es necesario leer manualmente los archivos grandes; la herramienta los valida y extrae solo los campos necesarios para el LLM.

  ## Parámetros
  - `change_control_path (str)`: Ruta al JSON estructurado del control de cambios. Debe ser siempre `/new/change_control.json`.
  - `new_method_path (str)`: Ruta al método analítico consolidado sobre el cual se aplicarán los parches. Usualmente `/new/new_method_final.json`.
  - `side_by_side_path (str)`: Ruta al JSON side-by-side (si existe). Normalmente `/new/side_by_side.json`.
  - `reference_methods_path (str)`: Ruta al JSON de métodos de referencia (si existe). Por defecto `/new/reference_methods.json`.

  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Resume la cantidad de acciones propuestas para implementar los cambios.
  - **Actualización del Estado:** Crea o reemplaza `/new/change_implementation_plan.json`, con un plan estructurado que incluye:
    - listado de cambios,
    - pruebas afectadas o nuevas,
    - acción sugerida (`replace`, `append`, `noop`, `investigar`),
    - JSON Patch propuesto para aplicar sobre el método nuevo.

  ## Siguiente Paso Esperado
  - Revisar el plan generado (leer `/new/change_implementation_plan.json`).
  - Someter cada acción a validación humana si es necesario y, posteriormente, llamar a la herramienta de parcheo (`apply_method_patch`) para aplicar los cambios aprobados.
"""

APPLY_METHOD_PATCH_TOOL_DESCRIPTION = """
  Genera y aplica el contenido completo de una prueba por accion del plan usando la informacion del metodo nuevo,
  del metodo legado, del side-by-side y de los metodos de referencia.
  
  ## Cuando usar
  - Despues de obtener el plan en `/new/change_implementation_plan.json` mediante `analyze_change_impact`.
  - Cuando necesites materializar **una** accion del plan (indice especifico) para actualizar `/new/new_method_final.json`.
  - Cada llamada procesa una accion: editar, adicionar, eliminar o dejar igual. Ejecuta tantas llamadas como acciones existan.
  
  ## Buenas Practicas
  - Proporciona siempre el `action_index` correcto; revisa el plan antes de llamar a la herramienta.
  - Asegurate de que los archivos de referencia (`legacy_method`, `side_by_side` y `reference_method`) esten cargados en el estado para
    que el LLM disponga de contexto completo.
  - La herramienta guarda el resultado en `/new/applied_changes/{action_index}.json` y actualiza `/new/new_method_final.json`.
  
  ## Parametros
  - `plan_path (str)`: Ruta al plan generado por `analyze_change_impact`. Default `/new/change_implementation_plan.json`.
  - `action_index (int)`: Indice (0-based) de la accion a ejecutar.
  - `side_by_side_path (str)`: Ruta al JSON del analisis side-by-side. Default `/new/side_by_side.json`.
  - `reference_method_path (str)`: Ruta al JSON de metodos de referencia. Default `/new/reference_methods.json`.
  - `legacy_method_path (str)`: Ruta al metodo legado estructurado. Default `/actual_method/test_solution_structured_content.json`.
  - `new_method_path (str)`: Ruta al metodo consolidado que sera modificado. Default `/new/new_method_final.json`.
  
  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Indica si la prueba se genero/aplico y resume notas del LLM.
  - **Actualizacion del Estado:** Sobrescribe `/new/new_method_final.json`, registra la ejecucion en `/logs/change_patch_log.jsonl`
    y deja el parche individual en `/new/applied_changes/{action_index}.json`.
  
  ## Siguiente Paso Esperado
  - Una vez procesadas todas las acciones, ejecutar `consolidate_new_method` para fusionar todos los parches en el metodo final a renderizar.
  """

CONSOLIDATE_NEW_METHOD_TOOL_DESCRIPTION = """
  Fusiona todos los parches individuales generados por `apply_method_patch` en un solo metodo final listo para renderizar.
  
  ## Cuando usar
  - Despues de aplicar todas las acciones con `apply_method_patch`.
  - Cuando necesites un unico JSON consistente para entregar o renderizar.
  
  ## Parametros
  - `patches_dir (str)`: Directorio virtual donde se guardan los parches individuales. Default `/new/applied_changes`.
  - `base_method_path (str)`: Ruta al metodo base sobre el que se aplicaran los parches. Default `/new/new_method_final.json`.
  - `output_path (str)`: Ruta de salida del metodo consolidado. Default `/new/new_method_final.json`.
  
  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Resumen de parches leidos y aplicados.
  - **Actualizacion del Estado:** Escribe el metodo consolidado en `output_path` con todos los cambios aplicados.
  
  ## Siguiente Paso Esperado
  - Revisar el metodo consolidado (si es necesario) y proceder con el renderizado o pasos de QA.
  """
