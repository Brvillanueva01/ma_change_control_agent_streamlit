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
Lee el archivo `/actual_method/method_metadata_TOC.json`, usa el TOC completo para identificar pruebas y soluciones mediante un LLM y recorta el markdown específico de cada una. El resultado se almacena en `/actual_method/test_solution_markdown.json`, listo para las herramientas posteriores de extracción estructurada.

## Cuándo usar
- Ejecuta esta herramienta inmediatamente después de `pdf_da_metadata_toc`, dentro del Structured Extraction Agent.
- Úsala siempre que necesites generar el listado de pruebas/soluciones con su markdown para alimentar las herramientas de limpieza y extracción estructurada.

## Buenas Prácticas
- **Precondición:** Asegúrate de que `state['files']` contenga `/actual_method/method_metadata_TOC.json` con `tabla_de_contenidos` (incluida hasta el último subnivel) y `full_markdown`.
- **Detección de encabezados:** El LLM (`gpt-4.1-mini`) produce un objeto `TestMethodsfromTOC`; cada entrada debe tener `raw`, `section_id` y `title`. Si el TOC lista soluciones individuales (ej. “Solución Hidróxido de potasio”), se capturan como elementos separados.
- **Extracción de markdown:** El código compara los encabezados contra `full_markdown` para recortar el texto entre encabezados consecutivos. Evita modificar manualmente el markdown consolidado.
- **Sin parámetros externos:** La herramienta solo usa el estado compartido, por lo que no requiere rutas adicionales ni prompts personalizados.

## Parámetros
- No recibe parámetros adicionales. Se invoca simplemente como `test_solution_clean_markdown(state=..., tool_call_id=...)`.

## Salida y efectos en el estado
- **ToolMessage:** Reporta cuántas pruebas/soluciones se generaron y cuántas obtuvieron markdown.
- **Estado (`state['files']`):** Crea/actualiza `/actual_method/test_solution_markdown.json` con:
  - `full_markdown`: texto consolidado del método.
  - `toc_entries`: TOC usado para la inferencia.
  - `items`: lista de `{raw, title, section_id, markdown}` para cada prueba o solución.

## Siguiente Paso Esperado
- Con este archivo disponible, ejecuta `test_solution_structured_extraction` u otras herramientas que consumen los segmentos de markdown para producir test methods parametrizados o textos limpios.
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

#############################################################################################################
# Extract parameter list tool description
#############################################################################################################
EXTRACT_PARAMETER_LIST_TOOL_DESC = """
Lee el archivo `/new/test_method_llm_summary.json` generado por las herramientas de Test Method (`test_method_llm` o `test_method_deterministic`) y, con ayuda de un LLM estructurado, construye un Parameter List normalizado y lo guarda en `/new/parameter_list.json`.

## Cuándo usar
- Ejecútala inmediatamente después de obtener el resumen consolidado del método para convertirlo en parámetros formales.
- Vuelve a correrla cuando el archivo `/new/test_method_llm_summary.json` cambie o necesites regenerar la lista para validar modificaciones.
- Úsala cada vez que los agentes requieran un JSON de parámetros listo para plantillas o reportes.

## Buenas Prácticas
- Verifica que el estado contenga `/new/test_method_llm_summary.json` con la clave `content`; sin ese archivo la herramienta devolverá un mensaje informativo y no generará nada.
- Mantén el resumen lo más limpio posible: el prompt espera texto continuo del método; evita adjuntar binarios u otros formatos.
- La salida está validada contra el modelo `ParameterList` (campos como `paramlist_id`, `paramlist_type`, `modifiable`, etc.), por lo que el LLM debe completar todos los campos requeridos.
- No proporciones parámetros adicionales: la herramienta detecta todo desde el estado y utiliza prompts internos (`GENERATE_PARAMETER_LIST_SYSTEM/HUMAN_PROMPT`).

## Parámetros
- No recibe parámetros adicionales. Invócala como `extract_parameter_list(state=..., tool_call_id=...)`.

## Salida y efectos en el estado
- **ToolMessage:** Informa que se generó el Parameter List e incluye ruta y número total de parámetros.
- **Estado (`state['files']`):** Crea/actualiza `/new/parameter_list.json` con `content` (JSON string) y `data` (lista de objetos `Parameter` ya parseados).
- Si no encuentra el resumen requerido o el LLM devuelve una lista vacía, responde con un ToolMessage explicando que no se pudo generar la información.

## Siguiente Paso Esperado
- Consume `/new/parameter_list.json` para alimentar agentes que renderizan plantillas (ej. XLSX) o procesos de aprobación de parámetros.
- Si necesitas otros artefactos derivados (como reportes o revisiones), úsalo como fuente única de parámetros aprobados.
"""

#############################################################################################################
# Generate parameter list parameters tool description
#############################################################################################################
EXTRACT_PARAMETER_LIST_PARAMETERS_TOOL_DESC = """
Genera en una sola ejecución la lista completa de `Parameter List Parameters` para todas las entradas disponibles en `/new/parameter_list.json`, combinando el catálogo refinado de Test Methods y el JSON estructurado de pruebas/soluciones. La herramienta arma los prompts especializados apropiados (según `tipo_prueba`) y paraleliza internamente las llamadas al LLM (`openai:gpt-5-mini`) mediante LangGraph.

## Cuándo usar
- Después de contar con `/new/parameter_list.json`, `/new/test_method_llm_summary.json` y `/actual_method/test_solution_structured_content.json`.
- Cuando el Parameter List Parameter Agent necesita producir todos los archivos `/new/param_details/*.json` sin coordinar múltiples invocaciones manuales.
- Antes de consolidar y renderizar (XLSX, reportes) para asegurar que cada ParamList tenga su secuencia completa de pasos.

## Requisitos previos en `state['files']`
- `/new/parameter_list.json`: lista de ParamLists (campo `data`).
- `/new/test_method_llm_summary.json`: catálogo refinado por el agente de Test Methods.
- `/actual_method/test_solution_structured_content.json`: contexto estructurado de pruebas/soluciones.
Si falta alguno o su estructura no es válida, la herramienta devuelve un `ToolMessage` con la explicación y no crea archivos.

## Cómo funciona
1. Recorre cada entrada de `/new/parameter_list.json`, resuelve `id_test_method` e `id_prueba_solution` y selecciona el prompt específico desde `DICCIONARIO_PROMPTS_PRUEBA`.
2. Genera un trabajo por ParamList con los mensajes de sistema/usuario y la ruta de salida (`/new/param_details/{indice}_{slug}.json`).
3. Ejecuta un LangGraph que envía todos los trabajos en paralelo al sub-agente generador de `ParamListParameters`.
4. Persiste cada resultado exitoso en `/new/param_details/` y acumula los errores sin detener los demás trabajos.
5. Devuelve un resumen agrupado con los ParamLists exitosos y los que fallaron o no pudieron prepararse.

## Parámetros
- `id_parameter_sequence_id` (opcional, ignorado): se conserva solo por compatibilidad. Omítelo o envíalo como `null`; la herramienta procesa automáticamente toda la lista.

## Salida y efectos en el estado
- **ToolMessage:** Reporta cuántas ParamLists generaron parámetros y detalla los casos con error.
- **Estado (`state['files']`):** Actualiza/crea cada archivo `/new/param_details/<indice>_<paramlist_id>.json` con `content` y `data` completos.
- No se crean archivos parciales cuando ocurre un error en un trabajo específico; el detalle queda en el mensaje.

## Siguiente paso esperado
- Ejecuta `consolidate_paramlist_parameters()` para unir todos los archivos de `/new/param_details/` en `/new/parameter_list_parameter.json` (fan-in).
- Continúa con `consolidate_context_render()` + `render_xlsx_document()` solo después de que esta herramienta y la consolidación hayan finalizado correctamente.
"""

#############################################################################################################
# Consolidate parameter list parameters tool description
#############################################################################################################
CONSOLIDATE_PARAMETER_LIST_PARAMETERS_TOOL_DESC = """
Consolida todos los archivos individuales generados por `extract_paramlist_parameter` (ubicados en `/new/param_details/`) en un solo JSON maestro `/new/parameter_list_parameter.json`. Esta herramienta cierra el fan-in del Paso 4 antes de renderizar plantillas o ejecutar validaciones finales.

## Cuándo usar
- Después de que el Parameter List Parameter Agent termine de generar **todas** las listas individuales en `/new/param_details/`.
- Justo antes de correr procesos fan-in (por ejemplo, `render_xlsx_document`) que esperan un único archivo con todos los parámetros.

## Requisitos previos
- El estado debe contener uno o más archivos en el prefijo `/new/param_details/`.
- Cada archivo debe tener la estructura emitida por `extract_paramlist_parameter` (`paramlist_id`, `id_parameter_sequence_id`, `paramlist_parameters`, etc.).

## Cómo funciona
1. Recorre `state['files']` y detecta todas las rutas que empiezan por `/new/param_details/`.
2. Carga cada archivo JSON (usando `data` o parseando `content`), agrega metadatos útiles como la ruta de origen y ordena por `id_parameter_sequence_id`.
3. Genera el payload consolidado:
   ```json
   {
     "param_details": [...],
     "total_items": N
   }
   ```
   y lo guarda en `/new/parameter_list_parameter.json`.

## Parámetros
- No recibe parámetros adicionales; basta con invocarla cuando el estado ya tiene los archivos individuales.

## Salida y efectos en el estado
- **ToolMessage:** Indica cuántos detalles fueron consolidados y confirma la ruta `/new/parameter_list_parameter.json`.
- **Estado:** Actualiza/crea `state['files']['/new/parameter_list_parameter.json']` con `content` (string JSON) y `data` (diccionario ya parseado). Los archivos individuales permanecen intactos para auditoría.
- Si no encuentra archivos en `/new/param_details/`, devuelve un mensaje informativo y no genera cambios.

## Siguiente paso esperado
- Usa `/new/parameter_list_parameter.json` como insumo directo para `render_xlsx_document` u otros procesos que necesitan toda la estructura de parámetros en un solo archivo.
"""

#############################################################################################################
# Consolidate render context tool description
#############################################################################################################
CONSOLIDATE_CONTEXT_RENDER_TOOL_DESC = """
Fusiona los insumos finales (`/new/test_method_llm_summary.json`, `/new/parameter_list.json` y `/new/parameter_list_parameter.json`) en un único archivo de contexto listo para el renderizado de la plantilla Excel.

## Cuándo usar
- Después de que el Paramlist Parameter Agent haya consolidado con éxito `/new/parameter_list_parameter.json`.
- Justo antes de renderizar el XLSX final; si cambia alguno de los tres insumos, vuelve a ejecutarla.

## Requisitos en `state['files']`
- `/new/test_method_llm_summary.json`: contiene la lista de Test Methods refinados (`test_methods_llm`).
- `/new/parameter_list.json`: catálogo completo de parameter lists.
- `/new/parameter_list_parameter.json`: salida de `consolidate_paramlist_parameters` con `param_details`.

## Cómo funciona
1. Verifica la existencia de los tres artefactos y carga sus `data` (o al menos su `content`).
2. Construye tablas normalizadas para la plantilla: `lista_parametros_ID`, `lista_parametros`, `test_metodo` y `listtest`.
3. Calcula métricas de control (conteos) y guarda todo el resultado en `/render/render_context.json`.

## Parámetros
- No recibe parámetros adicionales; se invoca simplemente como `consolidate_context_render(...)`.

## Salida y efectos en el estado
- **ToolMessage:** Resume cuántos Test Methods, Parameter Lists y Detalles se consolidaron y reporta la ruta `/render/render_context.json`.
- **Estado:** Actualiza `state['files']['/render/render_context.json']` con `content` (string JSON) y `data` (diccionario ya listo para la plantilla).
- Si falta algún archivo obligatorio, devuelve un ToolMessage informando el faltante y no genera contexto.

## Siguiente paso esperado
- Llama a `render_xlsx_document(context_path="/render/render_context.json")` para producir el reporte Excel final.
"""

#############################################################################################################
# Render XLSX Template
#############################################################################################################
RENDER_XLSX_DOCUMENT_TOOL_DESC = """
Genera el XLSX final del método analítico usando la plantilla oficial `templates/parametrix_template.xlsx` y el contexto preparado (`/render/render_context.json`).

## Cuándo usar
- Solo después de ejecutar `consolidate_context_render` y confirmar que el supervisor cerró el fan-out de parameters.
- En el último paso del flujo para entregar el archivo al usuario.

## Requisitos previos
- `/render/render_context.json` debe existir en `state['files']` (creado por `consolidate_context_render`).
- La plantilla física debe estar disponible en `templates/parametrix_template.xlsx` o en la ruta alternativa indicada.

## Parámetros
- `context_path (str, opcional)`: ruta del archivo de contexto; por defecto `/render/render_context.json`.
- `template_path (str, opcional)`: ruta a la plantilla XLSX si necesitas sobrescribir la predeterminada.

## Cómo funciona
1. Carga el contexto indicado y valida que la plantilla exista.
2. Rellena las hojas "Parameter Lists", "Parameter List Parameters", "Test Methods" y "Test Method ParamList" con el contexto provisto.
3. Renderiza y guarda el archivo en `output/parametrix_render_<timestamp>.xlsx`, adjuntando metadatos/base64 (si el tamaño lo permite) en el estado.

## Salida y efectos en el estado
- **ToolMessage:** Indica la ruta local donde quedó el XLSX final.
- **Estado:** Escribe una entrada en `/render/<archivo>.xlsx` con el metadato del reporte y, si es posible, el contenido en base64 para facilitar descargas posteriores.
- Si la librería `xlsxtpl` no está disponible o falta la plantilla, emite un mensaje explicando el bloqueo y no genera archivos parciales.

## Siguiente paso esperado
- El supervisor marca completado el plan y entrega el XLSX al usuario; no se requieren herramientas adicionales salvo que se solicite una nueva versión.
"""

#############################################################################################################
# Generate document annotation tool description
#############################################################################################################
STR_DOCUMENT_ANNOTATION_TOOL_DESC = """
Procesa un documento PDF de un método analítico, extrae la información estructurada usando OCR y la consolida en un único objeto JSON basado en el modelo 'MetodoAnalitico'.

## Cuándo usar
- Usar esta herramienta cuando el usuario proporcione una ruta (path) a un **método analítico en formato PDF** y pida "procesar", "leer", "extraer" o "analizar" su contenido.
- Esta herramienta es específica para extraer la estructura completa de un método analítico (pruebas, soluciones, etc.).

## Buenas Prácticas
- **Modelo Fijo:** Esta herramienta utiliza **siempre** el modelo de extracción Pydantic `MetodoAnalitico`. No requiere que el agente seleccione un modelo.
- **Manejo de Archivos:** La herramienta maneja automáticamente la división del PDF (chunking) y el procesamiento OCR con Mistral. El agente no necesita preocuparse por esto.
- **Validación:** La herramienta solo acepta archivos con extensión `.pdf`.

## Parámetros
- `dir_method (str)`: La ruta completa (path) al archivo **PDF** del método analítico que se va a procesar.

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** La herramienta devuelve un `ToolMessage` que contiene un **resumen legible** del contenido extraído. Este resumen se centra en el **conteo de pruebas y soluciones** identificadas (ej. "Pruebas identificadas: 5", "Soluciones totales: 12"). El agente debe usar este resumen para confirmar al usuario que el procesamiento se completó.
- **Actualización del Estado (State):** Esta herramienta guarda la **extracción JSON completa y estructurada** en la ruta interna `state['files']['/legacy/_structured_analytical_method.json']`.
    - `state['files']['...']['data']`: Contiene el objeto Pydantic (`MetodoAnalitico`) completo con todos los datos.
    - `state['files']['...']['content']`: Contiene la versión en string de ese mismo JSON.

## Siguiente Paso Esperado
- Después de ejecutar esta herramienta, el agente tiene el JSON completo disponible en el estado en `/legacy/_structured_analytical_method.json`.
- El agente **no debe** intentar leer este archivo completo (`read_file`) en su contexto, ya que es demasiado grande.
- El agente debe informar al usuario usando el resumen del `ToolMessage` y luego esperar a que el usuario solicite **información específica** (ej. "dame los detalles de la prueba de valoración", "lista las soluciones estándar"). Para responder, el agente deberá usar herramientas de consulta (como un `json_path_reader` o similar) para extraer solo la información solicitada de ese archivo JSON.
"""

#############################################################################################################
# Generate test method deterministic tool description
#############################################################################################################
TEST_METHOD_DETERMINISTIC_TOOL_DESC = """
Transforma el JSON estructurado de un método analítico (generado por `str_document_annotation`) en un "catálogo determinístico" de Test Methods.

Esta herramienta aplana la estructura jerárquica (Pruebas -> Soluciones) en una lista única, creando un 'Test Method' de tipo "Standard" por cada prueba y un 'Test Method' de tipo "Preparation" por cada solución asociada.

## Cuándo usar
- Usar esta herramienta **inmediatamente después** de que `str_document_annotation` haya procesado exitosamente un método analítico.
- Es el **segundo paso** en el flujo de migración. Su propósito es convertir la extracción JSON compleja en una lista plana lista para ser consumida por otros sistemas (como un LIMS).
- Llamar cuando el usuario pida "generar los test methods", "crear el catálogo de pruebas" o "transformar el método estructurado".

## Buenas Prácticas
- **Dependencia Crítica:** Esta herramienta **requiere** el JSON generado por `str_document_annotation`. Fallará si ese archivo no existe en el estado.
- **Fuente de Datos:** La herramienta busca automáticamente el JSON de entrada en la ruta por defecto: `state['files']['/legacy/_structured_analytical_method.json']`.
- **Transformación:** El número de "test methods" generados será la **suma** del número de pruebas (`type="Standard"`) más el número total de soluciones (`type="Preparation"`) en el documento original.

## Parámetros
- `method_path (Optional[str])`: La ruta al archivo JSON estructurado (el *output* de `str_document_annotation`).
    - Si se omite (`None`), la herramienta buscará automáticamente en la ruta por defecto: `/legacy/_structured_analytical_method.json`.
    - Solo necesitas especificar esto si el JSON de entrada se guardó en una ruta diferente a la estándar.

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** Devuelve un resumen confirmando la cantidad total de 'test methods' generados (detallando cuántas son pruebas estándar y cuántas son preparaciones) y la ruta del **nuevo** archivo JSON creado.
    - Ejemplo: "Generé 12 test methods determinísticos (5 pruebas estándar + 7 preparaciones). Archivo: /new/test_methods_deterministic.json"
- **Actualización del Estado (State):** Guarda un **NUEVO archivo JSON** en el estado.
    - La ruta de salida por defecto es `state['files']['/new/test_methods_deterministic.json']`.
    - Este nuevo archivo contiene la lista plana (`TestMethodsDeterministic`) y es el que debe usarse para consultas futuras sobre el catálogo.

## Siguiente Paso Esperado
- Después de ejecutar esta herramienta, el agente debe informar al usuario usando el resumen del `ToolMessage`.
- Si el usuario pide ver el catálogo generado o pregunta por "los test methods", el agente debe usar `read_file` o `json_path_reader` para consultar el **nuevo** archivo (ej. `/new/test_methods_deterministic.json`), **NO** el archivo original (`/legacy/_structured_analytical_method.json`).
"""

#############################################################################################################
# Generate test method LLM tool description
#############################################################################################################
TEST_METHOD_LLM_TOOL_DESC = """
Refina los metadatos de un **único** Test Method (prueba o solución) utilizando un LLM para crear nombres estandarizados y abreviados.

Esta es la herramienta 'fan-out' (o 'map'): está diseñada para ser llamada **múltiples veces en paralelo**, una vez por cada `id_prueba` que exista en el catálogo determinístico.

## Cuándo usar
- Usar esta herramienta **después** de haber generado el catálogo determinístico (`/new/test_methods_deterministic.json`).
- El agente debe obtener la lista de todos los `id_prueba` de ese archivo y luego llamar a `test_method_llm` **una vez por cada ID** de la lista.
- Por ejemplo, si hay 12 ítems en `test_methods_deterministic`, el agente debe llamar a esta herramienta 12 veces (preferiblemente en paralelo).

## Parámetros
- `id_prueba (str)`: El identificador único de la prueba o solución (ej. "5.2", "5.2.1") que se desea procesar y refinar con el LLM.

## Buenas Prácticas
- **Flujo de trabajo (Fan-Out):** No llames a esta herramienta una sola vez. El patrón correcto es:
    1. Leer `/new/test_methods_deterministic.json` para obtener la lista de todos los `id_prueba`.
    2. Invocar `test_method_llm(id_prueba=ID_1)`, `test_method_llm(id_prueba=ID_2)`, ... para todos los IDs.
- **Dependencias:** Esta herramienta lee dos archivos del estado:
    1. `/legacy/_structured_analytical_method.json` (para obtener los APIs).
    2. `/new/test_methods_deterministic.json` (para obtener el Test Method determinístico base).

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** Confirma la generación para el `id_prueba` específico y la ruta del **nuevo archivo individual** creado.
    - Ejemplo: "Generé el Test Method para el identificador de prueba: 5.2. Archivo: /new/test_method_5.2.json"
- **Actualización del Estado (State):** **NO** modifica el catálogo determinístico. En su lugar, crea un **NUEVO archivo JSON individual** en el estado por cada llamada.
    - La ruta es dinámica: `state['files']['/new/test_method_<id_prueba>.json']`.
    - Ejemplo: `/new/test_method_5.2.json`, `/new/test_method_5.3.json`, etc.

## Siguiente Paso Esperado
- Después de que **todas** las llamadas en paralelo a `test_method_llm` se hayan completado, el siguiente y **único** paso lógico es llamar a la herramienta `consolidate_test_method_llm()` para unificar todos los archivos individuales generados.
"""

CONSOLIDATE_TEST_METHOD_LLM_TOOL_DESC = """
Consolida todos los Test Methods individuales (generados por `test_method_llm`) en un único archivo JSON final.

Esta es la herramienta 'fan-in' (o 'reduce'). Su único propósito es buscar en el estado todos los archivos que coincidan con el patrón `/new/test_method_*.json`, extraer sus datos y unirlos en una sola lista.

## Cuándo usar
- Usar esta herramienta **exactamente una vez** y solo **después** de que todas las llamadas en paralelo a `test_method_llm` hayan finalizado exitosamente.
- Este es el paso final para recolectar y unificar los resultados del LLM.

## Parámetros
- Esta herramienta no requiere parámetros. Opera automáticamente sobre el estado `state['files']`.

## Buenas Prácticas
- **Orden de Operación:** Es **crítico** no llamar a esta herramienta prematuramente. Debe ser el último paso del flujo de refinamiento del LLM, después de que se hayan ejecutado todas las tareas de "fan-out".

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** Confirma cuántos Test Methods individuales se consolidaron y la ruta del **nuevo archivo resumen**.
    - Ejemplo: "Consolidé 12 Test Methods del LLM en /new/test_method_llm_summary.json."
- **Actualización del Estado (State):** Crea un **NUEVO archivo JSON** que contiene la lista completa de todos los Test Methods refinados por el LLM.
    - Ruta del archivo: `state['files']['/new/test_method_llm_summary.json']`.
    - Este archivo contiene el *resultado final* del proceso de refinamiento.

## Siguiente Paso Esperado
- Después de ejecutar esta herramienta, el agente debe informar al usuario que el catálogo final refinado está listo.
- Si el usuario solicita ver los resultados o pregunta por el catálogo, el agente debe leer el archivo `/new/test_method_llm_summary.json`.
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

STRUCTURED_SPECS_PROC_PROMPT_TOOL_DESC = """
Procesa una única prueba de método analítico por su ID, la transforma a un nuevo formato estructurado y la guarda como un archivo JSON individual.

## Cuándo usar
- Esta es la herramienta principal del "Fan-Out" (paralelización).
- Debe ser llamada **una vez por cada ID de prueba** que se obtuvo del archivo `/legacy/summary_and_tests.json`.
- El agente **debe** llamar a esta herramienta múltiples veces en paralelo (en un solo turno) si tiene múltiples IDs para procesar.

## Buenas Prácticas
- **Confianza en el Estado:** Esta herramienta *internamente* leerá el archivo JSON grande (`/legacy/legacy_method.json`) desde el estado. El agente **no** necesita leer o pasar ese contenido; solo debe proporcionar el `id_prueba`.
- **ID Exacto:** El `id_prueba` debe ser el string hexadecimal de 8 caracteres (hex8) exacto, tal como se extrajo.

## Parámetros
- `id_prueba (str)`: El ID único de 8 caracteres hexadecimales (ej. 'f47ac10b') de la prueba a procesar. Este ID debe venir de la `lista_pruebas` (o `pruebas_plan`) extraída del archivo `/legacy/summary_and_tests.json`.

## Salida y Efectos en el Estado
- **Mensaje de Retorno (ToolMessage):** La herramienta devuelve un `ToolMessage` que contiene **únicamente la ruta (path) al nuevo archivo JSON** que se creó (ej. '/new/pruebas_procesadas/f47ac10b.json').
- **Actualización del Estado (State):** Añade un **nuevo archivo** al estado en el directorio virtual `/new/pruebas_procesadas/`. El nombre del archivo será el `id_prueba` (ej. `f47ac10b.json`).

## Siguiente Paso Esperado
- El agente debe **recolectar todas las rutas de archivo** devueltas por cada una de estas llamadas en paralelo.
- Una vez que todas las pruebas hayan sido procesadas y todas las rutas recolectadas, el agente debe llamar a `consolidar_pruebas_procesadas` con la lista completa de rutas y la ruta al archivo base (`/legacy/legacy_method.json`).
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
  Genera y aplica el contenido completo de una prueba del plan de cambios usando la información del método nuevo,
  side-by-side y métodos de referencia.
  
  ## Cuándo usar
  - Después de obtener el plan en `/new/change_implementation_plan.json` mediante `analyze_change_impact`.
  - Cuando necesites materializar **una** acción del plan (índice específico) ya sea para revisión (`dry_run=True`) o para
    actualizar definitivamente `/new/new_method_final.json` (`dry_run=False`).
  - Se espera que el sub-agente invoque esta herramienta en paralelo, una vez por cada acción pendiente.
  
  ## Buenas Prácticas
  - Proporciona siempre el `action_index` correcto; revisa el plan antes de llamar a la herramienta.
  - Ejecuta primero con `dry_run=True` si deseas validar el contenido generado sin modificar el archivo final.
  - Asegúrate de que los archivos de referencia (`side_by_side` y `reference_method`) estén cargados en el estado para
    que el LLM disponga de contexto completo.
  
  ## Parámetros
  - `plan_path (str)`: Ruta al plan generado por `analyze_change_impact`. Default `/new/change_implementation_plan.json`.
  - `action_index (int)`: Índice (0-based) de la acción a ejecutar.
  - `side_by_side_path (str)`: Ruta al JSON del análisis side-by-side. Default `/new/side_by_side.json`.
  - `reference_method_path (str)`: Ruta al JSON de métodos de referencia. Default `/new/reference_method.json`.
  - `new_method_path (str)`: Ruta al método consolidado que será modificado. Default `/new/new_method_final.json`.
  - `dry_run (bool)`: Si es `True`, valida y reporta el resultado sin escribir archivos; `False` persiste los cambios.
  
  ## Salida y Efectos en el Estado
  - **Mensaje de Retorno (ToolMessage):** Indica si la prueba se generó/aplicó y resume notas del LLM.
  - **Actualización del Estado:**
    - `dry_run=True`: no se modifica `/new/new_method_final.json`; se usa solo para validación previa.
    - `dry_run=False`: sobrescribe `/new/new_method_final.json` con la versión actualizada y registra la ejecución en
      `/logs/change_patch_log.jsonl`.
  
  ## Siguiente Paso Esperado
  - Repetir la llamada con `dry_run=False` cuando el contenido generado sea aprobado.
  - Continuar procesando los siguientes `action_index` hasta completar el plan y luego avanzar al render o revisiones SOP.
  """

#############################################################################################################
# LLMS CALLS INSIDE TOOLS
#############################################################################################################

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




STRUCTURED_EXTRACTION_CHANGE_CONTROL = """
Eres un asistente experto en análisis de documentos de control de cambios (CC) farmacéuticos.
Tu tarea es leer el texto de entrada, que describe los cambios realizados, y extraer la información clave en un formato JSON estructurado.

Debes generar un JSON que se ajuste perfectamente al siguiente modelo de datos:

```json
{{
  "filename": "CC-001_resumen_cambios.md",
  "summary": "Un resumen conciso en lenguaje natural de los cambios descritos.",
  "lista_cambios": [
    "Descripción textual del primer cambio",
    "Descripción textual del segundo cambio",
    "..."
  ]
}}
````

# Reglas de Generación de Campos

Debes seguir estas reglas estrictamente:

**`filename`**:

  * Genera un nombre de archivo descriptivo basado en el contenido.
  * Debe ser corto, usar guiones bajos (`_`) en lugar de espacios, y terminar en `.md`.
  * Por ejemplo: `CC-00123_actualizacion_limites.md`.

**`summary`**:

  * Escribe un resumen muy conciso, en una o dos frases, que describa el propósito general de los cambios.
  * Ejemplo: "Actualización de los criterios de aceptación para la prueba de Dureza y ajuste del procedimiento de Disolución."

**`lista_cambios`**:

  * Esta es la tarea principal. Lee atentamente el texto de entrada.
  * Extrae cada cambio individual o "ítem de cambio" descrito como un **string separado** en la lista.
  * Copia el texto del cambio tan literalmente como sea posible, incluyendo detalles técnicos, valores antiguos y valores nuevos.
  * Si un cambio menciona la "justificación", inclúyela como parte del string de descripción del cambio.
  * Si el texto de entrada describe 5 cambios distintos, la `lista_cambios` debe contener 5 strings.

# Texto de Entrada (Control de Cambio)

El texto a continuación contiene la descripción detallada de los cambios.

<descripcion_detallada_cambio>
{metadata_content}
</descripcion_detallada_cambio>

Genera el JSON estructurado basado *únicamente* en el texto de entrada.
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

