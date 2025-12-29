from __future__ import annotations

import json
import logging
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
from src.models.analytical_method_models import MetodoAnaliticoNuevo

logger = logging.getLogger(__name__)

PATCHES_DIR_DEFAULT = "/new/applied_changes"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"


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
    if not value:
        return None
    return " ".join(value.strip().lower().split())


def _find_prueba_entry(
    pruebas: list[Any] | None, target_id: Optional[str], target_name: Optional[str]
) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    if not pruebas:
        return None, None

    normalized_target = _normalize_text(target_name)

    if target_id:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict) and raw.get("id_prueba") == target_id:
                return idx, raw

    if normalized_target:
        for idx, raw in enumerate(pruebas):
            if isinstance(raw, dict) and _normalize_text(raw.get("prueba")) == normalized_target:
                return idx, raw

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
    if base_payload is None:
        msg = f"No se encontro el metodo base en {base_method_path}."
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

    try:
        base_model = MetodoAnaliticoNuevo(**base_payload)
    except ValidationError as exc:
        msg = f"El metodo base no cumple el esquema esperado: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    working_method = base_model.model_dump(mode="json")
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

    try:
        validated = MetodoAnaliticoNuevo(**working_method)
    except ValidationError as exc:
        msg = f"El metodo consolidado no paso la validacion: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_dump = validated.model_dump(mode="json")
    method_str = json.dumps(method_dump, ensure_ascii=False, indent=2)

    # Resultado final: base_files + método consolidado
    files_update = base_files.copy()
    files_update[output_path] = {"content": method_str, "data": method_dump, "modified_at": datetime.now(timezone.utc).isoformat()}

    tool_message = (
        f"Metodo consolidado en {output_path}. "
        f"Aplicadas: {applied}, omitidas: {skipped}, no encontradas: {missing}, parches leidos: {len(patches)}."
    )
    logger.info(tool_message)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )
