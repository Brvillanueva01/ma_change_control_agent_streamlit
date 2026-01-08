import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

import copy
import json
import logging
from datetime import datetime, timezone
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
    DEFAULT_BASE_PATH,
    TEMP_DIR_MAPPING,
    _get_temp_dir,
)

logger = logging.getLogger(__name__)

# Directorio para registro de pruebas analíticas
ANALYTICAL_TESTS_DIR = "/analytical_tests"


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


def _temp_structured_dir(base_path: str, source_file_name: str) -> str:
    """Genera la ruta del directorio temporal para archivos paralelos."""
    temp_dir = _get_temp_dir(base_path)
    return f"{temp_dir}/{source_file_name}"


def _structured_content_path(base_path: str, source_file_name: str) -> str:
    """Genera la ruta del archivo consolidado final."""
    base = (base_path or DEFAULT_BASE_PATH).rstrip("/")
    return f"{base}/test_solution_structured_content_{source_file_name}.json"


def _analytical_tests_path(source_file_name: str) -> str:
    """Genera la ruta del archivo de registro de pruebas analíticas."""
    return f"{ANALYTICAL_TESTS_DIR}/{source_file_name}.json"


def _extract_analytical_tests_registry(
    candidate_entries: List[Dict[str, Any]],
    source_file_name: str,
    base_path: str,
) -> Dict[str, Any]:
    """Extrae el registro de pruebas analíticas de las entradas consolidadas."""
    tests_list = []
    
    for entry in candidate_entries:
        # Extraer pruebas del wrapper si existe
        tests = entry.get("tests", [])
        if not tests and "test_name" in entry:
            # Es una prueba directa, no un wrapper
            tests = [entry]
        
        for test in tests:
            if isinstance(test, dict):
                test_entry = {
                    "source_id": entry.get("source_id"),
                    "test_name": test.get("test_name") or test.get("section_title"),
                    "section_id": test.get("section_id"),
                    "test_type": test.get("test_type"),
                }
                tests_list.append(test_entry)
    
    # Determinar source_type basado en base_path
    source_type = "actual_method" if "actual_method" in base_path else "proposed_method"
    
    return {
        "source_file": source_file_name,
        "source_type": source_type,
        "source_path": _structured_content_path(base_path, source_file_name),
        "tests": tests_list,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


@tool(description=TEST_SOLUTION_STRUCTURED_CONSOLIDATION_TOOL_DESC)
def consolidate_test_solution_structured(
    source_file_name: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    base_path: str = DEFAULT_BASE_PATH,
) -> Command:
    """
    Consolida los archivos temporales de paralelización en un archivo final.
    
    Args:
        source_file_name: Nombre del archivo de origen (sin extensión)
        base_path: Ruta base (/actual_method o /proposed_method)
    """
    # Archivos originales para leer entradas individuales
    archivos_entrada = dict(state.get("files", {}))
    
    # Rutas calculadas
    temp_dir = _temp_structured_dir(base_path, source_file_name)
    structured_content_path = _structured_content_path(base_path, source_file_name)
    analytical_tests_path = _analytical_tests_path(source_file_name)
    markdown_doc_path = f"{base_path.rstrip('/')}/test_solution_markdown_{source_file_name}.json"

    # Archivos base que queremos retener (sin las ramas paralelas temporales)
    archivos_resultado = {
        k: v for k, v in archivos_entrada.items() 
        if not k.startswith(temp_dir + "/")
    }

    candidate_entries: List[Dict[str, Any]] = []
    consumed_paths: List[str] = []

    # Buscar archivos en la carpeta temporal
    for path, file_entry in archivos_entrada.items():
        if not isinstance(path, str):
            continue

        if not path.startswith(f"{temp_dir}/"):
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
        
        # Asegurar que source_file_name esté presente
        if "source_file_name" not in entry_copy:
            entry_copy["source_file_name"] = source_file_name

        candidate_entries.append(entry_copy)
        consumed_paths.append(path)

    if not candidate_entries:
        message = (
            f"No se encontraron archivos individuales en {temp_dir} para consolidar. "
            f"Verifique que source_file_name='{source_file_name}' sea correcto."
        )
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    candidate_entries.sort(key=_sort_key)

    # Resultado final: archivos_resultado + nuevo consolidado
    archivos_resultado_final = archivos_resultado.copy()

    # Guardar archivo consolidado en la carpeta final (no temporal)
    content_str = json.dumps(candidate_entries, indent=2, ensure_ascii=False)
    archivos_resultado_final[structured_content_path] = {
        "content": content_str.split("\n"),
        "data": candidate_entries,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Generar registro de pruebas analíticas en /analytical_tests/
    analytical_registry = _extract_analytical_tests_registry(
        candidate_entries, source_file_name, base_path
    )
    analytical_content_str = json.dumps(analytical_registry, indent=2, ensure_ascii=False)
    archivos_resultado_final[analytical_tests_path] = {
        "content": analytical_content_str.split("\n"),
        "data": analytical_registry,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Eliminar archivos temporales consumidos
    for consumed_path in consumed_paths:
        archivos_resultado_final.pop(consumed_path, None)

    num_tests = len(analytical_registry.get("tests", []))
    summary_message = (
        f"Consolidé {len(candidate_entries)} pruebas/soluciones estructuradas de '{source_file_name}' en "
        f"{structured_content_path}. Registro de {num_tests} pruebas analíticas guardado en {analytical_tests_path}."
    )
    logger.info(summary_message)

    return Command(
        update={
            "files": archivos_resultado_final,
            "messages": [ToolMessage(summary_message, tool_call_id=tool_call_id)],
        }
    )
