import logging
import json
# import re  <--- MODIFICACIÓN 1: Ya no necesitamos 're'
from pydantic import BaseModel, Field, ValidationError
from typing import Literal, Annotated, Optional, List

from langchain_core.tools import tool
from langgraph.types import Command
from langchain_core.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage, HumanMessage
from langgraph.prebuilt import InjectedState
from langchain.chat_models import init_chat_model

# Importaciones de tu proyecto (asumiendo que están correctas)
from src.prompts.tool_prompts import *
# Esto debe contener ExtractionModel (que ya incluye 'id_prueba: UUID')
from src.models.extraction_models import * 
from src.graph.state import DeepAgentState

# --- Configuración ---
logger = logging.getLogger(__name__)

## LLMs
spec_proc_gen_model = init_chat_model(model="openai:gpt-5-mini")


# --- Modelos Pydantic para el NUEVO formato de prueba ---
# (Estos modelos permanecen sin cambios)

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
        description="Identificador único (UUID o hash) de la prueba en el método legado.",
    )
    prueba: str = Field(..., description="Prueba del método analítico a la que se refiere el procedimiento.")
    procedimientos: str = Field(..., description="Descripción detallada de los procedimientos de la prueba analítica.")
    equipos: Optional[List[str]] = Field(..., description="Listado de Equipos declarados en la prueba")
    condiciones_cromatograficas: Optional[List[CondicionCromatografica]] = Field(..., description="Condiciones cromatográficas de la prueba analítica (Si Aplica)")
    reactivos: Optional[List[str]] = Field(..., description="Listado de los reactivos")
    soluciones: Optional[List[Solucion]] = Field(..., description="Listado de las soluciones")
    especificaciones: List[Especificacion] = Field(..., description="Especificaciones del método analítico")

class Pruebas(BaseModel):
    pruebas: List[Prueba] = Field(..., description="Procedimientos del método analítico")


# --- Herramienta Principal ---

@tool(description=STRUCTURED_SPECS_PROC_PROMPT_TOOL_DESC)
def structure_specs_procs(
    # --- MODIFICACIÓN 3: Cambiamos 'test: str' por 'id_prueba: str' ---
    id_prueba: str,  # El UUID (string) de la prueba que buscas
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Busca una prueba (test) específica por su ID (UUID), la transforma a un 
    nuevo formato Pydantic usando un LLM, y guarda el resultado en 
    un archivo JSON único para esa prueba en el estado 'files'.
    """
    
    logger.info(f"Iniciando 'structure_specs_procs' para el ID de prueba: {id_prueba}")
    files = state.get("files", {})
    
    # 1. Obtener el objeto Pydantic (BaseModel) directamente del estado
    # (Esta lógica de carga y validación es robusta y permanece igual)
    legacy_method_entry = files.get("/legacy/legacy_method.json")
    new_method_filename = "/new/new_method.json"
    files[new_method_filename] = legacy_method_entry

    # --- MANEJO DE ERRORES 1: (Sin cambios) ---
    if legacy_method_entry is None:
        error_msg = "Error: No se encontró '/legacy/legacy_method.json' en el estado. Asegúrate de que 'extract_legacy_sections' se haya ejecutado primero."
        logger.error(error_msg)
        return Command(
            update={
                "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
            }
        )

    # (Lógica de normalización de 'legacy_method_entry' sin cambios)
    legacy_method_payload = legacy_method_entry
    if isinstance(legacy_method_entry, dict):
        if "data" in legacy_method_entry:
            legacy_method_payload = legacy_method_entry["data"]
        elif "content" in legacy_method_entry and isinstance(legacy_method_entry["content"], str):
            try:
                legacy_method_payload = json.loads(legacy_method_entry["content"])
            except json.JSONDecodeError as exc:
                error_msg = (
                    "Error: No se pudo decodificar el contenido JSON de '/legacy/legacy_method.json'."
                    f" Detalle: {exc}"
                )
                logger.error(error_msg)
                return Command(
                    update={
                        "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
                    }
                )
    
    if isinstance(legacy_method_payload, ExtractionModel):
        legacy_method_obj = legacy_method_payload
    elif isinstance(legacy_method_payload, dict):
        try:
            legacy_method_obj = ExtractionModel(**legacy_method_payload)
        except ValidationError as exc:
            error_msg = (
                "Error: No se pudo reconstruir '/legacy/legacy_method.json' como"
                f" ExtractionModel. Detalle: {exc}"
            )
            logger.error(error_msg)
            return Command(
                update={
                    "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
                }
            )
    elif isinstance(legacy_method_payload, str):
        try:
            parsed_payload = json.loads(legacy_method_payload)
            legacy_method_obj = ExtractionModel(**parsed_payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            error_msg = (
                "Error: No se pudo interpretar el contenido de '/legacy/legacy_method.json'"
                f" como JSON válido del modelo ExtractionModel. Detalle: {exc}"
            )
            logger.error(error_msg)
            return Command(
                update={
                    "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
                }
            )
    else:
        error_msg = (
            "Error: El contenido almacenado en '/legacy/legacy_method.json' no es un formato"
            " compatible (dict o ExtractionModel)."
        )
        logger.error(error_msg)
        return Command(
            update={
                "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
            }
        )
        
    # 2. Validar que el objeto tenga el atributo 'pruebas' (Sin cambios)
    if not hasattr(legacy_method_obj, 'pruebas') or not legacy_method_obj.pruebas:
        error_msg = f"Error: El objeto Pydantic (tipo: {type(legacy_method_obj).__name__}) en 'legacy_method.json' no tiene un atributo 'pruebas' o está vacío."
        logger.error(error_msg)
        return Command(
            update={
                "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
            }
        )

    # --- MODIFICACIÓN 4: Buscar por 'id_prueba' (UUID) en lugar de 'prueba' (nombre) ---
    legacy_method_test_obj = next(
        (test_obj for test_obj in legacy_method_obj.pruebas if str(test_obj.id_prueba) == id_prueba), 
        None
    )

    # --- MANEJO DE ERRORES 2: (Mensaje de error actualizado) ---
    if legacy_method_test_obj is None:
        error_msg = f"Error: No se pudo encontrar la prueba con ID '{id_prueba}' dentro de 'legacy_method.json'."
        logger.warning(error_msg)
        return Command(
            update={
                "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]
            }
        )

    # 4. Transformar con el LLM especialista (Mensaje de error actualizado)
    test_json_string = json.dumps(legacy_method_test_obj.model_dump(), indent=2, ensure_ascii=False)

    try:
        structured_model = spec_proc_gen_model.with_structured_output(Prueba)

        prueba_en_nuevo_formato = structured_model.invoke([
            HumanMessage(content=GENERATE_STRUCTURED_CONTENT_TEST.format(
                extracted_content=test_json_string, 
            ))
        ])
        
    except Exception as exc: 
        error_msg = f"Error del LLM al transformar la prueba ID '{id_prueba}': {exc}"
        logger.error(f"{error_msg} - Input LLM: {test_json_string[:500]}...") # Loguea el error
        return Command(update={"messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)]})
    

    # --- MODIFICACIÓN 5: Usar el UUID como nombre de archivo (más robusto) ---
    
    # Crear un nombre de archivo único basado en el ID de la prueba
    nombre_archivo_salida = f"{id_prueba}.json"
    
    # Definir una ruta de salida (ej. en un "directorio" virtual)
    ruta_salida = f"/new/pruebas_procesadas/{nombre_archivo_salida}" 

    # Guardar el resultado (como dict) en el estado 'files'
    # Usamos model_dump() para guardar un dict, que es serializable.
    prueba_dict = prueba_en_nuevo_formato.model_dump()
    prueba_dict["id_prueba"] = id_prueba
    files[ruta_salida] = prueba_dict

    # 6. Devolver un mensaje de éxito (Mensaje de éxito actualizado)
    mensaje_exito = f"Prueba ID '{id_prueba}' procesada y guardada exitosamente en: {ruta_salida}"
    logger.info(mensaje_exito)

    return Command(
        update={
            "files": files,  # Actualiza el estado 'files' con el nuevo archivo
            "messages": [
                # Devolvemos la RUTA del archivo, como espera el agente
                ToolMessage(content=ruta_salida, tool_call_id=tool_call_id)
            ],
        }
    )
