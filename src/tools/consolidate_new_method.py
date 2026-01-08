from __future__ import annotations

import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

import json
import logging
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, List, Tuple

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import ValidationError

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import CONSOLIDATE_NEW_METHOD_TOOL_DESCRIPTION
# Ya no se usa MetodoAnaliticoNuevo - trabajamos directamente con dicts de TestSolution

logger = logging.getLogger(__name__)

PATCHES_DIR_DEFAULT = "/new/applied_changes"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"

# Directorios base para búsqueda dinámica de archivos
ACTUAL_METHOD_DIR = "/actual_method"
# Patrones para identificar archivos
METADATA_TOC_PATTERN = re.compile(r"method_metadata_TOC_(.+)\.json$")
STRUCTURED_CONTENT_PATTERN = re.compile(r"test_solution_structured_content_(.+)\.json$")

# Campos de metadata que se copian del método legado al método final
METADATA_FIELDS = [
    "apis",
    "tipo_metodo",
    "nombre_producto",
    "numero_metodo",
    "version_metodo",
    "codigo_producto",
    "objetivo",
    "alcance_metodo",
    "definiciones",
    "recomendaciones_seguridad",
    "materiales",
    "equipos",
    "anexos",
    "autorizaciones",
    "documentos_soporte",
    "historico_cambios",
]


def _load_json_payload(files: dict[str, Any], path: str) -> Optional[dict[str, Any] | list]:
    """
    Carga un payload JSON desde el filesystem virtual.
    
    Retorna dict, list, o None si no se encuentra o hay error de parseo.
    """
    entry = files.get(path)
    if entry is None:
        return None

    if isinstance(entry, dict):
        # Caso: entry tiene estructura {"data": ..., "content": ...}
        if "data" in entry and isinstance(entry["data"], (dict, list)):
            return entry["data"]
        if isinstance(entry.get("content"), str):
            try:
                return json.loads(entry["content"])
            except json.JSONDecodeError:
                logger.warning(f"Error parseando JSON desde 'content' en {path}")
                return None
        # Si no tiene 'data' ni 'content', asumimos que es el payload directo
        return entry

    if isinstance(entry, str):
        try:
            return json.loads(entry)
        except json.JSONDecodeError:
            logger.warning(f"Error parseando JSON string en {path}")
            return None
    
    if isinstance(entry, list):
        return entry

    return None


def _normalize_text(value: Optional[str]) -> Optional[str]:
    """Normaliza texto para comparación: minúsculas, sin acentos, sin espacios extra."""
    if not value:
        return None
    # Remover acentos
    normalized = unicodedata.normalize('NFD', value)
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return " ".join(normalized.strip().lower().split())


def _normalize_for_matching(value: Optional[str]) -> Optional[str]:
    """
    Normaliza texto para matching flexible:
    - Minúsculas, sin acentos
    - Remueve números de sección (ej: '7.1', '7.1.2')
    """
    if not value:
        return None
    normalized = _normalize_text(value)
    if not normalized:
        return None
    # Remover números de sección al inicio
    normalized = re.sub(r'^\d+(\.\d+)*\s*', '', normalized)
    return normalized.strip()


def _find_prueba_entry(
    pruebas: list[Any] | None, target_id: Optional[str], target_name: Optional[str]
) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    """
    Busca una prueba por section_id o por nombre (test_name/section_title).
    Soporta tanto formato TestSolution (section_id, test_name) como formato legacy (id_prueba, prueba).
    
    Usa matching flexible:
    1. Primero busca por ID exacto
    2. Luego busca por nombre exacto (normalizado)
    3. Luego busca por nombre flexible (sin números de sección, sin acentos)
    4. Finalmente busca por contenido parcial
    """
    if not pruebas:
        return None, None

    normalized_target = _normalize_text(target_name)
    flexible_target = _normalize_for_matching(target_name)

    # Buscar por ID (section_id o id_prueba)
    if target_id:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict):
                data_id = raw.get("section_id") or raw.get("id_prueba")
                if data_id == target_id:
                    return idx, raw

    # Buscar por nombre exacto (normalizado)
    if normalized_target:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict):
                data_name = raw.get("test_name") or raw.get("section_title") or raw.get("prueba")
                if _normalize_text(data_name) == normalized_target:
                    return idx, raw

    # Buscar por nombre flexible (sin números de sección)
    if flexible_target:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict):
                data_name = raw.get("test_name") or raw.get("section_title") or raw.get("prueba")
                data_flexible = _normalize_for_matching(data_name)
                if data_flexible and data_flexible == flexible_target:
                    return idx, raw

    # Buscar por contenido parcial
    if flexible_target:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict):
                data_name = raw.get("test_name") or raw.get("section_title") or raw.get("prueba")
                data_flexible = _normalize_for_matching(data_name)
                if data_flexible and (flexible_target in data_flexible or data_flexible in flexible_target):
                    return idx, raw

    return None, None


def _find_metadata_files(files: dict[str, Any], directory: str) -> List[str]:
    """
    Busca archivos con patrón method_metadata_TOC_*.json en un directorio.
    """
    found = []
    dir_prefix = directory.rstrip("/") + "/"
    for path in files.keys():
        if path.startswith(dir_prefix) and METADATA_TOC_PATTERN.search(path):
            found.append(path)
    return sorted(found)


def _find_structured_content_files(files: dict[str, Any], directory: str) -> List[str]:
    """
    Busca archivos con patrón test_solution_structured_content_*.json en un directorio.
    """
    found = []
    dir_prefix = directory.rstrip("/") + "/"
    for path in files.keys():
        if path.startswith(dir_prefix) and STRUCTURED_CONTENT_PATTERN.search(path):
            found.append(path)
    return sorted(found)


def _load_first_metadata(files: dict[str, Any], directory: str) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Carga el primer archivo de metadata encontrado en el directorio.
    
    Returns:
        Tupla (metadata_dict, path_usado) o (None, None) si no se encuentra
    """
    metadata_files = _find_metadata_files(files, directory)
    for file_path in metadata_files:
        payload = _load_json_payload(files, file_path)
        if payload and isinstance(payload, dict):
            return payload, file_path
    return None, None


def _iter_patch_payloads(files: dict[str, Any], patches_dir: str) -> List[Tuple[str, dict[str, Any]]]:
    prefix = patches_dir.rstrip("/") + "/"
    collected: List[Tuple[str, dict[str, Any]]] = []
    for path, entry in files.items():
        if isinstance(path, str) and path.startswith(prefix):
            payload = _load_json_payload(files, path)
            if isinstance(payload, dict):
                collected.append((path, payload))
    return sorted(collected, key=lambda item: item[1].get("action_index", 0))


@tool(description=CONSOLIDATE_NEW_METHOD_TOOL_DESCRIPTION)
def consolidate_new_method(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    patches_dir: str = PATCHES_DIR_DEFAULT,
    base_method_path: str = METHOD_DEFAULT_PATH,
    legacy_metadata_path: str = "",  # Ahora usa búsqueda dinámica, este parámetro es solo fallback
    output_path: str = METHOD_DEFAULT_PATH,
) -> Command:
    logger.info("Iniciando 'consolidate_new_method'")
    
    # Archivos originales para leer entradas
    source_files = dict(state.get("files", {}) or {})
    
    # Archivos base que queremos retener (sin las ramas paralelas de patches)
    base_files = {
        k: v for k, v in source_files.items()
        if not k.startswith(patches_dir.rstrip("/") + "/")
    }

    base_payload = _load_json_payload(source_files, base_method_path)
    base_source = base_method_path
    
    # Fallback: si no existe el método base especificado, cargar desde /actual_method/
    if base_payload is None:
        logger.warning(f"No se encontró método base en {base_method_path}, buscando en {ACTUAL_METHOD_DIR}/")
        structured_files = _find_structured_content_files(source_files, ACTUAL_METHOD_DIR)
        if structured_files:
            # Cargar todas las pruebas de los archivos encontrados
            all_tests = []
            for file_path in structured_files:
                file_payload = _load_json_payload(source_files, file_path)
                if file_payload:
                    if isinstance(file_payload, list):
                        # Lista de wrappers con source_id y tests
                        for wrapper in file_payload:
                            if isinstance(wrapper, dict) and "tests" in wrapper:
                                source_id = wrapper.get("source_id")
                                for test in wrapper.get("tests", []):
                                    if isinstance(test, dict):
                                        test_copy = dict(test)
                                        if source_id is not None:
                                            test_copy["_source_id"] = source_id
                                        all_tests.append(test_copy)
                            elif isinstance(wrapper, dict):
                                all_tests.append(wrapper)
                    elif isinstance(file_payload, dict):
                        tests = file_payload.get("tests") or file_payload.get("pruebas") or []
                        all_tests.extend(tests)
            
            if all_tests:
                base_payload = {"pruebas": all_tests}
                base_source = f"{ACTUAL_METHOD_DIR}/ ({len(structured_files)} archivo(s), {len(all_tests)} pruebas)"
                logger.info(f"Método base cargado desde {base_source}")
    
    if base_payload is None:
        msg = f"No se encontró el método base en {base_method_path} ni en {ACTUAL_METHOD_DIR}/."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Si el payload es una lista, asumimos que es la lista de pruebas directamente
    if isinstance(base_payload, list):
        base_payload = {"pruebas": base_payload}
        logger.info("El metodo base era una lista; se envolvio en {'pruebas': [...]}.")

    if not isinstance(base_payload, dict):
        msg = f"El metodo base en {base_method_path} no es un diccionario valido."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Cargar metadata del método legado (búsqueda dinámica)
    legacy_metadata, metadata_path_used = _load_first_metadata(source_files, ACTUAL_METHOD_DIR)
    metadata_loaded = False
    if legacy_metadata:
        logger.info(f"Metadata del método legado cargada desde {metadata_path_used}")
        metadata_loaded = True
    else:
        # Fallback: intentar con el parámetro legacy_metadata_path por compatibilidad
        legacy_metadata = _load_json_payload(source_files, legacy_metadata_path)
        if legacy_metadata and isinstance(legacy_metadata, dict):
            logger.info(f"Metadata del método legado cargada desde {legacy_metadata_path} (fallback)")
            metadata_loaded = True
        else:
            logger.warning(f"No se encontró metadata del método legado en {ACTUAL_METHOD_DIR}/ ni en {legacy_metadata_path}")
            legacy_metadata = {}

    # Trabajar directamente con el dict sin validación Pydantic
    working_method = base_payload
    patches = _iter_patch_payloads(source_files, patches_dir)
    consolidated_patch_paths: list[str] = [path for path, _ in patches]

    applied = 0
    skipped = 0
    missing = 0

    for _, patch in patches:
        accion = (patch.get("accion") or "").strip().lower()
        id_prueba = patch.get("id_prueba")
        nombre_prueba = patch.get("prueba")
        contenido = patch.get("contenido")

        target_index, _ = _find_prueba_entry(working_method.get("pruebas", []), id_prueba, nombre_prueba)

        if accion == "eliminar":
            if target_index is not None:
                working_method["pruebas"].pop(target_index)
                applied += 1
            else:
                missing += 1
        elif accion == "editar":
            if target_index is not None and isinstance(contenido, dict):
                working_method["pruebas"][target_index] = contenido
                applied += 1
            else:
                skipped += 1
        elif accion == "adicionar":
            if isinstance(contenido, dict):
                if target_index is not None:
                    working_method["pruebas"][target_index] = contenido
                else:
                    working_method.setdefault("pruebas", []).append(contenido)
                applied += 1
            else:
                skipped += 1
        elif accion == "dejar igual":
            skipped += 1
        else:
            skipped += 1

    # Fusionar metadata del método legado con las pruebas consolidadas
    # La metadata del método legado tiene prioridad para los campos de metadata
    # Las pruebas vienen del working_method (ya con los patches aplicados)
    final_method: dict[str, Any] = {}
    
    # Copiar campos de metadata desde el método legado
    metadata_fields_copied = 0
    for field in METADATA_FIELDS:
        if field in legacy_metadata and legacy_metadata[field] is not None:
            final_method[field] = legacy_metadata[field]
            metadata_fields_copied += 1
    
    # Agregar las pruebas consolidadas
    final_method["pruebas"] = working_method.get("pruebas", [])
    
    logger.info(f"Metadata copiada: {metadata_fields_copied} campos de {len(METADATA_FIELDS)} posibles")
    
    method_dump = final_method
    method_str = json.dumps(method_dump, ensure_ascii=False, indent=2)

    # Resultado final: base_files + método consolidado
    files_update = base_files.copy()
    files_update[output_path] = {"content": method_str, "data": method_dump, "modified_at": datetime.now(timezone.utc).isoformat()}

    metadata_msg = f", metadata copiada: {metadata_fields_copied} campos" if metadata_loaded else ", sin metadata"
    base_msg = f" (base: {base_source})" if base_source != base_method_path else ""
    pruebas_count = len(final_method.get("pruebas", []))
    tool_message = (
        f"Metodo consolidado en {output_path}{base_msg}. "
        f"Pruebas finales: {pruebas_count}. "
        f"Parches aplicados: {applied}, omitidos: {skipped}, no encontrados: {missing}, parches leidos: {len(patches)}{metadata_msg}."
    )
    logger.info(tool_message)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )
