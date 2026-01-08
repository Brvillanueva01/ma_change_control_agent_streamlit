"""
Tool mejorado para análisis de control de cambios con validaciones robustas,
retry logic y logging detallado.
"""

from __future__ import annotations

import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*",
)

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, Literal, List, Dict

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION
from src.prompts.tool_llm_calls_prompts import (
    UNIFIED_CHANGE_HUMAN_ANALYSIS_PROMPT,
    UNIFIED_CHANGE_SYSTEM_ANALYSIS_PROMPT,
)

# --- Configuración ---
logger = logging.getLogger(__name__)

# --- LLMs ---
change_control_analysis_model = init_chat_model(model="openai:gpt-5-mini")


# --- Modelos Pydantic ---
class CambioListaCambios(BaseModel):
    """Referencia a un cambio en la lista de cambios del control de cambios."""
    indice: int = Field(description="Índice del cambio en la lista de cambios (0-indexed)")
    texto: str = Field(description="Texto completo del cambio de /new/change_control_summary.json")
    source_reference_file: Optional[str] = Field(
        default=None,
        description="Código del método/archivo de referencia de donde proviene la prueba propuesta"
    )


class ElementoMetodoPropuesto(BaseModel):
    """Referencia a una prueba en el método propuesto."""
    prueba: str = Field(description="Nombre de la prueba en el método propuesto")
    indice: int = Field(description="Índice de la prueba en /proposed_method/test_solution_structured_content.json")
    source_id: Optional[int] = Field(default=None, description="source_id de la prueba en el método propuesto")
    source_file_name: Optional[str] = Field(
        default=None,
        description="Nombre del archivo de origen en /proposed_method/ de donde proviene esta prueba"
    )


class UnifiedInterventionAction(BaseModel):
    """Una acción individual en el plan de intervención."""
    orden: int = Field(description="Número de orden en el plan de intervención")
    cambio: str = Field(description="Descripción concisa del cambio a implementar")
    prueba_ma_legado: Optional[str] = Field(
        default=None,
        description="Nombre de la prueba del método legado o null si es nueva",
    )
    source_id_ma_legado: Optional[int] = Field(
        default=None,
        description="source_id numérico del wrapper en /actual_method/test_solution_structured_content.json o null",
    )
    accion: Literal["editar", "adicionar", "eliminar", "dejar igual"] = Field(
        description="Acción requerida: editar, adicionar, eliminar o dejar igual"
    )
    cambio_lista_cambios: Optional[CambioListaCambios] = Field(
        default=None,
        description="Elemento de lista_cambios con índice y texto. null si no hay cambio (dejar igual)",
    )
    elemento_metodo_propuesto: Optional[ElementoMetodoPropuesto] = Field(
        default=None,
        description="Prueba e índice en /proposed_method/test_solution_structured_content.json. null si no aplica (ej: eliminar)",
    )

    @field_validator("accion", mode="before")
    @classmethod
    def _normalize_accion(cls, value: Any) -> str:
        """Normaliza variaciones de nombres de acciones al formato estándar."""
        if isinstance(value, str):
            normalized = value.strip().lower().replace("\u00f1", "n")

            mapping = {
                "editar": "editar",
                "edita": "editar",
                "modificar": "editar",
                "actualizar": "editar",
                "adicionar": "adicionar",
                "agregar": "adicionar",
                "anadir": "adicionar",
                "aniadir": "adicionar",
                "nuevo": "adicionar",
                "nueva": "adicionar",
                "eliminar": "eliminar",
                "remover": "eliminar",
                "borrar": "eliminar",
                "quitar": "eliminar",
                "dejar igual": "dejar igual",
                "sin cambio": "dejar igual",
                "sin cambios": "dejar igual",
                "mantener": "dejar igual",
                "no cambiar": "dejar igual",
            }
            if normalized in mapping:
                return mapping[normalized]
        return value


class UnifiedInterventionPlan(BaseModel):
    """Plan completo de intervención con resumen y acciones."""
    resumen: str = Field(description="Resumen ejecutivo del plan de intervención")
    plan_intervencion: List[UnifiedInterventionAction] = Field(
        description="Listado ordenado de acciones por prueba"
    )


# --- Funciones auxiliares de carga y normalización ---

def _normalize_name(name: Optional[str]) -> Optional[str]:
    """Normaliza un nombre de prueba para comparación consistente."""
    if not name:
        return None

    normalized = name.strip().lower()

    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
        "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
        "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
        "ñ": "n",
    }
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)

    return " ".join(normalized.split())


def _safe_get_file_data(files: dict[str, Any], path: str) -> Optional[Any]:
    """
    Lee files[path]["data"] de forma segura.
    Fallback: si no existe "data" pero sí "content" (string JSON), intenta json.loads(content).
    """
    entry = files.get(path)
    if not isinstance(entry, dict):
        return None

    data = entry.get("data")
    if data is not None:
        return data

    content = entry.get("content")
    if isinstance(content, str) and content.strip():
        try:
            return json.loads(content)
        except Exception:
            logger.exception(f"No se pudo parsear content JSON en {path}")
            return None

    return None


def _collect_prueba_records_with_index(
    pruebas: Optional[list],
    source_id_key: str = "_source_id",
) -> list[dict[str, Any]]:
    """
    Convierte una lista de pruebas a formato unificado con índices.
    Output: [{"prueba": str, "source_id": Any, "indice": int}, ...]
    
    IMPORTANTE: Prioriza _source_id (identificador numérico del wrapper) sobre section_id
    para garantizar coincidencia con apply_method_patch.
    """
    if not pruebas:
        return []

    records: list[dict[str, Any]] = []

    for idx, prueba in enumerate(pruebas):
        nombre: Optional[str] = None
        source_id: Any = None

        # Caso 1: dict (lo más común en tus payloads)
        if isinstance(prueba, dict):
            # Priorizar test_name (formato TestSolution) sobre section_title
            nombre = (
                prueba.get("test_name")
                or prueba.get("section_title")
                or prueba.get("prueba")
                or prueba.get("nombre")
            )
            # CRÍTICO: Priorizar _source_id (id numérico del wrapper) para matching con apply_method_patch
            source_id = (
                prueba.get("_source_id")  # Primero: id numérico del wrapper (preservado de _extract_tests_from_legacy)
                or prueba.get(source_id_key)  # Segundo: clave especificada
                or prueba.get("source_id")  # Tercero: source_id directo
                or prueba.get("id_prueba")  # Cuarto: id_prueba legacy
            )

        # Caso 2: objeto (p.ej. Pydantic)
        else:
            if hasattr(prueba, "test_name") or hasattr(prueba, "section_title") or hasattr(prueba, "prueba"):
                nombre = getattr(prueba, "test_name", None) or getattr(prueba, "section_title", None) or getattr(prueba, "prueba", None)
                source_id = (
                    getattr(prueba, "_source_id", None)
                    or getattr(prueba, source_id_key, None)
                    or getattr(prueba, "source_id", None)
                    or getattr(prueba, "id_prueba", None)
                )

        if isinstance(nombre, str) and nombre.strip():
            record = {"prueba": nombre.strip(), "source_id": source_id, "indice": idx}
            # Preservar _source_file_name si existe (para pruebas de múltiples archivos)
            if isinstance(prueba, dict) and "_source_file_name" in prueba:
                record["_source_file_name"] = prueba["_source_file_name"]
            records.append(record)
        else:
            logger.warning(f"Prueba en índice {idx} no tiene nombre válido: {prueba}")

    logger.debug(f"Recolectadas {len(records)} pruebas con índices")
    return records

def _collect_cambios_from_structured(cc_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """
    Extrae únicamente:
      - cambios_pruebas_analiticas
      - pruebas_nuevas
    desde cc_payload (que corresponde a files[...]['data']).

    No aplica transformaciones adicionales.
    """
    if not isinstance(cc_payload, dict):
        return {"cambios_pruebas_analiticas": [], "pruebas_nuevas": []}

    cambios_pruebas = cc_payload.get("cambios_pruebas_analiticas", [])
    pruebas_nuevas = cc_payload.get("pruebas_nuevas", [])

    if not isinstance(cambios_pruebas, list):
        cambios_pruebas = []
    if not isinstance(pruebas_nuevas, list):
        pruebas_nuevas = []

    # Recomendado: filtrar solo dicts para reducir ruido
    cambios_pruebas = [x for x in cambios_pruebas if isinstance(x, dict)]
    pruebas_nuevas = [x for x in pruebas_nuevas if isinstance(x, dict)]

    return {
        "cambios_pruebas_analiticas": cambios_pruebas,
        "pruebas_nuevas": pruebas_nuevas,
    }


# --- Funciones de extracción de pruebas ---

def _extract_tests_from_legacy(legacy_payload) -> list:
    """Extrae lista de pruebas del método legado (aplanando wrappers tests/source_id)."""
    if not legacy_payload:
        return []

    if isinstance(legacy_payload, list):
        flattened: list[Any] = []
        for item in legacy_payload:
            if isinstance(item, dict):
                source_id = item.get("source_id")
                if "tests" in item and isinstance(item["tests"], list):
                    for test in item["tests"]:
                        if isinstance(test, dict):
                            test_copy = dict(test)
                            if source_id is not None:
                                test_copy["_source_id"] = source_id
                            flattened.append(test_copy)
                else:
                    flattened.append(item)

        if flattened:
            logger.debug(f"Extraídas {len(flattened)} pruebas del método legado (aplanadas con source_id)")
            return flattened

        logger.debug(f"Payload legado es lista directa con {len(legacy_payload)} elementos")
        return legacy_payload

    if isinstance(legacy_payload, dict):
        tests = legacy_payload.get("tests") or legacy_payload.get("pruebas") or []
        if isinstance(tests, list):
            return _extract_tests_from_legacy(tests)
        logger.debug("Payload legado dict con tests no-list; retornando tal cual")
        return tests

    logger.warning(f"Formato inesperado de legacy_payload: {type(legacy_payload)}")
    return []


def _extract_tests_from_proposed(proposed_payload) -> list:
    """Extrae lista de pruebas del método propuesto (aplanando wrappers tests/source_id)."""
    if not proposed_payload:
        return []

    if isinstance(proposed_payload, list):
        flattened: list[Any] = []
        for item in proposed_payload:
            if isinstance(item, dict):
                source_id = item.get("source_id")
                if "tests" in item and isinstance(item["tests"], list):
                    for test in item["tests"]:
                        if isinstance(test, dict):
                            test_copy = dict(test)
                            if source_id is not None:
                                test_copy["_source_id"] = source_id
                            flattened.append(test_copy)
                else:
                    flattened.append(item)

        if flattened:
            logger.debug(f"Extraídas {len(flattened)} pruebas del método propuesto (aplanadas)")
            return flattened

        logger.debug(f"Payload propuesto es lista directa con {len(proposed_payload)} elementos")
        return proposed_payload

    if isinstance(proposed_payload, dict):
        tests = proposed_payload.get("tests") or proposed_payload.get("pruebas") or []
        if isinstance(tests, list):
            return _extract_tests_from_proposed(tests)
        logger.debug("Payload propuesto dict con tests no-list; retornando tal cual")
        return tests

    logger.warning(f"Formato inesperado de proposed_payload: {type(proposed_payload)}")
    return []


# --- Funciones de validación ---

def _validate_context(llm_context: dict) -> tuple[bool, str]:
    """
    Valida estructura mínima del contexto.
    Nota: 'lista_cambios' ahora es un dict con:
      - cambios_pruebas_analiticas: list[dict]
      - pruebas_nuevas: list[dict]
    """
    required_keys = ["pruebas_metodo_legado", "lista_cambios", "pruebas_metodo_propuesto"]

    for key in required_keys:
        if key not in llm_context:
            return False, f"Falta clave requerida en contexto: '{key}'"

    if not isinstance(llm_context["pruebas_metodo_legado"], list):
        return False, "'pruebas_metodo_legado' debe ser una lista"

    lc = llm_context["lista_cambios"]
    if not isinstance(lc, dict):
        return False, "'lista_cambios' debe ser un dict con cambios_pruebas_analiticas y pruebas_nuevas"

    if not isinstance(lc.get("cambios_pruebas_analiticas", []), list):
        return False, "'lista_cambios.cambios_pruebas_analiticas' debe ser una lista"

    if not isinstance(lc.get("pruebas_nuevas", []), list):
        return False, "'lista_cambios.pruebas_nuevas' debe ser una lista"

    if not isinstance(llm_context["pruebas_metodo_propuesto"], list):
        return False, "'pruebas_metodo_propuesto' debe ser una lista"

    logger.info("Contexto validado exitosamente")
    return True, ""


def _validate_plan_completeness(
    plan: UnifiedInterventionPlan,
    expected_legacy_count: int,
    expected_new_count: int,
) -> tuple[bool, str]:
    """Verifica cobertura básica: legadas (por conteo) y nuevas (mínimo)."""
    legacy_actions = [a for a in plan.plan_intervencion if a.prueba_ma_legado is not None]
    new_actions = [a for a in plan.plan_intervencion if a.accion == "adicionar"]

    issues: list[str] = []

    if len(legacy_actions) != expected_legacy_count:
        issues.append(
            f"Cobertura incompleta de pruebas legadas: esperadas {expected_legacy_count}, encontradas {len(legacy_actions)}"
        )

    if len(new_actions) < expected_new_count:
        issues.append(
            f"Faltan pruebas nuevas: esperadas al menos {expected_new_count}, encontradas {len(new_actions)}"
        )

    for i, action in enumerate(plan.plan_intervencion, 1):
        if action.orden != i:
            issues.append(f"Orden incorrecto: acción en posición {i} tiene orden={action.orden}")

    if issues:
        for msg in issues:
            logger.warning(msg)
        return False, "; ".join(issues)

    logger.info(f"Plan completo: {len(legacy_actions)} acciones legadas, {len(new_actions)} nuevas")
    return True, "Plan validado correctamente"


# --- Función con retry para invocar LLM ---

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((json.JSONDecodeError, ValidationError)),
    reraise=True,
)
def _invoke_llm_with_retry(
    llm_structured,
    human_prompt: str,
    system_prompt: str,
) -> UnifiedInterventionPlan:
    """Invoca el LLM con retry automático en caso de errores de parseo/validación."""
    logger.debug("Invocando LLM para generar plan de intervención...")
    response = llm_structured.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )
    logger.debug("LLM respondió exitosamente")
    return response


# --- Tool principal ---

# --- Constantes de rutas ---
ACTUAL_METHOD_DIR = "/actual_method"
PROPOSED_METHOD_DIR = "/proposed_method"
ANALYTICAL_TESTS_DIR = "/analytical_tests"
CHANGE_CONTROL_DEFAULT_PATH = "/change_control/change_control_summary.json"
CHANGE_IMPLEMENTATION_PLAN_PATH = "/new/change_implementation_plan.json"

# Patrón para identificar archivos de contenido estructurado
import re
STRUCTURED_CONTENT_PATTERN = re.compile(r"test_solution_structured_content_(.+)\.json$")


def _find_structured_content_files(files: Dict[str, Any], base_dir: str) -> List[str]:
    """Encuentra todos los archivos test_solution_structured_content_*.json en un directorio."""
    found = []
    prefix = base_dir.rstrip("/") + "/"
    for path in files.keys():
        if isinstance(path, str) and path.startswith(prefix):
            if STRUCTURED_CONTENT_PATTERN.search(path):
                found.append(path)
    return sorted(found)


def _load_all_tests_from_directory(files: Dict[str, Any], base_dir: str) -> List[Dict[str, Any]]:
    """
    Carga y combina todas las pruebas de todos los archivos estructurados en un directorio.
    Preserva source_file_name para trazabilidad.
    """
    all_tests = []
    structured_files = _find_structured_content_files(files, base_dir)
    
    for file_path in structured_files:
        payload = _safe_get_file_data(files, file_path)
        if payload is None:
            continue
        
        # Extraer source_file_name de la ruta
        match = STRUCTURED_CONTENT_PATTERN.search(file_path)
        source_file_name = match.group(1) if match else "unknown"
        
        # Extraer pruebas
        if base_dir == ACTUAL_METHOD_DIR:
            tests = _extract_tests_from_legacy(payload)
        else:
            tests = _extract_tests_from_proposed(payload)
        
        # Agregar source_file_name a cada prueba
        for test in tests:
            if isinstance(test, dict):
                test["_source_file_name"] = source_file_name
        
        all_tests.extend(tests)
        logger.info(f"  Cargadas {len(tests)} pruebas de {file_path}")
    
    return all_tests


def _load_analytical_tests_registry(files: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Carga todos los registros de /analytical_tests/ y los organiza por source_type.
    
    Retorna: {
        "actual_method": [{source_file, tests: [...]}],
        "proposed_method": [{source_file, tests: [...]}]
    }
    """
    registry = {
        "actual_method": [],
        "proposed_method": [],
    }
    
    prefix = ANALYTICAL_TESTS_DIR.rstrip("/") + "/"
    
    for path, entry in files.items():
        if not isinstance(path, str) or not path.startswith(prefix):
            continue
        
        payload = _safe_get_file_data(files, path)
        if not isinstance(payload, dict):
            continue
        
        source_type = payload.get("source_type", "unknown")
        if source_type in registry:
            registry[source_type].append(payload)
            logger.debug(f"Cargado registro de pruebas: {path} ({source_type})")
    
    return registry



@tool(description=CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION)
def analyze_change_impact(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Analiza el impacto de cambios y genera un plan de intervención detallado.
    """
    logger.info("=" * 80)
    logger.info("Iniciando 'analyze_change_impact'")
    logger.info("=" * 80)

    files = state.get("files", {}) or {}
    logger.info(f"Archivos disponibles: {len(files)}")

    # --- Paso 1: Cargar payloads desde múltiples archivos ---
    logger.info("Cargando archivos necesarios...")

    # Cargar control de cambios
    cc_payload = _safe_get_file_data(files, CHANGE_CONTROL_DEFAULT_PATH)
    if not isinstance(cc_payload, dict):
        # Intentar ruta legacy
        cc_payload = _safe_get_file_data(files, "/new/change_control_summary.json")
    
    if not isinstance(cc_payload, dict):
        msg = f"ERROR: No se encontró (o es inválido) el control de cambios en {CHANGE_CONTROL_DEFAULT_PATH}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    logger.info("✓ Control de cambios cargado")

    # Cargar pruebas del método legado (puede haber múltiples archivos)
    legacy_files = _find_structured_content_files(files, ACTUAL_METHOD_DIR)
    if not legacy_files:
        msg = f"ERROR: No se encontraron archivos de método legado en {ACTUAL_METHOD_DIR}/"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    
    legacy_tests_raw = _load_all_tests_from_directory(files, ACTUAL_METHOD_DIR)
    logger.info(f"✓ Método legado cargado: {len(legacy_files)} archivo(s), {len(legacy_tests_raw)} pruebas")

    # Cargar pruebas del método propuesto (puede haber múltiples archivos)
    proposed_files = _find_structured_content_files(files, PROPOSED_METHOD_DIR)
    if not proposed_files:
        msg = f"ERROR: No se encontraron archivos de método propuesto en {PROPOSED_METHOD_DIR}/"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    
    proposed_tests_raw = _load_all_tests_from_directory(files, PROPOSED_METHOD_DIR)
    logger.info(f"✓ Método propuesto cargado: {len(proposed_files)} archivo(s), {len(proposed_tests_raw)} pruebas")
    
    # Cargar registro de pruebas analíticas (opcional, para referencia cruzada)
    analytical_registry = _load_analytical_tests_registry(files)
    logger.info(f"✓ Registro de pruebas analíticas: {len(analytical_registry['actual_method'])} actual, {len(analytical_registry['proposed_method'])} propuesto")

    # --- Paso 2: Validación mínima de cambios ---
    logger.info("Extrayendo secciones de cambios del resumen...")

    cambios_struct = _collect_cambios_from_structured(cc_payload)
    cambios_count = len(cambios_struct["cambios_pruebas_analiticas"])
    nuevas_count = len(cambios_struct["pruebas_nuevas"])

    # Legacy opcional (solo para compatibilidad; no lo usamos si hay estructurado)
    raw_lista_cambios = cc_payload.get("lista_cambios", [])
    has_legacy_lista = isinstance(raw_lista_cambios, list) and len(raw_lista_cambios) > 0

    use_structured_format = (cambios_count + nuevas_count) > 0

    if not use_structured_format and not has_legacy_lista:
        msg = (
            "ERROR: No se encontraron cambios en el control de cambios "
            "(ni 'cambios_pruebas_analiticas'/'pruebas_nuevas' ni 'lista_cambios')."
        )
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    total_cambios = (cambios_count + nuevas_count) if use_structured_format else len(raw_lista_cambios)
    logger.info(f"✓ Control de cambios cargado con {total_cambios} cambios (formato {'estructurado' if use_structured_format else 'legacy'})")
    
    # --- Paso 3: Extraer y normalizar datos ---
    logger.info("Extrayendo y normalizando datos...")

    # Las pruebas ya fueron cargadas en el paso 1
    pruebas_metodo_legado = _collect_prueba_records_with_index(
        legacy_tests_raw,
        source_id_key="_source_id",
    )
    logger.info(f"  → Pruebas método legado: {len(pruebas_metodo_legado)}")

    # IMPORTANTE: aquí 'lista_cambios' ES EL DICT con cambios_pruebas_analiticas/pruebas_nuevas (sin transformaciones)
    lista_cambios = cambios_struct
    logger.info(f"  → Cambios identificados: {cambios_count} cambios en pruebas + {nuevas_count} pruebas nuevas")

    pruebas_metodo_propuesto = _collect_prueba_records_with_index(
        proposed_tests_raw,
        source_id_key="_source_id",
    )
    logger.info(f"  → Pruebas método propuesto: {len(pruebas_metodo_propuesto)}")
    
    # --- Paso 4: Construir contexto unificado ---
    llm_context = {
        "pruebas_metodo_legado": pruebas_metodo_legado,
        "lista_cambios": lista_cambios,  # dict con 2 llaves
        "pruebas_metodo_propuesto": pruebas_metodo_propuesto,
    }

    is_valid, error_msg = _validate_context(llm_context)
    if not is_valid:
        msg = f"ERROR: Contexto inválido para LLM: {error_msg}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    context_json = json.dumps(llm_context, ensure_ascii=False, indent=2)
    logger.debug(f"Contexto unificado (primeros 500 chars): {context_json[:500]}...")

    # --- Paso 5: Invocar LLM ---
    logger.info("Invocando LLM para generar plan de intervención...")

    try:
        llm_structured = change_control_analysis_model.with_structured_output(UnifiedInterventionPlan)
        response = _invoke_llm_with_retry(
            llm_structured=llm_structured,
            human_prompt=UNIFIED_CHANGE_HUMAN_ANALYSIS_PROMPT.format(context=context_json),
            system_prompt=UNIFIED_CHANGE_SYSTEM_ANALYSIS_PROMPT,
        )
        logger.info("✓ Plan de intervención generado exitosamente")
    except Exception as exc:
        msg = f"ERROR: Fallo al invocar LLM después de reintentos: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # --- Paso 6: Validar completitud del plan ---
    logger.info("Validando completitud del plan...")

    legacy_test_names = {
        _normalize_name(p.get("prueba"))
        for p in pruebas_metodo_legado
        if isinstance(p, dict) and p.get("prueba")
    }

    # Con formato estructurado: esperadas nuevas = tamaño de pruebas_nuevas (opcional: excluir duplicadas vs legado)
    expected_new = sum(
        1
        for n in lista_cambios.get("pruebas_nuevas", [])
        if isinstance(n, dict)
        and _normalize_name(n.get("prueba")) is not None
        and _normalize_name(n.get("prueba")) not in legacy_test_names
    )

    is_complete, validation_msg = _validate_plan_completeness(
        response,
        expected_legacy_count=len(pruebas_metodo_legado),
        expected_new_count=expected_new,
    )

    if not is_complete:
        logger.warning(f"ADVERTENCIA: {validation_msg}")
    else:
        logger.info(f"✓ {validation_msg}")
    
    # --- Paso 7: Guardar resultado ---
    plan_payload = response.model_dump()

    files_update = dict(files)
    files_update[CHANGE_IMPLEMENTATION_PLAN_PATH] = {
        "content": json.dumps(plan_payload, ensure_ascii=False, indent=2),
        "data": plan_payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"✓ Plan guardado en {CHANGE_IMPLEMENTATION_PLAN_PATH}")

    # --- Paso 8: Mensaje resumen ---
    summary = response.resumen
    total_actions = len(response.plan_intervencion)

    acciones_count = {"editar": 0, "adicionar": 0, "eliminar": 0, "dejar igual": 0}
    for action in response.plan_intervencion:
        if action.accion in acciones_count:
            acciones_count[action.accion] += 1

    details = (
        f"Plan generado con {total_actions} acciones: "
        f"{acciones_count['editar']} a editar, "
        f"{acciones_count['adicionar']} a adicionar, "
        f"{acciones_count['eliminar']} a eliminar, "
        f"{acciones_count['dejar igual']} sin cambios."
    )

    tool_message = f"{summary}\n\n{details}".strip()
    if not is_complete:
        tool_message += f"\n\nADVERTENCIA: {validation_msg}"

    logger.info("=" * 80)
    logger.info("'analyze_change_impact' completado")
    logger.info("=" * 80)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )
