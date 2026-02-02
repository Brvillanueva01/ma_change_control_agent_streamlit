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
  - **source_file_name:** El nombre del archivo PDF (sin extensión) se extrae automáticamente y se usa para nombrar los archivos de salida.

  ## Parámetros
  - `dir_method (str)`: Ruta absoluta al archivo PDF del método analítico.
  - `base_path (str)`: Ruta base donde se guardarán los archivos. Default: `/actual_method`. Usa `/proposed_method` para métodos de referencia.

  ## Salida y efectos en el estado
  - **ToolMessage:** Devuelve un resumen con el número de campos poblados, la longitud del markdown consolidado, y el `source_file_name` a usar en las siguientes herramientas.
  - **Estado (`state['files']`):**
    - Guarda el JSON estructurado en `{base_path}/method_metadata_TOC_{source_file_name}.json`.
    - `state['files'][...]['data']` contiene el objeto `MetodoAnaliticoCompleto` (incluyendo `full_markdown` y `source_file_name`).

  ## Siguiente paso esperado
  - Tras ejecutar esta herramienta, pasa a `test_solution_clean_markdown(source_file_name="...")` usando el `source_file_name` indicado en el ToolMessage.
  - No vuelvas a ejecutar esta herramienta para el mismo PDF a menos que haya cambios en el documento fuente.
"""

#############################################################################################################
# Test/Solution Clean Markdown tool description
#############################################################################################################
TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC = """
  Lee el archivo `{base_path}/method_metadata_TOC_{source_file_name}.json`, usa el TOC completo para identificar pruebas y soluciones mediante un LLM y recorta el markdown específico de cada una. El resultado se almacena en `{base_path}/test_solution_markdown_{source_file_name}.json`.

  ## Cuándo usar
  - Ejecuta esta herramienta inmediatamente después de `pdf_da_metadata_toc`, dentro del Legacy Migration Agent o Reference Methods Agent.
  - Úsala siempre que necesites generar el listado de pruebas/soluciones con su markdown para alimentar las herramientas de extracción estructurada.

  ## Buenas Prácticas
  - **Precondición:** Asegúrate de que `state['files']` contenga `{base_path}/method_metadata_TOC_{source_file_name}.json` con `tabla_de_contenidos` y `markdown_completo`.
  - **Pre-procesamiento:** Por defecto elimina la TABLA DE CONTENIDO y recorta SOLO la sección PROCEDIMIENTOS/DESARROLLO para evitar duplicados de ESPECIFICACIONES. Si envías `method_format="hrm"`, conservará también la sección 3 SPECIFICATIONS para extraer los criterios de aceptación propios de HRM.
  - **source_file_name obligatorio:** Debes pasar el `source_file_name` que recibiste del paso anterior (pdf_da_metadata_toc).

  ## Parámetros
  - `source_file_name (str)`: Nombre del archivo de origen (sin extensión). **OBLIGATORIO**.
  - `base_path (str)`: Ruta base donde se encuentran los archivos. Default: `/actual_method`.
  - `method_format (str)`: Opcional. Usa `"latam"` (default) o `"hrm"`. HRM habilita la extracción desde la sección SPECIFICATIONS (ítem 3) cuando los criterios de aceptación vienen en ese formato.

  ## Salida y efectos en el estado
  - **ToolMessage:** Reporta cuántas pruebas/soluciones se generaron, cuántas obtuvieron markdown, y la ruta del archivo generado.
  - **Estado (`state['files']`):** Crea/actualiza `{base_path}/test_solution_markdown_{source_file_name}.json` con:
    - `full_markdown`: texto consolidado del método.
    - `toc_entries`: TOC usado para la inferencia.
    - `items`: lista de `{raw, title, section_id, markdown}` para cada prueba o solución.

  ## Siguiente Paso Esperado
  - Con este archivo disponible, ejecuta `test_solution_structured_extraction(id=..., source_file_name="...")` para cada ítem.
"""

#############################################################################################################
# Test/Solution Clean Markdown SBS (Side-by-Side) tool description
#############################################################################################################
TEST_SOLUTION_CLEAN_MARKDOWN_SBS_TOOL_DESC = """
  Version especializada para documentos Side-by-Side. Lee el archivo `{base_path}/method_metadata_TOC_{source_file_name}.json` generado por `sbs_proposed_column_to_pdf_md` y extrae pruebas/soluciones del markdown de la columna propuesta.

  ## Cuando usar
  - Ejecuta esta herramienta inmediatamente despues de `sbs_proposed_column_to_pdf_md`, dentro del Side-by-Side Agent.
  - Usala para procesar documentos comparativos donde ya se extrajo la columna del metodo propuesto.

  ## Diferencias con `test_solution_clean_markdown`
  - Sin pre-procesamiento de seccion PROCEDIMIENTOS: el markdown ya viene filtrado por columna desde `sbs_proposed_column_to_pdf_md`.
  - Prompt generico: no asume estructura de secciones numeradas (PROCEDIMIENTOS, ESPECIFICACIONES, etc.).
  - Optimizado para Side-by-Side: disenado para documentos comparativos con formato de tabla.

  ## Buenas Practicas
  - Precondicion: Asegurate de que `state['files']` contenga `{base_path}/method_metadata_TOC_{source_file_name}.json` con `markdown_completo`.
  - Ruta tipica: Usa `base_path="/proposed_method"` (valor por defecto) para documentos Side-by-Side.
  - **source_file_name obligatorio:** Debes pasar el `source_file_name` que recibiste del paso anterior.

  ## Parametros
  - `source_file_name (str)`: Nombre del archivo de origen (sin extension). **OBLIGATORIO**.
  - `base_path (str)`: Ruta base donde se encuentran los archivos. Default: `/proposed_method`.

  ## Salida y efectos en el estado
  - ToolMessage: Reporta cuantas pruebas/soluciones se generaron, cuantas obtuvieron markdown, y la ruta del archivo generado.
  - Estado (`state['files']`): Crea/actualiza `{base_path}/test_solution_markdown_{source_file_name}.json` con:
    - `full_markdown`: texto consolidado del metodo propuesto.
    - `toc_entries`: encabezados identificados.
    - `items`: lista de `{raw, title, section_id, markdown}` para cada prueba o solucion.

  ## Siguiente Paso Esperado
  - Con este archivo disponible, ejecuta `test_solution_structured_extraction(id=..., source_file_name="...", base_path="/proposed_method")` para cada item.
"""

#############################################################################################################
# Test/Solution Structured Extraction tool description
#############################################################################################################
TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC = """
  Convierte el markdown de una prueba o solución (generado por `test_solution_clean_markdown`) en un objeto estructurado `TestSolutions` y guarda cada resultado en una carpeta temporal para paralelización.

  ## Cuándo usar
  - Ejecuta esta herramienta después de tener disponible `{base_path}/test_solution_markdown_{source_file_name}.json`.
  - Invócala una vez por cada entrada (prueba o solución) que desees estructurar, usando el parámetro `id` que corresponde al consecutivo generado en la herramienta anterior.
  - **Ejecuta todas las llamadas en paralelo** para maximizar la eficiencia.

  ## Buenas Prácticas
  - **Precondición:** Verifica que el archivo de markdown exista con la lista de pruebas/soluciones.
  - **Selección de ítem:** El parámetro `id` debe coincidir con el campo `id` presente en cada objeto de `items`.
  - **Carpeta temporal:** Los archivos se guardan en `/temp_{base_path}/{source_file_name}/{{id}}.json` para permitir paralelización.
  - **source_file_name obligatorio:** Debes pasar el mismo `source_file_name` usado en los pasos anteriores.

  ## Parámetros
  - `id (int)`: Consecutivo asignado a la prueba/solución en `test_solution_markdown_{source_file_name}.json`. **OBLIGATORIO**.
  - `source_file_name (str)`: Nombre del archivo de origen (sin extensión). **OBLIGATORIO**.
  - `base_path (str)`: Ruta base. Default: `/actual_method`. Usa `/proposed_method` para side-by-side o métodos de referencia.

  ## Salida y efectos en el estado
  - **ToolMessage:** Confirma qué identificador se procesó, el source_file_name, y la ruta del archivo temporal.
  - **Estado (`state['files']`):**
    - Crea o actualiza `/temp_{base_path}/{source_file_name}/{{id}}.json` con el objeto `TestSolutions` procesado.
    - Cada archivo incluye `source_id` y `source_file_name` para trazabilidad.

  ## Siguiente Paso Esperado
  - Una vez que hayas generado todos los archivos individuales, ejecuta `consolidate_test_solution_structured(source_file_name="...")` para construir el archivo consolidado final.
"""

#############################################################################################################
# Test/Solution Structured Consolidation tool description
#############################################################################################################
TEST_SOLUTION_STRUCTURED_CONSOLIDATION_TOOL_DESC = """
  Une los archivos temporales generados por `test_solution_structured_extraction` y crea el archivo consolidado final. También genera automáticamente un registro de pruebas analíticas en `/analytical_tests/`.

  ## Cuándo usar
  - Ejecuta esta herramienta después de haber procesado todos los `id` necesarios con `test_solution_structured_extraction`.
  - Vuelve a correrla cuando agregues o modifiques archivos individuales y necesites refrescar el archivo consolidado.

  ## Buenas Prácticas
  - Asegúrate de que el estado contenga los archivos temporales en `/temp_{base_path}/{source_file_name}/`.
  - **source_file_name obligatorio:** Debes pasar el mismo `source_file_name` usado en los pasos anteriores.
  - Los archivos temporales se eliminan automáticamente después de la consolidación.

  ## Parámetros
  - `source_file_name (str)`: Nombre del archivo de origen (sin extensión). **OBLIGATORIO**.
  - `base_path (str)`: Ruta base. Default: `/actual_method`. Usa `/proposed_method` para side-by-side o métodos de referencia.

  ## Salida y efectos en el estado
  - **ToolMessage:** Reporta cuántas pruebas/soluciones se consolidaron, la ruta del archivo final, y el registro de pruebas analíticas generado.
  - **Estado (`state['files']`):**
    - Crea o actualiza `{base_path}/test_solution_structured_content_{source_file_name}.json` como una lista ordenada de objetos `TestSolutions`.
    - Crea o actualiza `/analytical_tests/{source_file_name}.json` con el registro de pruebas analíticas.
    - Elimina los archivos temporales de `/temp_{base_path}/{source_file_name}/`.

  ## Siguiente Paso Esperado
  - Usa el archivo consolidado para alimentar a los agentes de implementación de cambios.
  - El registro en `/analytical_tests/` estará disponible para referencia cruzada en `analyze_change_impact`.
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
  - Después de que existan los archivos procesados por `legacy_migration_agent`, `change_control_agent` y `side_by_side_agent` (o `reference_methods_agent`).
  - Cuando el supervisor necesita consolidar los cambios propuestos y traducirlos en instrucciones de edición sobre `/new/new_method_final.json`.
  - Úsala una sola vez por ciclo de implementación, una vez que todos los insumos relevantes estén listos.

  ## Búsqueda Automática de Archivos
  Esta herramienta busca automáticamente TODOS los archivos con patrón `test_solution_structured_content_*.json` en:
  - **Método legado:** `/actual_method/` (puede haber múltiples archivos)
  - **Método propuesto:** `/proposed_method/` (puede haber múltiples archivos de side-by-side o métodos de referencia)
  - **Control de cambios:** `/change_control/change_control_summary.json` (o `/new/change_control_summary.json` como fallback)
  - **Registro de pruebas:** `/analytical_tests/` (opcional, para referencia cruzada)
  - **Salida:** `/new/change_implementation_plan.json`

  ## Buenas Prácticas
  - **Precondición:** Asegúrate de que los archivos de entrada estén disponibles en el estado antes de llamar esta herramienta.
  - **Múltiples fuentes:** La herramienta combina pruebas de múltiples archivos automáticamente, preservando `_source_file_name` para trazabilidad.
  - **Sin parámetros:** Llama al tool sin argumentos adicionales.

  ## Parámetros
  - No requiere parámetros. La herramienta busca archivos automáticamente.

  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Resume la cantidad de acciones propuestas para implementar los cambios.
  - **Actualización del Estado:** Crea o reemplaza `/new/change_implementation_plan.json`, con un plan estructurado que incluye:
    - listado de cambios,
    - pruebas afectadas o nuevas,
    - acción sugerida (`editar`, `adicionar`, `eliminar`, `dejar igual`),
    - referencias al método propuesto para cada acción.

  ## Siguiente Paso Esperado
  - Revisar el plan generado (leer `/new/change_implementation_plan.json`).
  - Llamar a `apply_method_patch` para cada acción del plan para aplicar los cambios.
"""

APPLY_METHOD_PATCH_TOOL_DESCRIPTION = """
  Genera y aplica el contenido completo de una prueba por accion del plan usando la informacion del metodo legado
  y del metodo propuesto.
  
  ## Cuando usar
  - Despues de obtener el plan en `/new/change_implementation_plan.json` mediante `analyze_change_impact`.
  - Cuando necesites materializar **una** accion del plan (indice especifico) para actualizar `/new/new_method_final.json`.
  - Cada llamada procesa una accion: editar, adicionar, eliminar o dejar igual. Ejecuta tantas llamadas como acciones existan.
  
  ## Rutas de Archivos (FIJAS - NO CONFIGURABLES)
  Esta herramienta usa rutas predeterminadas fijas para los metodos de referencia:
  - **Metodo legado:** `/actual_method/test_solution_structured_content.json`
  - **Metodo propuesto:** `/proposed_method/test_solution_structured_content.json`
  
  ## Buenas Practicas
  - Proporciona siempre el `action_index` correcto; revisa el plan antes de llamar a la herramienta.
  - Asegurate de que los archivos de referencia esten cargados en el estado para que el LLM disponga de contexto completo.
  - La herramienta guarda el resultado en `/new/applied_changes/{action_index}.json` y actualiza `/new/new_method_final.json`.
  
  ## Parametros
  - `plan_path (str)`: Ruta al plan generado por `analyze_change_impact`. Default `/new/change_implementation_plan.json`.
  - `action_index (int)`: Indice (0-based) de la accion a ejecutar.
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
  Ademas, copia la metadata del metodo legado (tipo_metodo, nombre_producto, objetivo, alcance, definiciones, etc.) al metodo final.
  
  ## Cuando usar
  - Despues de aplicar todas las acciones con `apply_method_patch`.
  - Cuando necesites un unico JSON consistente para entregar o renderizar.
  
  ## Parametros
  - `patches_dir (str)`: Directorio virtual donde se guardan los parches individuales. Default `/new/applied_changes`.
  - `base_method_path (str)`: Ruta al metodo base sobre el que se aplicaran los parches. Default `/new/new_method_final.json`.
  - `legacy_metadata_path (str)`: Ruta al archivo de metadata del metodo legado. Default `/actual_method/method_metadata_TOC.json`.
  - `output_path (str)`: Ruta de salida del metodo consolidado. Default `/new/new_method_final.json`.
  
  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Resumen de parches leidos, aplicados y campos de metadata copiados.
  - **Actualizacion del Estado:** Escribe el metodo consolidado en `output_path` con:
    - Metadata del metodo legado (apis, tipo_metodo, nombre_producto, numero_metodo, version_metodo, codigo_producto, objetivo, alcance_metodo, definiciones, recomendaciones_seguridad, materiales, equipos, anexos, autorizaciones, documentos_soporte, historico_cambios).
    - Pruebas consolidadas con todos los cambios aplicados.
  
  ## Siguiente Paso Esperado
  - Ejecutar `render_method_docx` para generar el documento DOCX final.
  """

RENDER_METHOD_DOCX_TOOL_DESCRIPTION = """
  Renderiza el metodo analitico consolidado en un documento DOCX usando la plantilla corporativa.
  Lee el metodo desde el filesystem virtual y genera un archivo .docx listo para revision o entrega.
  
  ## Cuando usar
  - Despues de ejecutar `consolidate_new_method` exitosamente.
  - Cuando el metodo final en `/new/new_method_final.json` este listo y validado.
  - Como **ultimo paso** del flujo de implementacion de cambios.
  
  ## Rutas de Archivos
  - **Metodo fuente:** `/new/new_method_final.json` (default, configurable via `method_path`).
  - **Plantilla:** `src/template/Plantilla.docx` (default, configurable via `template_path`).
  - **Directorio de salida:** `output/` (default, configurable via `output_dir`).
  
  ## Parametros
  - `method_path (str)`: Ruta al metodo consolidado en el filesystem virtual. Default `/new/new_method_final.json`.
  - `template_path (str)`: Ruta absoluta a la plantilla DOCX. Default usa `src/template/Plantilla.docx`.
  - `output_dir (str)`: Directorio donde se guardara el documento generado. Default `output/`.
  
  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Resumen con nombre del producto, numero de metodo, cantidad de pruebas y ruta del archivo generado.
  - **Actualizacion del Estado:** Registra la informacion del documento generado en `/new/rendered_docx_info.json`.
  - **Archivo Fisico:** Genera el documento DOCX en el directorio de salida con formato `method_YYYYMMDD_HHMMSS.docx`.
  
  ## Siguiente Paso Esperado
  - Informar al supervisor que el documento esta listo.
  - El usuario puede abrir el archivo DOCX para revision final.
  """

#############################################################################################################
# Resolve Source References tool description
#############################################################################################################
RESOLVE_SOURCE_REFERENCES_TOOL_DESC = """
  Resuelve las referencias de archivos fuente en el control de cambios, mapeando códigos de producto
  a nombres de archivo reales en /actual_method/ y /proposed_method/.

  ## Cuándo usar
  - Ejecuta esta herramienta como **PRIMER PASO** del Change Implementation Agent, ANTES de `analyze_change_impact`.
  - Úsala después de que todos los subagentes de carga (legacy_migration, side_by_side, reference_methods, change_control) 
    hayan completado su trabajo.
  - Es necesaria cuando el Control de Cambios menciona códigos de producto/método (ej: "01-4280", "400006238") 
    que deben mapearse a los archivos reales procesados.

  ## Qué hace
  1. Lee los metadatos de `/actual_method/method_metadata_TOC_*.json` y `/proposed_method/method_metadata_TOC_*.json`
  2. Construye un mapeo de códigos (codigo_producto, numero_metodo) → source_file_name
  3. Lee `/new/change_control_summary.json`
  4. Para cada `source_reference_file` en cambios y pruebas nuevas, resuelve el `source_file_name` correspondiente
  5. Actualiza el CC summary con el campo `resolved_source_file_name`

  ## Parámetros
  - No requiere parámetros. Lee automáticamente del estado.

  ## Salida y efectos en el estado
  - **ToolMessage:** Resumen con cantidad de referencias resueltas y no resueltas.
  - **Estado (`state['files']`):**
    - Actualiza `/new/change_control_summary.json` con `resolved_source_file_name` en cada cambio/prueba nueva.
    - Crea `/new/source_reference_mapping.json` con el reporte detallado del mapeo.

  ## Siguiente Paso Esperado
  - Ejecutar `analyze_change_impact` que ahora podrá usar `resolved_source_file_name` para hacer matching correcto.
  """

