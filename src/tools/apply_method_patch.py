from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, List, Iterable

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import APPLY_METHOD_PATCH_TOOL_DESCRIPTION
from src.tools.analyze_change_impact import (
    UnifiedInterventionPlan,
    UnifiedInterventionAction,
)
from src.models.analytical_method_models import (
    Prueba as MetodoPrueba,
    MetodoAnaliticoNuevo,
    Especificacion,
    CondicionCromatografica,
    Solucion,
)

logger = logging.getLogger(__name__)

PLAN_DEFAULT_PATH = "/new/change_implementation_plan.json"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"
PATCH_LOG_PATH = "/logs/change_patch_log.jsonl"
PATCHES_DIR = "/new/applied_changes"
REFERENCE_METHOD_DEFAULT_PATH = "/new/reference_methods.json"
SIDE_BY_SIDE_DEFAULT_PATH = "/new/side_by_side.json"
LEGACY_METHOD_DEFAULT_PATH = "/actual_method/test_solution_structured_content.json"
PROPOSED_METHOD_DEFAULT_PATH = "/proposed_method/test_solution_structured_content.json"
method_patch_model = init_chat_model(model="openai:gpt-5-mini", temperature=0)


class GeneratedMethodPatch(BaseModel):
    """Respuesta estructurada del LLM para generar/editar una prueba."""
    prueba_resultante: MetodoPrueba
    comentarios: Optional[str] = Field(
        default=None,
        description="Notas breves sobre como se construyo la prueba final o recordatorios para el equipo",
    )


APPLY_METHOD_PATCH_SYSTEM = """Eres un quimico especialista en metodos analiticos farmaceuticos.
Debes generar el objeto `prueba_resultante` listo para insertarse en el metodo destino.

Acciones:
- editar: parte de la prueba objetivo actual y ajustala segun la descripcion del cambio, aprovechando la evidencia de legacy, side-by-side y metodos de referencia. Respeta o reutiliza el id proporcionado.
- adicionar: crea una prueba nueva usando el id_sugerido si existe; si falta, genera uno de 8 caracteres hexadecimales. Usa la mejor evidencia disponible.
- eliminar: conserva la trazabilidad. Devuelve la prueba con el mismo id y una nota clara de eliminacion en `procedimientos` y `especificaciones`.
- dejar igual: replica la prueba objetivo sin cambios.

Reglas:
- Siempre devuelve un JSON valido con `prueba_resultante` y `comentarios` (o null).
- Llena siempre `procedimientos` y al menos una entrada en `especificaciones`. Nunca dejes campos obligatorios vacios.
- Usa texto tecnico en espanol; respeta unidades y datos numericos de las fuentes.
- Si faltan datos en todas las fuentes, devuelve el esqueleto minimo con placeholders claros en espanol.

Formato de salida esperado:
{
  "prueba_resultante": {... objeto completo de la prueba ...},
  "comentarios": "Notas breves (o null)"
}
"""

APPLY_METHOD_PATCH_HUMAN_TEMPLATE = """Cambio aprobado:
<DESCRIPCION_CAMBIO>
{descripcion_cambio}
</DESCRIPCION_CAMBIO>

Accion solicitada: {accion}
ID sugerido: {id_sugerido}

<PRUEBA_OBJETIVO_METODO_DESTINO>
{prueba_objetivo}
</PRUEBA_OBJETIVO_METODO_DESTINO>

<PRUEBA_LEGACY>
{prueba_legacy}
</PRUEBA_LEGACY>

<PRUEBA_SIDE_BY_SIDE_PROPUESTA>
{prueba_side_propuesta}
</PRUEBA_SIDE_BY_SIDE_PROPUESTA>

<PRUEBA_METODOS_REFERENCIA>
{prueba_referencia}
</PRUEBA_METODOS_REFERENCIA>

<FUENTES_PLAN>
{pruebas_fuente_plan}
</FUENTES_PLAN>

<METADATOS_METODO_DESTINO>
{metadatos_metodo}
</METADATOS_METODO_DESTINO>
"""


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


def _transform_legacy_tests(legacy_tests: list) -> list[dict[str, Any]]:
    """
    Transforma pruebas del formato legado (TestSolution de structured_test_model.py) 
    al nuevo formato requerido por MetodoAnaliticoNuevo (Prueba de analytical_method_models.py).
    
    Formato legado (TestSolution):
    - section_id, section_title, test_name, test_type
    - condiciones_cromatograficas: CondicionCromatografica con nombre_condicion/valor_condicion
    - soluciones: List[Solucion] con nombre_solucion/preparacion_solucion/notas
    - procedimiento: Procedimiento con texto/notas/tiempo_retencion
    - criterio_aceptacion: CriterioAceptacion con texto/notas/tabla_criterios
    - equipos: List[str]
    - reactivos: List[str]
    - procedimiento_sst: List[OrdenInyeccion]
    
    Formato nuevo (Prueba):
    - id_prueba, prueba, procedimientos
    - condiciones_cromatograficas: List[CondicionCromatografica] con nombre/descripcion
    - soluciones: List[Solucion] con nombre_solucion/preparacion_solucion
    - equipos: List[str]
    - reactivos: List[str]
    - especificaciones: List[Especificacion] con prueba/texto_especificacion/subespecificacion
    
    El formato legado puede venir envuelto en: [{tests: [...], source_id: N}, ...]
    """
    # Primero, aplanar si hay wrappers con "tests" anidados
    flattened_tests = []
    for item in legacy_tests:
        if not isinstance(item, dict):
            continue
        # Si el item tiene "tests" anidado (wrapper de TestSolutions), extraer esas pruebas
        if "tests" in item and isinstance(item["tests"], list):
            flattened_tests.extend(item["tests"])
        else:
            flattened_tests.append(item)
    
    transformed = []
    
    for test in flattened_tests:
        if not isinstance(test, dict):
            continue
        
        # Nombre de la prueba (prioridad: test_name > section_title > prueba)
        prueba_nombre = test.get("test_name") or test.get("section_title") or test.get("prueba") or "Sin nombre"
        
        # Mapear campos del formato TestSolution al formato Prueba
        new_test: dict[str, Any] = {
            "id_prueba": test.get("section_id") or test.get("id_prueba"),
            "prueba": prueba_nombre,
            "procedimientos": "",
            "equipos": [],
            "condiciones_cromatograficas": [],
            "reactivos": [],
            "soluciones": [],
            "especificaciones": [],
        }
        
        # --- Extraer procedimiento ---
        # TestSolution.procedimiento es un objeto Procedimiento con {texto, notas, tiempo_retencion}
        proc = test.get("procedimiento")
        if isinstance(proc, dict):
            new_test["procedimientos"] = proc.get("texto") or ""
        elif isinstance(proc, str):
            new_test["procedimientos"] = proc
        
        # --- Extraer equipos (ya es List[str] en TestSolution) ---
        equipos = test.get("equipos")
        if isinstance(equipos, list):
            for eq in equipos:
                if isinstance(eq, str):
                    new_test["equipos"].append(eq)
                elif isinstance(eq, dict):
                    # Por si acaso viene como dict con "nombre"
                    new_test["equipos"].append(eq.get("nombre") or str(eq))
        
        # --- Extraer reactivos (ya es List[str] en TestSolution) ---
        reactivos = test.get("reactivos")
        if isinstance(reactivos, list):
            for r in reactivos:
                if isinstance(r, str):
                    new_test["reactivos"].append(r)
        
        # --- Extraer condiciones cromatográficas ---
        # TestSolution.condiciones_cromatograficas es CondicionCromatografica con nombre_condicion/valor_condicion
        # Prueba.condiciones_cromatograficas es List[CondicionCromatografica] con nombre/descripcion
        cond_crom = test.get("condiciones_cromatograficas")
        if isinstance(cond_crom, dict):
            # Mapear nombre_condicion -> nombre, valor_condicion -> descripcion
            new_test["condiciones_cromatograficas"].append({
                "nombre": cond_crom.get("nombre_condicion") or cond_crom.get("nombre") or "Condición",
                "descripcion": cond_crom.get("valor_condicion") or cond_crom.get("descripcion") or str(cond_crom),
            })
        elif isinstance(cond_crom, list):
            for cond in cond_crom:
                if isinstance(cond, dict):
                    new_test["condiciones_cromatograficas"].append({
                        "nombre": cond.get("nombre_condicion") or cond.get("nombre") or "Condición",
                        "descripcion": cond.get("valor_condicion") or cond.get("descripcion") or str(cond),
                    })
        
        # --- Extraer soluciones ---
        # TestSolution.soluciones es List[Solucion] con nombre_solucion/preparacion_solucion/notas
        # Prueba.soluciones es List[Solucion] con nombre_solucion/preparacion_solucion (sin notas)
        soluciones = test.get("soluciones")
        if isinstance(soluciones, list):
            for sol in soluciones:
                if isinstance(sol, dict):
                    new_test["soluciones"].append({
                        "nombre_solucion": sol.get("nombre_solucion") or sol.get("nombre") or "Solución",
                        "preparacion_solucion": sol.get("preparacion_solucion") or sol.get("preparacion") or "",
                    })
        
        # --- Extraer especificaciones desde criterio_aceptacion ---
        # TestSolution.criterio_aceptacion es CriterioAceptacion con texto/notas/tabla_criterios
        # Prueba.especificaciones es List[Especificacion] con prueba/texto_especificacion/subespecificacion
        criterio = test.get("criterio_aceptacion")
        especificaciones_existentes = test.get("especificaciones")
        
        if isinstance(especificaciones_existentes, list) and especificaciones_existentes:
            # Si ya tiene especificaciones en formato nuevo, usarlas directamente
            for esp in especificaciones_existentes:
                if isinstance(esp, dict):
                    new_test["especificaciones"].append({
                        "prueba": esp.get("prueba") or prueba_nombre,
                        "texto_especificacion": esp.get("texto_especificacion") or esp.get("criterio") or "",
                        "subespecificacion": esp.get("subespecificacion"),
                    })
        elif isinstance(criterio, dict):
            # Transformar CriterioAceptacion a Especificacion
            texto_criterio = criterio.get("texto") or ""
            
            # Construir subespecificaciones desde tabla_criterios si existe
            subespecificaciones = None
            tabla_criterios = criterio.get("tabla_criterios")
            if isinstance(tabla_criterios, list) and tabla_criterios:
                subespecificaciones = []
                for tc in tabla_criterios:
                    if isinstance(tc, dict):
                        subespecificaciones.append({
                            "nombre_subespecificacion": tc.get("etapa") or tc.get("nombre_subespecificacion") or "",
                            "criterio_aceptacion_subespecificacion": tc.get("criterio_aceptacion") or tc.get("criterio_aceptacion_subespecificacion") or "",
                        })
            
            new_test["especificaciones"].append({
                "prueba": prueba_nombre,
                "texto_especificacion": texto_criterio,
                "subespecificacion": subespecificaciones if subespecificaciones else None,
            })
        elif isinstance(criterio, str):
            new_test["especificaciones"].append({
                "prueba": prueba_nombre,
                "texto_especificacion": criterio,
                "subespecificacion": None,
            })
        else:
            # Crear especificación por defecto
            new_test["especificaciones"].append({
                "prueba": prueba_nombre,
                "texto_especificacion": "Ver procedimiento",
                "subespecificacion": None,
            })
        
        transformed.append(new_test)
    
    logger.debug(f"Transformadas {len(transformed)} pruebas del formato TestSolution al formato Prueba.")
    return transformed


def _to_jsonable(prueba: Any) -> Optional[dict[str, Any]]:
    if prueba is None:
        return None
    if isinstance(prueba, dict):
        return deepcopy(prueba)
    if hasattr(prueba, "model_dump"):
        return prueba.model_dump(mode="json")
    return json.loads(json.dumps(prueba, ensure_ascii=False))


def _extract_pruebas_list(payload: Any) -> list:
    """
    Extrae la lista de pruebas de un payload que puede ser:
    - Una lista de wrappers con estructura [{"tests": [...], "source_id": N}, ...] (formato legado)
    - Una lista directa de pruebas
    - Un dict con clave "pruebas" o "tests"
    - None
    
    Returns:
        Lista de pruebas aplanada (puede estar vacía)
    """
    if payload is None:
        return []
    
    if isinstance(payload, list):
        # Verificar si es una lista de wrappers con "tests" anidados
        # Formato: [{"tests": [...], "source_id": N}, ...]
        flattened = []
        for item in payload:
            if isinstance(item, dict) and "tests" in item and isinstance(item["tests"], list):
                # Es un wrapper, extraer las pruebas
                flattened.extend(item["tests"])
            elif isinstance(item, dict):
                # Es una prueba directa
                flattened.append(item)
        
        # Si se aplanaron pruebas, retornar la lista aplanada
        if flattened:
            return flattened
        # Si no hay nada, retornar la lista original
        return payload
    
    if isinstance(payload, dict):
        # Intentar extraer de "pruebas" o "tests"
        if "pruebas" in payload:
            pruebas = payload["pruebas"]
            if isinstance(pruebas, list):
                return _extract_pruebas_list(pruebas)  # Recursivo para manejar wrappers
            return []
        if "tests" in payload:
            tests = payload["tests"]
            if isinstance(tests, list):
                return tests
            return []
    
    return []


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


def _build_method_summary(method_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: method_payload.get(key)
        for key in [
            "tipo_metodo",
            "nombre_producto",
            "numero_metodo",
            "version_metodo",
            "codigo_producto",
        ]
    }


def _append_log(files: dict[str, Any], entry: dict[str, Any]) -> None:
    payload = json.dumps(entry, ensure_ascii=False)
    log_entry = payload + "\n"

    existing = files.get(PATCH_LOG_PATH)
    if isinstance(existing, dict) and isinstance(existing.get("content"), str):
        log_entry = existing["content"] + log_entry

    files[PATCH_LOG_PATH] = {"content": log_entry, "data": None, "modified_at": datetime.now(timezone.utc).isoformat()}


def _format_indices(indices: Iterable[int]) -> str:
    return ", ".join(str(idx) for idx in indices)


def _pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) if data is not None else "null"


def _save_patch(
    files: dict[str, Any],
    action_index: int,
    accion: str,
    prueba_json: Optional[dict[str, Any]],
    target_id: Optional[str],
    target_name: Optional[str],
) -> None:
    patch_payload = {
        "action_index": action_index,
        "accion": accion,
        "id_prueba": target_id or (prueba_json or {}).get("id_prueba"),
        "prueba": target_name or (prueba_json or {}).get("prueba"),
        "contenido": prueba_json,
    }
    patch_path = f"{PATCHES_DIR}/{action_index}.json"
    files[patch_path] = {
        "content": json.dumps(patch_payload, ensure_ascii=False, indent=2),
        "data": patch_payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }


@tool(description=APPLY_METHOD_PATCH_TOOL_DESCRIPTION)
def apply_method_patch(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    plan_path: str = PLAN_DEFAULT_PATH,
    action_index: int = 0,
    side_by_side_path: str = SIDE_BY_SIDE_DEFAULT_PATH,
    proposed_method_path: str = PROPOSED_METHOD_DEFAULT_PATH,
    reference_method_path: str = REFERENCE_METHOD_DEFAULT_PATH,
    legacy_method_path: str = LEGACY_METHOD_DEFAULT_PATH,
    new_method_path: str = METHOD_DEFAULT_PATH,
) -> Command:
    logger.info("Iniciando 'apply_method_patch' para la accion %s", action_index)
    files = state.get("files", {}) or {}

    plan_payload = _load_json_payload(files, plan_path)
    if plan_payload is None:
        msg = f"No se encontro el plan de implementacion en {plan_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Validar y cargar el plan unificado
    try:
        unified_plan = UnifiedInterventionPlan.model_validate(plan_payload)
    except ValidationError as exc:
        msg = f"El plan de intervencion tiene formato invalido: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    if action_index < 0 or action_index >= len(unified_plan.plan_intervencion):
        msg = f"El indice {action_index} esta fuera del rango del plan ({len(unified_plan.plan_intervencion)} acciones)."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    action: UnifiedInterventionAction = unified_plan.plan_intervencion[action_index]
    accion_normalizada = action.accion
    descripcion_cambio = action.cambio or ""
    target_id = action.source_id_ma_legado
    target_name = action.prueba_ma_legado
    
    # Extraer referencias de side_by_side y metodo_referencia
    id_side = None
    name_side = None
    idx_side = None
    if action.elemento_side_by_side:
        name_side = action.elemento_side_by_side.prueba
        idx_side = action.elemento_side_by_side.indice
    
    id_ref = None
    name_ref = None
    idx_ref = None
    if action.elemento_metodo_referencia:
        name_ref = action.elemento_metodo_referencia.prueba
        idx_ref = action.elemento_metodo_referencia.indice

    # Cargar método base: primero intentar el nuevo, si no existe usar el legado
    method_payload = _load_json_payload(files, new_method_path)
    using_legacy_as_base = False
    
    if method_payload is None:
        logger.info(f"No existe {new_method_path}, usando método legado como base.")
        legacy_raw = _load_json_payload(files, legacy_method_path)
        using_legacy_as_base = True
        
        if legacy_raw is None:
            msg = f"No se encontró ni el método nuevo ({new_method_path}) ni el legado ({legacy_method_path})."
            logger.error(msg)
            return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
        
        # El archivo legado puede ser una lista directa de pruebas o un dict con "tests"
        if isinstance(legacy_raw, list):
            # Transformar pruebas del formato legado al nuevo formato
            pruebas_transformadas = _transform_legacy_tests(legacy_raw)
            method_payload = {"pruebas": pruebas_transformadas}
            logger.debug(f"Método legado transformado: {len(pruebas_transformadas)} pruebas.")
        else:
            method_payload = legacy_raw

    # Normalizar estructura: el método legado puede tener "tests" en lugar de "pruebas"
    if isinstance(method_payload, dict):
        if "tests" in method_payload and "pruebas" not in method_payload:
            # Transformar pruebas del formato legado al nuevo formato
            pruebas_transformadas = _transform_legacy_tests(method_payload.pop("tests"))
            method_payload["pruebas"] = pruebas_transformadas
            logger.debug(f"Renombrado y transformado 'tests' a 'pruebas': {len(pruebas_transformadas)} pruebas.")

    try:
        method_model = MetodoAnaliticoNuevo(**method_payload)
    except ValidationError as exc:
        msg = f"El metodo actual no cumple el esquema esperado: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_json = method_model.model_dump(mode="json")
    pruebas_metodo = method_json.get("pruebas", [])

    target_index, target_prueba = _find_prueba_entry(pruebas_metodo, target_id, target_name)
    if accion_normalizada in {"editar", "eliminar"} and target_prueba is None:
        msg = (
            f"No se pudo localizar la prueba objetivo (id: {target_id}, nombre: {target_name}) "
            f"en el metodo destino para la accion {accion_normalizada}."
        )
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    raw_side_by_side_payload = _load_json_payload(files, side_by_side_path)
    proposed_payload = _load_json_payload(files, proposed_method_path)
    if proposed_payload:
        side_by_side_payload = {"metodo_modificacion_propuesta": proposed_payload}
        logger.info("Usando metodo propuesto de /proposed_method/ para side-by-side.")
    else:
        side_by_side_payload = raw_side_by_side_payload
    reference_payload = _load_json_payload(files, reference_method_path)
    legacy_payload = _load_json_payload(files, legacy_method_path)

    # Extraer lista de pruebas del legado (puede ser lista directa o dict con "pruebas"/"tests")
    legacy_pruebas_list = _extract_pruebas_list(legacy_payload)
    legacy_prueba = _find_prueba_data(legacy_pruebas_list, target_id, target_name)
    
    # Buscar en side_by_side usando índice o nombre (solo metodo_modificacion_propuesta)
    side_propuesta = None
    if side_by_side_payload and isinstance(side_by_side_payload, dict):
        metodo_propuesta_list = _extract_pruebas_list(side_by_side_payload.get("metodo_modificacion_propuesta") or [])
        if idx_side is not None and 0 <= idx_side < len(metodo_propuesta_list):
            side_propuesta = metodo_propuesta_list[idx_side]
        elif name_side:
            side_propuesta = _find_prueba_data(metodo_propuesta_list, None, name_side)
    
    # Buscar en reference_methods usando índice o nombre
    ref_prueba = None
    if reference_payload:
        ref_pruebas_list = _extract_pruebas_list(reference_payload)
        if idx_ref is not None and 0 <= idx_ref < len(ref_pruebas_list):
            ref_prueba = ref_pruebas_list[idx_ref]
        elif name_ref:
            ref_prueba = _find_prueba_data(ref_pruebas_list, None, name_ref)

    fuentes_contexto = []
    if legacy_prueba:
        fuentes_contexto.append({"origen": "metodo_legacy", "contenido": legacy_prueba})
    if side_propuesta:
        fuentes_contexto.append({"origen": "side_by_side_modificacion", "contenido": side_propuesta})
    if ref_prueba:
        fuentes_contexto.append({"origen": "reference_method", "contenido": ref_prueba})

    method_summary = _build_method_summary(method_json)
    suggested_id = target_id or id_side or id_ref

    if accion_normalizada == "dejar igual":
        summary_message = f"Accion #{action_index}: se mantiene sin cambios la prueba objetivo (id: {target_id})."
        logger.info(summary_message)
        return Command(update={"messages": [ToolMessage(content=summary_message, tool_call_id=tool_call_id)]})

    if accion_normalizada == "eliminar":
        updated_method = deepcopy(method_json)
        if target_index is not None:
            removed = updated_method["pruebas"].pop(target_index)
        else:
            removed = None

        try:
            validated_method = MetodoAnaliticoNuevo(**updated_method)
        except ValidationError as exc:
            msg = f"La version resultante del metodo no paso la validacion despues de eliminar: {exc}"
            logger.exception(msg)
            return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

        method_dump = validated_method.model_dump(mode="json")
        method_str = json.dumps(method_dump, ensure_ascii=False, indent=2)

        summary_message = f"Prueba eliminada del metodo (accion #{action_index}, id: {target_id}, nombre: {target_name})."

        files_update = dict(files)
        _save_patch(files_update, action_index, accion_normalizada, None, target_id, target_name)
        files_update[new_method_path] = {"content": method_str, "data": method_dump}
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_path": plan_path,
            "method_path": new_method_path,
            "action_index": action_index,
            "accion": accion_normalizada,
            "target_id": target_id,
        }
        _append_log(files_update, log_entry)

        logger.info(summary_message)
        return Command(
            update={
                "files": files_update,
                "messages": [ToolMessage(content=summary_message, tool_call_id=tool_call_id)],
            }
        )

    # Acciones editar / adicionar -> LLM
    human_prompt = APPLY_METHOD_PATCH_HUMAN_TEMPLATE.format(
        descripcion_cambio=descripcion_cambio or "(sin descripcion)",
        accion=accion_normalizada,
        id_sugerido=suggested_id or "(sin id sugerido)",
        prueba_objetivo=_pretty_json(target_prueba),
        prueba_legacy=_pretty_json(legacy_prueba),
        prueba_side_propuesta=_pretty_json(side_propuesta),
        prueba_referencia=_pretty_json(ref_prueba),
        pruebas_fuente_plan=_pretty_json(fuentes_contexto),
        metadatos_metodo=_pretty_json(method_summary),
    )

    llm_structured = method_patch_model.with_structured_output(GeneratedMethodPatch)
    try:
        llm_response = llm_structured.invoke(
            [
                SystemMessage(content=APPLY_METHOD_PATCH_SYSTEM),
                HumanMessage(content=human_prompt),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"El LLM no pudo generar la prueba actualizada: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    prueba_payload = _to_jsonable(llm_response.prueba_resultante) or {}
    if suggested_id and not prueba_payload.get("id_prueba"):
        prueba_payload["id_prueba"] = suggested_id

    try:
        prueba_actualizada = MetodoPrueba(**prueba_payload)
    except ValidationError as exc:
        msg = f"El contenido generado por el LLM no cumple el esquema de una prueba: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    prueba_json = prueba_actualizada.model_dump(mode="json")
    updated_method = deepcopy(method_json)
    if accion_normalizada == "editar" and target_index is not None:
        updated_method["pruebas"][target_index] = prueba_json
    elif accion_normalizada == "adicionar":
        updated_method.setdefault("pruebas", []).append(prueba_json)
    else:
        msg = f"La accion {accion_normalizada} no es soportada para generacion automatica."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        validated_method = MetodoAnaliticoNuevo(**updated_method)
    except ValidationError as exc:
        msg = f"La version resultante del metodo no paso la validacion: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    method_dump = validated_method.model_dump(mode="json")
    method_str = json.dumps(method_dump, ensure_ascii=False, indent=2)

    summary_message = f"Prueba actualizada aplicada al metodo (accion #{action_index}, {accion_normalizada})."
    if llm_response.comentarios:
        summary_message += f" Notas del LLM: {llm_response.comentarios}"

    files_update = dict(files)
    _save_patch(files_update, action_index, accion_normalizada, prueba_json, target_id, target_name)
    files_update[new_method_path] = {"content": method_str, "data": method_dump}
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "plan_path": plan_path,
        "method_path": new_method_path,
        "action_index": action_index,
        "accion": accion_normalizada,
        "target_id": target_id,
    }
    _append_log(files_update, log_entry)

    logger.info(summary_message)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=summary_message, tool_call_id=tool_call_id)],
        }
    )
