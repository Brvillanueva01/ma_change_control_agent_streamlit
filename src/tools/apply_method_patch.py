from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any, Iterable, Optional, Sequence

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import ValidationError

from src.graph.state import DeepAgentState
from src.prompts.tool_prompts import APPLY_METHOD_PATCH_TOOL_DESCRIPTION
from src.tools.analyze_change_impact import ChangeImpactPlan
from src.tools.consolidar_pruebas_procesadas import MetodoAnaliticoNuevo

logger = logging.getLogger(__name__)

PLAN_DEFAULT_PATH = "/new/change_implementation_plan.json"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"
PATCH_LOG_PATH = "/logs/change_patch_log.jsonl"


def _load_json_payload(files: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    entry = files.get(path)
    if entry is None:
        return None

    if isinstance(entry, dict):
        if isinstance(entry.get("data"), dict):
            return entry["data"]
        if isinstance(entry.get("content"), str):
            try:
                return json.loads(entry["content"])
            except json.JSONDecodeError:
                return None
        return entry

    if isinstance(entry, str):
        try:
            return json.loads(entry)
        except json.JSONDecodeError:
            return None

    return None


def _decode_pointer(path: str) -> list[str]:
    if not path:
        return []
    if not path.startswith("/"):
        raise ValueError(f"Rutas JSON Patch deben iniciar con '/': {path}")
    tokens = path.lstrip("/").split("/")
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def _get_child(container: Any, token: str, *, create: bool) -> Any:
    if isinstance(container, dict):
        if token not in container:
            if create:
                container[token] = {}
            else:
                raise KeyError(f"No existe la clave '{token}' en el objeto destino")
        return container[token]

    if isinstance(container, list):
        if token == "-":
            if create:
                container.append({})
                return container[-1]
            raise IndexError("El token '-' solo es válido para operaciones de inserción")

        try:
            index = int(token)
        except ValueError as exc:
            raise ValueError(f"Índice de lista inválido: {token}") from exc

        if index >= len(container):
            if create:
                while len(container) <= index:
                    container.append({})
            else:
                raise IndexError(f"Índice fuera de rango: {index}")
        return container[index]

    raise TypeError("El contenedor debe ser dict o list para navegar por un JSON pointer")


def _apply_to_parent(parent: Any, token: str, op: str, value: Any) -> None:
    if isinstance(parent, dict):
        if op == "add" or op == "replace":
            parent[token] = value
            return
        raise ValueError(f"Operación '{op}' no soportada para objetos JSON")

    if isinstance(parent, list):
        if token == "-":
            if op != "add":
                raise ValueError("El token '-' solo es válido para operaciones 'add'")
            parent.append(value)
            return

        try:
            index = int(token)
        except ValueError as exc:
            raise ValueError(f"Índice de lista inválido: {token}") from exc

        if op == "replace":
            if index >= len(parent):
                raise IndexError(f"Índice fuera de rango para replace: {index}")
            parent[index] = value
            return
        if op == "add":
            if index > len(parent):
                raise IndexError(f"No se puede insertar en índice {index} mayores al tamaño de la lista")
            parent.insert(index, value)
            return
        raise ValueError(f"Operación '{op}' no soportada para listas JSON")

    raise TypeError("Los nodos intermedios deben ser objetos o listas")


def _apply_operations(document: dict[str, Any], operations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(document)
    for op in operations:
        operation = op.get("op")
        path = op.get("path")
        if operation not in {"add", "replace"}:
            raise ValueError(f"Operación JSON Patch no soportada: {operation}")
        if not isinstance(path, str):
            raise ValueError("Cada operación debe contener una ruta 'path' en formato string")

        tokens = _decode_pointer(path)
        if not tokens:
            # reemplazo del documento completo
            if operation != "replace":
                raise ValueError("Solo se permite reemplazar el documento completo con 'replace'")
            result = deepcopy(op.get("value"))
            continue

        parent = result
        for token in tokens[:-1]:
            parent = _get_child(parent, token, create=(operation == "add"))

        _apply_to_parent(parent, tokens[-1], operation, op.get("value"))

    return result


def _append_log(files: dict[str, Any], entry: dict[str, Any]) -> None:
    payload = json.dumps(entry, ensure_ascii=False)
    log_entry = payload + "\n"

    existing = files.get(PATCH_LOG_PATH)
    if isinstance(existing, dict) and isinstance(existing.get("content"), str):
        log_entry = existing["content"] + log_entry

    files[PATCH_LOG_PATH] = {"content": log_entry, "data": None}


def _format_indices(indices: Iterable[int]) -> str:
    return ", ".join(str(idx) for idx in indices)


@tool(description=APPLY_METHOD_PATCH_TOOL_DESCRIPTION)
def apply_method_patch(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    plan_path: str = PLAN_DEFAULT_PATH,
    new_method_path: str = METHOD_DEFAULT_PATH,
    patch_indices: Optional[list[int]] = None,
    dry_run: bool = True,
) -> Command:
    logger.info("Iniciando 'apply_method_patch'")
    files = state.get("files", {}) or {}

    plan_payload = _load_json_payload(files, plan_path)
    if plan_payload is None:
        msg = f"No se encontró el plan de implementación en {plan_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        plan = ChangeImpactPlan.model_validate(plan_payload)
    except ValidationError as exc:
        msg = f"El plan de implementación tiene un formato inválido: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_payload = _load_json_payload(files, new_method_path)
    if method_payload is None:
        msg = f"No se encontró el método analítico en {new_method_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        MetodoAnaliticoNuevo(**method_payload)
    except ValidationError as exc:
        msg = f"El método actual no cumple el esquema esperado: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    indices: Sequence[int]
    if patch_indices is None or len(patch_indices) == 0:
        indices = list(range(len(plan.plan)))
    else:
        indices = sorted(set(patch_indices))

    if not indices:
        msg = "No hay acciones seleccionadas para aplicar."
        logger.warning(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    current_document = deepcopy(method_payload)
    applied_indices: list[int] = []
    skipped_indices: list[int] = []

    for idx in indices:
        if idx < 0 or idx >= len(plan.plan):
            logger.warning("Índice %s fuera de rango. Se omite.", idx)
            skipped_indices.append(idx)
            continue

        action = plan.plan[idx]
        if not action.patch:
            logger.info("Acción %s no contiene operaciones de patch. Se omite.", idx)
            skipped_indices.append(idx)
            continue

        try:
            current_document = _apply_operations(current_document, action.patch)
            applied_indices.append(idx)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Fallo al aplicar el patch %s: %s", idx, exc)
            skipped_indices.append(idx)

    if not applied_indices:
        message = "No se aplicaron parches. Verifica que los índices sean correctos y que cada acción contenga operaciones válidas."
        return Command(update={"messages": [ToolMessage(content=message, tool_call_id=tool_call_id)]})

    try:
        validated_method = MetodoAnaliticoNuevo(**current_document)
    except ValidationError as exc:
        msg = f"La versión resultante del método no pasó la validación: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_json = validated_method.model_dump(mode="json")
    method_str = json.dumps(method_json, ensure_ascii=False, indent=2)

    files_update = dict(files)

    summary_message = (
        "Dry-run: los parches serían aplicados" if dry_run else "Parches aplicados exitosamente"
    ) + f" para los índices [{_format_indices(applied_indices)}]."

    if not dry_run:
        files_update[new_method_path] = {"content": method_str, "data": method_json}
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "plan_path": plan_path,
            "method_path": new_method_path,
            "indices_aplicados": applied_indices,
            "indices_omitidos": skipped_indices,
        }
        _append_log(files_update, log_entry)

    logger.info(summary_message)

    return Command(
        update={
            "files": files_update if not dry_run else files,
            "messages": [ToolMessage(content=summary_message, tool_call_id=tool_call_id)],
        }
    )
