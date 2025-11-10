from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Optional, Literal, List

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from src.graph.state import DeepAgentState
from src.models.change_control import ChangeControlModel
from src.models.extraction_models import ExtractionModel, Prueba
from src.models.side_by_side_model import SideBySideModel
from src.prompts.tool_prompts import CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION

# --- Configuración ---
logger = logging.getLogger(__name__)

## LLMs
change_control_analysis_model = init_chat_model(model="openai:gpt-5-mini")

CHANGE_IMPLEMENTATION_PLAN_PATH = "/new/change_implementation_plan.json"


class ChangeImpactAction(BaseModel):
    cambio: str = Field(description="Texto del cambio descrito en el control de cambios")
    pruebas_fuente: List[str] = Field(description="Pruebas identificadas en side-by-side o métodos de referencia")
    prueba_metodo_nuevo: str = Field(description="Nombre de la prueba en el método analítico nuevo que se ve impactada")
    accion: Literal["replace","append","noop","investigar"] = Field(description="Acción sugerida: replace, append, noop, investigar")
    justificacion: str = Field(description="Razonamiento de la acción sugerida")
    patch: Optional[List[dict[str, Any]]] = Field(default=None, description="Operaciones JSON Patch para aplicar sobre /new/new_method_final.json")

class ChangeImpactPlan(BaseModel):
    resumen: str = Field(description="Resumen ejecutivo del plan de implementación")
    plan: List[ChangeImpactAction] = Field(description="Lista de acciones propuestas")


ANALYZE_CHANGE_PROMPT = """Eres un especialista en validación farmacéutica.
Debes analizar el siguiente contexto estructurado y producir un plan de implementación de cambios para el método analítico.

Consideraciones clave:
1. Cada ítem de `cambios` describe una modificación propuesta. Determina si corresponde a una prueba ya existente en el método nuevo.
2. Usa los nombres de pruebas en `pruebas_metodo_nuevo`, `pruebas_side_by_side` y `pruebas_referencia` para identificar equivalencias.
3. Si el cambio corresponde a una prueba existente, propone `accion = "replace"` y describe el patch JSON que actualizaría la información relevante.
4. Si el cambio introduce una prueba nueva, propone `accion = "append"` con un patch que agregue la prueba en la ruta `/pruebas/-` del método nuevo. Incluye la estructura mínima esperada (nombre de prueba y campos clave a completar más adelante).
5. Si no es posible determinar la acción, utiliza `accion = "investigar"` y explica qué información hace falta.

Devuelve tu respuesta en el siguiente formato JSON:
```json
{{
  "resumen": "...",
  "plan": [
    {{
      "cambio": "texto del cambio",
      "pruebas_fuente": ["lista de pruebas usadas como referencia"],
      "prueba_metodo_nuevo": "nombre coincidido o null si no aplica",
      "accion": "replace" | "append" | "noop" | "investigar",
      "justificacion": "explicación concisa",
      "patch": [
        {{"op": "replace", "path": "/pruebas/IDX", "value": {{...}}}} |
        {{"op": "add", "path": "/pruebas/-", "value": {{...}}}}
      ]
    }}
  ]
}}
```

Contexto estructurado:
<context>
{context}
</context>
"""


def _load_json_payload(files: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    """Extrae un payload JSON normalizado desde el filesystem virtual."""

    entry = files.get(path)
    if entry is None:
        return None

    if isinstance(entry, dict):
        if "data" in entry and isinstance(entry["data"], dict):
            return entry["data"]
        if "content" in entry and isinstance(entry["content"], str):
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


def _normalize_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    normalized = name.strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    return " ".join(normalized.split())


def _collect_prueba_names(pruebas: list[Prueba] | list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for prueba in pruebas or []:
        if isinstance(prueba, Prueba):
            names.append(prueba.prueba)
        elif isinstance(prueba, dict):
            value = prueba.get("prueba")
            if isinstance(value, str):
                names.append(value)
    return names


@tool(description=CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION)
def analyze_change_impact(
    change_control_path: str,
    new_method_path: str,
    side_by_side_path: str,
    reference_methods_path: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    logger.info("Iniciando 'analyze_change_impact'")
    files = state.get("files", {}) or {}

    cc_payload = _load_json_payload(files, change_control_path)
    new_method_payload = _load_json_payload(files, new_method_path)
    sbs_payload = _load_json_payload(files, side_by_side_path)
    ref_payload = _load_json_payload(files, reference_methods_path)

    if cc_payload is None:
        msg = f"No se encontró el archivo de control de cambios en {change_control_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        cc_model = ChangeControlModel(**cc_payload)
    except ValidationError as exc:
        msg = f"Error al validar control de cambios: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        sbs_model = SideBySideModel(**sbs_payload) if sbs_payload else None
    except ValidationError as exc:
        logger.warning("No se pudo validar side-by-side: %s", exc)
        sbs_model = None

    try:
        ref_model = ExtractionModel(**ref_payload) if ref_payload else None
    except ValidationError as exc:
        logger.warning("No se pudo validar métodos de referencia: %s", exc)
        ref_model = None

    changes_context = [
        {
            "prueba": item.prueba,
            "descripcion": item.texto,
            "prueba_normalizada": _normalize_name(item.prueba),
        }
        for item in cc_model.descripcion_cambio
    ]

    side_by_side_context = {
        "metodo_actual": _collect_prueba_names(sbs_model.metodo_actual) if sbs_model else [],
        "metodo_modificacion_propuesta": _collect_prueba_names(sbs_model.metodo_modificacion_propuesta) if sbs_model else [],
    }

    reference_context = _collect_prueba_names(ref_model.pruebas) if ref_model else []

    new_method_tests = []
    if isinstance(new_method_payload, dict):
        pruebas_data = new_method_payload.get("pruebas", [])
        new_method_tests = _collect_prueba_names(pruebas_data)

    llm_context = {
        "cambios": changes_context,
        "pruebas_side_by_side": side_by_side_context if sbs_model else None,
        "pruebas_referencia": {
            "disponible": True,
            "pruebas": reference_context,
        }
        if ref_model
        else None,
        "pruebas_metodo_nuevo": new_method_tests,
    }

    context_json = json.dumps(llm_context, ensure_ascii=False, indent=2)
    logger.debug("Contexto para LLM: %s", context_json)

    llm_structured = change_control_analysis_model.with_structured_output(ChangeImpactPlan)
    response = llm_structured.invoke([HumanMessage(content=ANALYZE_CHANGE_PROMPT.format(context=context_json))])
    plan_payload = response.model_dump()

    files_update = dict(files)
    files_update[CHANGE_IMPLEMENTATION_PLAN_PATH] = {
        "content": json.dumps(plan_payload, ensure_ascii=False, indent=2),
        "data": plan_payload,
    }

    summary = response.resumen
    details = f"Se generaron {len(response.plan)} acciones para implementar cambios."
    tool_message = f"{summary} {details}".strip()

    logger.info("Plan de implementación guardado en %s", CHANGE_IMPLEMENTATION_PLAN_PATH)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )