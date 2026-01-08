"""
Herramienta refactorizada para aplicar parches de método analítico.

Este módulo simplifica la carga y búsqueda de pruebas en métodos
analíticos (tanto legados como propuestos) a través de un índice
consistente. La idea principal es:

* Usar una única función ``load_tests`` para obtener una lista de
  pruebas a partir de un payload JSON que puede ser una lista de
  wrappers, una lista directa de pruebas o un dict con clave
  ``pruebas``/``tests``. Siempre que exista un ``source_id`` en el
  wrapper se preserva como ``_source_id`` en cada prueba.

* Construir un índice con ``build_test_index`` que permita localizar
  pruebas por tres claves: ``_source_id`` (id numérico del wrapper),
  ``section_id`` y un nombre normalizado (sin tildes ni mayúsculas).

* Utilizar una función ``find_test`` que consulte ese índice para
  devolver tanto el índice dentro de la lista como el objeto de
  prueba correspondiente. Primero se intenta por id numérico,
  luego por sección y finalmente por nombre.
"""

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
from typing import Annotated, Any, Dict, List, Optional, Tuple

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import APPLY_METHOD_PATCH_TOOL_DESCRIPTION
from src.tools.analyze_change_impact import (
    UnifiedInterventionPlan,
    UnifiedInterventionAction,
    ElementoMetodoPropuesto,
)
from src.models.structured_test_model import (
    TestSolution,
    MetodoAnaliticoFinal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes y configuración
# ---------------------------------------------------------------------------

PLAN_DEFAULT_PATH = "/new/change_implementation_plan.json"
METHOD_DEFAULT_PATH = "/new/new_method_final.json"
PATCH_LOG_PATH = "/logs/change_patch_log.jsonl"
PATCHES_DIR = "/new/applied_changes"

# Directorios base para búsqueda dinámica de archivos
ACTUAL_METHOD_DIR = "/actual_method"
PROPOSED_METHOD_DIR = "/proposed_method"
# Patrón para identificar archivos de contenido estructurado
STRUCTURED_CONTENT_PATTERN = re.compile(r"test_solution_structured_content_(.+)\.json$")

method_patch_model = init_chat_model(model="openai:gpt-5-mini")
MAX_LLM_RETRIES = 3


class EmptyLLMResponseError(Exception):
    """Excepción lanzada cuando el LLM retorna una respuesta vacía."""
    pass


class GeneratedMethodPatch(BaseModel):
    """Respuesta estructurada del LLM para generar/editar una prueba."""
    prueba_resultante: TestSolution
    comentarios: Optional[str] = Field(
        default=None,
        description="Notas breves sobre como se construyo la prueba final o recordatorios para el equipo",
    )


APPLY_METHOD_PATCH_SYSTEM = """Eres un quimico especialista en metodos analiticos farmaceuticos.
Debes generar el objeto `prueba_resultante` listo para insertarse en el metodo destino.

El objeto prueba_resultante debe seguir la estructura TestSolution con los siguientes campos:
- section_id (str): Numero de seccion (ej: "7.1", "7.2")
- section_title (str): Titulo completo de la seccion
- test_name (str): Nombre descriptivo del test
- test_type (str): Tipo de prueba ("Descripcion", "Identificacion", "Valoracion", "Impurezas", "Peso promedio", "Disolucion", "Uniformidad de contenido", "Uniformidad de unidades de dosificacion", "Control microbiologico", "Humedad", "Dureza", "Espesores", "Perdida por Secado", "Otros analisis")
- condiciones_cromatograficas (opcional): Condiciones HPLC/GC si aplica
- soluciones (opcional): Lista de soluciones con nombre_solucion y preparacion_solucion
- procedimiento (opcional): Objeto con texto del procedimiento, sst si aplica, tiempo_retencion, notas
- calculos (opcional): Formulas y variables de calculo
- criterio_aceptacion (opcional): Objeto con texto, tipo_criterio, tabla_criterios, notas
- equipos (opcional): Lista de equipos
- reactivos (opcional): Lista de reactivos
- referencias (opcional): Lista de referencias

Acciones:
- editar: parte de la prueba objetivo actual y ajustala segun la descripcion del cambio, aprovechando la evidencia del metodo legado y el metodo propuesto. Respeta el section_id proporcionado.
- adicionar: crea una prueba nueva con un section_id apropiado. Usa la mejor evidencia disponible del metodo propuesto.
- eliminar: conserva la trazabilidad. Devuelve la prueba con el mismo section_id y una nota clara de eliminacion en procedimiento.texto y criterio_aceptacion.texto.
- dejar igual: replica la prueba objetivo sin cambios.

Reglas:
- Siempre devuelve un JSON valido con `prueba_resultante` y `comentarios` (o null).
- Los campos obligatorios son: section_id, section_title, test_name, test_type.
- Usa texto tecnico en espanol; respeta unidades y datos numericos de las fuentes.
- Si faltan datos en todas las fuentes, devuelve el esqueleto minimo con placeholders claros en espanol.
- COPIA VERBATIM el texto de procedimientos y criterios de aceptacion cuando sea posible.

Formato de salida esperado:
{
  "prueba_resultante": {
    "section_id": "7.X",
    "section_title": "TITULO DE LA PRUEBA",
    "test_name": "Nombre descriptivo",
    "test_type": "Valoracion",
    "procedimiento": {"texto": "...", "sst": null, "tiempo_retencion": null, "notas": null},
    "criterio_aceptacion": {"texto": "...", "tipo_criterio": null, "tabla_criterios": null, "notas": null},
    ...
  },
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

<PRUEBA_METODO_PROPUESTO>
{prueba_propuesta}
</PRUEBA_METODO_PROPUESTO>

<METADATOS_METODO_DESTINO>
{metadatos_metodo}
</METADATOS_METODO_DESTINO>
"""


# ---------------------------------------------------------------------------
# Utilidades de normalización y carga de pruebas (REFACTORIZADO)
# ---------------------------------------------------------------------------

def _normalize_name(value: Optional[str]) -> Optional[str]:
    """Convierte un nombre a minúsculas, sin tildes ni espacios redundantes."""
    if not value:
        return None
    # Eliminar acentos
    normalized = unicodedata.normalize('NFD', value)
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    # Minúsculas y colapsar espacios
    return " ".join(normalized.strip().lower().split())


def _strip_section_prefix(name: Optional[str]) -> Optional[str]:
    """Elimina números de sección al inicio (ej. '7.3 Título' -> 'Título')."""
    if not name:
        return None
    return re.sub(r'^\d+(\.\d+)*\s*', '', name).strip()


def load_tests(payload: Any) -> List[Dict[str, Any]]:
    """
    Extrae una lista de pruebas de un payload que puede ser:
    - Una lista de wrappers {"tests": [...], "source_id": N}
    - Una lista directa de pruebas
    - Un dict con clave "pruebas" o "tests"

    Siempre que exista "source_id" en el wrapper, se copia a
    ``_source_id`` de cada prueba para conservar la trazabilidad.
    """
    tests: List[Dict[str, Any]] = []
    if payload is None:
        return tests
    
    # Si es lista
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "tests" in item and isinstance(item["tests"], list):
                # Es un wrapper con tests anidados
                sid = item.get("source_id")
                for test in item["tests"]:
                    if isinstance(test, dict):
                        t = test.copy()
                        if sid is not None:
                            t["_source_id"] = sid
                        tests.append(t)
            elif isinstance(item, dict):
                # Es una prueba directa
                tests.append(item.copy())
        return tests
    
    # Si es dict
    if isinstance(payload, dict):
        inner = payload.get("pruebas") or payload.get("tests")
        if isinstance(inner, list):
            return load_tests(inner)  # Recursivo para aplanar
        # Si es un dict de un método ya procesado
        if "pruebas" in payload and isinstance(payload["pruebas"], list):
            return [p.copy() for p in payload["pruebas"]]
    
    return tests


def build_test_index(tests: List[Dict[str, Any]]) -> Dict[str, Dict[str, Tuple[int, Dict[str, Any]]]]:
    """
    Construye un índice para localizar pruebas de forma eficiente. Devuelve
    un diccionario con tres subíndices:

    * ``by_wrapper``: clave = ``_source_id`` (string), valor = (idx, prueba)
    * ``by_section``: clave = ``section_id`` (string), valor = (idx, prueba)
    * ``by_name``: clave = nombre normalizado y sin prefijo de sección,
      valor = (idx, prueba)
    """
    by_wrapper: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    by_section: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    by_name: Dict[str, Tuple[int, Dict[str, Any]]] = {}
    
    for idx, test in enumerate(tests):
        # Clave por wrapper id (_source_id tiene prioridad)
        wid = test.get("_source_id") or test.get("source_id")
        if wid is not None:
            by_wrapper[str(wid)] = (idx, test)
        
        # Clave por sección
        sid = test.get("section_id")
        if sid is not None:
            by_section[str(sid)] = (idx, test)
        
        # Clave por nombre normalizado
        name = test.get("test_name") or test.get("section_title") or test.get("prueba")
        if name:
            key = _normalize_name(_strip_section_prefix(name))
            if key:
                by_name[key] = (idx, test)
    
    return {"by_wrapper": by_wrapper, "by_section": by_section, "by_name": by_name}


def find_test(
    index: Dict[str, Dict[str, Tuple[int, Dict[str, Any]]]],
    wrapper_id: Optional[int] = None,
    section_id: Optional[str] = None,
    name: Optional[str] = None
) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """
    Busca una prueba usando un índice. El orden de prioridad es:

    1. ``wrapper_id`` (``_source_id``) si se proporciona.
    2. ``section_id`` si es una cadena no vacía.
    3. ``name`` normalizado (sin prefijos de sección) y coincidencias parciales.

    Retorna una tupla (posición en la lista, prueba) o (None, None) si no se encuentra.
    """
    # 1. Buscar por wrapper id (_source_id)
    if wrapper_id is not None:
        entry = index["by_wrapper"].get(str(wrapper_id))
        if entry:
            return entry
    
    # 2. Buscar por section id
    if section_id:
        entry = index["by_section"].get(str(section_id))
        if entry:
            return entry
    
    # 3. Buscar por nombre normalizado exacto
    if name:
        key = _normalize_name(_strip_section_prefix(name))
        if key:
            entry = index["by_name"].get(key)
            if entry:
                return entry
            # Si no hay coincidencia exacta, buscar parcial
            for k, e in index["by_name"].items():
                if key in k or k in key:
                    return e
    
    return None, None


def _load_json_payload(files: Dict[str, Any], path: str) -> Optional[Dict[str, Any] | List]:
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


def _find_structured_content_files(files: Dict[str, Any], directory: str) -> List[str]:
    """
    Busca archivos con patrón test_solution_structured_content_*.json en un directorio.
    
    Args:
        files: Diccionario de archivos del estado
        directory: Directorio base (ej: '/actual_method')
    
    Returns:
        Lista de rutas de archivos encontrados
    """
    found = []
    dir_prefix = directory.rstrip("/") + "/"
    for path in files.keys():
        if path.startswith(dir_prefix) and STRUCTURED_CONTENT_PATTERN.search(path):
            found.append(path)
    return sorted(found)


def _load_all_tests_from_directory(files: Dict[str, Any], directory: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Carga todas las pruebas de archivos test_solution_structured_content_*.json en un directorio.
    
    Args:
        files: Diccionario de archivos del estado
        directory: Directorio base (ej: '/actual_method')
    
    Returns:
        Tupla (lista_de_pruebas, lista_de_archivos_usados)
    """
    all_tests: List[Dict[str, Any]] = []
    used_files: List[str] = []
    
    content_files = _find_structured_content_files(files, directory)
    
    for file_path in content_files:
        payload = _load_json_payload(files, file_path)
        if payload is not None:
            tests = load_tests(payload)
            # Agregar _source_file_name a cada prueba para trazabilidad
            match = STRUCTURED_CONTENT_PATTERN.search(file_path)
            source_file_name = match.group(1) if match else None
            for test in tests:
                if source_file_name:
                    test["_source_file_name"] = source_file_name
            all_tests.extend(tests)
            used_files.append(file_path)
            logger.info(f"  Cargadas {len(tests)} pruebas de {file_path}")
    
    return all_tests, used_files




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


@retry(
    stop=stop_after_attempt(MAX_LLM_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((EmptyLLMResponseError, ValidationError)),
    reraise=True,
)
def _invoke_patch_llm(
    llm_structured,
    system_prompt: str,
    human_prompt: str,
) -> GeneratedMethodPatch:
    """
    Invoca el LLM para generar el patch con retry automático.
    Lanza EmptyLLMResponseError si la respuesta está vacía.
    """
    logger.debug("Invocando LLM para generar patch de prueba...")
    response = llm_structured.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )
    
    if response is None:
        logger.warning("LLM retornó respuesta None, reintentando...")
        raise EmptyLLMResponseError("El LLM retornó una respuesta vacía (None)")
    
    if not hasattr(response, 'prueba_resultante') or response.prueba_resultante is None:
        logger.warning("LLM retornó respuesta sin prueba_resultante, reintentando...")
        raise EmptyLLMResponseError("El LLM retornó una respuesta sin prueba_resultante")
    
    logger.debug("LLM respondió exitosamente con prueba_resultante")
    return response


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
    new_method_path: str = METHOD_DEFAULT_PATH,
) -> Command:
    """
    Aplica una acción del plan de intervención al método. Utiliza índices
    para localizar la prueba objetivo en el método destino y conservar
    la trazabilidad mediante ``_source_id``. Si el método de destino
    no existe, se construye a partir del método legado. Para pruebas
    nuevas se utilizan los datos del método propuesto.
    """
    logger.info("Iniciando 'apply_method_patch' para la accion %s", action_index)
    files = state.get("files", {}) or {}

    # -------------------------------------------------------------------------
    # 1. Cargar el plan de intervención
    # -------------------------------------------------------------------------
    plan_payload = _load_json_payload(files, plan_path)
    if plan_payload is None:
        msg = f"No se encontró el plan de implementación en {plan_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    try:
        plan = UnifiedInterventionPlan.model_validate(plan_payload)
    except ValidationError as exc:
        msg = f"Formato de plan inválido: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    if action_index < 0 or action_index >= len(plan.plan_intervencion):
        msg = f"El índice {action_index} está fuera de rango (0–{len(plan.plan_intervencion) - 1})."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    action: UnifiedInterventionAction = plan.plan_intervencion[action_index]
    accion = (action.accion or "").lower().strip()
    descripcion = action.cambio or ""
    legacy_id = action.source_id_ma_legado
    legacy_name = action.prueba_ma_legado

    # -------------------------------------------------------------------------
    # 2. Cargar método base (nuevo o legado)
    # -------------------------------------------------------------------------
    method_entry = _load_json_payload(files, new_method_path)
    if method_entry and isinstance(method_entry, (dict, list)):
        method_payload = method_entry
    else:
        # Fallback: buscar archivos con patrón dinámico en /actual_method/
        legacy_tests, legacy_files = _load_all_tests_from_directory(files, ACTUAL_METHOD_DIR)
        if not legacy_tests:
            msg = f"No se encontró ningún método en {new_method_path} ni archivos test_solution_structured_content_*.json en {ACTUAL_METHOD_DIR}/."
            logger.error(msg)
            return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
        # Aplanar el método legado a un dict {"pruebas": [...]}
        method_payload = {"pruebas": legacy_tests}
        logger.info(f"Usando método legado como base: {len(method_payload['pruebas'])} pruebas de {len(legacy_files)} archivo(s).")

    # -------------------------------------------------------------------------
    # 3. Construir índice del método
    # -------------------------------------------------------------------------
    method_tests = load_tests(method_payload)
    method_index = build_test_index(method_tests)

    # -------------------------------------------------------------------------
    # 4. Localizar la prueba objetivo (para editar/eliminar)
    # -------------------------------------------------------------------------
    target_idx: Optional[int] = None
    target_prueba: Optional[Dict[str, Any]] = None
    if accion in {"editar", "eliminar"}:
        target_idx, target_prueba = find_test(method_index, legacy_id, None, legacy_name)
        if target_prueba is None:
            msg = f"No se encontró la prueba objetivo (id={legacy_id}, nombre={legacy_name}) en el método."
            logger.error(msg)
            return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # -------------------------------------------------------------------------
    # 5. Cargar métodos de referencia para el LLM
    # -------------------------------------------------------------------------
    # Cargar pruebas del método propuesto (búsqueda dinámica)
    proposed_tests, proposed_files = _load_all_tests_from_directory(files, PROPOSED_METHOD_DIR)
    if proposed_tests:
        logger.info(f"Cargadas {len(proposed_tests)} pruebas propuestas de {len(proposed_files)} archivo(s).")
    proposed_index = build_test_index(proposed_tests) if proposed_tests else {"by_wrapper": {}, "by_section": {}, "by_name": {}}

    # Cargar pruebas del método legado (para referencia del LLM, búsqueda dinámica)
    legacy_tests, legacy_files_ref = _load_all_tests_from_directory(files, ACTUAL_METHOD_DIR)
    if legacy_tests:
        logger.info(f"Cargadas {len(legacy_tests)} pruebas legadas de {len(legacy_files_ref)} archivo(s) para referencia.")
    legacy_index = build_test_index(legacy_tests) if legacy_tests else {"by_wrapper": {}, "by_section": {}, "by_name": {}}

    # Buscar prueba legacy original para el LLM
    legacy_prueba: Optional[Dict[str, Any]] = None
    if legacy_id is not None or legacy_name:
        _, legacy_prueba = find_test(legacy_index, legacy_id, None, legacy_name)

    # Seleccionar prueba de referencia del método propuesto
    prop_test: Optional[Dict[str, Any]] = None
    source_id_propuesto: Optional[int] = None
    if action.elemento_metodo_propuesto:
        idx_prop = action.elemento_metodo_propuesto.indice
        prop_id = action.elemento_metodo_propuesto.source_id
        prop_name = action.elemento_metodo_propuesto.prueba
        prop_source_file = action.elemento_metodo_propuesto.source_file_name
        source_id_propuesto = prop_id
        
        # Si hay source_file_name, filtrar pruebas por ese archivo primero
        if prop_source_file:
            # Filtrar pruebas que coincidan con el source_file_name
            filtered_tests = [
                t for t in proposed_tests 
                if t.get("_source_file_name") and prop_source_file in t.get("_source_file_name", "")
            ]
            if filtered_tests:
                logger.info(f"Filtradas {len(filtered_tests)} pruebas del archivo '{prop_source_file}'")
                # Buscar por índice dentro del archivo filtrado, o por nombre
                if idx_prop is not None and 0 <= idx_prop < len(filtered_tests):
                    prop_test = filtered_tests[idx_prop]
                elif prop_name:
                    # Buscar por nombre en las pruebas filtradas
                    prop_name_norm = _normalize_name(prop_name)
                    for t in filtered_tests:
                        t_name = _normalize_name(t.get("test_name") or t.get("section_title") or t.get("prueba"))
                        if t_name and prop_name_norm and prop_name_norm in t_name:
                            prop_test = t
                            break
            else:
                logger.warning(f"No se encontraron pruebas con source_file_name que contenga '{prop_source_file}'")
        
        # Fallback: búsqueda sin filtro de archivo (comportamiento original)
        if prop_test is None:
            if idx_prop is not None and 0 <= idx_prop < len(proposed_tests):
                prop_test = proposed_tests[idx_prop]
            elif prop_id is not None:
                _, prop_test = find_test(proposed_index, prop_id, None, None)
            elif prop_name:
                _, prop_test = find_test(proposed_index, None, None, prop_name)

    method_summary = _build_method_summary(method_payload if isinstance(method_payload, dict) else {})

    # -------------------------------------------------------------------------
    # 6. Procesar la acción
    # -------------------------------------------------------------------------
    
    # Caso dejar igual: no se modifica nada
    if accion == "dejar igual":
        msg = f"Acción #{action_index}: se deja sin cambios la prueba con id={legacy_id}."
        logger.info(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Caso eliminar: quitar la prueba y actualizar
    if accion == "eliminar":
        updated_tests = method_tests.copy()
        if target_idx is not None:
            updated_tests.pop(target_idx)
        
        updated_payload = {"pruebas": updated_tests}
        files_update = dict(files)
        files_update[new_method_path] = {
            "content": json.dumps(updated_payload, ensure_ascii=False, indent=2),
            "data": updated_payload,
            "modified_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_patch(files_update, action_index, accion, None, legacy_id, legacy_name)
        _append_log(files_update, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_path": plan_path,
            "method_path": new_method_path,
            "action_index": action_index,
            "accion": accion,
            "target_id": legacy_id,
        })
        summary = f"Prueba eliminada (id={legacy_id}, nombre={legacy_name})."
        logger.info(summary)
        return Command(update={"files": files_update, "messages": [ToolMessage(content=summary, tool_call_id=tool_call_id)]})

    # Casos editar / adicionar -> invocar LLM
    human_prompt = APPLY_METHOD_PATCH_HUMAN_TEMPLATE.format(
        descripcion_cambio=descripcion or "(sin descripción)",
        accion=accion,
        id_sugerido=legacy_id or "(sin id)",
        prueba_objetivo=_pretty_json(target_prueba),
        prueba_legacy=_pretty_json(legacy_prueba),
        prueba_propuesta=_pretty_json(prop_test),
        metadatos_metodo=_pretty_json(method_summary),
    )

    llm_structured = method_patch_model.with_structured_output(GeneratedMethodPatch)
    try:
        llm_response = _invoke_patch_llm(llm_structured, APPLY_METHOD_PATCH_SYSTEM, human_prompt)
    except EmptyLLMResponseError as exc:
        msg = f"El LLM retornó respuesta vacía después de {MAX_LLM_RETRIES} intentos: {exc}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    except Exception as exc:  # noqa: BLE001
        msg = f"Error invocando LLM: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    prueba_json = llm_response.prueba_resultante.model_dump(mode="json")
    comentario = llm_response.comentarios

    # Conservar _source_id para mantener trazabilidad
    if accion == "editar" and target_prueba:
        original_id = target_prueba.get("_source_id") or target_prueba.get("source_id")
        if original_id is not None:
            prueba_json["_source_id"] = original_id
            logger.debug(f"Preservado _source_id={original_id} en prueba editada")
    elif accion == "adicionar" and source_id_propuesto is not None:
        prueba_json["_source_id"] = source_id_propuesto
        logger.debug(f"Asignado _source_id={source_id_propuesto} a prueba nueva")

    # Si se sugirió un id de sección y no está presente, asignarlo
    if legacy_id and not prueba_json.get("section_id"):
        prueba_json["section_id"] = legacy_id

    # Validar estructura de la prueba generada
    try:
        TestSolution(**prueba_json)
    except ValidationError as exc:
        msg = f"El contenido generado por el LLM no cumple el esquema TestSolution: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Actualizar método
    updated_tests = method_tests.copy()
    if accion == "editar" and target_idx is not None:
        updated_tests[target_idx] = prueba_json
    elif accion == "adicionar":
        updated_tests.append(prueba_json)
    else:
        msg = f"Acción no soportada: {accion}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    updated_payload = {"pruebas": updated_tests}
    files_update = dict(files)
    files_update[new_method_path] = {
        "content": json.dumps(updated_payload, ensure_ascii=False, indent=2),
        "data": updated_payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_patch(files_update, action_index, accion, prueba_json, legacy_id, legacy_name)
    _append_log(files_update, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "plan_path": plan_path,
        "method_path": new_method_path,
        "action_index": action_index,
        "accion": accion,
        "target_id": legacy_id,
    })

    summary = f"Prueba {accion} aplicada (id={legacy_id})."
    if comentario:
        summary += f" Notas: {comentario}"
    logger.info(summary)
    
    return Command(update={"files": files_update, "messages": [ToolMessage(content=summary, tool_call_id=tool_call_id)]})
