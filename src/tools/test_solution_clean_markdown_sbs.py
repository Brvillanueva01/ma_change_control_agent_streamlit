import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from langsmith import traceable
from pydantic import BaseModel, Field

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import TEST_SOLUTION_CLEAN_MARKDOWN_SBS_TOOL_DESC

logger = logging.getLogger(__name__)

DEFAULT_BASE_PATH = "/proposed_method"

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

CHUNK_SYSTEM_PROMPT = """
    ### ROLE
    Eres un experto en análisis de documentos de métodos analíticos farmacéuticos. Tu objetivo es identificar ÚNICAMENTE los **NOMBRES DE PRUEBAS ANALÍTICAS PRINCIPALES** de un documento en formato Markdown.

    ### TASK
    Analiza el texto en Markdown e identifica SOLO los encabezados que corresponden a **PRUEBAS ANALÍTICAS**. Las pruebas pueden aparecer:
    - Con numeración (ej: "7.1 DESCRIPCIÓN", "## 7.8 VALORACIÓN")
    - Sin numeración (ej: "DESCRIPCIÓN (USP)", "**VALORACIÓN (USP)**", "SOLVENTES RESIDUALES (USP)")
    - En diferentes formatos: encabezados markdown (#, ##), texto en negrita (**texto**), o texto en mayúsculas dentro de tablas

    ### LENGUAJE
    - Detecta el idioma predominante del texto y manténlo. **No traduzcas.**
    - Copia los encabezados exactamente como aparezcan (si el documento está en inglés, devuelve los títulos en inglés; si está en español, en español).

    Para cada prueba analítica detectada, extrae:
    - `raw`: El encabezado/título EXACTO como aparece en el markdown (solo la línea del título, NO el contenido).
    - `section_id`: El número de sección si existe (ej: "7.1", "7.8"), o `null` si no tiene numeración.
    - `title`: El nombre de la prueba SIN la numeración inicial, copiado EXACTAMENTE como aparece.

    ### CRITERIOS DE INCLUSIÓN (QUÉ SÍ EXTRAER)
    Extrae encabezados que sean **pruebas analíticas**, tales como:
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
    - Preparación de soluciones (Solución estándar, Solución madre, Solución test, Solución muestra, Solución Stock, etc.)
    - Preparación de reactivos (Tioacetamida SR, Buffer, Fase móvil, Diluyente, etc.)
    - Condiciones cromatográficas / Condiciones Instrumentales
    - Procedimiento / Procedimientos / Test de adecuabilidad
    - Criterio de aceptación (como sección independiente)
    - Cálculos / Fórmulas
    - Equipos / Materiales
    - Subsecciones numeradas con más de un punto decimal (ej: 7.1.1, 7.9.2, 7.10.3)
    - Encabezados de página/documento (ej: "DE CAMBIO SC-25-777", "PRUEBAS PARA LA MATERIA PRIMA", "Página X de Y")
    
    **IMPORTANTE - NO extraigas contenido de tablas de adecuabilidad del sistema:**
    - Filas de tablas que contengan columnas como "Solución", "Número de Inyecciones", "Parámetro a evaluar", "Especificación"
    - Valores en columnas de "Parámetro a evaluar" (ej: "Resolución", "Señal/ruido", "Pureza Enantiomérica", "Identificación de picos", "Cuantificación Solvente Residual")
    - Filas que describen inyecciones de soluciones (ej: "Solución estándar | 1 | ...", "Solución muestra | 1 | ...")
    - Las pruebas analíticas son ENCABEZADOS/TÍTULOS de sección (##, ###, **texto**), NO contenido dentro de celdas de tablas de procedimiento
    
    **Parámetros de SST (Test de Adecuabilidad del Sistema) - NO extraer:**
    - "Relación Pico/Valle", "Desviación Estándar Relativa (%RSD)", "Factor de Cola", "Asimetría", "Señal/Ruido (S/N)", "Resolución R", "Factor de Capacidad", "Platos Teóricos"
    - Estos son PARÁMETROS de adecuabilidad que aparecen en tablas, NO pruebas analíticas principales

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

    **Ejemplo 9 - NO es prueba analítica (NO extraer - contenido de tabla de adecuabilidad):**
    Input: "|  Solución estándar | 1 | Identificación de picos | Identificar los picos principales...  |"
    → NO extraer ("Identificación de picos" es un PARÁMETRO A EVALUAR dentro de una tabla, NO un encabezado de prueba)

    **Ejemplo 10 - NO es prueba analítica (NO extraer - parámetro en tabla):**
    Input: "|  5. Resolución (Muestra) | 1 | Pureza Enantiomérica | No más de 2.5%  |"
    → NO extraer ("Pureza Enantiomérica" aquí es un parámetro de evaluación en una fila de tabla, NO un título de prueba)

    **Ejemplo 11 - NO es prueba analítica (NO extraer - parámetro en tabla):**
    Input: "|  Solución muestra (1 réplica) | 1 | Cuantificación Solvente Residual | Tolueno: No más de 890 ppm  |"
    → NO extraer (es una fila de tabla de procedimiento con parámetros, NO un encabezado de prueba)
"""

CHUNK_HUMAN_PROMPT_TEMPLATE = """
    A continuación se encuentra la sección del documento a analizar:
    
    <DOCUMENT_CHUNK>
    {chunk_text}
    </DOCUMENT_CHUNK>
"""

llm_model = init_chat_model(model="openai:gpt-5-mini", temperature=0)


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
        model_name="gpt-5-mini",
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        separators=CHUNK_SEPARATORS,
    )


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
) -> TestMethodsFromChunk:
    """Extrae encabezados de un chunk individual usando el LLM."""
    structured_llm = llm_model.with_structured_output(TestMethodsFromChunk)

    system_message = SystemMessage(content=CHUNK_SYSTEM_PROMPT)
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
) -> List[TestMethodsFromChunk]:
    """Extrae encabezados de todos los chunks en paralelo."""
    if not chunks:
        return []

    total_chunks = len(chunks)
    logger.info("Procesando %d chunks en paralelo para extracción de encabezados...", total_chunks)

    tasks = [
        _extract_headers_from_chunk(chunk, idx + 1, total_chunks)
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


@traceable(name="test_solution_clean_markdown_sbs")
def _run_extraction_pipeline(full_markdown: str) -> List[Dict[str, Optional[str]]]:
    """
    Pipeline principal de extracción:
    1. Divide el markdown en chunks
    2. Extrae encabezados de cada chunk en paralelo
    3. Deduplica y fusiona resultados
    4. Filtra solo pruebas principales
    5. Construye segmentos de markdown (sin pre-procesamiento adicional; la columna ya viene filtrada)
    """
    chunks = _split_markdown_into_chunks(full_markdown)
    logger.info("Markdown dividido en %d chunks", len(chunks))

    if not chunks:
        return []

    chunk_results = asyncio.run(_extract_headers_from_all_chunks(chunks))

    merged_headers = _merge_headers_from_chunks(chunk_results)
    logger.info("Se identificaron %d encabezados de pruebas/soluciones", len(merged_headers))

    filtered_headers = _filter_primary_test_methods(merged_headers)
    logger.info("Después de filtrar subapartados: %d pruebas principales", len(filtered_headers))

    tests_with_markdown = _build_markdown_segments(filtered_headers, full_markdown)

    return tests_with_markdown


@tool(description=TEST_SOLUTION_CLEAN_MARKDOWN_SBS_TOOL_DESC)
def test_solution_clean_markdown_sbs(
    source_file_name: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    base_path: str = DEFAULT_BASE_PATH,
) -> Command:
    """
    Herramienta que extrae pruebas/soluciones del markdown de documentos Side-by-Side.

    Args:
        source_file_name: Nombre del archivo de origen (sin extensión, ej: 'ANEXO NAPROXENO')
        base_path: Ruta base (/proposed_method por defecto)
    
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

    tests_with_markdown = _run_extraction_pipeline(full_markdown)

    toc_entries = [
        test.get("raw") or test.get("title")
        for test in tests_with_markdown
        if test.get("raw") or test.get("title")
    ]

    payload = {
        "full_markdown": full_markdown,
        "toc_entries": toc_entries,
        "items": tests_with_markdown,
    }

    files[markdown_doc_name] = {
        "content": json.dumps(payload, indent=2, ensure_ascii=False),
        "data": payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    total_items = len(tests_with_markdown)
    populated_items = sum(1 for item in tests_with_markdown if item.get("markdown"))
    summary_message = (
        f"Extracción completada para '{source_file_name}': {total_items} pruebas/soluciones identificadas; "
        f"{populated_items} incluyen markdown extraído. Archivo: {markdown_doc_name}"
    )

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(summary_message, tool_call_id=tool_call_id)],
        }
    )
