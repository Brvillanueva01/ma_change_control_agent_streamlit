import logging
import json
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional, Annotated, Dict, Union, Any

from langchain_core.tools import tool
from langgraph.types import Command
from langchain_core.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState

# --- Asunciones de importación (asegúrate de que estas rutas sean correctas) ---
# 1. El modelo de estado
from src.graph.state import DeepAgentState 
# 2. Los modelos Pydantic *LEGADOS* (necesarios para el modelo base)
from src.models.extraction_models import (
    ExtractionModel, 
    AlcanceMetodo, 
    Equipo, 
    Anexo, 
    Autorizacion, 
    DocumentoSoporte, 
    HistoricoCambio
)

# --- Configuración del Logger ---
logger = logging.getLogger(__name__)


# --- Modelos Pydantic para el NUEVO formato de prueba ---
# (Estos modelos definen la estructura de los archivos de prueba que esta
# herramienta va a leer y consolidar)

class Subespecificacion(BaseModel):
    nombre_subespecificacion: str = Field(..., description="Nombre de la subespecificación")
    criterio_aceptacion_subespecificacion: str = Field(..., description="Criterio de aceptación de la subespecificación")

class Especificacion(BaseModel):
    prueba: str = Field(..., description="Prueba del método analítico a la que se refiere la especificación.")
    texto_especificacion: str = Field(..., description="Texto de la especificacion incluyendo criterio de aceptación")
    subespecificacion: Optional[List[Subespecificacion]] = Field(..., description="Subespecificaciones del método analítico")

class Solucion(BaseModel):
    nombre_solucion: str = Field(..., description="Nombre de la solución")
    preparacion_solucion: str = Field(..., description="Texto descriptivo de la preparación de la solución")

class CondicionCromatografica(BaseModel):
    nombre: str = Field(..., description="Nombre de la condición cromatográfica")
    descripcion: str = Field(..., description="Descripción de la condición cromatográfica")

class Prueba(BaseModel):
    id_prueba: Optional[str] = Field(
        default=None,
        description="Identificador único (UUID o hash) de la prueba dentro del método.",
    )
    prueba: str = Field(..., description="Prueba del método analítico a la que se refiere el procedimiento.")
    procedimientos: str = Field(..., description="Descripción detallada de los procedimientos de la prueba analítica.")
    equipos: Optional[List[str]] = Field(..., description="Listado de Equipos declarados en la prueba")
    condiciones_cromatograficas: Optional[List[CondicionCromatografica]] = Field(..., description="Condiciones cromatográficas de la prueba analítica (Si Aplica)")
    reactivos: Optional[List[str]] = Field(..., description="Listado de los reactivos")
    soluciones: Optional[List[Solucion]] = Field(..., description="Listado de las soluciones")
    especificaciones: List[Especificacion] = Field(..., description="Especificaciones del método analítico")


# --- NUEVO MODELO Pydantic para el ARCHIVO FINAL ---
# Este modelo es la "plantilla" para el archivo final.
# Hereda la mayoría de los campos de ExtractionModel pero redefine 'pruebas'.

class MetodoAnaliticoNuevo(BaseModel):
    """Modelo para el método analítico final consolidado."""
    tipo_metodo: Optional[str] = Field(None)
    nombre_producto: Optional[str] = Field(None)
    numero_metodo: Optional[str] = Field(None)
    version_metodo: Optional[str] = Field(None)
    codigo_producto: Optional[str] = Field(None)
    objetivo: Optional[str] = Field(None)
    
    # Dependencias de 'extraction_models'
    alcance_metodo: Optional[AlcanceMetodo] = Field(None)
    definiciones: Optional[List[str]] = Field(None)
    recomendaciones_seguridad: Optional[List[str]] = Field(None)
    materiales: Optional[List[str]] = Field(None)
    equipos: Optional[List[Equipo]] = Field(None)
    anexos: Optional[List[Anexo]] = Field(None)
    autorizaciones: Optional[List[Autorizacion]] = Field(None)
    documentos_soporte: Optional[List[DocumentoSoporte]] = Field(None)
    historico_cambios: Optional[List[HistoricoCambio]] = Field(None)
    
    # --- LA CLAVE DEL PARCHEO ---
    # La lista de pruebas ahora es de tipo List[Prueba] (el nuevo formato)
    pruebas: List[Prueba] = Field(description="La lista de pruebas procesadas en el nuevo formato.")


# --- Función Utilitaria para Cargar el Objeto Base ---

def _load_legacy_obj_from_state(
    files: dict,
    file_path: str
) -> Union[ExtractionModel, str]:
    """
    Carga de forma robusta el ExtractionModel desde el estado, 
    manejando dicts, JSON strings y wrappers.
    Devuelve el objeto ExtractionModel o un string de error.
    """
    legacy_method_entry = files.get(file_path)

    if legacy_method_entry is None:
        return f"Error: No se encontró '{file_path}' en el estado."

    legacy_method_payload = legacy_method_entry
    if isinstance(legacy_method_entry, dict):
        if "data" in legacy_method_entry:
            legacy_method_payload = legacy_method_entry["data"]
        elif "content" in legacy_method_entry and isinstance(legacy_method_entry["content"], str):
            try:
                legacy_method_payload = json.loads(legacy_method_entry["content"])
            except json.JSONDecodeError as exc:
                return f"Error: No se pudo decodificar el JSON de '{file_path}'. Detalle: {exc}"

    if isinstance(legacy_method_payload, ExtractionModel):
        return legacy_method_payload
    elif isinstance(legacy_method_payload, dict):
        try:
            return ExtractionModel(**legacy_method_payload)
        except ValidationError as exc:
            return f"Error: No se pudo reconstruir '{file_path}' como ExtractionModel. Detalle: {exc}"
    elif isinstance(legacy_method_payload, str):
        try:
            parsed_payload = json.loads(legacy_method_payload)
            return ExtractionModel(**parsed_payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            return f"Error: No se pudo interpretar '{file_path}' como JSON de ExtractionModel. Detalle: {exc}"
    else:
        return f"Error: El contenido en '{file_path}' no es un formato compatible."


# --- Herramienta Principal: consolidar_pruebas_procesadas (Fan-In) ---

@tool
def consolidar_pruebas_procesadas(
    rutas_pruebas_nuevas: List[str], # Lista de rutas a los JSON de pruebas procesadas
    ruta_archivo_base: str,         # Ruta al JSON base (legacy_method.json)
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Fusiona (parchea) las nuevas pruebas procesadas (desde rutas_pruebas_nuevas) 
    con la información base del método legado (desde ruta_archivo_base) 
    y guarda el archivo final consolidado en /new/new_method_final.json.
    """
    logger.info(f"Iniciando 'consolidar_pruebas_procesadas' con {len(rutas_pruebas_nuevas)} pruebas.")
    files = state.get("files", {})

    # --- PASO 1: Cargar el Objeto Base Legado ---
    legacy_method_obj_or_error = _load_legacy_obj_from_state(files, ruta_archivo_base)
    
    if isinstance(legacy_method_obj_or_error, str):
        logger.error(legacy_method_obj_or_error)
        return Command(update={"messages": [ToolMessage(content=legacy_method_obj_or_error, tool_call_id=tool_call_id)]})
    
    legacy_method_obj = legacy_method_obj_or_error
    
    # Convertir el objeto base (que tiene datos extra) a un dict
    # para que podamos usarlo como base para el nuevo modelo.
    base_data_dict = legacy_method_obj.model_dump()

    # --- PASO 2: Cargar todas las Pruebas Nuevas Procesadas ---
    nuevas_pruebas_lista: List[Prueba] = []
    
    for ruta_prueba in rutas_pruebas_nuevas:
        # Lee el dict que 'structure_specs_procs' guardó
        prueba_dict = files.get(ruta_prueba)
        
        if not prueba_dict:
            logger.warning(f"No se encontró el archivo de prueba: {ruta_prueba}. Saltando.")
            continue
            
        # Garantizar que el id_prueba venga incluido incluso si fue generado antes del cambio
        if isinstance(ruta_prueba, str):
            fallback_id = Path(ruta_prueba).stem
        else:
            fallback_id = None

        if isinstance(prueba_dict, dict) and "id_prueba" not in prueba_dict and fallback_id:
            prueba_dict = dict(prueba_dict)
            prueba_dict["id_prueba"] = fallback_id

        try:
            # Valida el dict en el modelo Pydantic 'Prueba'
            prueba_obj = Prueba(**prueba_dict)
            nuevas_pruebas_lista.append(prueba_obj)
        except ValidationError as exc:
            error_msg = f"Error al validar el archivo {ruta_prueba}. Detalle: {exc}"
            logger.error(error_msg)
            return Command(update={"messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]})
    
    # --- PASO 3: "Parchear" - Crear el Objeto Final ---
    # Reemplaza la clave 'pruebas' (que tenía datos legados) 
    # con la nueva lista de objetos 'Prueba'.
    base_data_dict["pruebas"] = nuevas_pruebas_lista
    
    try:
        # Cargar el dict fusionado en el modelo final
        # Pydantic validará los campos requeridos.
        final_method = MetodoAnaliticoNuevo(**base_data_dict)
    except ValidationError as exc:
        error_msg = f"Error al crear el objeto 'MetodoAnaliticoNuevo' final. Detalle: {exc}"
        logger.error(error_msg)
        return Command(update={"messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]})

    # --- PASO 4: Guardar el Archivo Final ---
    ruta_final = "/new/new_method_final.json"
    
    try:
        final_json_payload = final_method.model_dump(mode="json")
        final_json_string = json.dumps(final_json_payload, indent=2, ensure_ascii=False)
        
        # Guardar en el formato {"content": ...} para compatibilidad con 'read_file'
        files[ruta_final] = {
            "content": final_json_string,
            "data": final_json_payload,
        }
        
    except Exception as exc:
        error_msg = f"Error al serializar el método final. Detalle: {exc}"
        logger.error(error_msg)
        return Command(update={"messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]})

    # --- PASO 5: Devolver Éxito ---
    mensaje_exito = f"Consolidación completada. {len(nuevas_pruebas_lista)} pruebas fusionadas. Archivo final guardado en: {ruta_final}"
    logger.info(mensaje_exito)
    
    return Command(
        update={
            "files": files,  # Actualiza el estado 'files' con el nuevo archivo final
            "messages": [
                ToolMessage(content=mensaje_exito, tool_call_id=tool_call_id)
            ],
        }
    )
