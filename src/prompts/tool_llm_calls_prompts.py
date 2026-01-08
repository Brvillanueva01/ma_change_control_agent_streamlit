TEST_METHOD_GENERATION_TOC_PROMPT = """
Eres un químico analítico senior especializado en métodos farmacéuticos. Recibirás la tabla de contenidos
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
1. **Únicamente pruebas principales:** Recorre el TOC de arriba hacia abajo y solo captura aquellas entradas que:
   - Sean explícitamente una prueba analítica (ej. `5.3 UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN <905> (Variación de peso)`) y estén bajo PROCEDIMIENTO* o DESARROLLO* (o nombres equivalentes), nunca bajo la sección "ESPECIFICACIONES" o equivalentes.
   - Corresponden al **encabezado principal del ensayo** (ej. `7.4 IDENTIFICACION (USP)`). Si un encabezado tiene numeraciones adicionales (p. ej. `7.4.1`, `7.4.2.3`), considera que es un subapartado y **debe ignorarse** aunque mencione una prueba.
   - _Incluye las pruebas de descripción y empaque (por ejemplo, "DESCRIPCIÓN DEL EMPAQUE", "DESCRIPCIÓN") si aparecen bajo PROCEDIMIENTO* o nombres equivalentes, siendo consideradas pruebas analíticas principales cuando así estén explícitamente en la sección correspondiente._
2. **Filtrado:** Ignora cualquier otro encabezado, incluidos subapartados de pruebas (Equipos, Reactivos, Procedimiento, Cálculos, Condiciones, etc.), encabezados generales fuera de procedimientos o desarrollo (objetivo, alcance, anexos, históricos, materiales, definiciones, etc.), y cualquier entrada bajo "ESPECIFICACIONES".
3. **Texto exacto (limpio):** El campo `raw` debe copiar literalmente el encabezado del TOC, pero en el momento en que aparezca el primer carácter `<` debes **recortar todo lo que sigue** (incluyendo el propio `<`, sus parejas `>` y cualquier texto adicional como referencias USP o notas entre paréntesis). Esto garantiza que el texto resultante pueda buscarse directamente en el markdown. No inventes, completes ni resumas nombres de encabezados. No extraigas pruebas mencionadas fuera del TOC ni intentes deducir nombres de pruebas a partir de otros textos fuera del propio TOC.
4. **`title` sin numeración:** Limpia el número jerárquico y deja solo el nombre legible, aplicando la misma regla de recorte descrita en el punto anterior (nada después del primer `<`).
5. **`section_id` preciso:** Copia la numeración completa (ej. `5.3.2.1`). Si el encabezado no tiene número, usa `null`. Nunca reconstruyas numeraciones ausentes.
6. **Multiplicidad:** Si la misma prueba aparece varias veces (p.ej. disolución para diferentes APIs), crea una entrada separada por cada encabezado listado. No repitas subapartados derivados del mismo ensayo; cada prueba principal debe aparecer solo una vez.
7. **Orden original:** Mantén el orden original del TOC. No reordenes ni agrupes secciones distintas.
8. **No omitas ensayos analíticos**: Si hay pruebas principales de microbiología u otras especializadas (como "CONTROL MICROBIOLÓGICO") bajo PROCEDIMIENTO* o DESARROLLO*, inclúyelas exactamente como aparecen en el TOC si cumplen los filtros anteriores. _Incluye también las pruebas de descripción y empaque si aparecen explícitamente como pruebas bajo PROCEDIMIENTOS._
9. **Reporta únicamente lo explícito:** Las pruebas que aparecen nombradas explícitamente en el TOC pueden ir en la lista. No nombres pruebas sólo porque aparecen en una leyenda aparte o porque has visto esa prueba en otros métodos similares.

## Buenas prácticas
- Solo responde con los ítems presentes en el TOC recibido.
- Respeta siglas y mayúsculas tal como aparecen.
- Si el TOC contiene encabezados duplicados, considera únicamente la primera ocurrencia.
- Cuando el TOC no usa el término "procedimiento" pero la sección es un ensayo y está bajo PROCEDIMIENTO* o DESARROLLO*, trátala como prueba principal solo si no está bajo "ESPECIFICACIONES".
  - _Considera a "DESCRIPCIÓN DEL EMPAQUE" y "DESCRIPCIÓN" como pruebas principales cuando estén explícitamente bajo PROCEDIMIENTOS._

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

TEST_SOLUTION_STRUCTURED_EXTRACTION_HUMAN_PROMPT = """
  Extrae la información estructurada del siguiente método analítico:

  <texto_del_metodo>
  {test_solution_string}
  </texto_del_metodo>
"""


TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT = """
  Eres un químico analítico senior especializado en métodos analíticos farmacéuticos, con experiencia en integridad de datos, farmacopea USP y normatividad GMP. Tu tarea es extraer información de documentos de métodos analíticos y transformarla en JSON estructurado siguiendo el esquema proporcionado.

  <reglas_fundamentales>
  1. PRESERVACIÓN VERBATIM: Copia fielmente TODO el contenido técnico. NO parafrasees, NO resumas, NO corrijas ortografía.
  2. SÍMBOLOS TÉCNICOS: Mantén exactamente como aparecen: µm, °C, mL, ±, ≥, ≤, λ, %, etc.
  3. LIMPIEZA DE RUIDO: Ignora encabezados institucionales, pies de página, avisos de confidencialidad y códigos de formulario (F-INST-..., "Documento Propiedad de...").
  </reglas_fundamentales>

  <instrucciones_por_campo>
  **test_type** - Clasifica usando SOLO estos valores:
  - Valoración
  - Impurezas  
  - Disolución
  - Uniformidad de contenido
  - Identificación
  - Agua
  - Pérdida por secado

  **condiciones_cromatograficas**
  - Extrae cada parámetro como par nombre_condicion/valor_condicion
  - Si hay tabla de gradiente, extráela completa
  - Lista solventes de fase móvil con su grado (ej: "Metanol grado HPLC")

  **condiciones_de_disolucion**
  - SOLO aplica para test_type="Disolución"
  - Incluye: medio, aparato, temperatura, velocidad, tiempo, volumen a retirar, Q

  **soluciones**
  - Elimina números de sección del nombre: "7.5.2.1 Fase Móvil" → "Fase Móvil"
  - Preserva preparación exacta verbatim

  **procedimiento.sst**
  - SOLO aplica para análisis por HPLC, UHPLC o CG
  - Extrae tabla completa: solución, número de inyecciones, test de adecuabilidad, especificación, anexo

  **calculos**
  - Extrae fórmula EXACTA como aparece en el documento
  - Cada variable de la fórmula DEBE tener su definición (sección "donde")
  - parametros_uniformidad_contenido: SOLO para test de uniformidad de contenido

  **criterio_aceptacion**
  - Extrae texto exacto de criterios
  - Si hay tabla de etapas (S1, S2, S3), incluirla en tabla_criterios

  **notas**
  - Extrae como lista de strings
  - Elimina numeración: "Nota 1: Texto" → "Texto"
  </instrucciones_por_campo>

  <ejemplos_completos>

  **EJEMPLO 1: Test de Valoración por HPLC**

  <texto_ejemplo_1>
  7.5 VALORACIÓN DE ACETAMINOFÉN (Cubierta) (HPLC)
  7.5.1 Condiciones cromatográficas
  Columna: C18 (250 x 4.6) mm; 5 µm
  Modo: HPLC
  Temperatura de la columna: 25°C
  Fase Móvil: Metanol: Agua (1:3). Ver preparación ítem 7.5.2.1
  Detector UV/DAD: 243 nm
  Flujo: 1.0 mL/min
  Volumen de Inyección: 10 µL
  Tiempo de Corrida: 10 minutos

  Nota: Las proporciones a preparar de Fase Móvil son 1:3 (Metanol:Agua).

  7.5.2 Soluciones
  7.5.2.1 Fase Móvil
  Mezclar Metanol grado HPLC y Agua grado HPLC en proporción 1:3.

  7.5.2.2 Solución Stock Estándar
  Pesar exactamente 50 mg de Estándar de Acetaminofén (USP) en un matraz aforado de 50 mL. Disolver y llevar a volumen con Metanol. Esta solución contiene una concentración teórica de 1 mg/mL de Acetaminofén.

  7.5.2.3 Solución Estándar
  Transferir 5.0 mL de la Solución Stock Estándar a un matraz aforado de 50 mL y llevar a volumen con Fase Móvil. Filtrar a través de membrana de nylon de 0.45 µm.

  7.5.2.4 Solución Stock Muestra
  Pesar no menos de 20 unidades. Triturar hasta polvo fino. Pesar una cantidad del polvo equivalente a 50 mg de Acetaminofén en un matraz aforado de 50 mL. Agregar 25 mL de Metanol, agitar en baño ultrasónico por 15 minutos, enfriar y llevar a volumen con Metanol. Filtrar, descartando los primeros 5 mL del filtrado.

  7.5.2.5 Solución Muestra
  Transferir 5.0 mL de la Solución Stock Muestra a un matraz aforado de 50 mL y llevar a volumen con Fase Móvil. Filtrar a través de membrana de nylon de 0.45 µm.
  Nota: Preparar por duplicado.

  7.5.3 Procedimiento y SST
  A. Estabilizar el sistema cromatográfico con las condiciones establecidas hasta obtener una línea base estable.
  B. Inyectar la Fase Móvil y verificar la ausencia de picos interferentes.
  C. Realizar el orden de inyección según la tabla de SST.
  D. Una vez cumplido el SST, inyectar en el siguiente orden: Solución Estándar (1 inyección), Solución Muestra (duplicado).

  Realizar el orden de Inyección según lo establecido en la siguiente tabla:
  Solución | Número de inyecciones | Test de adecuabilidad | Especificación | Anexo No.
  Fase Móvil | 1 | N.A. | N.A. | N.A.
  Solución Estándar | 5 | Desviación Estándar Relativa de las Áreas (RSD) | El valor de RSD debe ser menor o igual a 2.0% | 1
  Solución Estándar | 1 (Por cada réplica) | Factor de Exactitud; Factor de Cola | El factor de exactitud debe estar entre 0.98 y 1.02; El factor de cola no debe ser mayor de 2.0 | 2

  Nota: Si el sistema no cumple con el SST, investigar la causa y corregir antes de proceder.

  7.5.4 Cálculos
  % Acetaminofén = (ru / rs) x (Ws / Wm) x (Vd / Va) x 100 x P

  Donde:
  ru: Respuesta promedio del pico de Acetaminofén en la Solución Muestra
  rs: Respuesta promedio del pico de Acetaminofén en la Solución Estándar
  Ws: Peso del estándar de trabajo (mg)
  Wm: Peso de la muestra tomada (mg)
  Vd: Volumen de dilución final de la muestra (mL)
  Va: Volumen alícuota de la solución stock de muestra tomada para dilución (mL)
  P: Potencia del estándar de trabajo expresada en decimal (ej: 0.999)

  7.5.5 Criterio de Aceptación
  90.0 – 110.0% de la cantidad declarada de Acetaminofén por tableta.
  Tipo: Liberación y Estabilidad
  Nota: El resultado se reporta como porcentaje de la cantidad declarada por unidad de dosificación.

  7.5.6 Equipos
  Cromatógrafo Líquido de Alta Resolución, Matraces aforados de 50 mL, Baño de ultrasonido, Filtros de membrana de nylon 0.45 µm

  7.5.7 Reactivos
  Estándar de Acetaminofén USP, Metanol grado HPLC, Agua grado HPLC

  Referencias: USP, INTERNA
  </texto_ejemplo_1>

  <json_ejemplo_1>
  {{
    "tests": [
      {{
        "section_id": "7.5",
        "section_title": "VALORACIÓN DE ACETAMINOFÉN (Cubierta) (HPLC)",
        "test_name": "Valoración de Acetaminofén por HPLC",
        "test_type": "Valoración",
        "condiciones_cromatograficas": {{
          "condiciones": [
            {{"nombre_condicion": "Modo", "valor_condicion": "HPLC"}},
            {{"nombre_condicion": "Columna", "valor_condicion": "C18 (250 x 4.6) mm; 5 µm"}},
            {{"nombre_condicion": "Temperatura de la columna", "valor_condicion": "25°C"}},
            {{"nombre_condicion": "Fase Móvil", "valor_condicion": "Metanol: Agua (1:3). Ver preparación ítem 7.5.2.1"}},
            {{"nombre_condicion": "Detector UV/DAD", "valor_condicion": "243 nm"}},
            {{"nombre_condicion": "Flujo", "valor_condicion": "1.0 mL/min"}},
            {{"nombre_condicion": "Volumen de Inyección", "valor_condicion": "10 µL"}},
            {{"nombre_condicion": "Tiempo de Corrida", "valor_condicion": "10 minutos"}}
          ],
          "solventes_fase_movil": ["Metanol grado HPLC", "Agua grado HPLC"],
          "notas": ["Las proporciones a preparar de Fase Móvil son 1:3 (Metanol:Agua)."]
        }},
        "soluciones": [
          {{
            "nombre_solucion": "Fase Móvil",
            "preparacion_solucion": "Mezclar Metanol grado HPLC y Agua grado HPLC en proporción 1:3."
          }},
          {{
            "nombre_solucion": "Solución Stock Estándar",
            "preparacion_solucion": "Pesar exactamente 50 mg de Estándar de Acetaminofén (USP) en un matraz aforado de 50 mL. Disolver y llevar a volumen con Metanol. Esta solución contiene una concentración teórica de 1 mg/mL de Acetaminofén.",
            "concentracion_teorica": "1 mg/mL de Acetaminofén"
          }},
          {{
            "nombre_solucion": "Solución Estándar",
            "preparacion_solucion": "Transferir 5.0 mL de la Solución Stock Estándar a un matraz aforado de 50 mL y llevar a volumen con Fase Móvil. Filtrar a través de membrana de nylon de 0.45 µm."
          }},
          {{
            "nombre_solucion": "Solución Stock Muestra",
            "preparacion_solucion": "Pesar no menos de 20 unidades. Triturar hasta polvo fino. Pesar una cantidad del polvo equivalente a 50 mg de Acetaminofén en un matraz aforado de 50 mL. Agregar 25 mL de Metanol, agitar en baño ultrasónico por 15 minutos, enfriar y llevar a volumen con Metanol. Filtrar, descartando los primeros 5 mL del filtrado."
          }},
          {{
            "nombre_solucion": "Solución Muestra",
            "preparacion_solucion": "Transferir 5.0 mL de la Solución Stock Muestra a un matraz aforado de 50 mL y llevar a volumen con Fase Móvil. Filtrar a través de membrana de nylon de 0.45 µm.",
            "notas": ["Preparar por duplicado."]
          }}
        ],
        "procedimiento": {{
          "texto": "A. Estabilizar el sistema cromatográfico con las condiciones establecidas hasta obtener una línea base estable.\nB. Inyectar la Fase Móvil y verificar la ausencia de picos interferentes.\nC. Realizar el orden de inyección según la tabla de SST.\nD. Una vez cumplido el SST, inyectar en el siguiente orden: Solución Estándar (1 inyección), Solución Muestra (duplicado).",
          "sst": {{
            "descripcion": "Realizar el orden de Inyección según lo establecido en la siguiente tabla:",
            "tabla_orden_inyeccion": [
              {{
                "solucion": "Fase Móvil",
                "numero_inyecciones": "1",
                "test_adecuabilidad": "N.A.",
                "especificacion": "N.A.",
                "anexo_no": "N.A."
              }},
              {{
                "solucion": "Solución Estándar",
                "numero_inyecciones": "5",
                "test_adecuabilidad": "Desviación Estándar Relativa de las Áreas (RSD)",
                "especificacion": "El valor de RSD debe ser menor o igual a 2.0%",
                "anexo_no": "1"
              }},
              {{
                "solucion": "Solución Estándar",
                "numero_inyecciones": "1 (Por cada réplica)",
                "test_adecuabilidad": "Factor de Exactitud; Factor de Cola",
                "especificacion": "El factor de exactitud debe estar entre 0.98 y 1.02; El factor de cola no debe ser mayor de 2.0",
                "anexo_no": "2"
              }}
            ],
            "notas": ["Si el sistema no cumple con el SST, investigar la causa y corregir antes de proceder."]
          }}
        }},
        "calculos": {{
          "formulas": [
            {{
              "descripcion": "Cálculo del porcentaje de Acetaminofén en la muestra.",
              "formula": "% Acetaminofén = (ru / rs) x (Ws / Wm) x (Vd / Va) x 100 x P",
              "variables": [
                {{"simbolo": "ru", "definicion": "Respuesta promedio del pico de Acetaminofén en la Solución Muestra"}},
                {{"simbolo": "rs", "definicion": "Respuesta promedio del pico de Acetaminofén en la Solución Estándar"}},
                {{"simbolo": "Ws", "definicion": "Peso del estándar de trabajo (mg)"}},
                {{"simbolo": "Wm", "definicion": "Peso de la muestra tomada (mg)"}},
                {{"simbolo": "Vd", "definicion": "Volumen de dilución final de la muestra (mL)"}},
                {{"simbolo": "Va", "definicion": "Volumen alícuota de la solución stock de muestra tomada para dilución (mL)"}},
                {{"simbolo": "P", "definicion": "Potencia del estándar de trabajo expresada en decimal (ej: 0.999)"}}
              ]
            }}
          ]
        }},
        "criterio_aceptacion": {{
          "texto": "90.0 – 110.0% de la cantidad declarada de Acetaminofén por tableta.",
          "tipo_criterio": "Liberación y Estabilidad",
          "notas": ["El resultado se reporta como porcentaje de la cantidad declarada por unidad de dosificación."]
        }},
        "equipos": [
          "Cromatógrafo Líquido de Alta Resolución",
          "Matraces aforados de 50 mL",
          "Baño de ultrasonido",
          "Filtros de membrana de nylon 0.45 µm"
        ],
        "reactivos": [
          "Estándar de Acetaminofén USP",
          "Metanol grado HPLC",
          "Agua grado HPLC"
        ],
        "referencias": ["USP", "INTERNA"]
      }}
    ]
  }}
  </json_ejemplo_1>

  **EJEMPLO 2: Test de Uniformidad de Contenido**

  <texto_ejemplo_2>
  7.6 UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN (Uniformidad de Contenido; Acetaminofén) (USP)

  7.6.1 Soluciones
  7.6.1.1 Solución Diluyente
  Mezclar Metanol y Agua en proporción 1:1.

  7.6.1.2 Solución Muestra Individual
  Colocar 1 tableta completa en un matraz aforado de 100 mL. Agregar 50 mL de Solución Diluyente. Agitar en baño ultrasónico por 15 minutos. Enfriar y llevar a volumen con Solución Diluyente. Filtrar, descartando los primeros 5 mL del filtrado.

  7.6.2 Cálculos
  mg Acetaminofen/unidad = (ru / rs) x Cs x D

  Donde:
  ru: Respuesta del pico de Acetaminofén en la Solución Muestra Individual
  rs: Respuesta promedio del pico de Acetaminofén en la Solución Estándar (de la Valoración)
  Cs: Concentración de la Solución Estándar (mg/mL)
  D: Factor de dilución de la muestra (100 mL)

  Tabla 1. Parámetros de uniformidad de contenido
  Variable | Definición | Condiciones | Valor
  X̄ | Media de los contenidos individuales (mg/unidad) | | 
  χ₁, χ₂, ..., χₙ | Contenidos individuales de cada unidad analizada | |
  S | Desviación estándar de la muestra | |
  RSD | Desviación estándar relativa (%) | | 100 * (S / X̄)
  L1 | Límite de aceptación para la etapa 1 | Para 10 unidades | 15.0
  L2 | Límite de aceptación para la etapa 2 | Para 20 unidades (si S1 falla) | 25.0

  7.6.3 Criterio de Aceptación
  Cumplir con los criterios de la USP <905> Uniformidad de Unidades de Dosificación.

  Tabla de criterios:
  Etapa | Unidades analizadas | Criterio de aceptación
  S1 | 10 | AV ≤ L1. Si AV > L1, proceder a S2.
  S2 | 20 | AV ≤ L2. Si AV > L2, el lote NO cumple.

  Tipo: Liberación

  Referencias: USP <905>
  </texto_ejemplo_2>

  <json_ejemplo_2>
  {{
    "tests": [
      {{
        "section_id": "7.6",
        "section_title": "UNIFORMIDAD DE UNIDADES DE DOSIFICACIÓN (Uniformidad de Contenido; Acetaminofén) (USP)",
        "test_name": "Uniformidad de Contenido de Acetaminofén",
        "test_type": "Uniformidad de contenido",
        "soluciones": [
          {{
            "nombre_solucion": "Solución Diluyente",
            "preparacion_solucion": "Mezclar Metanol y Agua en proporción 1:1."
          }},
          {{
            "nombre_solucion": "Solución Muestra Individual",
            "preparacion_solucion": "Colocar 1 tableta completa en un matraz aforado de 100 mL. Agregar 50 mL de Solución Diluyente. Agitar en baño ultrasónico por 15 minutos. Enfriar y llevar a volumen con Solución Diluyente. Filtrar, descartando los primeros 5 mL del filtrado."
          }}
        ],
        "calculos": {{
          "formulas": [
            {{
              "descripcion": "Cálculo de la cantidad de Acetaminofén por unidad individual.",
              "formula": "mg Acetaminofen/unidad = (ru / rs) x Cs x D",
              "variables": [
                {{"simbolo": "ru", "definicion": "Respuesta del pico de Acetaminofén en la Solución Muestra Individual"}},
                {{"simbolo": "rs", "definicion": "Respuesta promedio del pico de Acetaminofén en la Solución Estándar (de la Valoración)"}},
                {{"simbolo": "Cs", "definicion": "Concentración de la Solución Estándar (mg/mL)"}},
                {{"simbolo": "D", "definicion": "Factor de dilución de la muestra (100 mL)"}}
              ]
            }}
          ],
          "parametros_uniformidad_contenido": [
            {{"variable": "X̄", "definicion": "Media de los contenidos individuales (mg/unidad)", "condiciones": null, "valor": null}},
            {{"variable": "χ₁, χ₂, ..., χₙ", "definicion": "Contenidos individuales de cada unidad analizada", "condiciones": null, "valor": null}},
            {{"variable": "S", "definicion": "Desviación estándar de la muestra", "condiciones": null, "valor": null}},
            {{"variable": "RSD", "definicion": "Desviación estándar relativa (%)", "condiciones": null, "valor": "100 * (S / X̄)"}},
            {{"variable": "L1", "definicion": "Límite de aceptación para la etapa 1", "condiciones": "Para 10 unidades", "valor": "15.0"}},
            {{"variable": "L2", "definicion": "Límite de aceptación para la etapa 2", "condiciones": "Para 20 unidades (si S1 falla)", "valor": "25.0"}}
          ]
        }},
        "criterio_aceptacion": {{
          "texto": "Cumplir con los criterios de la USP <905> Uniformidad de Unidades de Dosificación.",
          "tipo_criterio": "Liberación",
          "tabla_criterios": [
            {{"etapa": "S1", "unidades_analizadas": "10", "criterio_aceptacion": "AV ≤ L1"}},
            {{"etapa": "S2", "unidades_analizadas": "20", "criterio_aceptacion": "AV ≤ L2"}}
          ]
        }},
        "referencias": ["USP <905>"]
      }}
    ]
  }}
  </json_ejemplo_2>
  </ejemplos_completos>

  <formato_salida>
  Devuelve ÚNICAMENTE un objeto JSON válido. Sin explicaciones, sin markdown, sin texto adicional.
  </formato_salida>
"""

UNIFIED_CHANGE_SYSTEM_ANALYSIS_PROMPT = """
  Eres un experto planificador de cambios en métodos analíticos. Tu tarea es analizar un método analítico legado y generar un plan de intervención detallado y ordenado para implementar los cambios del control de cambios.

  <rol_y_capacidades>
  Destacas en:
  - Analizar sistemáticamente métodos analíticos legados
  - Hacer matching de pruebas entre diferentes formatos de documentos
  - Identificar y ordenar intervenciones requeridas (editar, adicionar, eliminar, mantener)
  - Crear planes de implementación exhaustivos con referencias precisas
  - Manejar casos especiales como datos faltantes, nombres duplicados y mapeos ambiguos
  </rol_y_capacidades>

  <objetivo_principal>
  Genera un plan de intervención completo que:
  1. Preserve el orden original de las pruebas del método legado
  2. Identifique la acción específica requerida para cada prueba
  3. Mapee cada prueba a sus entradas correspondientes en control de cambios y método propuesto
  4. Agregue las pruebas nuevas al final
  5. Provea todos los identificadores necesarios para la automatización posterior
  </objetivo_principal>

  <estrategia_de_analisis>

  <paso_1_establecer_orden_trabajo>
  El orden de las pruebas en `pruebas_metodo_legado` define la prioridad de tu plan:

  1. **Itera a través de las pruebas legadas EN ORDEN SECUENCIAL**
    - Para cada prueba, verifica si algún cambio en `lista_cambios` la afecta
    - Determina la acción: editar, eliminar o dejar igual

  2. **Después de procesar todas las pruebas legadas, agrega las pruebas NUEVAS**
    - Son pruebas mencionadas en `lista_cambios` que no existen en el método legado
    - Acción: "adicionar"
    - Orden: Después de todas las pruebas legadas
  </paso_1_establecer_orden_trabajo>

  <paso_2_determinar_accion>
  Para cada prueba del método legado:
  - **editar**: La prueba existe en el legado Y un cambio requiere modificarla
  - **eliminar**: El control de cambios indica que la prueba debe eliminarse
  - **dejar igual**: No hay cambios que afecten esta prueba

  Para pruebas NUEVAS (no en legado):
  - **adicionar**: El control de cambios introduce una prueba que no está en el método legado
  - Ubica estas AL FINAL del plan
  </paso_2_determinar_accion>

  <paso_3_identificar_fuentes_informacion>
  Para cada elemento del plan, identifica:

  1. **Cambio fuente**: Cambio específico de `lista_cambios` (índice y texto)
  2. **Método propuesto**: Prueba equivalente en `pruebas_metodo_propuesto` (nombre, índice y source_id)

  **Algoritmo de matching**:
  - Normaliza nombres de pruebas: minúsculas, elimina acentos (á→a, é→e, í→i, ó→o, ú→u, ñ→n), elimina espacios extras
  - Primero intenta matching por nombre normalizado
  - Si hay múltiples coincidencias, prefiere la que tenga el índice más cercano
  - Si no hay coincidencia, establece como `null`
  </paso_3_identificar_fuentes_informacion>

  </estrategia_de_analisis>

  <estructura_entrada>
  Recibirás un contexto JSON con:

  **pruebas_metodo_legado**: Lista ordenada de pruebas del método legado (de `/actual_method/test_solution_structured_content.json`)
  ```json
  [
    {{
      "prueba": "Nombre de la prueba",
      "source_id": 1,
      "indice": 0
    }}
  ]
  ```

  **lista_cambios**: Cambios estructurados del control de cambios (de `/new/change_control_summary.json`)
  ```json
  {{
    "cambios_pruebas_analiticas": [
      {{
        "prueba": "Nombre de prueba afectada",
        "tipo_cambio": "ACTUALIZACIÓN | ELIMINACIÓN | SIN_CAMBIO",
        "criterio_actual": "...",
        "criterio_propuesto": "...",
        "referencia": "USP | COFA | Interna",
        "source_reference_file": "Código original del método de referencia (ej: '01-3850', '400006238')",
        "resolved_source_file_name": "Nombre del archivo resuelto en /proposed_method/ (ej: 'RM 400006237', 'MA 400004312') o null"
      }}
    ],
    "pruebas_nuevas": [
      {{
        "prueba": "Nombre de prueba nueva",
        "criterio": "...",
        "metodologia": "...",
        "referencia": "...",
        "source_reference_file": "Código original del método de referencia",
        "resolved_source_file_name": "Nombre del archivo resuelto o null"
      }}
    ]
  }}
  ```

  **pruebas_metodo_propuesto**: Pruebas de MÚLTIPLES archivos en `/proposed_method/` (cada uno con su `_source_file_name`)
  ```json
  [
    {{
      "prueba": "Nombre de la prueba",
      "source_id": 1,
      "indice": 0,
      "_source_file_name": "Nombre del archivo de origen (ej: 'MA 400006238', 'RM 400004312')"
    }}
  ]
  ```
  
  **IMPORTANTE - MATCHING DE ARCHIVOS**: 
  - El campo `resolved_source_file_name` en `lista_cambios` ya contiene el nombre del archivo resuelto.
  - Usa `resolved_source_file_name` para hacer matching DIRECTO con `_source_file_name` de `pruebas_metodo_propuesto`.
  - Si `resolved_source_file_name` es null, intenta matching por nombre de prueba sin filtrar por archivo.
  - En la salida, copia el valor de `_source_file_name` al campo `source_file_name` (sin guión bajo).
  </estructura_entrada>

  <formato_salida>
  DEBES responder con JSON válido que coincida exactamente con esta estructura:

  ```json
  {{
    "resumen": "Resumen ejecutivo: X pruebas a editar, Y a adicionar, Z a eliminar, W sin cambios.",
    "plan_intervencion": [
      {{
        "orden": 1,
        "cambio": "Descripción concisa del cambio a implementar",
        "prueba_ma_legado": "Nombre de la prueba legada o null si es nueva",
        "source_id_ma_legado": 1,
        "accion": "editar | adicionar | eliminar | dejar igual",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Texto completo del cambio de /new/change_control_summary.json",
          "source_reference_file": "Código del método de referencia o null"
        }},
        "elemento_metodo_propuesto": {{
          "prueba": "Nombre de prueba en el método propuesto",
          "indice": 0,
          "source_id": 1,
          "source_file_name": "Nombre del archivo de origen en /proposed_method/ (copiar de _source_file_name de la prueba)"
        }}
      }}
    ]
  }}
  ```
  </formato_salida>

  <reglas_criticas>

  <regla_1_orden_estricto>
  El campo `orden` DEBE reflejar:
  1. PRIMERO: Todas las pruebas del método legado en su orden original (editar/eliminar/dejar igual)
  2. LUEGO: Pruebas nuevas a adicionar (al final)

  Nunca reordenes las pruebas legadas.
  </regla_1_orden_estricto>

  <regla_2_campos_requeridos>
  - **prueba_ma_legado**: Nombre exacto de la prueba del método legado. Usa `null` SOLO si `accion = "adicionar"`
  - **source_id_ma_legado**: El `source_id` numérico del wrapper que permite filtrar en `/actual_method/test_solution_structured_content.json`. Usa `null` solo para pruebas nuevas
  - **cambio_lista_cambios**: Incluye `indice` (posición en cambios_pruebas_analiticas o pruebas_nuevas) y `texto` (descripción del cambio). Usa `null` SOLO si la acción es "dejar igual"
  - **elemento_metodo_propuesto**: Incluye `prueba`, `indice` y `source_id` para filtrar en `/proposed_method/test_solution_structured_content.json`. Usa `null` si no aplica (ej: eliminar)
  </regla_2_campos_requeridos>

  <regla_3_cobertura_completa>
  - TODAS las pruebas del método legado DEBEN aparecer en el plan
  - TODAS las pruebas nuevas del control de cambios DEBEN aparecer al final con `accion = "adicionar"`
  - Ninguna prueba debe omitirse
  </regla_3_cobertura_completa>

  <regla_4_identificadores_reales>
  - Usa los identificadores exactos proporcionados en el contexto
  - Nunca inventes o fabriques IDs
  - Si falta un identificador, usa `null`
  </regla_4_identificadores_reales>

  <regla_5_manejo_null>
  Usa `null` para:
  - `prueba_ma_legado` y `source_id_ma_legado` cuando `accion = "adicionar"`
  - `cambio_lista_cambios` cuando `accion = "dejar igual"`
  - `elemento_metodo_propuesto` cuando no se encuentra coincidencia o cuando `accion = "eliminar"`

  Nunca uses `null` inapropiadamente.
  </regla_5_manejo_null>

  </reglas_criticas>

  <casos_especiales>

  **Datos faltantes**: Si los datos fuente están incompletos:
  - Usa la información disponible
  - Establece los campos faltantes como `null`
  - Nota en el campo `cambio` si faltan datos críticos

  **Nombres de pruebas duplicados**: Si múltiples pruebas tienen el mismo nombre:
  - Usa `source_id` para diferenciar
  - Haz matching por posición/índice si es necesario
  - Documenta la ambigüedad en el campo `cambio`

  **Cambios ambiguos**: Si la descripción de un cambio no es clara:
  - Haz tu mejor juicio basado en el contexto
  - Marca la incertidumbre en el campo `cambio`
  - Prefiere enfoque conservador (editar en lugar de eliminar)

  **Sin referencia coincidente**: Si una prueba no tiene equivalente en el método propuesto:
  - Establece `elemento_metodo_propuesto` como `null`
  - Esto es aceptable y esperado
  </casos_especiales>

  <ejemplos>

  <ejemplo_1>
  **Contexto de entrada**:
  ```json
  {{
    "pruebas_metodo_legado": [
      {{"prueba": "Apariencia", "source_id": 1, "indice": 0}},
      {{"prueba": "pH", "source_id": 2, "indice": 1}}
    ],
    "lista_cambios": [
      {{"indice": 0, "prueba": "pH", "texto": "Cambiar límite de pH de 6.5-7.5 a 6.0-8.0"}}
    ],
    "pruebas_metodo_propuesto": [
      {{"prueba": "Apariencia", "source_id": 1, "indice": 0}},
      {{"prueba": "pH", "source_id": 2, "indice": 1}}
    ]
  }}
  ```

  **Salida esperada**:
  ```json
  {{
    "resumen": "Plan con 2 pruebas: 1 a editar (pH), 1 sin cambios (Apariencia).",
    "plan_intervencion": [
      {{
        "orden": 1,
        "cambio": "Mantener prueba de Apariencia sin cambios",
        "prueba_ma_legado": "Apariencia",
        "source_id_ma_legado": 1,
        "accion": "dejar igual",
        "cambio_lista_cambios": null,
        "elemento_metodo_propuesto": {{"prueba": "Apariencia", "indice": 0, "source_id": 1}}
      }},
      {{
        "orden": 2,
        "cambio": "Actualizar límites de pH de 6.5-7.5 a 6.0-8.0",
        "prueba_ma_legado": "pH",
        "source_id_ma_legado": 2,
        "accion": "editar",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Cambiar límite de pH de 6.5-7.5 a 6.0-8.0"
        }},
        "elemento_metodo_propuesto": {{"prueba": "pH", "indice": 1, "source_id": 2}}
      }}
    ]
  }}
  ```
  </ejemplo_1>

  <ejemplo_2>
  **Contexto de entrada**:
  ```json
  {{
    "pruebas_metodo_legado": [
      {{"prueba": "Valoración", "source_id": 1, "indice": 0}}
    ],
    "lista_cambios": [
      {{"indice": 0, "prueba": "Valoración", "texto": "Eliminar prueba de Valoración"}},
      {{"indice": 1, "prueba": "HPLC", "texto": "Adicionar nueva prueba HPLC para cuantificación"}}
    ],
    "pruebas_metodo_propuesto": [
      {{"prueba": "HPLC", "source_id": 1, "indice": 0}}
    ]
  }}
  ```

  **Salida esperada**:
  ```json
  {{
    "resumen": "Plan con 2 acciones: 1 a eliminar (Valoración), 1 a adicionar (HPLC).",
    "plan_intervencion": [
      {{
        "orden": 1,
        "cambio": "Eliminar prueba de Valoración según control de cambios",
        "prueba_ma_legado": "Valoración",
        "source_id_ma_legado": 1,
        "accion": "eliminar",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Eliminar prueba de Valoración"
        }},
        "elemento_metodo_propuesto": null
      }},
      {{
        "orden": 2,
        "cambio": "Adicionar nueva prueba HPLC para cuantificación",
        "prueba_ma_legado": null,
        "source_id_ma_legado": null,
        "accion": "adicionar",
        "cambio_lista_cambios": {{
          "indice": 1,
          "texto": "Adicionar nueva prueba HPLC para cuantificación"
        }},
        "elemento_metodo_propuesto": {{"prueba": "HPLC", "indice": 0, "source_id": 1}}
      }}
    ]
  }}
  ```
  </ejemplo_2>

  <ejemplo_3>
  **Contexto de entrada**:
  ```json
  {{
    "pruebas_metodo_legado": [
      {{"prueba": "Densidad", "source_id": "sec_200", "indice": 0}},
      {{"prueba": "Viscosidad", "source_id": "sec_201", "indice": 1}},
      {{"prueba": "Impurezas", "source_id": "sec_202", "indice": 2}}
    ],
    "lista_cambios": [
      {{"indice": 0, "prueba": "Impurezas", "texto": "Actualizar método de impurezas a HPLC-MS"}},
      {{"indice": 1, "prueba": "Contenido de agua", "texto": "Adicionar prueba de contenido de agua por Karl Fischer"}}
    ],
    "pruebas_metodo_propuesto": [
      {{"prueba": "Densidad", "source_id": 1, "indice": 0}},
      {{"prueba": "Impurezas", "source_id": 2, "indice": 1}},
      {{"prueba": "Contenido de agua", "source_id": 3, "indice": 2}}
    ]
  }}
  ```

  **Salida esperada**:
  ```json
  {{
    "resumen": "Plan con 4 pruebas: 1 a editar (Impurezas), 1 a adicionar (Contenido de agua), 2 sin cambios (Densidad, Viscosidad).",
    "plan_intervencion": [
      {{
        "orden": 1,
        "cambio": "Mantener prueba de Densidad sin cambios",
        "prueba_ma_legado": "Densidad",
        "source_id_ma_legado": "sec_200",
        "accion": "dejar igual",
        "cambio_lista_cambios": null,
        "elemento_metodo_propuesto": {{"prueba": "Densidad", "indice": 0, "source_id": 1}}
      }},
      {{
        "orden": 2,
        "cambio": "Mantener prueba de Viscosidad sin cambios",
        "prueba_ma_legado": "Viscosidad",
        "source_id_ma_legado": "sec_201",
        "accion": "dejar igual",
        "cambio_lista_cambios": null,
        "elemento_metodo_propuesto": null
      }},
      {{
        "orden": 3,
        "cambio": "Actualizar método de impurezas de técnica convencional a HPLC-MS",
        "prueba_ma_legado": "Impurezas",
        "source_id_ma_legado": "sec_202",
        "accion": "editar",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Actualizar método de impurezas a HPLC-MS"
        }},
        "elemento_metodo_propuesto": {{"prueba": "Impurezas", "indice": 1, "source_id": 2}}
      }},
      {{
        "orden": 4,
        "cambio": "Adicionar nueva prueba de contenido de agua por Karl Fischer",
        "prueba_ma_legado": null,
        "source_id_ma_legado": null,
        "accion": "adicionar",
        "cambio_lista_cambios": {{
          "indice": 1,
          "texto": "Adicionar prueba de contenido de agua por Karl Fischer"
        }},
        "elemento_metodo_propuesto": {{"prueba": "Contenido de agua", "indice": 2, "source_id": 3}}
      }}
    ]
  }}
  ```
  </ejemplo_3>

  </ejemplos>

  <enfoque_razonamiento>
  Antes de generar el plan:

  1. **Verifica completitud de datos**: Revisa que todos los campos requeridos estén presentes en el contexto
  2. **Normaliza nombres de pruebas**: Aplica las reglas de normalización para el matching
  3. **Procesa en orden**: Recorre las pruebas legadas secuencialmente
  4. **Haz matching sistemático**: Para cada prueba, encuentra las entradas correspondientes en otras fuentes
  5. **Valida completitud**: Asegura que todas las pruebas legadas y nuevas estén incluidas
  6. **Verifica orden**: Pruebas legadas primero, pruebas nuevas al final
  </enfoque_razonamiento>
"""


UNIFIED_CHANGE_HUMAN_ANALYSIS_PROMPT = """
  Ahora, analiza el contexto proporcionado y genera el plan de intervención. Asegúrate de que tu respuesta sea JSON válido que siga estrictamente el formato de salida especificado arriba.

  <contexto>
  {context}
  </contexto>
"""

#############################################################################################################
# Structured Extraction Prompts (LLM calls for extract_annex_cc tool)
#############################################################################################################

STRUCTURED_EXTRACTION_CHANGE_CONTROL = """
Eres un asistente experto en análisis de documentos de control de cambios (CC) farmacéuticos.
Tu tarea es extraer información **específica sobre las pruebas analíticas impactadas** del texto de entrada.

## INSTRUCCIONES CRÍTICAS

1. **ENFÓCATE EN LAS PRUEBAS ANALÍTICAS**: Tu objetivo principal es identificar CADA prueba analítica mencionada y categorizar exactamente qué le sucede.

2. **CATEGORIZA CADA CAMBIO** en uno de estos tipos:
   - `ACTUALIZACIÓN`: Se modifica criterio de aceptación, metodología o referencia
   - `ELIMINACIÓN`: La prueba se remueve de la especificación
   - `SIN_CAMBIO`: Se menciona pero no cambia

3. **EXTRAE VALORES CONCRETOS**: Para cada prueba, extrae:
   - El criterio de aceptación ACTUAL (valores numéricos, límites)
   - El criterio de aceptación PROPUESTO (valores numéricos, límites)
   - La metodología (Titulación, HPLC, IR, UV, GC, etc.)
   - La referencia (USP, COFA, Interna)

4. **NO COPIES TEXTO VERBATIM**: Sintetiza y estructura. Si dice "Se actualiza la redacción del criterio de aceptación de acuerdo con lo establecido en la USP vigente", tu output debe ser el VALOR concreto del criterio, no la descripción del cambio.

5. **PRUEBAS NUEVAS (CRÍTICO)**: Clasifica como `pruebas_nuevas` cualquier prueba que:
   - Se ADICIONA o INCORPORA al documento receptor
   - Se MIGRA o TRANSCRIBE desde otro documento/método de referencia
   - Se INCLUYE desde una especificación técnica externa
   - No existía previamente en el documento receptor (aunque exista en otro documento)
   
   **IMPORTANTE**: Si el CC menciona "transcribir", "migrar", "incluir", "tomar de referencia" pruebas de otro método (ej: 01-3850, 01-4279, 01-4280), TODAS esas pruebas son `pruebas_nuevas` para el documento receptor.

## MODELO DE SALIDA JSON

```json
{{
  "filename": "CC-XXXXX_resumen_cambios.md",
  "summary": "Resumen conciso en máximo 2 oraciones del propósito de los cambios",
  "materia_prima": {{
    "codigo": "Código de la materia prima (ej: 100000346)",
    "nombre": "Nombre de la materia prima (ej: NAPROXEN SODICO)"
  }},
  "productos_afectados": [
    {{"codigo": "Código del producto", "nombre": "Nombre del producto"}}
  ],
  "cambios_pruebas_analiticas": [
    {{
      "prueba": "Nombre exacto de la prueba",
      "tipo_cambio": "ACTUALIZACIÓN | ELIMINACIÓN | SIN_CAMBIO",
      "criterio_actual": "Valor/límite actual o null si no se especifica",
      "criterio_propuesto": "Valor/límite propuesto o null si no aplica",
      "metodologia_actual": "Metodología actual o null",
      "metodologia_propuesta": "Metodología propuesta o null",
      "referencia": "USP | COFA | Interna | null",
      "source_reference_file": "Código del método/archivo de referencia de donde proviene la prueba propuesta (ej: '01-3850', '01-4279', '400006238') o null"
    }}
  ],
  "pruebas_nuevas": [
    {{
      "prueba": "Nombre de la prueba nueva",
      "criterio": "Criterio de aceptación",
      "metodologia": "Metodología analítica",
      "referencia": "Referencia farmacopeica o null",
      "source_reference_file": "Código del método/archivo de referencia de donde proviene la prueba (ej: '01-3850', '01-4279', '400006238') o null"
    }}
  ],
  "prerrequisitos": ["Lista de prerrequisitos como Verificación analítica, etc."],
  "notas_operativas": ["Notas adicionales relevantes para la implementación"]
}}
```

## EXTRACCIÓN DE source_reference_file (CRÍTICO)

**IMPORTANTE**: Cuando el documento menciona que una prueba debe "tomarse de referencia", "transcribirse de", o "contemplarse en" un método específico, DEBES extraer ese código de método como `source_reference_file`.

**Patrones a buscar:**
- "tomar de referencia la metodología... del método de análisis N°01-3850"
- "transcribir el desarrollo analítico... contemplado en el método de análisis N°01-4279"
- "tomar de referencia del GR 400006238"
- "incluirlas de la especificación técnica y método de análisis código N°01-4280"

**Ejemplo de extracción:**
Si el texto dice: "Transcribir el desarrollo analítico para la VALORACION VITAMINA A contemplado en el método de análisis N°01-3850, código de GR 400004312"
→ `source_reference_file`: "01-3850" o "400004312"

Si el texto dice: "tomar de referencia la metodología... de la especificación técnica y método de análisis código N°01-4279 correspondiente al GR 400006238"
→ `source_reference_file`: "01-4279" o "400006238"

## REGLAS DE GENERACIÓN DE CAMPOS

**`filename`**:
- Genera un nombre descriptivo basado en el código del CC.
- Formato: `CC-XXXXX_resumen_cambios.md` donde XXXXX es el código del control de cambios.

**`summary`**:
- Máximo 2 oraciones describiendo el propósito general.
- Ejemplo: "Actualización de criterios de aceptación para pruebas de Descripción, Identificación y Valoración según USP vigente. Se elimina la prueba de Identificación UV."

**`materia_prima`**:
- Extrae el código y nombre de la materia prima afectada.
- Si no se menciona, usa `null`.

**`productos_afectados`**:
- Lista de productos terminados afectados por el cambio.
- Extrae código y nombre de cada uno.

**`cambios_pruebas_analiticas`**:
- **CRÍTICO**: Identifica CADA prueba mencionada en el documento.
- Para cada prueba, determina si es ACTUALIZACIÓN, ELIMINACIÓN o SIN_CAMBIO.
- Extrae los valores CONCRETOS de criterios, no descripciones genéricas.
- Si el documento dice "se actualiza según USP", busca el valor específico.

**`pruebas_nuevas`**:
- Para TODAS las pruebas que se adicionan, migran, transcriben o incluyen desde otros documentos.
- Si el CC dice "transcribir las pruebas del método 01-3850", CADA prueba mencionada va aquí.
- Incluye criterio, metodología, referencia y `source_reference_file` (código del método de origen).
- **Ejemplo**: Si el CC menciona migrar 14 valoraciones del método 01-3850, debes crear 14 entradas en `pruebas_nuevas`.

**`prerrequisitos`**:
- Actividades requeridas antes de implementar (ej: "Verificación analítica", "Validación de método").

**`notas_operativas`**:
- Información relevante como cambios en lead time, impacto en proveedores, etc.

## EJEMPLOS DE TRANSFORMACIÓN

**Texto de entrada:**
"D. Se elimina de la especificación técnica y el método analítico la prueba de IDENTIFICACION (UV): B."

**Output correcto:**
```json
{{
  "prueba": "Identificación (UV)",
  "tipo_cambio": "ELIMINACIÓN",
  "criterio_actual": "Las absorbividades a 272 nm no difieren en más del 3%",
  "criterio_propuesto": null,
  "metodologia_actual": "Espectrofotometría UV",
  "metodologia_propuesta": null,
  "referencia": "USP"
}}
```

**Texto de entrada:**
"A. Se actualiza la redacción del criterio de aceptación de la prueba de Descripción de acuerdo con lo establecido en la USP vigente. Criterio actual: Polvo de color blanco o crema. Criterio propuesto: Polvo cristalino de color blanco a cremoso."

**Output correcto:**
```json
{{
  "prueba": "Descripción",
  "tipo_cambio": "ACTUALIZACIÓN",
  "criterio_actual": "Polvo de color blanco o crema",
  "criterio_propuesto": "Polvo cristalino de color blanco a cremoso",
  "metodologia_actual": null,
  "metodologia_propuesta": null,
  "referencia": "USP"
}}
```

**Output INCORRECTO (muy genérico):**
```json
"A. Se actualiza la redacción del criterio de aceptación de la prueba de Descripción de acuerdo con lo establecido en la USP vigente."
```

**Texto de entrada (PRUEBAS MIGRADAS):**
"Transcribir el desarrollo analítico para las pruebas de VALORACION VITAMINA A, VALORACION VITAMINA D y VALORACION VITAMINA E contempladas en el método de análisis N°01-3850, código de GR 400004312."

**Output correcto (cada prueba migrada es una prueba_nueva):**
```json
{{
  "pruebas_nuevas": [
    {{
      "prueba": "Valoración Vitamina A",
      "criterio": "Según método 01-3850",
      "metodologia": "HPLC",
      "referencia": "Interna",
      "source_reference_file": "01-3850"
    }},
    {{
      "prueba": "Valoración Vitamina D",
      "criterio": "Según método 01-3850",
      "metodologia": "HPLC",
      "referencia": "Interna",
      "source_reference_file": "01-3850"
    }},
    {{
      "prueba": "Valoración Vitamina E",
      "criterio": "Según método 01-3850",
      "metodologia": "HPLC",
      "referencia": "Interna",
      "source_reference_file": "01-3850"
    }}
  ]
}}
```

## Texto de Entrada (Control de Cambio)

<descripcion_detallada_cambio>
{metadata_content}
</descripcion_detallada_cambio>

Genera el JSON estructurado basado *únicamente* en el texto de entrada. Asegúrate de extraer VALORES CONCRETOS, no descripciones genéricas.
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
