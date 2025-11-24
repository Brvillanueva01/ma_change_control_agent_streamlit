from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any, Optional, List

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from src.graph.state import DeepAgentState
from src.prompts.tool_prompts import APPLY_METHOD_PATCH_TOOL_DESCRIPTION
from src.tools.analyze_change_impact import ChangeImpactPlan
from src.tools.consolidar_pruebas_procesadas import (
    MetodoAnaliticoNuevo,
    Prueba as MetodoPrueba,
    Especificacion,
    CondicionCromatografica,
    Solucion,
)

logger = logging.getLogger(__name__)

PLAN_DEFAULT_PATH = "/new/change_implementation_plan.json"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"
PATCH_LOG_PATH = "/logs/change_patch_log.jsonl"
REFERENCE_METHOD_DEFAULT_PATH = "/new/reference_method.json"
SIDE_BY_SIDE_DEFAULT_PATH = "/new/side_by_side.json"
method_patch_model = init_chat_model(model="openai:gpt-5-mini", temperature=0)


class MetodoPruebaLLM(BaseModel):
    id_prueba: str = Field(
        ...,
        description="Identificador único (usa el existente cuando corresponda o genera uno nuevo al agregar pruebas).",
    )
    prueba: str = Field(
        ...,
        description="Nombre exacto de la prueba en el método nuevo.",
    )
    procedimientos: str = Field(
        ...,
        description="Procedimiento detallado o nota de eliminación; no puede quedar vacío.",
    )
    equipos: Optional[List[str]] = Field(
        default=None,
        description="Lista de equipos utilizados; usa null si no aplica.",
    )
    condiciones_cromatograficas: Optional[List[CondicionCromatografica]] = Field(
        default=None,
        description="Condiciones cromatográficas completas, si existen.",
    )
    reactivos: Optional[List[str]] = Field(
        default=None,
        description="Reactivos utilizados; null si no aplica.",
    )
    soluciones: Optional[List[Solucion]] = Field(
        default=None,
        description="Soluciones preparadas; usa [] o null según corresponda.",
    )
    especificaciones: List[Especificacion] = Field(
        ...,
        description="Al menos una especificación con criterio de aceptación.",
    )


class GeneratedMethodPatch(BaseModel):
    prueba_resultante: MetodoPruebaLLM
    comentarios: Optional[str] = Field(
        default=None,
        description="Notas breves sobre cómo se construyó la prueba final o recordatorios para el equipo",
    )


APPLY_METHOD_PATCH_INSTRUCTION = """Eres un químico especialista en métodos analíticos farmacéuticos.
Recibes un contexto en JSON que incluye:
- La descripción del cambio aprobado (`cambio`), la acción solicitada y su justificación.
- La prueba objetivo del método nuevo (si existe actualmente).
- Pruebas de referencia provenientes de side-by-side o métodos de referencia completos.
- Metadatos del método nuevo (tipo, versión, número, etc.).

Objetivo:
1. Analiza la acción solicitada (`accion_recomendada` = "replace" o "append") y decide el contenido final de la prueba.
2. Usa las pruebas fuente como inspiración. Copia fielmente los campos relevantes y adapta lo necesario para mantener consistencia con el método nuevo.
3. Respeta la estructura del modelo `Prueba` (campos obligatorios: `id_prueba`, `prueba`, `procedimientos`, `especificaciones` con al menos un item). Si un campo no aplica, coloca `null` (para strings/listas) o `[]` según corresponda, pero no lo omitas.
4. Mantén texto técnico en español, conserva unidades y formato de listas cuando se proporcionen.

Salida esperada (JSON):
{{
  "prueba_resultante": {{... objeto completo de la prueba final ...}},
  "comentarios": "Notas breves opcionales para el equipo (o null)"
}}

Reglas importantes:
- **Nunca devuelvas** un objeto vacío (`{}`) ni omitas campos obligatorios. Si la instrucción implica eliminar o desactivar una prueba, aún debes devolver la estructura completa con `procedimientos` explicando la eliminación y `especificaciones` documentando el criterio histórico.
- **Siempre** llena `procedimientos` y `especificaciones[0].texto_especificacion` con texto en español (puede ser una nota de eliminación si aplica).
- Repite el `id_prueba` proporcionado en el contexto (o genera uno nuevo solo si se trata de un append y no existe).

Ejemplo agnóstico de `prueba_resultante` válido:
{{
  "id_prueba": "<ID_DE_PRUEBA>",
  "prueba": "<NOMBRE_DE_LA_PRUEBA>",
  "procedimientos": "<DESCRIPCIÓN_DE_LOS_PROCEDIMIENTOS>",
  "equipos": ["<EQUIPO_1>", "<EQUIPO_2>"],
  "condiciones_cromatograficas": null,
  "reactivos": ["<REACTIVO_1>", "<REACTIVO_2>"],
  "soluciones": [
    {{
      "nombre_solucion": "<NOMBRE_SOLUCIÓN>",
      "preparacion_solucion": "<PREPARACIÓN_DE_LA_SOLUCIÓN>"
    }}
  ],
  "especificaciones": [
    {{
      "prueba": "<NOMBRE_DE_LA_PRUEBA>",
      "texto_especificacion": "<CRITERIO_DE_ACEPTACIÓN>",
      "subespecificacion": []
    }}
  ]
}}

Ejemplo cuando la acción es eliminar pero debe dejar trazabilidad:
{{
  "id_prueba": "<ID_EXISTENTE>",
  "prueba": "<NOMBRE_DE_LA_PRUEBA>",
  "procedimientos": "Esta prueba se elimina del método y se conserva únicamente como referencia histórica. Registrar en el historial de cambios y consultar el documento de origen para el contenido previo.",
  "equipos": null,
  "condiciones_cromatograficas": null,
  "reactivos": null,
  "soluciones": [],
  "especificaciones": [
    {{
      "prueba": "<NOMBRE_DE_LA_PRUEBA>",
      "texto_especificacion": "Prueba eliminada por redundancia con <FUENTE>. Mantener registro en SOP correspondiente.",
      "subespecificacion": []
    }}
  ]
}}

Contexto:
{context}
"""

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


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return " ".join(value.strip().lower().split())


def _to_jsonable(prueba: Any) -> Optional[dict[str, Any]]:
    if prueba is None:
        return None
    if isinstance(prueba, dict):
        return deepcopy(prueba)
    if hasattr(prueba, "model_dump"):
        return prueba.model_dump(mode="json")
    return json.loads(json.dumps(prueba, ensure_ascii=False))


def _find_prueba_entry(
    pruebas: list[Any] | None, target_id: Optional[str], target_name: Optional[str]
) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    if not pruebas:
        return None, None

    normalized_target = _normalize_text(target_name)

    if target_id:
        for idx, raw in enumerate(pruebas):
            data = _to_jsonable(raw)
            if isinstance(data, dict) and isinstance(data.get("id_prueba"), str) and data["id_prueba"] == target_id:
                return idx, data

    if normalized_target:
        for idx, raw in enumerate(pruebas):
            data = _to_jsonable(raw)
            if isinstance(data, dict) and _normalize_text(data.get("prueba")) == normalized_target:
                return idx, data

    return None, None


def _find_prueba_data(pruebas: list[Any] | None, target_id: Optional[str], target_name: Optional[str]) -> Optional[dict[str, Any]]:
    _, data = _find_prueba_entry(pruebas, target_id, target_name)
    return data


def _resolve_reference_context(
    fuentes: list,
    side_by_side_payload: Optional[dict[str, Any]],
    reference_payload: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for fuente in fuentes:
        origen = getattr(fuente, "origen", None) or "desconocido"
        dataset: list[Any] | None = None
        if origen == "side_by_side_actual":
            dataset = (side_by_side_payload or {}).get("metodo_actual")
        elif origen == "side_by_side_modificacion":
            dataset = (side_by_side_payload or {}).get("metodo_modificacion_propuesta")
        elif origen == "reference_method":
            dataset = (reference_payload or {}).get("pruebas")

        contenido = _find_prueba_data(dataset, getattr(fuente, "id_prueba", None), getattr(fuente, "prueba", None))
        details.append(
            {
                "origen": origen,
                "id_prueba": getattr(fuente, "id_prueba", None),
                "prueba": getattr(fuente, "prueba", None),
                "contenido": contenido,
            }
        )
    return details


def _build_llm_context(
    action, target_prueba: Optional[dict[str, Any]], referencias: list[dict[str, Any]], method_payload: dict[str, Any]
) -> dict[str, Any]:
    resumen_metodo = {
        key: method_payload.get(key)
        for key in [
            "tipo_metodo",
            "nombre_producto",
            "numero_metodo",
            "version_metodo",
            "codigo_producto",
        ]
    }

    return {
        "cambio": action.cambio,
        "accion_recomendada": action.accion,
        "justificacion": action.justificacion,
        "prueba_metodo_nuevo": {
            "id_prueba": action.id_prueba_metodo_nuevo,
            "prueba": action.prueba_metodo_nuevo,
            "contenido": target_prueba,
        },
        "pruebas_fuente": referencias,
        "metodo_nuevo": resumen_metodo,
    }


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
    action_index: int = 0,
    side_by_side_path: str = SIDE_BY_SIDE_DEFAULT_PATH,
    reference_method_path: str = REFERENCE_METHOD_DEFAULT_PATH,
    new_method_path: str = METHOD_DEFAULT_PATH,
    dry_run: bool = True,
) -> Command:
    logger.info("Iniciando 'apply_method_patch' para la acción %s", action_index)
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

    if action_index < 0 or action_index >= len(plan.plan):
        msg = f"El índice {action_index} está fuera del rango del plan ({len(plan.plan)} acciones)."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    action = plan.plan[action_index]
    if action.accion not in {"replace", "append"}:
        msg = f"La acción '{action.accion}' no requiere modificación automática (índice {action_index})."
        logger.info(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_payload = _load_json_payload(files, new_method_path)
    if method_payload is None:
        msg = f"No se encontró el método analítico en {new_method_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        method_model = MetodoAnaliticoNuevo(**method_payload)
    except ValidationError as exc:
        msg = f"El método actual no cumple el esquema esperado: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_json = method_model.model_dump(mode="json")
    pruebas_metodo = method_json.get("pruebas", [])

    target_index, target_prueba = _find_prueba_entry(pruebas_metodo, action.id_prueba_metodo_nuevo, action.prueba_metodo_nuevo)
    if action.accion == "replace" and target_prueba is None:
        msg = (
            f"No se pudo localizar la prueba '{action.prueba_metodo_nuevo}' (id: {action.id_prueba_metodo_nuevo}) "
            f"en el método para ejecutar un replace."
        )
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    side_by_side_payload = _load_json_payload(files, side_by_side_path)
    reference_payload = _load_json_payload(files, reference_method_path)
    referencia_detalle = _resolve_reference_context(action.pruebas_fuente, side_by_side_payload, reference_payload)

    llm_context = _build_llm_context(action, target_prueba, referencia_detalle, method_json)
    context_json = json.dumps(llm_context, ensure_ascii=False, indent=2)

    llm_structured = method_patch_model.with_structured_output(GeneratedMethodPatch)
    try:
        llm_response = llm_structured.invoke(
            [HumanMessage(content=APPLY_METHOD_PATCH_INSTRUCTION.format(context=context_json))]
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"El LLM no pudo generar la prueba actualizada: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        prueba_actualizada = MetodoPrueba(**llm_response.prueba_resultante)
    except ValidationError as exc:
        msg = f"El contenido generado por el LLM no cumple el esquema de una prueba: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    prueba_json = prueba_actualizada.model_dump(mode="json")
    updated_method = deepcopy(method_json)
    if action.accion == "replace" and target_index is not None:
        updated_method["pruebas"][target_index] = prueba_json
    elif action.accion == "append":
        updated_method["pruebas"].append(prueba_json)

    try:
        validated_method = MetodoAnaliticoNuevo(**updated_method)
    except ValidationError as exc:
        msg = f"La versión resultante del método no pasó la validación: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_dump = validated_method.model_dump(mode="json")
    method_str = json.dumps(method_dump, ensure_ascii=False, indent=2)

    summary_message = (
        "Dry-run: se generó la prueba actualizada"
        if dry_run
        else "Prueba actualizada aplicada al método"
    )
    summary_message += f" (acción #{action_index}, {action.accion})."
    if llm_response.comentarios:
        summary_message += f" Notas del LLM: {llm_response.comentarios}"

    files_update = dict(files)
    if not dry_run:
        files_update[new_method_path] = {"content": method_str, "data": method_dump}
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "plan_path": plan_path,
            "method_path": new_method_path,
            "action_index": action_index,
            "accion": action.accion,
        }
        _append_log(files_update, log_entry)

    logger.info(summary_message)

    return Command(
        update={
            "files": files_update if not dry_run else files,
            "messages": [ToolMessage(content=summary_message, tool_call_id=tool_call_id)],
        }
    )
