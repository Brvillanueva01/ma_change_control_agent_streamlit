"""
Herramienta para resolver referencias de archivos fuente en el control de cambios.

Esta herramienta mapea los códigos de producto mencionados en el CC a los nombres
de archivos reales en /actual_method/ y /proposed_method/.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional, Any, Tuple

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import RESOLVE_SOURCE_REFERENCES_TOOL_DESC

logger = logging.getLogger(__name__)

# Patrones para archivos de metadatos
METADATA_PATTERN = "method_metadata_TOC_"
CC_SUMMARY_PATH = "/new/change_control_summary.json"


def _extract_product_codes(text: str) -> List[str]:
    """Extrae códigos de producto de un texto.
    
    Busca patrones como:
    - 400002641 (9 dígitos)
    - 01-3608 (formato método)
    - GR 400006238
    """
    codes = []
    
    # Patrón para códigos de 9 dígitos (códigos de producto)
    product_codes = re.findall(r'\b4\d{8}\b', text)
    codes.extend(product_codes)
    
    # Patrón para códigos de método (01-XXXX)
    method_codes = re.findall(r'\b\d{2}-\d{4}\b', text)
    codes.extend(method_codes)
    
    return list(set(codes))


def _normalize_code(code: str) -> str:
    """Normaliza un código para comparación.
    
    Elimina prefijos como 'GR ', 'MA ', 'RM ' y espacios.
    """
    if not code:
        return ""
    # Eliminar prefijos comunes
    normalized = re.sub(r'^(GR|MA|RM|CC)\s*', '', code.strip(), flags=re.IGNORECASE)
    # Eliminar espacios y guiones para comparación flexible
    return normalized.strip()


def _build_source_mapping(files: Dict[str, Any]) -> Dict[str, str]:
    """Construye un mapeo de códigos de producto a nombres de archivo.
    
    Lee los metadatos de /actual_method/ y /proposed_method/ y extrae:
    - codigo_producto -> source_file_name
    - numero_metodo -> source_file_name
    - Códigos en lista_productos_alcance -> source_file_name
    
    Returns:
        Dict[str, str]: Mapeo código -> source_file_name
    """
    mapping: Dict[str, str] = {}
    
    for file_path, file_info in files.items():
        # Solo procesar archivos de metadatos
        if METADATA_PATTERN not in file_path:
            continue
        
        # Verificar que sea de actual_method o proposed_method
        if "/actual_method/" not in file_path and "/proposed_method/" not in file_path:
            continue
        
        data = file_info.get("data", {})
        if not data:
            continue
        
        source_file_name = data.get("source_file_name")
        if not source_file_name:
            continue
        
        # Mapear codigo_producto
        codigo_producto = data.get("codigo_producto")
        if codigo_producto:
            normalized = _normalize_code(codigo_producto)
            if normalized:
                mapping[normalized] = source_file_name
                logger.debug(f"Mapeado codigo_producto '{normalized}' -> '{source_file_name}'")
        
        # Mapear numero_metodo
        numero_metodo = data.get("numero_metodo")
        if numero_metodo:
            normalized = _normalize_code(numero_metodo)
            if normalized:
                mapping[normalized] = source_file_name
                logger.debug(f"Mapeado numero_metodo '{normalized}' -> '{source_file_name}'")
        
        # Mapear códigos de productos en alcance
        alcance = data.get("alcance_metodo", {})
        if alcance and isinstance(alcance, dict):
            productos = alcance.get("lista_productos_alcance", [])
            for producto in productos:
                if isinstance(producto, dict):
                    codigo = producto.get("codigo_producto")
                    if codigo:
                        normalized = _normalize_code(codigo)
                        if normalized:
                            mapping[normalized] = source_file_name
                            logger.debug(f"Mapeado alcance '{normalized}' -> '{source_file_name}'")
    
    return mapping


def _resolve_reference(
    source_reference: Optional[str], 
    mapping: Dict[str, str]
) -> Tuple[Optional[str], bool]:
    """Resuelve una referencia de archivo fuente usando el mapeo.
    
    Args:
        source_reference: Código de referencia del CC (ej: "01-4280", "400006238")
        mapping: Mapeo código -> source_file_name
    
    Returns:
        Tuple[resolved_name, was_resolved]: El nombre resuelto y si se encontró match
    """
    if not source_reference:
        return None, False
    
    normalized = _normalize_code(source_reference)
    if not normalized:
        return source_reference, False
    
    # Búsqueda exacta
    if normalized in mapping:
        return mapping[normalized], True
    
    # Búsqueda parcial (el código está contenido en alguna clave)
    for key, value in mapping.items():
        if normalized in key or key in normalized:
            return value, True
    
    # No se encontró match
    return source_reference, False


def _update_cc_summary(
    cc_data: Dict[str, Any], 
    mapping: Dict[str, str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Actualiza el CC summary con los source_file_name resueltos.
    
    Args:
        cc_data: Datos del change_control_summary.json
        mapping: Mapeo código -> source_file_name
    
    Returns:
        Tuple[updated_data, resolution_report]: Datos actualizados y reporte
    """
    updated = dict(cc_data)
    report = {
        "resolved": [],
        "unresolved": [],
        "mapping_used": mapping
    }
    
    # Actualizar cambios_pruebas_analiticas
    cambios = updated.get("cambios_pruebas_analiticas", [])
    for cambio in cambios:
        if not isinstance(cambio, dict):
            continue
        
        source_ref = cambio.get("source_reference_file")
        resolved, was_resolved = _resolve_reference(source_ref, mapping)
        
        if was_resolved:
            cambio["resolved_source_file_name"] = resolved
            report["resolved"].append({
                "prueba": cambio.get("prueba"),
                "original": source_ref,
                "resolved": resolved
            })
        elif source_ref:
            cambio["resolved_source_file_name"] = None
            report["unresolved"].append({
                "prueba": cambio.get("prueba"),
                "original": source_ref
            })
    
    # Actualizar pruebas_nuevas
    pruebas_nuevas = updated.get("pruebas_nuevas", [])
    for prueba in pruebas_nuevas:
        if not isinstance(prueba, dict):
            continue
        
        source_ref = prueba.get("source_reference_file")
        resolved, was_resolved = _resolve_reference(source_ref, mapping)
        
        if was_resolved:
            prueba["resolved_source_file_name"] = resolved
            report["resolved"].append({
                "prueba": prueba.get("prueba"),
                "original": source_ref,
                "resolved": resolved
            })
        elif source_ref:
            prueba["resolved_source_file_name"] = None
            report["unresolved"].append({
                "prueba": prueba.get("prueba"),
                "original": source_ref
            })
    
    return updated, report


@tool(description=RESOLVE_SOURCE_REFERENCES_TOOL_DESC)
def resolve_source_references(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Resuelve las referencias de archivos fuente en el control de cambios.
    
    Lee los metadatos de /actual_method/ y /proposed_method/ para construir
    un mapeo de códigos de producto a nombres de archivo, y luego actualiza
    el change_control_summary.json con los source_file_name resueltos.
    
    Esta herramienta debe ejecutarse ANTES de analyze_change_impact para
    asegurar que las referencias de archivos estén correctamente mapeadas.
    """
    files = state.get("files", {})
    
    # 1. Construir mapeo de códigos a source_file_name
    mapping = _build_source_mapping(files)
    
    if not mapping:
        message = (
            "No se encontraron archivos de metadatos en /actual_method/ o /proposed_method/. "
            "Asegúrate de que los agentes de carga hayan procesado los documentos primero."
        )
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )
    
    logger.info(f"Mapeo construido con {len(mapping)} entradas: {list(mapping.keys())}")
    
    # 2. Leer change_control_summary.json
    cc_file = files.get(CC_SUMMARY_PATH)
    if not cc_file:
        message = (
            f"No se encontró {CC_SUMMARY_PATH}. "
            "Asegúrate de que el change_control_agent haya procesado el documento primero."
        )
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )
    
    cc_data = cc_file.get("data", {})
    if not cc_data:
        # Intentar parsear desde content
        content = cc_file.get("content", [])
        if isinstance(content, list):
            content = "\n".join(content)
        try:
            cc_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            message = f"No se pudo parsear {CC_SUMMARY_PATH}."
            logger.error(message)
            return Command(
                update={
                    "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
                }
            )
    
    # 3. Actualizar CC summary con referencias resueltas
    updated_cc, report = _update_cc_summary(cc_data, mapping)
    
    # 4. Guardar CC actualizado
    updated_files = dict(files)
    content_str = json.dumps(updated_cc, indent=2, ensure_ascii=False)
    updated_files[CC_SUMMARY_PATH] = {
        "content": content_str.split("\n"),
        "data": updated_cc,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # 5. Guardar reporte de resolución
    report_path = "/new/source_reference_mapping.json"
    report_str = json.dumps(report, indent=2, ensure_ascii=False)
    updated_files[report_path] = {
        "content": report_str.split("\n"),
        "data": report,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # 6. Construir mensaje de resumen
    resolved_count = len(report["resolved"])
    unresolved_count = len(report["unresolved"])
    
    summary_lines = [
        f"Resolución de referencias completada:",
        f"- Mapeo construido: {len(mapping)} códigos de producto/método",
        f"- Referencias resueltas: {resolved_count}",
        f"- Referencias sin resolver: {unresolved_count}",
    ]
    
    if report["resolved"]:
        summary_lines.append("\nReferencias resueltas:")
        for item in report["resolved"][:5]:  # Mostrar máximo 5
            summary_lines.append(f"  - {item['prueba']}: {item['original']} → {item['resolved']}")
        if len(report["resolved"]) > 5:
            summary_lines.append(f"  ... y {len(report['resolved']) - 5} más")
    
    if report["unresolved"]:
        summary_lines.append("\n⚠️ Referencias sin resolver:")
        for item in report["unresolved"]:
            summary_lines.append(f"  - {item['prueba']}: {item['original']}")
    
    summary_lines.append(f"\nArchivos actualizados: {CC_SUMMARY_PATH}, {report_path}")
    
    message = "\n".join(summary_lines)
    logger.info(message)
    
    return Command(
        update={
            "files": updated_files,
            "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
        }
    )
