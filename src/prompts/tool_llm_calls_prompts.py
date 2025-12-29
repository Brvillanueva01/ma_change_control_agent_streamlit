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


TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT = """
# RESTRICCIÓN ABSOLUTA: GENERA EXACTAMENTE 1 TEST
El array `tests` en tu respuesta DEBE contener UN SOLO objeto. Si generas más de 1 elemento, tu respuesta será RECHAZADA. No dupliques contenido bajo ninguna circunstancia.

Rol: quimico analitico senior especializado en metodos farmaceuticos. Recibiras el markdown completo de **una sola** prueba o solucion (encabezado, numeracion y texto literal del metodo). Convierte esa entrada en un objeto `TestSolutions` que cumpla estrictamente con los modelos Pydantic provistos.

## Entrada
```markdown
{test_solution_string}
```

## Objetivo
- Identificar `section_id`, `section_title`, `test_name` y `test_type` de la prueba/solucion.
- Extraer toda la informacion estructurada disponible siguiendo el modelo `TestSolutions`.
- No inventes datos ni reformules el texto: si algo no aparece, deja `null` o listas vacias.

## Instrucciones de extraccion
1. **Section/title/test_name:** Usa la numeracion y el encabezado literal. Si no hay titulo o nombre de prueba, escribe "Por definir".
2. **Test type:** Elige solo entre estos valores: "Descripcion", "Identificacion", "Valoracion", "Impurezas", "Peso promedio", "Disolucion", "Uniformidad de contenido", "Control microbiologico", "Humedad en cascarilla", "Humedad en contenido", "Dureza", "Espesores", "Uniformidad de unidades de dosificacion", "Perdida por Secado", "Check list de autorizacion", "Hoja de trabajo instrumental HPLC", "Solucion", "Otros analisis". Si no es obvio, selecciona la etiqueta mas cercana al texto.
3. **Texto literal siempre:** Respeta ortografia, mayusculas y simbolos del documento. No resumes ni corriges. Si un campo es opcional y no hay informacion, usa `null` o `[]`.
4. **Condiciones cromatograficas:** Si se listan columna, fase movil, flujo, temperatura o gradiente, llevalas a `condiciones_cromatograficas` con pares `nombre_condicion`/`valor_condicion`. Si hay tabla de gradiente, usa `tabla_gradiente` (tiempo, proporcion_a, proporcion_b). Extrae los solventes de fase movil en `solventes_fase_movil` (ej: ["Agua (grado HPLC)", "Acetonitrilo"]). Notas adicionales van en `notas`.
5. **Soluciones:** Captura cada encabezado de solucion/fase movil/buffer/diluyente de esta prueba. `nombre_solucion` es el encabezado literal. `preparacion_solucion` es el bloque completo de preparacion copiado tal cual, desde la linea debajo del encabezado hasta antes del siguiente encabezado de solucion, procedimiento o criterio. Usa `notas` solo para aclaraciones textuales que no sean cantidades.
6. **Procedimiento:** Incluye solo el procedimiento de la prueba (no de las soluciones). Copia el bloque completo en `procedimiento.texto`. Usa `procedimiento.notas` para aclaraciones breves y `procedimiento.tiempo_retencion` si el texto trae tiempos relativos/factores de respuesta.
7. **Criterio de aceptacion:** Copia el texto literal en `criterio_aceptacion.texto`. Si hay tabla de etapas (S1/S2), llena `tabla_criterios` con `etapa`, `unidades_analizadas` y `criterio_aceptacion`. Notas opcionales en `notas`.
8. **Equipos y reactivos:** Lista literal de equipos o reactivos mencionados explicitamente en esta prueba (no agregues globales no vistos).
9. **Procedimiento SST:** Si se describe orden de inyeccion para adecuabilidad del sistema, registra cada entrada con `solucion`, `numero_inyecciones`, `test_adecuabilidad` y `especificacion`. Si no existe, deja `[]`.

## Formato de salida (JSON valido, EXACTAMENTE UN elemento en `tests`)

**REGLA CRÍTICA:** El array `tests` debe contener **EXACTAMENTE 1 objeto**. NUNCA generes 2 o más elementos en el array. Si detectas que estás a punto de duplicar el contenido, DETENTE inmediatamente.
```json
{{
  "tests": [
    {{
      "section_id": "...",
      "section_title": "...",
      "test_name": "...",
      "test_type": "...",
      "condiciones_cromatograficas": {{
        "condiciones": [
          {{
            "nombre_condicion": "...",
            "valor_condicion": "..."
          }}
        ],
        "tabla_gradiente": [
          {{
            "tiempo": ...,
            "proporcion_a": ...,
            "proporcion_b": ...
          }}
        ],
        "solventes_fase_movil": ["Agua (grado HPLC)", "Acetonitrilo (grado HPLC)"],
        "notas": ["..."]
      }},
      "soluciones": [
        {{
          "nombre_solucion": "...",
          "preparacion_solucion": "...",
          "notas": ["..."]
        }}
      ],
      "procedimiento": {{
        "texto": "...",
        "notas": ["..."],
        "tiempo_retencion": [
          {{
            "nombre": "...",
            "tiempo_relativo_retencion": "...",
            "factor_respuesta_relativa": "..."
          }}
        ]
      }},
      "criterio_aceptacion": {{
        "texto": "...",
        "notas": ["..."],
        "tabla_criterios": [
          {{
            "etapa": "...",
            "unidades_analizadas": "...",
            "criterio_aceptacion": "..."
          }}
        ]
      }},
      "equipos": ["..."],
      "reactivos": ["..."],
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
- No cites informacion que no este en el markdown recibido.
- Si el campo no aplica o no existe, usa `null` o `[]` segun corresponda.
- Devuelve un JSON valido y nada mas.
- **UN SOLO TEST:** El array `tests` debe tener EXACTAMENTE 1 elemento. Si generas más de 1, tu respuesta será inválida.
- **ANTI-REPETICION:** NUNCA repitas el mismo texto mas de una vez. Si hay referencias como "Ver Anexo X" o "Ver item X", mencionala UNA SOLA VEZ en el campo `referencias` como lista corta. No generes secuencias repetitivas.
- **LONGITUD MAXIMA:** El campo `referencias` debe tener maximo 5 elementos. Agrupa referencias similares si hay mas.
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
  3. Mapee cada prueba a sus entradas correspondientes en control de cambios, comparación lado a lado y métodos de referencia
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
  2. **Referencia lado a lado**: Prueba equivalente en `side_by_side.metodo_modificacion_propuesta` (nombre e índice)
  3. **Método de referencia**: Prueba equivalente en `metodos_referencia` (nombre e índice)

  **Algoritmo de matching**:
  - Normaliza nombres de pruebas: minúsculas, elimina acentos (á→a, é→e, í→i, ó→o, ú→u, ñ→n), elimina espacios extras
  - Primero intenta matching por nombre normalizado
  - Si hay múltiples coincidencias, prefiere la que tenga el índice más cercano
  - Si no hay coincidencia, establece como `null`
  </paso_3_identificar_fuentes_informacion>

  </estrategia_de_analisis>

  <estructura_entrada>
  Recibirás un contexto JSON con:

  **pruebas_metodo_legado**: Lista ordenada de pruebas del método legado
  ```json
  [
    {{
      "prueba": "Nombre de la prueba",
      "source_id": "section_id del JSON estructurado",
      "indice": 0
    }}
  ]
  ```

  **lista_cambios**: Cambios del control de cambios
  ```json
  [
    {{
      "indice": 0,
      "prueba": "Nombre de prueba afectada",
      "texto": "Descripción completa del cambio"
    }}
  ]
  ```

  **side_by_side**: Comparación lado a lado
  ```json
  {{
    "metodo_actual": [{{"prueba": "...", "source_id": "...", "indice": 0}}],
    "metodo_modificacion_propuesta": [{{"prueba": "...", "source_id": "...", "indice": 0}}]
  }}
  ```

  **metodos_referencia**: Pruebas de métodos de referencia
  ```json
  [
    {{"prueba": "...", "source_id": "...", "indice": 0}}
  ]
  ```
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
        "source_id_ma_legado": "section_id de /actual_method/test_solution_structured_content.json o null",
        "accion": "editar | adicionar | eliminar | dejar igual",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Texto completo del cambio de /new/change_control_summary.json"
        }},
        "elemento_side_by_side": {{
          "prueba": "Nombre de prueba en metodo_modificacion_propuesta",
          "indice": 0
        }},
        "elemento_metodo_referencia": {{
          "prueba": "Nombre de prueba en métodos de referencia",
          "indice": 0
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
  - **source_id_ma_legado**: El `section_id` que permite filtrar en `/actual_method/test_solution_structured_content.json`. Usa `null` solo para pruebas nuevas
  - **cambio_lista_cambios**: Siempre incluye `indice` y `texto` del cambio aplicable. Usa `null` SOLO si la acción es "dejar igual"
  - **elemento_side_by_side**: Incluye `prueba` e `indice` para filtrar en `/new/side_by_side.json`. Usa `null` si no aplica
  - **elemento_metodo_referencia**: Incluye `prueba` e `indice` para filtrar en `/new/reference_methods.json`. Usa `null` si no aplica
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
  - `elemento_side_by_side` o `elemento_metodo_referencia` cuando no se encuentra coincidencia

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

  **Sin referencia coincidente**: Si una prueba no tiene equivalente en lado a lado o referencia:
  - Establece los campos correspondientes como `null`
  - Esto es aceptable y esperado
  </casos_especiales>

  <ejemplos>

  <ejemplo_1>
  **Contexto de entrada**:
  ```json
  {{
    "pruebas_metodo_legado": [
      {{"prueba": "Apariencia", "source_id": "sec_001", "indice": 0}},
      {{"prueba": "pH", "source_id": "sec_002", "indice": 1}}
    ],
    "lista_cambios": [
      {{"indice": 0, "prueba": "pH", "texto": "Cambiar límite de pH de 6.5-7.5 a 6.0-8.0"}}
    ],
    "side_by_side": {{
      "metodo_actual": [{{"prueba": "pH", "source_id": "ph_old", "indice": 0}}],
      "metodo_modificacion_propuesta": [{{"prueba": "pH", "source_id": "ph_new", "indice": 0}}]
    }},
    "metodos_referencia": [{{"prueba": "pH", "source_id": "ref_ph", "indice": 0}}]
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
        "source_id_ma_legado": "sec_001",
        "accion": "dejar igual",
        "cambio_lista_cambios": null,
        "elemento_side_by_side": null,
        "elemento_metodo_referencia": null
      }},
      {{
        "orden": 2,
        "cambio": "Actualizar límites de pH de 6.5-7.5 a 6.0-8.0",
        "prueba_ma_legado": "pH",
        "source_id_ma_legado": "sec_002",
        "accion": "editar",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Cambiar límite de pH de 6.5-7.5 a 6.0-8.0"
        }},
        "elemento_side_by_side": {{
          "prueba": "pH",
          "indice": 0
        }},
        "elemento_metodo_referencia": {{
          "prueba": "pH",
          "indice": 0
        }}
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
      {{"prueba": "Valoración", "source_id": "sec_100", "indice": 0}}
    ],
    "lista_cambios": [
      {{"indice": 0, "prueba": "Valoración", "texto": "Eliminar prueba de Valoración"}},
      {{"indice": 1, "prueba": "HPLC", "texto": "Adicionar nueva prueba HPLC para cuantificación"}}
    ],
    "side_by_side": {{
      "metodo_actual": [],
      "metodo_modificacion_propuesta": [{{"prueba": "HPLC", "source_id": "hplc_1", "indice": 0}}]
    }},
    "metodos_referencia": [{{"prueba": "HPLC", "source_id": "ref_hplc", "indice": 0}}]
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
        "source_id_ma_legado": "sec_100",
        "accion": "eliminar",
        "cambio_lista_cambios": {{
          "indice": 0,
          "texto": "Eliminar prueba de Valoración"
        }},
        "elemento_side_by_side": null,
        "elemento_metodo_referencia": null
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
        "elemento_side_by_side": {{
          "prueba": "HPLC",
          "indice": 0
        }},
        "elemento_metodo_referencia": {{
          "prueba": "HPLC",
          "indice": 0
        }}
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
    "side_by_side": {{
      "metodo_actual": [
        {{"prueba": "Densidad", "source_id": "dens_old", "indice": 0}},
        {{"prueba": "Impurezas", "source_id": "imp_old", "indice": 1}}
      ],
      "metodo_modificacion_propuesta": [
        {{"prueba": "Densidad", "source_id": "dens_new", "indice": 0}},
        {{"prueba": "Impurezas", "source_id": "imp_new", "indice": 1}},
        {{"prueba": "Contenido de agua", "source_id": "water_new", "indice": 2}}
      ]
    }},
    "metodos_referencia": [
      {{"prueba": "Impurezas", "source_id": "ref_imp", "indice": 0}},
      {{"prueba": "Contenido de agua", "source_id": "ref_water", "indice": 1}}
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
        "elemento_side_by_side": {{
          "prueba": "Densidad",
          "indice": 0
        }},
        "elemento_metodo_referencia": null
      }},
      {{
        "orden": 2,
        "cambio": "Mantener prueba de Viscosidad sin cambios",
        "prueba_ma_legado": "Viscosidad",
        "source_id_ma_legado": "sec_201",
        "accion": "dejar igual",
        "cambio_lista_cambios": null,
        "elemento_side_by_side": null,
        "elemento_metodo_referencia": null
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
        "elemento_side_by_side": {{
          "prueba": "Impurezas",
          "indice": 1
        }},
        "elemento_metodo_referencia": {{
          "prueba": "Impurezas",
          "indice": 0
        }}
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
        "elemento_side_by_side": {{
          "prueba": "Contenido de agua",
          "indice": 2
        }},
        "elemento_metodo_referencia": {{
          "prueba": "Contenido de agua",
          "indice": 1
        }}
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
