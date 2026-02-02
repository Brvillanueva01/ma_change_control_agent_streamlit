import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional

import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from langsmith import traceable
from pydantic import BaseModel, Field

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC

logger = logging.getLogger(__name__)

DEFAULT_BASE_PATH = "/actual_method"

CHUNK_SIZE_TOKENS = 3000
CHUNK_OVERLAP_TOKENS = 0
CHUNK_SEPARATORS = [
    "\n\n",
    "\n",
    ". ",
    "? ",
    "! ",
    "; ",
    " ",
    "",
]

# Patrones para identificar secciones de PROCEDIMIENTOS/DESARROLLO
PROCEDURES_SECTION_PATTERNS = [
    # Español
    r"^#+\s*\d*\.?\d*\s*PROCEDIMIENTOS?\b",
    r"^#+\s*\d*\.?\d*\s*DESARROLLO\b",
    r"^\d+\.?\s*PROCEDIMIENTOS?\b",
    r"^\d+\.?\s*DESARROLLO\b",
    r"^\*\*\s*\d*\.?\d*\s*PROCEDIMIENTOS?\b",
    r"^\*\*\s*\d*\.?\d*\s*DESARROLLO\b",
    # Inglés
    r"^#+\s*\d*\.?\d*\s*PROCEDURES?\b",
    r"^#+\s*\d*\.?\d*\s*ANALYTICAL\s+PROCEDURES?\b",
    r"^#+\s*\d*\.?\d*\s*TEST\s+PROCEDURES?\b",
    r"^\d+\.?\s*PROCEDURES?\b",
    r"^\d+\.?\s*ANALYTICAL\s+PROCEDURES?\b",
    r"^\d+\.?\s*TEST\s+PROCEDURES?\b",
    r"^\*\*\s*\d*\.?\d*\s*PROCEDURES?\b",
    r"^\*\*\s*\d*\.?\d*\s*ANALYTICAL\s+PROCEDURES?\b",
    r"^\*\*\s*\d*\.?\d*\s*TEST\s+PROCEDURES?\b",
]

# Patrones para identificar secciones que terminan PROCEDIMIENTOS
END_PROCEDURES_PATTERNS = [
    # Español
    r"^#+\s*\d+\.?\s*REFERENCIA",
    r"^#+\s*\d+\.?\s*ANEXOS?",
    r"^#+\s*\d+\.?\s*DOCUMENTOS\s+RELACIONADOS",
    r"^#+\s*\d+\.?\s*HIST[ÓO]RICO",
    r"^\d+\.?\s*REFERENCIA",
    r"^\d+\.?\s*ANEXOS?",
    r"^\d+\.?\s*DOCUMENTOS\s+RELACIONADOS",
    r"^\d+\.?\s*HIST[ÓO]RICO",
    # Inglés
    r"^#+\s*\d+\.?\s*REFERENCES?\b",
    r"^#+\s*\d+\.?\s*ANNEX(?:ES)?\b",
    r"^#+\s*\d+\.?\s*APPENDIX(?:ES)?\b",
    r"^#+\s*\d+\.?\s*RELATED\s+DOCUMENTS\b",
    r"^#+\s*\d+\.?\s*SUPPORTING\s+DOCUMENTS\b",
    r"^#+\s*\d+\.?\s*(CHANGE|REVISION)\s+HISTORY\b",
    r"^\d+\.?\s*REFERENCES?\b",
    r"^\d+\.?\s*ANNEX(?:ES)?\b",
    r"^\d+\.?\s*APPENDIX(?:ES)?\b",
    r"^\d+\.?\s*RELATED\s+DOCUMENTS\b",
    r"^\d+\.?\s*SUPPORTING\s+DOCUMENTS\b",
    r"^\d+\.?\s*(CHANGE|REVISION)\s+HISTORY\b",
]

CHUNK_SYSTEM_PROMPT_LATAM = """
### ROLE
Eres un experto en análisis de documentos de métodos analíticos farmacéuticos. Tu objetivo es identificar ÚNICAMENTE los **NOMBRES DE PRUEBAS ANALÍTICAS PRINCIPALES** de la sección de **PROCEDIMIENTOS** de un documento en formato Markdown.

### TASK
Analiza el texto en Markdown e identifica SOLO los encabezados que corresponden a **PRUEBAS ANALÍTICAS** dentro de la sección de PROCEDIMIENTOS/DESARROLLO. Las pruebas pueden aparecer:
- Con numeración (ej: "5.1 DESCRIPCIÓN", "## 5.8 VALORACIÓN")
- Sin numeración (ej: "DESCRIPCIÓN (USP)", "**VALORACIÓN (USP)**", "SOLVENTES RESIDUALES (USP)")
- En diferentes formatos: encabezados markdown (#, ##), texto en negrita (**texto**), o texto en mayúsculas dentro de tablas

### LENGUAJE
- Detecta el idioma predominante del texto. **No traduzcas.**
- Copia encabezados exactamente como aparezcan en el documento (si el documento está en inglés, devuelve los títulos en inglés; si está en español, en español).

Para cada prueba analítica detectada, extrae:
- `raw`: El encabezado/título EXACTO como aparece en el markdown (solo la línea del título, NO el contenido).
- `section_id`: El número de sección si existe (ej: "5.1", "5.8"), o `null` si no tiene numeración.
- `title`: El nombre de la prueba SIN la numeración inicial, copiado EXACTAMENTE como aparece.

### IMPORTANTE: SECCIÓN CORRECTA
- **SOLO** extrae pruebas de la sección **PROCEDIMIENTOS** o **DESARROLLO** (típicamente sección 5, 6 o 7 dependiendo del documento).
- **NUNCA** extraigas de la sección **ESPECIFICACIONES** (típicamente sección 3).
- **NUNCA** extraigas de la **TABLA DE CONTENIDO** o **ÍNDICE**.
- Las pruebas en ESPECIFICACIONES solo listan criterios de aceptación, NO procedimientos analíticos.

### CRITERIOS DE INCLUSIÓN (QUÉ SÍ EXTRAER)
Extrae encabezados que sean **pruebas analíticas** de la sección PROCEDIMIENTOS, tales como:
- DESCRIPCIÓN / DESCRIPCION
- PUNTO DE FUSIÓN / PUNTO DE FUSION
- IDENTIFICACIÓN / IDENTIFICACION (IR, UV, HPLC, etc.)
- VALORACIÓN / VALORACION / ENSAYO / POTENCIA
- PUREZA CROMATOGRÁFICA / PUREZA CROMATOGRAFICA
- SUSTANCIAS RELACIONADAS / IMPUREZAS / IMPUREZAS ORGÁNICAS / IMPUREZAS ORGANICAS
- PUREZA ENANTIOMÉRICA / PUREZA ENANTIOMERICA
- UNIFORMIDAD DE CONTENIDO / UNIFORMIDAD DE DOSIS
- DISOLUCIÓN / DISOLUCION
- pH
- PÉRDIDA POR SECADO / PERDIDA POR SECADO / HUMEDAD
- METALES PESADOS
- SOLVENTES RESIDUALES
- CENIZAS SULFATADAS
- LÍMITE MICROBIANO / LIMITE MICROBIANO
- ESTERILIDAD
- ENDOTOXINAS BACTERIANAS
- LÍMITE DE NAPROXENO LIBRE / NAPROXENO LIBRE (y similares para otros APIs)
- Otras pruebas analíticas con nombres similares

### CRITERIOS DE EXCLUSIÓN (QUÉ NO EXTRAER)
**NO extraigas** las siguientes secciones:
- **Entradas de TABLA DE CONTENIDO** (líneas con "..." seguido de número de página)
- **Sección ESPECIFICACIONES** (sección 3.x con criterios de aceptación, NO procedimientos)
- Preparación de soluciones (Solución estándar, Solución madre, Solución test, Solución muestra, Solución Stock, etc.)
- Preparación de reactivos (Tioacetamida SR, Buffer, Fase móvil, Diluyente, etc.)
- Condiciones cromatográficas / Condiciones Instrumentales
- Procedimiento / Procedimientos / Test de adecuabilidad (como subsección)
- Criterio de aceptación (como sección independiente)
- Cálculos / Fórmulas
- Equipos / Materiales
- Subsecciones numeradas con más de un punto decimal (ej: 5.1.1, 5.9.2, 5.10.3)
- Encabezados de página/documento (ej: "DE CAMBIO SC-25-777", "PRUEBAS PARA LA MATERIA PRIMA", "Página X de Y")
- **Parámetros de SST (Test de Adecuabilidad del Sistema)**: NO extraer parámetros que aparecen en tablas de orden de inyección como: "Relación Pico/Valle", "Desviación Estándar Relativa de las Áreas (RSD)", "Factor de Cola", "Factor de Exactitud", "Asimetría", "Señal/Ruido (S/N)", "Resolución", "Factor de Capacidad", "Platos Teóricos". Estos son parámetros de adecuabilidad, NO pruebas analíticas.
- **Contenido de celdas de tablas de SST**: Si el texto proviene de una tabla con columnas como "Solución", "Número de Inyecciones", "Test de Adecuabilidad", "Especificación", NO extraer ningún valor de esas celdas como prueba analítica.

### REGLAS DE EXTRACCIÓN
- **raw**: Copia SOLO la línea del encabezado/título EXACTAMENTE como aparece (incluyendo #, **, |, etc.), NO incluyas el contenido/procedimiento de la prueba.
- **section_id**: Extrae el número de sección si existe (ej: "7.1", "7.8"). Si NO hay número, usa `null`. **NUNCA inventes números de sección**.
- **title**: Copia el nombre de la prueba EXACTAMENTE como aparece, sin la numeración inicial.

### OUTPUT FORMAT
```json
{{
  "test_methods": [
    {{
      "raw": "string",
      "section_id": "string o null",
      "title": "string"
    }}
  ]
}}
```

Si no encuentras ninguna prueba analítica principal, devuelve:
```json
{{
  "test_methods": []
}}
```

### EJEMPLOS

**Ejemplo 1 - Prueba CON numeración:**
Input: "## 7.8 NAPROXENO LIBRE (USP)"
Output:
```json
{{
  "raw": "## 7.8 NAPROXENO LIBRE (USP)",
  "section_id": "7.8",
  "title": "NAPROXENO LIBRE (USP)"
}}
```

**Ejemplo 2 - Prueba SIN numeración (en tabla):**
Input: "|  DESCRIPCIÓN (USP)  |"
Output:
```json
{{
  "raw": "|  DESCRIPCIÓN (USP)  |",
  "section_id": null,
  "title": "DESCRIPCIÓN (USP)"
}}
```

**Ejemplo 3 - Prueba SIN numeración (texto plano en mayúsculas):**
Input: "SOLVENTES RESIDUALES (USP)"
Output:
```json
{{
  "raw": "SOLVENTES RESIDUALES (USP)",
  "section_id": null,
  "title": "SOLVENTES RESIDUALES (USP)"
}}
```

**Ejemplo 4 - Prueba SIN numeración (en negrita):**
Input: "**PRUEBA DE PUREZA ENANTIOMERICA (USP)**"
Output:
```json
{{
  "raw": "**PRUEBA DE PUREZA ENANTIOMERICA (USP)**",
  "section_id": null,
  "title": "PRUEBA DE PUREZA ENANTIOMERICA (USP)"
}}
```

**Ejemplo 5 - Prueba CON numeración y encabezado markdown:**
Input: "## IMPUREZAS ORGANICAS (USP)"
Output:
```json
{{
  "raw": "## IMPUREZAS ORGANICAS (USP)",
  "section_id": null,
  "title": "IMPUREZAS ORGANICAS (USP)"
}}
```

**Ejemplo 6 - NO es prueba analítica (NO extraer):**
Input: "### Solución Stock Estándar de Naproxeno Sódico"
→ NO extraer (es preparación de solución)

**Ejemplo 7 - NO es prueba analítica (NO extraer):**
Input: "## Procedimiento"
→ NO extraer (es un procedimiento, no una prueba)

**Ejemplo 8 - NO es prueba analítica (NO extraer):**
Input: "## Cálculos"
→ NO extraer (es sección de cálculos)
"""

CHUNK_SYSTEM_PROMPT_HRM = """
### ROLE
Eres un experto en análisis de documentos de métodos analíticos farmacéuticos. Tu objetivo es identificar **TODOS los NOMBRES DE PRUEBAS ANALÍTICAS PRINCIPALES** tanto en la sección de **PROCEDIMIENTOS/DESARROLLO** como en la sección **SPECIFICATIONS / ESPECIFICACIONES** (usualmente ítem 3 en métodos HRM) de un documento en formato Markdown.

### TASK
Analiza el texto en Markdown e identifica los encabezados que corresponden a **PRUEBAS ANALÍTICAS** dentro de las secciones válidas. Las pruebas pueden aparecer:
- Con numeración (ej: "3.1 DESCRIPTION", "## 7.1 IDENTIFICATION")
- Sin numeración (ej: "DESCRIPTION", "**APPEARANCE**", "IMPURITIES")
- En diferentes formatos: encabezados markdown (#, ##), texto en negrita (**texto**), texto plano en mayúsculas o dentro de tablas

### LENGUAJE
- Detecta el idioma predominante del texto. **No traduzcas.**
- Copia encabezados exactamente como aparezcan en el documento (si el documento está en inglés, devuelve los títulos en inglés; si está en español, en español).

Para cada prueba analítica detectada, extrae:
- `raw`: El encabezado/título EXACTO como aparece en el markdown (solo la línea del título, NO el contenido).
- `section_id`: El número de sección si existe (ej: "3.1", "7.1"), o `null` si no tiene numeración.
- `title`: El nombre de la prueba SIN la numeración inicial, copiado EXACTAMENTE como aparece.

### IMPORTANTE: SECCIONES VÁLIDAS
- **Incluye** pruebas que estén en **SPECIFICATIONS/ESPECIFICACIONES** (ítem 3) porque ahí se listan los criterios de aceptación en el formato HRM.
- **Incluye** pruebas en **PROCEDIMIENTOS/DESARROLLO**.
- **NUNCA** extraigas de la **TABLA DE CONTENIDO** o **ÍNDICE** ni de secciones generales como alcance, objetivo, glosario, referencias, anexos, históricos.

### CRITERIOS DE INCLUSIÓN
Extrae encabezados que sean **pruebas analíticas** en las secciones válidas:
- DESCRIPTION / APPEARANCE / DESCRIPCIÓN
- IDENTIFICATION / IDENTIFICACIÓN (IR, UV, HPLC, etc.)
- ASSAY / VALORACIÓN / ENSAYO / POTENCY
- DISSOLUTION / DISOLUCIÓN
- IMPURITIES / RELATED SUBSTANCES / SUSTANCIAS RELACIONADAS
- WATER / LOSS ON DRYING / PÉRDIDA POR SECADO / HUMEDAD
- pH
- UNIFORMITY OF DOSAGE UNITS / UNIFORMIDAD DE CONTENIDO
- RESIDUAL SOLVENTS / SOLVENTES RESIDUALES
- HEAVY METALS / METALES PESADOS
- MICROBIOLOGICAL LIMITS / ESTERILIDAD / ENDOTOXINAS
- Otras pruebas analíticas con nombres equivalentes

### CRITERIOS DE EXCLUSIÓN (QUÉ NO EXTRAER)
**NO extraigas** las siguientes secciones:
- **Entradas de TABLA DE CONTENIDO** (líneas con "..." seguido de número de página)
- Encabezados generales fuera de SPECIFICATIONS o PROCEDIMIENTOS (objetivo, alcance, anexos, referencias, históricos, glosario, definiciones)
- Preparación de soluciones, reactivos, condiciones instrumentales, cálculo, equipos
- Subsecciones numeradas con más de un punto decimal (ej: 5.1.1, 5.9.2, 5.10.3)
- Parámetros de SST u orden de inyección

### REGLAS DE EXTRACCIÓN
- `raw`: Copia SOLO la línea del encabezado/título EXACTAMENTE como aparece (incluyendo #, **, |, etc.), NO incluyas el contenido.
- `section_id`: Extrae el número de sección si existe. Si NO hay número, usa `null`. **NUNCA inventes números de sección**.
- `title`: Copia el nombre de la prueba EXACTAMENTE como aparece, sin la numeración inicial.

### OUTPUT FORMAT
```json
{
  "test_methods": [
    {
      "raw": "string",
      "section_id": "string o null",
      "title": "string"
    }
  ]
}
```

Si no encuentras ninguna prueba analítica principal, devuelve:
```json
{
  "test_methods": []
}
```

### EJEMPLOS

**Ejemplo 1 - HRM en SPECIFICATIONS:**
Input: "3.1 DESCRIPTION"
Output:
```json
{
  "raw": "3.1 DESCRIPTION",
  "section_id": "3.1",
  "title": "DESCRIPTION"
}
```

**Ejemplo 2 - Prueba en PROCEDIMIENTOS:**
Input: "## 7.5 ASSAY (HPLC)"
Output:
```json
{
  "raw": "## 7.5 ASSAY (HPLC)",
  "section_id": "7.5",
  "title": "ASSAY (HPLC)"
}
```

**Ejemplo 3 - NO es prueba analítica (NO extraer):**
Input: "## Objective"
→ NO extraer (es sección general)
"""

CHUNK_HUMAN_PROMPT_TEMPLATE = """
A continuación se encuentra la sección del documento a analizar:
 
<DOCUMENT_CHUNK>
{chunk_text}
</DOCUMENT_CHUNK>
"""

llm_model = init_chat_model(model="openai:gpt-5-mini")


def _normalize_method_format(value: Optional[str]) -> str:
    """Normaliza el formato de método recibido desde UI o prompts."""
    if not value:
        return "latam"
    value = value.strip().lower()
    if "hrm" in value:
        return "hrm"
    if "latam" in value:
        return "latam"
    return "latam"


def _infer_method_format(provided_format: Optional[str], markdown: str) -> str:
    """
    Determina el formato a utilizar.
    - Respeta el formato proporcionado explícitamente (UI/prompt).
    - Si no se proporcionó, detecta HRM cuando el documento contiene una sección 3.* SPECIFICATIONS.
    """
    normalized = _normalize_method_format(provided_format)
    if normalized != "latam":
        return normalized

    try:
        if re.search(r"(?im)^\\s*3\\.?\\s*specifications\\b", markdown or ""):
            return "hrm"
    except re.error:
        pass

    return "latam"


class TestMethodFromChunk(BaseModel):
    """Representa un encabezado de prueba/solución extraído de un chunk."""

    raw: str = Field(
        ...,
        description="Texto EXACTO del encabezado tal como aparece en el markdown.",
    )
    section_id: Optional[str] = Field(
        None,
        description="Número de sección (ej: 5.3, 7.2.1) o null si no existe.",
    )
    title: str = Field(
        ...,
        description="Nombre del encabezado sin la numeración inicial.",
    )


class TestMethodsFromChunk(BaseModel):
    """Lista de encabezados extraídos de un chunk."""

    test_methods: List[TestMethodFromChunk] = Field(
        default_factory=list,
        description="Lista de encabezados de pruebas/soluciones encontrados en el chunk.",
    )


def _create_text_splitter() -> RecursiveCharacterTextSplitter:
    """Crea el splitter con configuración de tokens para chunking semántico."""
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-4.1-mini",
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        separators=CHUNK_SEPARATORS,
    )


def _remove_toc_section(markdown: str) -> str:
    """
    Elimina la sección de TABLA DE CONTENIDO del markdown.
    
    Detecta patrones como:
    - "## TABLA DE CONTENIDO" hasta la siguiente sección principal
    - Líneas con formato de índice: "X.X NOMBRE ... N" (puntos suspensivos + número de página)
    """
    if not markdown:
        return ""
    
    lines = markdown.split("\n")
    filtered_lines: List[str] = []
    in_toc = False
    
    # Patrones para detectar inicio de TOC
    toc_start_patterns = [
        re.compile(r"^#+\s*TABLA\s+DE\s+CONTENIDO", re.IGNORECASE),
        re.compile(r"^#+\s*ÍNDICE", re.IGNORECASE),
        re.compile(r"^#+\s*INDICE", re.IGNORECASE),
        re.compile(r"^\*\*\s*TABLA\s+DE\s+CONTENIDO", re.IGNORECASE),
        re.compile(r"^#+\s*TABLE\s+OF\s+CONTENTS", re.IGNORECASE),
        re.compile(r"^#+\s*CONTENTS\b", re.IGNORECASE),
        re.compile(r"^\*\*\s*TABLE\s+OF\s+CONTENTS", re.IGNORECASE),
    ]
    
    # Patrón para detectar líneas de TOC (con ... y número de página)
    toc_line_pattern = re.compile(r"^[\d\.]+\s+[A-ZÁÉÍÓÚÑ].*\.{2,}\s*\d+\s*$", re.IGNORECASE)
    
    # Patrón para detectar nueva sección principal (fin de TOC)
    section_start_pattern = re.compile(r"^#+\s*\d+\.?\s+[A-ZÁÉÍÓÚÑ]", re.IGNORECASE)
    
    for line in lines:
        stripped = line.strip()
        
        # Detectar inicio de TOC
        if any(p.match(stripped) for p in toc_start_patterns):
            in_toc = True
            logger.debug("Detectado inicio de TOC: %s", stripped[:50])
            continue
        
        # Si estamos en TOC, verificar si es línea de índice o fin de TOC
        if in_toc:
            # Verificar si es una línea de TOC (con ...)
            if toc_line_pattern.match(stripped):
                continue
            # Verificar si es el inicio de una nueva sección (fin de TOC)
            if section_start_pattern.match(stripped) and not toc_line_pattern.match(stripped):
                in_toc = False
                filtered_lines.append(line)
                continue
            # Líneas vacías o de formato dentro del TOC se saltan
            if not stripped or stripped.startswith("|") or "..." in stripped:
                continue
        
        # Filtrar líneas sueltas que parecen entradas de TOC (con ... y número)
        if toc_line_pattern.match(stripped):
            continue
            
        filtered_lines.append(line)
    
    result = "\n".join(filtered_lines)
    logger.info("TOC removido: %d líneas originales -> %d líneas filtradas", len(lines), len(filtered_lines))
    return result


def _extract_procedures_section(markdown: str) -> str:
    """
    Extrae SOLO la sección de PROCEDIMIENTOS/DESARROLLO del markdown.
    
    Busca el inicio de secciones como:
    - "## 5 PROCEDIMIENTOS"
    - "## DESARROLLO"
    - "5. PROCEDIMIENTOS"
    
    Y extrae hasta la siguiente sección de nivel superior (REFERENCIA, ANEXOS, etc.)
    """
    if not markdown:
        return ""
    
    lines = markdown.split("\n")
    
    # Compilar patrones de inicio
    start_patterns = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in PROCEDURES_SECTION_PATTERNS]
    end_patterns = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in END_PROCEDURES_PATTERNS]
    
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    
    # Buscar inicio de sección PROCEDIMIENTOS
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if any(p.match(stripped) for p in start_patterns):
            start_idx = idx
            logger.info("Encontrada sección PROCEDIMIENTOS en línea %d: %s", idx, stripped[:60])
            break
    
    if start_idx is None:
        logger.warning("No se encontró sección PROCEDIMIENTOS/DESARROLLO en el documento")
        return markdown  # Devolver todo si no se encuentra la sección
    
    # Buscar fin de sección PROCEDIMIENTOS
    for idx, line in enumerate(lines[start_idx + 1:], start=start_idx + 1):
        stripped = line.strip()
        if any(p.match(stripped) for p in end_patterns):
            end_idx = idx
            logger.info("Fin de sección PROCEDIMIENTOS en línea %d: %s", idx, stripped[:60])
            break
    
    # Extraer la sección
    if end_idx is not None:
        extracted_lines = lines[start_idx:end_idx]
    else:
        extracted_lines = lines[start_idx:]
    
    result = "\n".join(extracted_lines)
    logger.info(
        "Sección PROCEDIMIENTOS extraída: líneas %d-%d (%d líneas)",
        start_idx,
        end_idx if end_idx else len(lines),
        len(extracted_lines)
    )
    return result


def _preprocess_markdown_for_extraction(markdown: str, include_specifications: bool = False) -> str:
    """
    Pre-procesa el markdown antes de la extracción:
    1. Elimina la tabla de contenido (TOC)
    2. Extrae solo la sección PROCEDIMIENTOS/DESARROLLO (formato LATAM)
       o conserva SPECIFICATIONS + PROCEDIMIENTOS (formato HRM)
    """
    if not markdown:
        return ""
    
    # Paso 1: Eliminar TOC
    markdown_without_toc = _remove_toc_section(markdown)
    
    # Paso 2: Controlar secciones según formato
    if include_specifications:
        # Para HRM conservamos el markdown completo (sin TOC) para incluir SPECIFICATIONS
        return markdown_without_toc

    # Para formato LATAM mantener solo PROCEDIMIENTOS/DESARROLLO
    procedures_section = _extract_procedures_section(markdown_without_toc)
    return procedures_section


def _split_markdown_into_chunks(full_markdown: str) -> List[str]:
    """Divide el markdown en chunks usando el splitter configurado."""
    if not full_markdown:
        return []
    splitter = _create_text_splitter()
    return splitter.split_text(full_markdown)


async def _extract_headers_from_chunk(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    system_prompt: str,
) -> TestMethodsFromChunk:
    """Extrae encabezados de un chunk individual usando el LLM."""
    structured_llm = llm_model.with_structured_output(TestMethodsFromChunk)

    system_message = SystemMessage(content=system_prompt)
    human_message = HumanMessage(
        content=CHUNK_HUMAN_PROMPT_TEMPLATE.format(
            chunk_text=chunk_text,
        )
    )

    try:
        result = await structured_llm.ainvoke([system_message, human_message])
        return result
    except Exception as e:
        logger.warning(
            "Error extrayendo encabezados del chunk %d/%d: %s",
            chunk_index,
            total_chunks,
            str(e),
        )
        return TestMethodsFromChunk(test_methods=[])


@traceable(name="extract_headers_parallel")
async def _extract_headers_from_all_chunks(
    chunks: List[str],
    system_prompt: str,
) -> List[TestMethodsFromChunk]:
    """Extrae encabezados de todos los chunks en paralelo."""
    if not chunks:
        return []

    total_chunks = len(chunks)
    logger.info("Procesando %d chunks en paralelo para extracción de encabezados...", total_chunks)

    tasks = [
        _extract_headers_from_chunk(chunk, idx + 1, total_chunks, system_prompt)
        for idx, chunk in enumerate(chunks)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results: List[TestMethodsFromChunk] = []
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Chunk %d falló con excepción: %s", idx + 1, str(result))
            valid_results.append(TestMethodsFromChunk(test_methods=[]))
        else:
            valid_results.append(result)

    return valid_results


def _clean_header_text(value: Optional[str]) -> str:
    """Limpia el texto de un encabezado, removiendo contenido después de '<'."""
    if not value:
        return ""
    text = value.strip()
    angle_idx = text.find("<")
    if angle_idx != -1:
        text = text[:angle_idx]
    return text.strip()


def _merge_headers_from_chunks(
    chunk_results: List[TestMethodsFromChunk],
) -> List[Dict[str, Optional[str]]]:
    """
    Combina los resultados de todos los chunks en una lista única.
    """
    merged: List[Dict[str, Optional[str]]] = []

    for chunk_result in chunk_results:
        if not chunk_result or not chunk_result.test_methods:
            continue

        for test in chunk_result.test_methods:
            raw_value = _clean_header_text(test.raw) or _clean_header_text(test.title)
            title_value = _clean_header_text(test.title)
            section_id = (test.section_id or "").strip() or None

            merged.append(
                {
                    "raw": raw_value or None,
                    "title": title_value or None,
                    "section_id": section_id,
                }
            )

    return merged


def _filter_primary_test_methods(
    test_methods: List[Dict[str, Optional[str]]],
) -> List[Dict[str, Optional[str]]]:
    """Filtra solo pruebas principales (sin subapartados profundos)."""
    if not test_methods:
        return []

    filtered: List[Dict[str, Optional[str]]] = []
    for test in test_methods:
        section_id = (test.get("section_id") or "").strip()
        if section_id:
            dot_count = section_id.count(".")
            if dot_count > 1:
                logger.debug(
                    "Descartando subapartado %s (%s) por numeración profunda",
                    test.get("title") or test.get("raw"),
                    section_id,
                )
                continue
        filtered.append(test)

    return filtered


def _find_header_positions(full_markdown: str, raw_header: str) -> List[int]:
    """Encuentra las posiciones de un encabezado en el markdown."""
    if not raw_header or not full_markdown:
        return []

    header = raw_header.strip()
    if not header:
        return []

    patterns: List[str] = [header]
    header_wo_number = re.sub(r"^\s*\d+(\.\d+)*\s+", "", header)
    if header_wo_number and header_wo_number != header:
        patterns.append(header_wo_number)

    header_wo_digits = re.sub(r"\d+", "", header).strip()
    if header_wo_digits and header_wo_digits not in patterns:
        patterns.append(header_wo_digits)

    for pattern in patterns:
        if not pattern:
            continue
        try:
            regex = re.compile(re.escape(pattern), flags=re.IGNORECASE)
        except re.error:
            logger.warning("Regex inválido para encabezado '%s'", raw_header)
            continue

        matches = list(regex.finditer(full_markdown))
        if matches:
            return [match.start() for match in matches]

    return []


def _find_historico_marker(full_markdown: str) -> Optional[int]:
    """Encuentra la posición del marcador 'Histórico de cambios'."""
    if not full_markdown:
        return None
    pattern = re.compile(r"hist[óo]rico\s+de\s+cambios", flags=re.IGNORECASE)
    match = pattern.search(full_markdown)
    return match.start() if match else None


@traceable(name="build_markdown_segments")
def _build_markdown_segments(
    test_methods: List[Dict[str, Optional[str]]],
    full_markdown: str,
) -> List[Dict[str, Optional[str]]]:
    """Construye los segmentos de markdown para cada prueba/solución."""
    if not test_methods:
        return []

    markers: List[Dict[str, int]] = []
    for idx, test in enumerate(test_methods):
        raw_header = (test.get("raw") or test.get("title") or "").strip()
        if not raw_header:
            logger.warning("No se encontró encabezado legible para la prueba %s", test)
            continue

        positions = _find_header_positions(full_markdown, raw_header)
        if not positions:
            logger.warning(
                "No se encontró el encabezado '%s' en el markdown consolidado",
                raw_header,
            )
            continue

        for pos in positions:
            markers.append({"test_index": idx, "start": pos})

    if not markers:
        return [
            {
                "id": idx + 1,
                "raw": test.get("raw"),
                "title": test.get("title"),
                "section_id": test.get("section_id"),
                "markdown": "",
            }
            for idx, test in enumerate(test_methods)
        ]

    markers.sort(key=lambda item: item["start"])
    segments_by_test: Dict[int, List[str]] = {}
    historico_marker = _find_historico_marker(full_markdown)

    for idx, marker in enumerate(markers):
        start = marker["start"]
        end = markers[idx + 1]["start"] if idx + 1 < len(markers) else len(full_markdown)
        if (
            historico_marker is not None
            and idx == len(markers) - 1
            and historico_marker >= start
        ):
            end = min(end, historico_marker)
        section_text = full_markdown[start:end].strip()
        if not section_text:
            continue
        segments_by_test.setdefault(marker["test_index"], []).append(section_text)

    results: List[Dict[str, Optional[str]]] = []
    for idx, test in enumerate(test_methods):
        markdown_chunks = segments_by_test.get(idx, [])
        combined_markdown = "\n\n".join(markdown_chunks).strip()
        results.append(
            {
                "id": idx + 1,
                "raw": test.get("raw"),
                "title": test.get("title"),
                "section_id": test.get("section_id"),
                "markdown": combined_markdown,
            }
        )

    return results


def _metadata_toc_path(base_path: str, source_file_name: str) -> str:
    """Genera la ruta del archivo de metadata/TOC."""
    base = (base_path or DEFAULT_BASE_PATH).rstrip("/")
    return f"{base}/method_metadata_TOC_{source_file_name}.json"


def _markdown_doc_path(base_path: str, source_file_name: str) -> str:
    """Genera la ruta del archivo de markdown de pruebas/soluciones."""
    base = (base_path or DEFAULT_BASE_PATH).rstrip("/")
    return f"{base}/test_solution_markdown_{source_file_name}.json"


@traceable(name="test_solution_clean_markdown")
def _run_extraction_pipeline(
    full_markdown: str,
    include_specifications: bool = False,
) -> List[Dict[str, Optional[str]]]:
    """
    Pipeline principal de extracción:
    0. Pre-procesa el markdown (elimina TOC y, según el formato, conserva SPECIFICATIONS)
    1. Divide el markdown en chunks
    2. Extrae encabezados de cada chunk en paralelo
    3. Deduplica y fusiona resultados
    4. Filtra solo pruebas principales
    5. Construye segmentos de markdown usando el markdown ORIGINAL (para preservar contexto)
    """
    # Paso 0: Pre-procesar markdown para extracción de headers
    preprocessed_markdown = _preprocess_markdown_for_extraction(
        full_markdown, include_specifications=include_specifications
    )
    logger.info(
        "Markdown pre-procesado: %d caracteres originales -> %d caracteres filtrados",
        len(full_markdown),
        len(preprocessed_markdown)
    )
    
    # Usar markdown pre-procesado para identificar headers
    chunks = _split_markdown_into_chunks(preprocessed_markdown)
    logger.info("Markdown dividido en %d chunks", len(chunks))

    if not chunks:
        return []

    system_prompt = CHUNK_SYSTEM_PROMPT_LATAM if not include_specifications else CHUNK_SYSTEM_PROMPT_HRM
    chunk_results = asyncio.run(_extract_headers_from_all_chunks(chunks, system_prompt))

    merged_headers = _merge_headers_from_chunks(chunk_results)
    logger.info("Se identificaron %d encabezados de pruebas/soluciones", len(merged_headers))

    filtered_headers = _filter_primary_test_methods(merged_headers)
    logger.info("Después de filtrar subapartados: %d pruebas principales", len(filtered_headers))

    # Usar el markdown pre-procesado para construir segmentos (evita duplicados de ESPECIFICACIONES)
    tests_with_markdown = _build_markdown_segments(filtered_headers, preprocessed_markdown)

    return tests_with_markdown


@tool(description=TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC)
def test_solution_clean_markdown(
    source_file_name: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    base_path: str = DEFAULT_BASE_PATH,
    method_format: str = "latam",
) -> Command:
    """
    Herramienta que extrae pruebas/soluciones del markdown usando chunking + LLM.

    Args:
        source_file_name: Nombre del archivo de origen (sin extensión, ej: 'MA 100000346')
        base_path: Ruta base (/actual_method o /proposed_method)
        method_format: 'latam' (default) o 'hrm'. HRM conserva la sección 3 SPECIFICATIONS para extraer criterios.
    
    Nuevo enfoque:
    1. Divide el markdown en chunks usando RecursiveCharacterTextSplitter
    2. Extrae encabezados de cada chunk en paralelo con GPT-4.1-mini
    3. Deduplica y fusiona los resultados
    4. Construye los segmentos de markdown para cada prueba
    """
    files = dict(state.get("files", {}))
    metadata_doc_name = _metadata_toc_path(base_path, source_file_name)
    markdown_doc_name = _markdown_doc_path(base_path, source_file_name)

    method_metadata_TOC = files.get(metadata_doc_name)

    if not method_metadata_TOC:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"No se encontró el archivo {metadata_doc_name}",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    metadata_toc_data = method_metadata_TOC.get("data", {})
    full_markdown = metadata_toc_data.get("markdown_completo")

    if not full_markdown:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"El archivo {metadata_doc_name} no contiene markdown consolidado.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    resolved_format = _infer_method_format(method_format, full_markdown)
    include_specifications = resolved_format == "hrm"

    tests_with_markdown = _run_extraction_pipeline(
        full_markdown, include_specifications=include_specifications
    )

    toc_entries = [
        test.get("raw") or test.get("title")
        for test in tests_with_markdown
        if test.get("raw") or test.get("title")
    ]

    payload = {
        "full_markdown": full_markdown,
        "toc_entries": toc_entries,
        "items": tests_with_markdown,
        "method_format": resolved_format,
    }

    content_str = json.dumps(payload, indent=2, ensure_ascii=False)
    files[markdown_doc_name] = {
        "content": content_str.split("\n"),
        "data": payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    total_items = len(tests_with_markdown)
    populated_items = sum(1 for item in tests_with_markdown if item.get("markdown"))
    summary_message = (
        f"Extracción completada para '{source_file_name}' "
        f"(formato: {resolved_format.upper()}): {total_items} pruebas/soluciones identificadas; "
        f"{populated_items} incluyen markdown extraído. Archivo: {markdown_doc_name}"
    )

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(summary_message, tool_call_id=tool_call_id)],
        }
    )
