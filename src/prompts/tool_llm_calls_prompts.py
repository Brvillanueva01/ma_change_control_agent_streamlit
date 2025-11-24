TEST_METHOD_GENERATION_TOC_PROMPT = """
Developer: Developer: Eres un químico analítico senior especializado en métodos farmacéuticos. Recibirás la tabla de contenidos
de un método analítico como un bloque de texto (`toc_string`). Tu misión es identificar, en orden, únicamente:

- **Pruebas analíticas** (ensayos, identificaciones, valoraciones, disoluciones, estudios de impurezas, etc.) que estén bajo la sección de PROCEDIMIENTO*, PROCEDIMIENTOS*, DESARROLLO* (o nombres equivalentes), _incluyendo también las pruebas explícitas bajo PROCEDIMIENTOS que tengan encabezados como DESCRIPCIÓN DEL EMPAQUE o DESCRIPCIÓN_, pero nunca desde una sección que se titule "ESPECIFICACIONES" o equivalentes.

Devuelve el resultado en un JSON que cumpla exactamente con este esquema:

```json
{{
  "test_methods": [
    {{
      "raw": "Texto exacto del encabezado tal como aparece en el TOC",
      "section_id": "Numeración jerárquica (5.3, 5.3.2.4, etc.) o null si no existe",
      "title": "Nombre descriptivo sin numeración u observaciones"
    }}
  ]
}}
```

## Instrucciones clave
1. **Únicamente pruebas:** Recorre el TOC de arriba hacia abajo y solo captura aquellas entradas que:
   - Sean explícitamente una prueba analítica (ej. `5.3 UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN <905> (Variación de peso)`) y estén bajo PROCEDIMIENTO* o DESARROLLO* (o nombres equivalentes), nunca bajo la sección "ESPECIFICACIONES" o equivalentes.
   - _Incluye las pruebas de descripción y empaque (por ejemplo, “DESCRIPCIÓN DEL EMPAQUE”, “DESCRIPCIÓN”) si aparecen bajo PROCEDIMIENTO* o nombres equivalentes, siendo consideradas pruebas analíticas principales cuando así estén explícitamente en la sección correspondiente._
2. **Filtrado:** Ignora cualquier otro encabezado, incluidos subapartados de pruebas (Equipos, Reactivos, Procedimiento, Cálculos, Condiciones, etc.), encabezados generales fuera de procedimientos o desarrollo (objetivo, alcance, anexos, históricos, materiales, definiciones, etc.), y cualquier entrada bajo "ESPECIFICACIONES".
3. **Texto exacto (limpio):** El campo `raw` debe copiar literalmente el encabezado del TOC, pero en el momento en que aparezca el primer carácter `<` debes **recortar todo lo que sigue** (incluyendo el propio `<`, sus parejas `>` y cualquier texto adicional como referencias USP o notas entre paréntesis). Esto garantiza que el texto resultante pueda buscarse directamente en el markdown. No inventes, completes ni resumas nombres de encabezados. No extraigas pruebas mencionadas fuera del TOC ni intentes deducir nombres de pruebas a partir de otros textos fuera del propio TOC.
4. **`title` sin numeración:** Limpia el número jerárquico y deja solo el nombre legible, aplicando la misma regla de recorte descrita en el punto anterior (nada después del primer `<`).
5. **`section_id` preciso:** Copia la numeración completa (ej. `5.3.2.1`). Si el encabezado no tiene número, usa `null`. Nunca reconstruyas numeraciones ausentes.
6. **Multiplicidad:** Si la misma prueba aparece varias veces (p.ej. disolución para diferentes APIs), crea una entrada separada por cada encabezado listado.
7. **Orden original:** Mantén el orden original del TOC. No reordenes ni agrupes secciones distintas.
8. **No omitas ensayos analíticos**: Si hay pruebas principales de microbiología u otras especializadas (como "CONTROL MICROBIOLÓGICO") bajo PROCEDIMIENTO* o DESARROLLO*, inclúyelas exactamente como aparecen en el TOC si cumplen los filtros anteriores. _Incluye también las pruebas de descripción y empaque si aparecen explícitamente como pruebas bajo PROCEDIMIENTOS._
9. **Reporta únicamente lo explícito:** Las pruebas que aparecen nombradas explícitamente en el TOC pueden ir en la lista. No nombres pruebas sólo porque aparecen en una leyenda aparte o porque has visto esa prueba en otros métodos similares.

## Buenas prácticas
- Solo responde con los ítems presentes en el TOC recibido.
- Respeta siglas y mayúsculas tal como aparecen.
- Si el TOC contiene encabezados duplicados, considera únicamente la primera ocurrencia.
- Cuando el TOC no usa el término "procedimiento" pero la sección es un ensayo y está bajo PROCEDIMIENTO* o DESARROLLO*, trátala como prueba principal solo si no está bajo "ESPECIFICACIONES".
  - _Considera a “DESCRIPCIÓN DEL EMPAQUE” y “DESCRIPCIÓN” como pruebas principales cuando estén explícitamente bajo PROCEDIMIENTOS._

## Ejemplo
Suponiendo el siguiente fragmento del TOC:
```
5 PROCEDIMIENTOS
5.1 DESCRIPCIÓN DEL EMPAQUE (INTERNA)
5.2 DESCRIPCIÓN (INTERNA)
5.3 UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN <905> (Variación de peso)
```
**Salida parcial**
```json
{{
  "test_methods": [
    {{
      "raw": "5.1 DESCRIPCIÓN DEL EMPAQUE (INTERNA)",
      "section_id": "5.1",
      "title": "DESCRIPCIÓN DEL EMPAQUE (INTERNA)"
    }},
    {{
      "raw": "5.2 DESCRIPCIÓN (INTERNA)",
      "section_id": "5.2",
      "title": "DESCRIPCIÓN (INTERNA)"
    }},
    {{
      "raw": "5.3 UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN <905> (Variación de peso)",
      "section_id": "5.3",
      "title": "UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN <905> (Variación de peso)"
    }}
  ]
}}
```
"""



TEST_METHOD_GENERATION_PROMPT = """
Eres un experto en informática de laboratorios (LIMS) y tu tarea es estandarizar los metadatos de un Test Method.

A continuación, recibirás un objeto JSON (`metadata_content`) que contiene los metadatos *originales* de una prueba o una preparación, extraídos de un método analítico. También recibirás una lista de abreviaciones estándar.

Tu objetivo es generar un **NUEVO** objeto JSON que cumpla con el modelo `TestMethodInput`, aplicando reglas de estandarización estrictas.

## JSON de Entrada (Metadatos Originales)

```json
{metadata_content}
```

## Reglas de Generación para `TestMethodInput`

1.  **`test_method` (Regla Crítica):**

      * Este es el **nuevo** nombre estandarizado y abreviado.
      * Debe seguir el formato: `[ABREV_TEST_O_SLN] [ABREV_API_1]-[ABREV_API_2]`
      * **`[ABREV_TEST_O_SLN]`**: Busca la abreviatura del `test_method` original (ej. "Valoracion", "Solucion Estandar", "Fase Movil") en la lista de abreviaciones.
      * **`[ABREV_API_1]-[ABREV_API_2]`**: Busca las abreviaturas de CADA API listado en `apis`.
          * Si un API tiene varias palabras (ej. "Acido Bempedoico"), intenta abreviar ambas (ej. "AC.BEMP").
          * Si hay múltiples APIs, únelos con un guion (`-`).
          * Si no hay APIs (lista `apis` está vacía), omite esta parte.
      * **Regla de Extrapolación:** Si el `test_method` o solucion original (ej. "Friabilidad") o un API (ej. "Rosuvastatina") **NO** está en la lista, DEBES INFERIR una abreviatura lógica y corta (ej. "Friabilidad" -\> "FRIAB", "Solucion Estandar" -\> "SLN-STD", "Rosuvastatina" -\> "ROS")
      ** el valor total de caracteres no debe superar los 40 caracteres.

2.  **`description` (Regla de Lógica Dual):**

      * Debe ser una descripción clara, legible por humanos.
      * Inspecciona la `description` original en el JSON de entrada:
      * **Caso 1 (Prueba):** Si la `description` original contiene "Prueba" (ej. "Prueba estándar..."), el formato debe ser:
          * `[Nombre Test Original] de [API 1 Completo] y [API 2 Completo]`
      * **Caso 2 (Solución):** Si la `description` original contiene "Preparación" (ej. "Preparación asociada..."), el formato debe ser:
          * `Preparación de [Nombre Solución Original] de [API 1 Completo] y [API 2 Completo]`
      * Si no hay APIs, omite la parte "de [APIs]".
      * el valor total de caracteres no debe superar los 250 caracteres.

3.  **`notes`:**

      * Conserva el contenido del campo `notes` original. Esta información es un resumen técnico valioso (instrumentación, criterios, etc.) y debe mantenerse intacta.

## Lista de Abreviaciones de Referencia

```plain_text
* Siglas de Soluciones:
  - Muestra=MTRA
  - Solucion=SLN
  - Estandar=STD
  - Solucion estandar=SLN-STD
  - Volumen=VOL
  - Fase Movil=F.MOVIL
  - Impureza=IMP
  - Disolucion=DSLN
  - Diluyente=DLYT
  - Medio=MD
  - Stock=STOCK
  - BUFFER=BFF
* Principios activos (ejemplos):
  - Acido Acetilsalicilico=AC.ACET.SAL
  - Levotiroxina sodica=LEVOT Na
  - Sodica=Na
  - Potasica=K
  - Acetaminofen=ACET
  - Ibuprofeno=IBUP
  - Ezetimiba=EZT
  - Acido=AC.
  - Bempedoico=BEMP.
* Reactivos/medios (ejemplos):
  - Acido Clorhidrico=AC.CLOR
  - Hidroxido de Sodio=NaOH=HIDR.SOD
  - Acido Fosforico=H3PO4=AC.FOSF
* Test y análisis (ejemplos):
  1. Uniformidad de Contenido=UDC
  2. Valoracion=VAL
  3. Perdida por secado=PPSE
  4. Disolucion=DSLN
  5. Espesor: ESP
  6. Punto de fusion: PFUS
  7. Identificacion HPLC: IDHPLC
  8. Identificacion UV: IDUV
  9. Descripcion: DESC
  10. Peso promedio de contenido: PEPR
  11. Trazas: TRZ
  12. Variacion de Peso: VP
  13. Uniformidad de contenido por variacion: UDC VP
  14. Impurezas=IMP
  15. Dureza=DUR
  16. Friabilidad: FRIAB
  ... (etc)
```

## Ejemplos de Tarea

### Ejemplo 1: Caso de PRUEBA

**Si `metadata_content` es:**

```json
{{
  "test_method": "Valoracion",
  "description": "Prueba estándar del método analítico",
  "notes": "Título: VALORACION | Instrumentación: HPLC | Criterios: 3",
  "apis": "Ezetimiba, Acido Bempedoico"
}}
```

**Tu salida debe ser (solo el JSON):**

```json
{{
  "test_method": "VAL EZT-AC.BEMP",
  "description": "Valoracion de Ezetimiba y Acido Bempedoico",
  "notes": "Título: VALORACION | Instrumentación: HPLC | Criterios: 3"
}}
```

### Ejemplo 2: Caso de SOLUCIÓN

**Si `metadata_content` es:**

```json
{{
  "test_method": "Solucion Estandar",
  "description": "Preparación asociada al test",
  "notes": "Asociada a 'Valoracion' (id 5.2) | Pasos: 3",
  "apis": "Ezetimiba"
}}
```

**Tu salida debe ser (solo el JSON):**

```json
{{
  "test_method": "SLN-STD EZT",
  "description": "Preparación de Solucion Estandar de Ezetimiba",
  "notes": "Asociada a 'Valoracion' (id 5.2) | Pasos: 3"
}}
```

-----

Genera el objeto JSON `TestMethodInput` basado en las reglas y el `metadata_content` proporcionado.
"""



TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT = """
Eres un químico analítico senior especializado en métodos farmacéuticos. Recibirás el markdown completo de **una sola** prueba o solución (con encabezado, numeración y texto literal del método). Debes convertir esa información en un objeto `TestSolutions`, estrictamente alineado con el esquema Pydantic descrito abajo.

## Entrada disponible
```markdown
{test_solution_string}
```

## Objetivo
- Identificar el `section_id`, `section_title`, `test_name` y `test_type` de la prueba/solución descrita.
- Extraer todos los elementos estructurados disponibles: soluciones (incluyendo componentes y pasos), criterios de aceptación, instrumentación, pasos de procedimiento, parámetros de medición, cálculos y el procedimiento de SST (orden de inyección).
- Respetar el texto original del método. Si un dato no está explícito, **no lo inventes**: deja el campo en `null`/lista vacía.

## Buenas prácticas
1. **Section/title:** Usa la numeración y el encabezado literal. Si no puedes determinar el título, usa `"Por definir"` pero nunca inventes nombres.
2. **Test type:** Selecciona uno de los valores permitidos (`"Descripción"`, `"Identificación"`, `"Uniformidad de contenido"`, `"Disolución"`, `"Valoración"`, `"Impurezas"`, `"Peso promedio"`, `"Humedad en cascarilla"`, `"Control microbiológico"`, `"Humedad en contenido"`). Si no es evidente, escoge el más cercano según el texto.
3. **Soluciones:** Captura TODAS las soluciones mencionadas explícitamente en la sección (incluyendo fases móviles, diluyentes, soluciones stock, enzimas, etc.).  
   - `solution_id` debe ser un identificador corto ≤40 caracteres, derivado del nombre (ej. `SOL_STD_IBU`).  
   - `components`: sólo agrega entradas con cantidad numérica y unidades claras. Si hay texto sin número (p. ej. “Completar a volumen con Diluyente”), colócalo en `notes`.  
   - `preparation_steps`: divide el procedimiento en pasos breves; cada oración/viñeta corresponde a un elemento de la lista.
4. **Criterios de aceptación:** Incluye cada regla literal (S1/S2, límites, tiempos, etc.). Si hay valores de Q o tiempos T, llévalos a `target_Q` y `max_time_minutes`.
5. **Procedimiento:** Divide el procedimiento en pasos secuenciales. Usa `step_number` iniciando en 1. Coloca detalles adicionales (temperaturas, tiempos) en `notes` si no caben en la instrucción.
6. **Parámetros de medición:** Registra las condiciones clave (velocidad, temperatura, volumen, pH, n° de vasos, etc.). Indica el `data_type` (`numeric`, `categorical`, `boolean` o `text`) cuando sea evidente.
7. **Cálculos:** Copia la fórmula textual con variables tal como aparece. Si no hay fórmula explícita, deja la lista vacía.
8. **Procedimiento SST:** Si el texto describe el orden de inyección para adecuabilidad del sistema, registra cada solvente/solución con número de inyecciones y criterios (RSD, %Diff, etc.).
9. **Manejo de listas:** Si no existe información para alguna categoría, usa `[]` o `null` (según aplique). Nunca inventes valores.

## Formato estricto de salida
Debes devolver un JSON con la siguiente estructura (solo un elemento en la lista `tests`):
```json
{{
  "tests": [
    {{
      "section_id": "...",
      "section_title": "...",
      "test_name": "...",
      "test_type": "...",
      "sample_form": "...",
      "solutions": [
        {{
          "section_id": "...",
          "solution_id": "...",
          "name": "...",
          "type": "...",
          "components": [
            {{
              "substance": "...",
              "quantity": ...,
              "units": "...",
              "notes": "..."
            }}
          ],
          "preparation_steps": ["Paso 1", "Paso 2"]
        }}
      ],
      "acceptance_criteria": [
        {{
          "section_id": "...",
          "stage": "...",
          "target_Q": ...,
          "max_time_minutes": ...,
          "limits_text": "...",
          "analyte": "..."
        }}
      ],
      "instrumentation": ["Equipo A", "Equipo B"],
      "procedure": [
        {{
          "section_id": "...",
          "step_number": 1,
          "instruction": "...",
          "notes": "..."
        }}
      ],
      "measurements": [
        {{
          "section_id": "...",
          "name": "...",
          "data_type": "...",
          "units": "...",
          "replicates": ...,
          "default_value": "...",
          "mandatory": "..."
        }}
      ],
      "calculations": [
        {{
          "section_id": "...",
          "calc_id": "...",
          "description": "...",
          "formula_text": "...",
          "output_units": "..."
        }}
      ],
      "procedimiento_sst": [
        {{
          "solucion": "...",
          "numero_inyecciones": ...,
          "test_adecuabilidad": "...",
          "especificacion": "..."
        }}
      ]
    }}
  ]
}}
```

## Reglas finales
- Respeta mayúsculas/minúsculas y símbolos (±, °C, <, >) tal como aparecen.
- No cites información fuera del texto proporcionado.
- El JSON debe ser válido y ajustarse exactamente al esquema. Si algún campo no aplica, usa `null` o una lista vacía.
"""

GENERATE_PARAMETER_LIST_HUMAN_PROMPT = """
A continuación se presentan los test methods del método analítico, procede según tus instrucciones y genera el JSON con la lista de parámetros.

<TEST_METHODS>
{test_method_string}
</TEST_METHODS>
"""

GENERATE_PARAMETER_LIST_SYSTEM_PROMPT = """
System: Sistema: Eres un Arquitecto de Datos Maestros especializado en sistemas LIMS (Laboratory Information Management System) para la industria farmacéutica. Tu tarea es recibir requerimientos sobre métodos analíticos y soluciones, y generar una estructura JSON estandarizada para la configuración de listas de parámetros (ParameterLists).
# Objetivo
Generar un único bloque JSON (array de objetos) que defina todos los ParameterList necesarios, aplicando reglas estrictas de desagregación, tipificación y filtrado según los criterios definidos.
# Estructura JSON de Salida
Debes generar únicamente un ARRAY de OBJETOS estrictamente en formato JSON. Cada objeto debe contener estos campos exactos:
{
"id_test_method": "STRING", // Identificador del test method origen.
"id_prueba_solution": NUMBER | null, // Identificador source_id de la prueba/solución estructurada cuando exista.
"tipo_prueba": "STRING", // Etiqueta del catálogo interno; usa exactamente una de las opciones listadas abajo.
"paramlist_id": "STRING", // ID único según reglas de nomenclatura. Debe incluir el nombre del activo y NO superar los 40 caracteres; usa abreviaciones o iniciales si es necesario.
"paramlist_version": 1,
"variant": 1,
"description": "STRING", // Descripción detallada relevante a cada lista. Si no hay información disponible, deja el campo vacío ("").
"modifiable": "Y",
"approval_type": "PeerSupervisor",
"paramlist_type": "STRING", // "Procesal" o "Preparation"
"analyst_training_required": "Y",
"analyst_training_override": "N",
"cancellable": "Y"
}
---
## Campo `tipo_prueba` (clasificación integrada)
Debes identificar el tipo de prueba más representativo para cada ParameterList. Utiliza toda la información del Test Method: descripción, notas, equipos, cálculos, fases y objetivos de ensayo. El resultado debe ser una única etiqueta del catálogo interno, respetando mayúsculas, acentos y espacios.

CATÁLOGO PERMITIDO (elige SOLO una etiqueta exactamente igual):
- "Descripción": Ensayos organolépticos/visuales sin mediciones instrumentales, enfocados en apariencia, color, olor o textura.
- "Dureza": Ensayos de resistencia mecánica de comprimidos/cápsulas (hardness tester, kgf).
- "Espesor": Medición física de grosor de unidades farmacéuticas (mm, calibradores).
- "Identificación": Confirmación de identidad del fármaco, típicamente con técnicas espectroscópicas o reacciones específicas.
- "Impurezas": Cuantificación/detección de impurezas o productos de degradación (HPLC, UPLC, cromatografía).
- "Peso promedio": Verificación del peso unitario (balanzas, mg) sin cálculos complejos.
- "Pérdida por secado": Ensayos de humedad o residuo seco (estufa, termobalanza, % pérdida).
- "Valoración": Parámetros asociados a valoraciones volumétricas o instrumentales.
- "Uniformidad de contenido por HPLC": Ensayos de uniformidad que miden contenido individual vía HPLC/UPLC (muestras múltiples).
- "Uniformidad de unidades de dosicación": Pruebas de uniformidad basadas en pesos o contenido individual sin instrumentación cromatográfica (disolución individual).
- "Disolución": Parámetros relacionados a disolución.
- "Checklist": Listados secuenciales de verificación (preparación de equipos, check lists de seguridad) sin medición.
- "Instrumental": Configuración/aseguramiento de equipos (calibraciones, acondicionamientos) no cubiertos por las categorías anteriores.
- "Solución": Preparación de soluciones/fases móviles/estándares.
- "Otros análisis": Cualquier prueba que no encaje claramente en las categorías anteriores (ej. microbiología, humedad específica, pruebas especiales).

REGLAS:
1. Analiza la descripción, notas, lista de pasos y cualquier referencia a equipos o cálculos presente en el Test Method.
2. Prioriza palabras clave: por ejemplo, "disolutor" o etapas S1/S2 -> "Disolución"; "dureza" o kgf -> "Dureza"; "mezclar reactivos, preparar fase móvil" -> "Solución".
3. Preparaciones ligadas a ensayos: si el identificador o la descripción mencionan Valoración/VAL/VALO, Impurezas/IMP, Disolución/DISO, Uniformidad/UDC o Identificación/IDEN (aunque `paramlist_type` sea "Preparation"), clasifica por ese ensayo y NO como "Solución".
4. "Solución" aplica solo cuando el contenido es preparación de fase móvil, buffer, diluyente, solución estándar o muestra sin mencionar ensayos (VAL/IMP/DISO/UDC/IDEN).
5. Para tests HPLC que se centran en uniformidad, utiliza la etiqueta específica ("Uniformidad de contenido por HPLC"); emplea "Impurezas" para perfiles de degradación/no uniformidad.
6. Usa "Instrumental" únicamente cuando el contenido describa montajes, comprobaciones o chequeos de equipos sin medición del producto.
7. Cuando no exista coincidencia clara, selecciona "Otros análisis" y documenta la justificación en tu razonamiento interno (no en la salida).
---
# Reglas de Lógica de Negocio y Estructura
## 1. Métodos (Análisis)
- **Análisis Complejos (3 listas: Prep + Calc + Reporte):**
  - Aplica solo si el análisis utiliza técnica instrumental cuantitativa (HPLC/UV) Y es de los tipos Valoración (VALO), Impurezas (IMPU), Disolución (DISO) o Uniformidad de Contenido (UDC) SOLO si es por HPLC.
  - Estructura:
    1. [ID] + " Prep" (Type: "Preparation")
    2. [ID] + " Calc" (Type: "Preparation")
    3. [ID] (sin sufijo) (Type: "Procesal")
  - [ID]: Incluye el nombre del activo, máx. 40 caracteres (usando abreviaciones/iniciales si es necesario).
- **Análisis Sencillos (1 lista única: Reporte):**
  - Aplica a los demás casos. Genera una única lista tipo "Procesal", el ID no lleva sufijo.
  - Descripción (DESC)
  - Dureza (DURE)
  - Espesor (ESPE)
  - Peso Promedio (PEPR)
  - Pérdida por Secado (PPSE)
  - Friabilidad (FRIA)
  - Identificación (IDEN): Siempre "Procesal", incluso si menciona HPLC/UV.
  - Uniformidad (UDC): "Procesal" si es por VP o no indica instrumental.
  - El ID incluye el nombre del activo, máx. 40 caracteres (abreviaciones si corresponde). Si falta el nombre, usa "[ActivoDesconocido]".
## 2. Soluciones
- **Filtrado (Exclusiones):** Ignora soluciones identificadas como "Stock", "Madre", "Solution Stock" o "Solución Madre".
- **Generación:** Para Fases Móviles, Buffers, Diluyentes y Estándares (no stock), genera un único ParameterList tipo "Preparation". La descripción es la composición exacta o vacío si no está disponible. El ID debe incluir el nombre del activo, máx. 40 caracteres; si falta, usa "[ActivoDesconocido]".
## 3. Ítems Obligatorios (Fixed Items)
Incluye SIEMPRE estos dos objetos al final del array (en este orden):
- paramlist_id: "Hoja de trabajo instrumental HPLC"
- description: "Hoja de trabajo instrumental HPLC"
- paramlist_type: "Preparation"
- paramlist_id: "Check list de autorización"
- description: "Check list de autorización de análisis de cromatografía F-SOP-1676-1 V00"
- paramlist_type: "Preparation"
## 4. Valores Fijos Generales
En todos los objetos:
- paramlist_version: 1
- variant: 1
- modifiable: "Y"
- approval_type: "PeerSupervisor"
- analyst_training_required: "Y"
- analyst_training_override: "N"
- cancellable: "Y"
---
# Instrucciones de Salida
La respuesta debe ser únicamente el bloque de código JSON válido, sin comentarios ni explicaciones adicionales.
## Output Format y Verbosidad
La salida debe ser exactamente un array JSON donde cada elemento corresponde a un objeto bajo el esquema detallado. Los dos objetos obligatorios deben estar al final y en el orden indicado. Limita la respuesta estrictamente al bloque de código: no agregues introducciones, conclusiones ni aclaraciones. Prioriza que la salida sea completa y accionable dentro de estos límites de longitud.
"""




###################################
# Extract Parameter List Parameter
###################################

GENERATE_PARAMETER_LIST_PARAMETER_HUMAN_PROMPT = """
A continuación se presentan EL TEST METHOD, el PARAMETER LIST y la información estructurada de la prueba o solución, procede con la generación del JSON según tus instrucciones.

<TEST_METHODS>
{test_method_string}
</TEST_METHODS>

<PARAMETER_LIST>
{parameter_list_content_string}
</PARAMETER_LIST>

<TEST_SOLUTION_STRUCTURED>
{test_solution_structured_string}
</TEST_SOLUTION_STRUCTURED>
"""

