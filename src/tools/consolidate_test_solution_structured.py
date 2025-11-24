import copy
import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import (
    TEST_SOLUTION_STRUCTURED_CONSOLIDATION_TOOL_DESC,
)
from .test_solution_structured_extraction import (
    TEST_SOLUTION_STRUCTURED_CONTENT,
    TEST_SOLUTION_STRUCTURED_DIR,
)

logger = logging.getLogger(__name__)


def _load_structured_entry(path: str, file_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entry_data = file_entry.get("data")
    if isinstance(entry_data, dict):
        return entry_data

    entry_content = file_entry.get("content")
    if isinstance(entry_content, str):
        try:
            parsed = json.loads(entry_content)
        except json.JSONDecodeError:
            logger.warning(
                "No se pudo parsear el archivo %s como JSON válido durante la consolidación.",
                path,
            )
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _infer_source_id_from_path(path: str) -> Optional[int]:
    filename = path.rsplit("/", 1)[-1]
    candidate = filename.split(".", 1)[0]
    try:
        return int(candidate)
    except ValueError:
        return None


def _sort_key(entry: Dict[str, Any]) -> tuple:
    source_id = entry.get("source_id")
    if isinstance(source_id, int):
        return (0, source_id)
    if isinstance(source_id, str):
        try:
            return (0, int(source_id))
        except ValueError:
            return (1, source_id)
    return (2, str(source_id))


@tool(description=TEST_SOLUTION_STRUCTURED_CONSOLIDATION_TOOL_DESC)
def consolidate_test_solution_structured(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    files = dict(state.get("files", {}))
    candidate_entries: List[Dict[str, Any]] = []

    for path, file_entry in files.items():
        if not isinstance(path, str):
            continue

        if not path.startswith(f"{TEST_SOLUTION_STRUCTURED_DIR}/"):
            continue

        if not isinstance(file_entry, dict):
            continue

        entry = _load_structured_entry(path, file_entry)
        if entry is None:
            continue

        entry_copy = copy.deepcopy(entry)
        if "source_id" not in entry_copy or entry_copy["source_id"] is None:
            inferred_id = _infer_source_id_from_path(path)
            if inferred_id is not None:
                entry_copy["source_id"] = inferred_id

        candidate_entries.append(entry_copy)

    if not candidate_entries:
        message = (
            "No se encontraron archivos individuales en "
            f"{TEST_SOLUTION_STRUCTURED_DIR} para consolidar."
        )
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    candidate_entries.sort(key=_sort_key)

    files[TEST_SOLUTION_STRUCTURED_CONTENT] = {
        "content": json.dumps(candidate_entries, indent=2, ensure_ascii=False),
        "data": candidate_entries,
    }

    summary_message = (
        "Consolidé "
        f"{len(candidate_entries)} pruebas/soluciones estructuradas en "
        f"{TEST_SOLUTION_STRUCTURED_CONTENT}."
    )
    logger.info(summary_message)

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(summary_message, tool_call_id=tool_call_id)],
        }
    )
