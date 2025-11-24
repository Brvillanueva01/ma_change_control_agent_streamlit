import json
import logging
import re
import unicodedata
from typing import Annotated, Dict, List, Optional

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC
from src.prompts.tool_llm_calls_prompts import TEST_METHOD_GENERATION_TOC_PROMPT

logger = logging.getLogger(__name__)

TEST_SOLUTION_MARKDOWN_DOC_NAME = "/actual_method/test_solution_markdown.json"
TEST_METADATA_TOC_DOC_NAME = "/actual_method/method_metadata_TOC.json"
SOLUTION_KEYWORDS = [
    "solucion",
    "soluciones",
    "diluyente",
    "diluente",
    "diluent",
    "fase movil",
    "mobile phase",
    "solvente",
    "solvent",
    "buffer",
    "standard solution",
    "stock solution",
    "working solution",
    "solucion patron",
    "solucion estandar",
    "solucion madre",
]

# LLM para Herramientas
llm_model = init_chat_model(model="openai:gpt-5-mini", temperature=0)


class TestMethodfromTOC(BaseModel):
    raw: str = Field(
        ...,
        description=(
            "Texto EXACTO del encabezado de la prueba o de la solución tal como aparece en la sección "
            "de procedimientos, sin inferencias adicionales."
        ),
    )
    section_id: Optional[str] = Field(
        None,
        description=(
            "Número de sección de la prueba o solución en formato X.Y.Z (5.3, 7.2, etc.). "
            "Dejar en null si no se observa claramente."
        ),
    )
    title: str = Field(
        ...,
        description=(
            "Nombre de la prueba o solución sin numeración."
        ),
    )


class TestMethodsfromTOC(BaseModel):
    test_methods: List[TestMethodfromTOC] = Field(
        ...,
        description=(
            "Lista ordenada de pruebas/soluciones identificadas en el TOC."
        ),
    )


def _normalize_test_methods(test_methods_model: TestMethodsfromTOC) -> List[Dict[str, Optional[str]]]:
    if not test_methods_model or not test_methods_model.test_methods:
        return []

    def _clean_header_text(value: Optional[str]) -> str:
        if not value:
            return ""
        text = value.strip()
        angle_idx = text.find("<")
        if angle_idx != -1:
            text = text[:angle_idx]
        return text.strip()

    normalized: List[Dict[str, Optional[str]]] = []
    for test in test_methods_model.test_methods:
        payload = test if isinstance(test, dict) else test.model_dump()
        raw_value = _clean_header_text(payload.get("raw") or "") or _clean_header_text(
            payload.get("title") or ""
        )
        title_value = _clean_header_text(payload.get("title") or "")
        normalized.append(
            {
                "raw": raw_value or None,
                "title": title_value or None,
                "section_id": (payload.get("section_id") or "").strip() or None,
            }
        )
    return normalized


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def _normalize_header_key(value: Optional[str]) -> str:
    if not value:
        return ""
    ascii_value = _strip_accents(value)
    return re.sub(r"\s+", " ", ascii_value).strip().lower()


def _is_probable_solution_heading(header: str) -> bool:
    if not header:
        return False
    candidate = re.sub(r"^[#\-*\u2022]+\s*", "", header).strip()
    if not candidate or len(candidate) > 200:
        return False
    if re.match(r"^\d+(\.\d+)*\s+\S+", candidate):
        return True
    keyword_prefix = re.compile(
        r"^(solucion|diluyente|diluente|diluent|fase|mobile phase|solvent|solvente|buffer|standard solution|stock solution|working solution)",
        flags=re.IGNORECASE,
    )
    return bool(keyword_prefix.match(candidate))


def _derive_solution_headings_from_markdown(full_markdown: str) -> List[Dict[str, Optional[int]]]:
    if not full_markdown:
        return []

    derived: List[Dict[str, Optional[int]]] = []
    cursor = 0

    for raw_line in full_markdown.splitlines(keepends=True):
        stripped_line = raw_line.strip()
        line_length = len(raw_line)

        if not stripped_line:
            cursor += line_length
            continue

        normalized_line = re.sub(r"\s+", " ", stripped_line)
        normalized_for_search = _normalize_header_key(normalized_line)

        if not any(keyword in normalized_for_search for keyword in SOLUTION_KEYWORDS):
            cursor += line_length
            continue

        cleaned_heading = re.sub(r"^#+\s*", "", normalized_line).strip()

        if not _is_probable_solution_heading(cleaned_heading):
            cursor += line_length
            continue

        derived.append({"text": cleaned_heading, "start": cursor})
        cursor += line_length

    return derived


def _augment_toc_entries_with_markdown(
    toc_entries: List[str],
    full_markdown: str,
) -> List[str]:
    if not toc_entries:
        return []

    base_entries = [entry for entry in toc_entries if entry]
    derived_candidates = _derive_solution_headings_from_markdown(full_markdown)

    if not derived_candidates:
        return base_entries

    seen = {_normalize_header_key(entry) for entry in base_entries if entry}
    new_entries: List[Dict[str, Optional[int]]] = []

    for candidate in derived_candidates:
        key = _normalize_header_key(candidate.get("text"))
        if not key or key in seen:
            continue
        new_entries.append(candidate)
        seen.add(key)

    if not new_entries:
        return base_entries

    new_entries.sort(key=lambda item: item.get("start", float("inf")))
    derived_only = [item["text"] for item in new_entries]
    logger.info(
        "Se agregaron %s encabezados derivados del markdown para soluciones/diluyentes.",
        len(derived_only),
    )

    return base_entries + derived_only


def _find_header_positions(full_markdown: str, raw_header: str) -> List[int]:
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
    if not full_markdown:
        return None
    pattern = re.compile(r"hist[óo]rico\s+de\s+cambios", flags=re.IGNORECASE)
    match = pattern.search(full_markdown)
    return match.start() if match else None

from langsmith import traceable

@traceable
def _build_markdown_segments(
    test_methods: List[Dict[str, Optional[str]]],
    full_markdown: str,
) -> List[Dict[str, Optional[str]]]:
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
                "raw": test.get("raw"),
                "title": test.get("title"),
                "section_id": test.get("section_id"),
                "markdown": "",
            }
            for test in test_methods
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


@tool(description=TEST_SOLUTION_CLEAN_MARKDOWN_TOOL_DESC)
def test_solution_clean_markdown(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:

    files = dict(state.get("files", {}))
    method_metadata_TOC = files.get(TEST_METADATA_TOC_DOC_NAME)

    if not method_metadata_TOC:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No se encontró el archivo method_metadata_TOC.json",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    metadata_toc_data = method_metadata_TOC.get("data", {})
    toc_entries = metadata_toc_data.get("tabla_de_contenidos")
    full_markdown = metadata_toc_data.get("markdown_completo")

    if not toc_entries:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "El archivo method_metadata_TOC.json no contiene una tabla de contenidos.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    if not full_markdown:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "El archivo method_metadata_TOC.json no contiene markdown consolidado.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    toc_entries_clean = [entry for entry in toc_entries]
    toc_entries_enriched = _augment_toc_entries_with_markdown(
        toc_entries_clean,
        full_markdown,
    )
    toc_string = "\n".join(toc_entries_enriched)

    structured_model = llm_model.with_structured_output(TestMethodsfromTOC)

    system_message = [
        SystemMessage(
            content=TEST_METHOD_GENERATION_TOC_PROMPT
        )
    ]

    human_message = HumanMessage(
        content=f"""
            Entrega únicamente el JSON final, sin texto adicional.
            `toc_string`:
            <Tabla_de_contenidos>
            {toc_string}
            </Tabla_de_contenidos>
        """
    )

    # Combine both system and human messages as a single list for the LLM call
    test_method_input = structured_model.invoke(system_message + [human_message])

    normalized_tests = _normalize_test_methods(test_method_input)
    tests_with_markdown = _build_markdown_segments(normalized_tests, full_markdown)

    payload = {
        "full_markdown": full_markdown,
        "toc_entries": toc_entries_enriched,
        "items": tests_with_markdown,
    }

    files[TEST_SOLUTION_MARKDOWN_DOC_NAME] = {
        "content": json.dumps(payload, indent=2, ensure_ascii=False),
        "data": payload,
    }

    total_items = len(tests_with_markdown)
    populated_items = sum(1 for item in tests_with_markdown if item.get("markdown"))
    derived_count = max(len(toc_entries_enriched) - len(toc_entries_clean), 0)
    summary_message = (
        f"Generadas {total_items} pruebas/soluciones desde el TOC; "
        f"{populated_items} incluyen markdown extraído."
    )
    if derived_count:
        summary_message += f" Se añadieron {derived_count} encabezados derivados del markdown."

    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(summary_message, tool_call_id=tool_call_id)
            ],
        }
    )
