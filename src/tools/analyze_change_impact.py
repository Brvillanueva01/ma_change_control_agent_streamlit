"""
Tool mejorado para análisis de control de cambios con validaciones robustas,
retry logic y logging detallado.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, Literal, List

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION
from src.prompts.tool_llm_calls_prompts import UNIFIED_CHANGE_HUMAN_ANALYSIS_PROMPT, UNIFIED_CHANGE_SYSTEM_ANALYSIS_PROMPT

# --- Configuración ---
logger = logging.getLogger(__name__)

## LLMs
change_control_analysis_model = init_chat_model(model="openai:gpt-5-mini")

CHANGE_IMPLEMENTATION_PLAN_PATH = "/new/change_implementation_plan.json"
PROPOSED_METHOD_DEFAULT_PATH = "/proposed_method/test_solution_structured_content.json"


# --- Modelos Pydantic ---
class CambioListaCambios(BaseModel):
    """Referencia a un cambio en la lista de cambios del control de cambios."""
    indice: int = Field(description="Índice del cambio en la lista de cambios (0-indexed)")
    texto: str = Field(description="Texto completo del cambio de /new/change_control_summary.json")


class ElementoSideBySide(BaseModel):
    """Referencia a una prueba en la comparación lado a lado."""
    prueba: str = Field(description="Nombre de la prueba en metodo_modificacion_propuesta")
    indice: int = Field(description="Índice de la prueba en /new/side_by_side.json")


class ElementoMetodoReferencia(BaseModel):
    """Referencia a una prueba en los métodos de referencia."""
    prueba: str = Field(description="Nombre de la prueba en métodos de referencia")
    indice: int = Field(description="Índice de la prueba en /new/reference_methods.json")


class UnifiedInterventionAction(BaseModel):
    """Una acción individual en el plan de intervención."""
    orden: int = Field(description="Número de orden en el plan de intervención")
    cambio: str = Field(description="Descripción concisa del cambio a implementar")
    prueba_ma_legado: Optional[str] = Field(
        default=None,
        description="Nombre de la prueba del método legado o null si es nueva",
    )
    source_id_ma_legado: Optional[str] = Field(
        default=None,
        description="section_id de la prueba en /actual_method/test_solution_structured_content.json o null",
    )
    accion: Literal["editar", "adicionar", "eliminar", "dejar igual"] = Field(
        description="Acción requerida: editar, adicionar, eliminar o dejar igual"
    )
    cambio_lista_cambios: Optional[CambioListaCambios] = Field(
        default=None,
        description="Elemento de lista_cambios con índice y texto. null si no hay cambio (dejar igual)",
    )
    elemento_side_by_side: Optional[ElementoSideBySide] = Field(
        default=None,
        description="Prueba e índice en /new/side_by_side.json. null si no aplica",
    )
    elemento_metodo_referencia: Optional[ElementoMetodoReferencia] = Field(
        default=None,
        description="Prueba e índice en /new/reference_methods.json. null si no aplica",
    )

    @field_validator("accion", mode="before")
    @classmethod
    def _normalize_accion(cls, value: Any) -> str:
        """Normaliza las variaciones de nombres de acciones al formato estándar."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            # Reemplazar ñ por n
            normalized = normalized.replace("\u00f1", "n")
            
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

def _load_json_payload(files: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    """
    Extrae un payload JSON normalizado desde el filesystem virtual.
    
    Args:
        files: Diccionario de archivos del estado
        path: Ruta del archivo a cargar
        
    Returns:
        Diccionario con los datos JSON o None si no se encuentra/parsea
    """
    entry = files.get(path)
    if entry is None:
        logger.warning(f"No se encontró archivo en la ruta: {path}")
        return None

    # Caso 1: Entry es un diccionario con estructura anidada
    if isinstance(entry, dict):
        if "data" in entry and isinstance(entry["data"], dict):
            return entry["data"]
        if "content" in entry and isinstance(entry["content"], str):
            try:
                return json.loads(entry["content"])
            except json.JSONDecodeError as e:
                logger.error(f"Error al parsear JSON desde 'content' en {path}: {e}")
                return None
        # Si no tiene 'data' ni 'content', asumimos que es el payload directo
        return entry

    # Caso 2: Entry es una cadena JSON
    if isinstance(entry, str):
        try:
            return json.loads(entry)
        except json.JSONDecodeError as e:
            logger.error(f"Error al parsear JSON string en {path}: {e}")
            return None

    logger.warning(f"Formato no reconocido para archivo en {path}: {type(entry)}")
    return None


def _normalize_name(name: Optional[str]) -> Optional[str]:
    """
    Normaliza un nombre de prueba para comparación consistente.
    
    Aplicaciones:
    - Convierte a minúsculas
    - Elimina acentos
    - Normaliza espacios en blanco
    
    Args:
        name: Nombre a normalizar
        
    Returns:
        Nombre normalizado o None si el input es None/vacío
    """
    if not name:
        return None
    
    normalized = name.strip().lower()
    
    # Reemplazos de acentos
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
        "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
        "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
        "ñ": "n",
    }
    
    for src, dst in replacements.items():
        normalized = normalized.replace(src, dst)
    
    # Normalizar espacios (múltiples espacios → un espacio)
    return " ".join(normalized.split())


def _collect_prueba_records_with_index(
    pruebas: Optional[list], 
    source_id_key: str = "id_prueba"
) -> list[dict[str, Any]]:
    """
    Convierte una lista de pruebas a formato unificado con índices.
    
    Args:
        pruebas: Lista de objetos de prueba (pueden ser Pydantic models o dicts)
        source_id_key: Nombre del campo que contiene el ID (puede variar)
        
    Returns:
        Lista de diccionarios con formato: {"prueba": str, "source_id": str, "indice": int}
    """
    if not pruebas:
        return []
    
    records: list[dict[str, Any]] = []
    
    for idx, prueba in enumerate(pruebas):
        nombre: Optional[str] = None
        source_id: Optional[str] = None

        # Caso 1: Objeto Pydantic con atributos
        if hasattr(prueba, "prueba"):
            nombre = getattr(prueba, "prueba", None)
            # Intentar obtener source_id de varios campos posibles
            source_id = (
                getattr(prueba, source_id_key, None) or 
                getattr(prueba, "section_id", None) or
                getattr(prueba, "id", None)
            )
        
        # Caso 2: Diccionario
        elif isinstance(prueba, dict):
            nombre = prueba.get("prueba") or prueba.get("test_name") or prueba.get("nombre")
            source_id = (
                prueba.get(source_id_key) or 
                prueba.get("section_id") or 
                prueba.get("id") or
                prueba.get("id_prueba")
            )

        # Solo agregar si al menos tenemos un nombre
        if isinstance(nombre, str) and nombre.strip():
            record: dict[str, Any] = {
                "prueba": nombre.strip(),
                "source_id": source_id,
                "indice": idx,
            }
            records.append(record)
        else:
            logger.warning(f"Prueba en índice {idx} no tiene nombre válido: {prueba}")

    logger.debug(f"Recolectadas {len(records)} pruebas con índices")
    return records


def _collect_cambios_with_index(cambios: Optional[list]) -> list[dict[str, Any]]:
    """
    Convierte una lista de cambios a formato unificado con índices.
    
    Args:
        cambios: Lista de objetos de cambio (pueden ser Pydantic models o dicts)
        
    Returns:
        Lista de diccionarios con formato: {"indice": int, "prueba": str, "texto": str}
    """
    if not cambios:
        return []
    
    records: list[dict[str, Any]] = []
    
    for idx, cambio in enumerate(cambios):
        prueba: Optional[str] = None
        texto: Optional[str] = None

        # Caso 1: Objeto Pydantic
        if hasattr(cambio, "prueba"):
            prueba = getattr(cambio, "prueba", None)
            texto = getattr(cambio, "texto", None) or getattr(cambio, "descripcion", None)
        
        # Caso 2: Diccionario
        elif isinstance(cambio, dict):
            prueba = cambio.get("prueba")
            texto = cambio.get("texto") or cambio.get("descripcion") or cambio.get("cambio")

        record = {
            "indice": idx,
            "prueba": prueba.strip() if isinstance(prueba, str) else None,
            "texto": texto.strip() if isinstance(texto, str) else None,
        }
        records.append(record)

    logger.debug(f"Recolectados {len(records)} cambios con índices")
    return records


def _collect_cambios_from_strings(cambios_strings: list[str]) -> list[dict[str, Any]]:
    """
    Convierte una lista de strings de cambios a formato unificado con índices.
    
    El archivo change_control_summary.json contiene lista_cambios como List[str],
    donde cada string describe un cambio completo.
    
    Args:
        cambios_strings: Lista de strings describiendo cada cambio
        
    Returns:
        Lista de diccionarios con formato: {"indice": int, "prueba": str|None, "texto": str}
    """
    if not cambios_strings:
        return []
    
    records: list[dict[str, Any]] = []
    
    for idx, cambio_text in enumerate(cambios_strings):
        if not isinstance(cambio_text, str):
            cambio_text = str(cambio_text) if cambio_text else ""
        
        # Intentar extraer nombre de prueba del texto
        # Patrones comunes: "Prueba X: descripción" o "X - descripción"
        prueba: Optional[str] = None
        texto = cambio_text.strip()
        
        # Buscar patrones como "Prueba:" o nombre seguido de ":"
        if ":" in texto:
            parts = texto.split(":", 1)
            potential_prueba = parts[0].strip()
            # Si la primera parte es corta, probablemente es el nombre de la prueba
            if len(potential_prueba) < 100:
                prueba = potential_prueba
        
        record = {
            "indice": idx,
            "prueba": prueba,
            "texto": texto,
        }
        records.append(record)
    
    logger.debug(f"Recolectados {len(records)} cambios desde strings")
    return records


# --- Constantes de rutas ---
LEGACY_METHOD_DEFAULT_PATH = "/actual_method/test_solution_structured_content.json"
CHANGE_CONTROL_DEFAULT_PATH = "/new/change_control_summary.json"
SIDE_BY_SIDE_DEFAULT_PATH = "/new/side_by_side.json"
REFERENCE_METHOD_DEFAULT_PATH = "/new/reference_methods.json"


# --- Funciones de extracción de pruebas ---

def _extract_tests_from_legacy(legacy_payload) -> list:
    """
    Extrae lista de pruebas del método legado.
    
    La estructura real del legado puede ser:
    1. Lista de wrappers: [{"tests": [...], "source_id": N}, ...]
    2. Dict con "tests" o "pruebas": {"tests": [...]} o {"pruebas": [...]}
    3. Lista directa de pruebas
    
    Args:
        legacy_payload: Payload del archivo test_solution_structured_content.json
        
    Returns:
        Lista de pruebas aplanada (pueden ser dicts o objetos)
    """
    if not legacy_payload:
        return []
    
    # Si es lista, puede ser lista de wrappers o lista directa de pruebas
    if isinstance(legacy_payload, list):
        flattened = []
        for item in legacy_payload:
            if isinstance(item, dict):
                # Verificar si es un wrapper con "tests" anidado
                if "tests" in item and isinstance(item["tests"], list):
                    flattened.extend(item["tests"])
                else:
                    # Es una prueba directa
                    flattened.append(item)
        
        if flattened:
            logger.debug(f"Extraídas {len(flattened)} pruebas del método legado (aplanadas)")
            return flattened
        
        logger.debug(f"Payload legado es lista directa con {len(legacy_payload)} elementos")
        return legacy_payload
    
    # Si es dict, buscar "tests" o "pruebas"
    if isinstance(legacy_payload, dict):
        tests = legacy_payload.get("tests") or legacy_payload.get("pruebas") or []
        # Recursivamente aplanar si es necesario
        if isinstance(tests, list):
            return _extract_tests_from_legacy(tests)
        logger.debug(f"Extraídas {len(tests)} pruebas del método legado")
        return tests
    
    logger.warning(f"Formato inesperado de legacy_payload: {type(legacy_payload)}")
    return []


def _extract_tests_from_sbs(sbs_payload: Optional[dict], key: str) -> list:
    """
    Extrae lista de pruebas de la comparación lado a lado.
    
    Args:
        sbs_payload: Payload del archivo side_by_side.json
        key: Clave a extraer ("metodo_modificacion_propuesta")
        
    Returns:
        Lista de pruebas
    """
    if not sbs_payload or not isinstance(sbs_payload, dict):
        return []
    
    items = sbs_payload.get(key) or []
    
    # Cada item puede tener estructura anidada {"tests": [...]}
    result = []
    for item in items:
        if isinstance(item, dict) and "tests" in item:
            result.extend(item.get("tests") or [])
        else:
            result.append(item)
    
    logger.debug(f"Extraídas {len(result)} pruebas de side_by_side['{key}']")
    return result


def _extract_tests_from_ref(ref_payload: Optional[dict]) -> list:
    """
    Extrae lista de pruebas de métodos de referencia.
    
    Args:
        ref_payload: Payload del archivo reference_methods.json
        
    Returns:
        Lista de pruebas
    """
    if not ref_payload:
        return []
    
    if isinstance(ref_payload, dict):
        tests = ref_payload.get("tests") or ref_payload.get("pruebas") or []
        logger.debug(f"Extraídas {len(tests)} pruebas de métodos de referencia")
        return tests
    
    if isinstance(ref_payload, list):
        logger.debug(f"Payload de referencia es lista directa con {len(ref_payload)} elementos")
        return ref_payload
    
    logger.warning(f"Formato inesperado de ref_payload: {type(ref_payload)}")
    return []


# --- Funciones de validación ---

def _validate_context(llm_context: dict) -> tuple[bool, str]:
    """
    Valida que el contexto tenga la estructura mínima requerida.
    
    Args:
        llm_context: Contexto que se enviará al LLM
        
    Returns:
        Tupla (es_válido, mensaje_error)
    """
    required_keys = ["pruebas_metodo_legado", "lista_cambios", "side_by_side", "metodos_referencia"]
    
    for key in required_keys:
        if key not in llm_context:
            return False, f"Falta clave requerida en contexto: '{key}'"
    
    # Validar tipos
    if not isinstance(llm_context["pruebas_metodo_legado"], list):
        return False, "'pruebas_metodo_legado' debe ser una lista"
    
    if not isinstance(llm_context["lista_cambios"], list):
        return False, "'lista_cambios' debe ser una lista"
    
    if not isinstance(llm_context["side_by_side"], dict):
        return False, "'side_by_side' debe ser un diccionario"
    
    if not isinstance(llm_context["metodos_referencia"], list):
        return False, "'metodos_referencia' debe ser una lista"
    
    # Validar que side_by_side tenga las claves esperadas
    sbs = llm_context["side_by_side"]
    if "metodo_modificacion_propuesta" not in sbs:
        return False, "'side_by_side' debe contener 'metodo_modificacion_propuesta'"
    
    logger.info("Contexto validado exitosamente")
    return True, ""


def _validate_plan_completeness(
    plan: UnifiedInterventionPlan, 
    expected_legacy_count: int,
    expected_new_count: int
) -> tuple[bool, str]:
    """
    Verifica que el plan cubra todas las pruebas esperadas.
    
    Args:
        plan: Plan de intervención generado por el LLM
        expected_legacy_count: Número esperado de pruebas legadas
        expected_new_count: Número esperado de pruebas nuevas
        
    Returns:
        Tupla (es_completo, mensaje)
    """
    # Contar acciones por tipo
    legacy_actions = [
        a for a in plan.plan_intervencion 
        if a.prueba_ma_legado is not None
    ]
    new_actions = [
        a for a in plan.plan_intervencion 
        if a.accion == "adicionar"
    ]
    
    issues = []
    
    # Validar cobertura de pruebas legadas
    if len(legacy_actions) != expected_legacy_count:
        msg = (
            f"Cobertura incompleta de pruebas legadas: "
            f"esperadas {expected_legacy_count}, encontradas {len(legacy_actions)}"
        )
        issues.append(msg)
        logger.warning(msg)
    
    # Validar pruebas nuevas
    if len(new_actions) < expected_new_count:
        msg = (
            f"Faltan pruebas nuevas: "
            f"esperadas al menos {expected_new_count}, encontradas {len(new_actions)}"
        )
        issues.append(msg)
        logger.warning(msg)
    
    # Validar orden
    for i, action in enumerate(plan.plan_intervencion, 1):
        if action.orden != i:
            msg = f"Orden incorrecto: acción en posición {i} tiene orden={action.orden}"
            issues.append(msg)
            logger.warning(msg)
    
    if issues:
        return False, "; ".join(issues)
    
    logger.info(f"Plan completo: {len(legacy_actions)} acciones legadas, {len(new_actions)} nuevas")
    return True, "Plan validado correctamente"


# --- Función con retry para invocar LLM ---

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((json.JSONDecodeError, ValidationError)),
    reraise=True
)
def _invoke_llm_with_retry(llm_structured, human_prompt: str, system_prompt: str) -> UnifiedInterventionPlan:
    """
    Invoca el LLM con retry automático en caso de errores de parseo.
    
    Args:
        llm_structured: Modelo LLM configurado con structured output
        prompt: Prompt completo a enviar
        
    Returns:
        Plan de intervención validado
        
    Raises:
        ValidationError: Si el LLM no devuelve datos válidos después de 3 intentos
        json.JSONDecodeError: Si hay error de parseo JSON persistente
    """
    logger.debug("Invocando LLM para generar plan de intervención...")
    response = llm_structured.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
    logger.debug("LLM respondió exitosamente")
    return response


# --- Tool principal ---

@tool(description=CHANGE_CONTROL_ANALYSIS_TOOL_DESCRIPTION)
def analyze_change_impact(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    proposed_method_path: str = PROPOSED_METHOD_DEFAULT_PATH,
    side_by_side_path: str = SIDE_BY_SIDE_DEFAULT_PATH,
    legacy_method_path: str = LEGACY_METHOD_DEFAULT_PATH,
    reference_methods_path: str = REFERENCE_METHOD_DEFAULT_PATH,
    change_control_path: str = CHANGE_CONTROL_DEFAULT_PATH,
) -> Command:
    """
    Analiza el impacto de cambios y genera un plan de intervención detallado.
    
    Este tool:
    1. Carga y valida todos los archivos necesarios (rutas por defecto)
    2. Extrae y normaliza las pruebas de cada fuente
    3. Invoca un LLM para generar el plan de intervención
    4. Valida la completitud del plan
    5. Guarda el resultado en el filesystem virtual
    
    Args:
        state: Estado del grafo con el filesystem virtual
        tool_call_id: ID de la llamada al tool
        
    Returns:
        Command con el estado actualizado y mensaje de resultado
    """
    logger.info("=" * 80)
    logger.info("Iniciando 'analyze_change_impact'")
    logger.info("=" * 80)
    
    files = state.get("files", {}) or {}
    logger.info(f"Archivos disponibles: {len(files)}")
    
    # --- Paso 1: Cargar payloads ---
    logger.info("Cargando archivos necesarios...")
    
    cc_payload = _load_json_payload(files, change_control_path)
    raw_sbs_payload = _load_json_payload(files, side_by_side_path)
    proposed_payload = _load_json_payload(files, proposed_method_path)
    ref_payload = _load_json_payload(files, reference_methods_path)
    legacy_payload = _load_json_payload(files, legacy_method_path)

    # Preferir el método propuesto estructurado si existe; si no, usar side-by-side tradicional
    if proposed_payload:
        sbs_payload = {"metodo_modificacion_propuesta": proposed_payload}
        logger.info("Usando metodo propuesto de /proposed_method/ para side-by-side.")
    else:
        sbs_payload = raw_sbs_payload
    
    # Validar archivo crítico
    if cc_payload is None:
        msg = f"ERROR: No se encontró el archivo de control de cambios en {change_control_path}."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    
    logger.info("✓ Control de cambios cargado")
    if sbs_payload: logger.info("✓ Side-by-side cargado")
    if ref_payload: logger.info("✓ Métodos de referencia cargados")
    if legacy_payload: logger.info("✓ Método legado cargado")
    
    # --- Paso 2: Extraer lista de cambios del resumen ---
    logger.info("Extrayendo lista de cambios del resumen...")
    
    # El archivo change_control_summary.json tiene estructura:
    # {"filename": str, "summary": str, "lista_cambios": List[str]}
    raw_lista_cambios = cc_payload.get("lista_cambios", [])
    
    if not raw_lista_cambios:
        msg = "ERROR: No se encontró 'lista_cambios' en el archivo de control de cambios o está vacía."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    
    logger.info(f"✓ Control de cambios cargado con {len(raw_lista_cambios)} cambios")
    
    # --- Paso 3: Extraer y normalizar datos ---
    logger.info("Extrayendo y normalizando datos...")
    
    # Método legado
    legacy_tests_raw = _extract_tests_from_legacy(legacy_payload)
    pruebas_metodo_legado = _collect_prueba_records_with_index(
        legacy_tests_raw, 
        source_id_key="section_id"
    )
    logger.info(f"  → Pruebas método legado: {len(pruebas_metodo_legado)}")
    
    # Lista de cambios - convertir strings a formato estructurado
    lista_cambios = _collect_cambios_from_strings(raw_lista_cambios)
    logger.info(f"  → Cambios identificados: {len(lista_cambios)}")
    
    # Side-by-side (solo metodo_modificacion_propuesta)
    sbs_propuesta_raw = _extract_tests_from_sbs(sbs_payload, "metodo_modificacion_propuesta")
    side_by_side_context = {
        "metodo_modificacion_propuesta": _collect_prueba_records_with_index(sbs_propuesta_raw),
    }
    logger.info(f"  → Side-by-side propuesta: {len(side_by_side_context['metodo_modificacion_propuesta'])}")
    
    # Métodos de referencia
    ref_tests_raw = _extract_tests_from_ref(ref_payload)
    metodos_referencia = _collect_prueba_records_with_index(ref_tests_raw)
    logger.info(f"  → Métodos de referencia: {len(metodos_referencia)}")
    
    # --- Paso 4: Construir contexto unificado ---
    llm_context = {
        "pruebas_metodo_legado": pruebas_metodo_legado,
        "lista_cambios": lista_cambios,
        "side_by_side": side_by_side_context,
        "metodos_referencia": metodos_referencia,
    }
    
    # Validar contexto
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
            llm_structured = llm_structured,
            human_prompt = UNIFIED_CHANGE_HUMAN_ANALYSIS_PROMPT.format(context=context_json),
            system_prompt = UNIFIED_CHANGE_SYSTEM_ANALYSIS_PROMPT
        )
        logger.info("✓ Plan de intervención generado exitosamente")
    except Exception as exc:
        msg = f"ERROR: Fallo al invocar LLM después de reintentos: {exc}"
        logger.exception(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})
    
    # --- Paso 6: Validar completitud del plan ---
    logger.info("Validando completitud del plan...")
    
    # Contar pruebas nuevas esperadas (las que no están en legado)
    legacy_test_names = {_normalize_name(p["prueba"]) for p in pruebas_metodo_legado}
    expected_new = sum(
        1 for c in lista_cambios 
        if c["prueba"] and _normalize_name(c["prueba"]) not in legacy_test_names
    )
    
    is_complete, validation_msg = _validate_plan_completeness(
        response,
        expected_legacy_count=len(pruebas_metodo_legado),
        expected_new_count=expected_new
    )
    
    if not is_complete:
        logger.warning(f"ADVERTENCIA: {validation_msg}")
        # Continuamos pero registramos la advertencia
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
    
    # --- Paso 8: Generar mensaje de resumen ---
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
        tool_message += f"\n\n⚠️ ADVERTENCIA: {validation_msg}"
    
    logger.info("=" * 80)
    logger.info("'analyze_change_impact' completado exitosamente")
    logger.info("=" * 80)
    
    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )
