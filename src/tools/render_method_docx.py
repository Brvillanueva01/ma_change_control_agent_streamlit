from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import RENDER_METHOD_DOCX_TOOL_DESCRIPTION

try:
    from docxtpl import DocxTemplate, InlineImage
    from docx.shared import Mm
    from jinja2.exceptions import UndefinedError
except ImportError:
    DocxTemplate = None
    InlineImage = None
    Mm = None
    UndefinedError = None

logger = logging.getLogger(__name__)

# Rutas por defecto
METHOD_DEFAULT_PATH = "/new/new_method_final.json"
TEMPLATE_DEFAULT_PATH = Path(__file__).parent.parent / "template" / "Plantilla.docx"
OUTPUT_DEFAULT_DIR = Path(__file__).parent.parent.parent / "output"


def _clean_text(text: str) -> str:
    """Normaliza texto y remueve caracteres de control que rompen DOCX."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _latex_to_text_general(text: str) -> str:
    """
    Convierte LaTeX a texto matematico compatible con Word (texto plano).
    Normaliza fracciones, elimina delimitadores y reemplaza simbolos comunes
    para reducir riesgos de caracteres ilegales en el DOCX.
    """
    if not isinstance(text, str):
        return text

    out = text.replace("\r\n", "\n").replace("\r", "\n")

    # Fracciones anidadas: \frac{a}{b} -> (a/b)
    frac_pattern = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    while frac_pattern.search(out):
        out = frac_pattern.sub(r"(\1/\2)", out)

    # Eliminar delimitadores y comandos de formato sin contenido
    out = re.sub(r"\\left|\\right", "", out)
    out = re.sub(r"\\[()]", "", out)
    out = out.replace("$", "")
    out = re.sub(r"\\mathrm\{\s*~?([^}]+)\s*\}", r"\1", out)
    out = re.sub(r"\\text\{\s*([^}]+)\s*\}", r"\1", out)

    replacements = [
        (r"\\%", "%"),
        (r"\\times", "\u00d7"),
        (r"\\cdot", "\u00b7"),
        (r"\\pm", "\u00b1"),
        (r"\\mu", "\u00b5"),
        (r"\\alpha", "\u03b1"),
        (r"\\beta", "\u03b2"),
        (r"\\gamma", "\u03b3"),
        (r"\\deg(re(e)?|)ree?", "\u00b0"),
        (r"\^\{\\circ\}", "\u00b0"),
        (r"\^\{([^}]+)\}", r"^\1"),
    ]
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)

    # Normalizacion basica
    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    out = re.sub(r"\s*/\s*", "/", out)
    out = re.sub(r"(\d)\s+%", r"\1%", out)

    # Normalizacion matematica general
    out = re.sub(r"\u00b5\s+g", "\u00b5g", out)
    out = re.sub(r"m\s+g", "mg", out)
    out = re.sub(r"n\s+g", "ng", out)
    out = re.sub(r"m\s+L", "mL", out)
    out = re.sub(r"\s*\u00d7\s*", "\u00d7", out)
    return out


def _deep_latex_cleanup(obj: Any) -> Any:
    """Limpieza recursiva: aplica _latex_to_text_general a todos los strings."""
    if isinstance(obj, str):
        return _latex_to_text_general(obj)
    if isinstance(obj, list):
        return [_deep_latex_cleanup(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_latex_cleanup(v) for k, v in obj.items()}
    return obj


def _normalize_str(value: Any) -> str:
    """Limpia un valor a string seguro para la plantilla."""
    return _latex_to_text_general(_clean_text(value if value is not None else ""))


def _as_list(value: Any) -> List[Any]:
    """Garantiza lista (evita fallos en plantillas al iterar)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _sanitize(obj: Any) -> Any:
    """Limpieza recursiva basica para strings/dicts/listas."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return _normalize_str(obj)
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    return obj


def _normalize_condiciones(cond: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cond = cond or {}
    return {
        "condiciones": _sanitize(_as_list(cond.get("condiciones"))),
        "tabla_gradiente": _sanitize(cond.get("tabla_gradiente")),
        "solventes_fase_movil": _sanitize(_as_list(cond.get("solventes_fase_movil"))),
        "notas": _sanitize(_as_list(cond.get("notas"))),
    }


def _normalize_sst(sst: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sst = sst or {}
    return {
        "descripcion": _normalize_str(sst.get("descripcion")),
        "tabla_orden_inyeccion": _sanitize(_as_list(sst.get("tabla_orden_inyeccion"))),
        "notas": _sanitize(_as_list(sst.get("notas"))),
    }


def _normalize_procedimiento(proc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    proc = proc or {}
    return {
        "texto": _normalize_str(proc.get("texto")),
        "sst": _normalize_sst(proc.get("sst")),
        "tiempo_retencion": _sanitize(_as_list(proc.get("tiempo_retencion"))),
        "notas": _sanitize(_as_list(proc.get("notas"))),
    }


def _normalize_calculos(calculos: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    calculos = calculos or {}
    formulas = []
    for formula in _as_list(calculos.get("formulas")):
        if not isinstance(formula, dict):
            continue
        formulas.append({
            "descripcion": _normalize_str(formula.get("descripcion")),
            "formula": _normalize_str(formula.get("formula")),
            "variables": _sanitize(_as_list(formula.get("variables"))),
        })
    return {
        "formulas": formulas,
        "parametros_uniformidad_contenido": _sanitize(calculos.get("parametros_uniformidad_contenido")),
        "interpretacion_resultados_disolucion": _sanitize(calculos.get("interpretacion_resultados_disolucion")),
    }


def _normalize_criterio(criterio: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    criterio = criterio or {}
    return {
        "texto": _normalize_str(criterio.get("texto")),
        "tipo_criterio": _normalize_str(criterio.get("tipo_criterio")),
        "tabla_criterios": _sanitize(_as_list(criterio.get("tabla_criterios"))),
        "notas": _sanitize(_as_list(criterio.get("notas"))),
    }


def _normalize_prueba(prueba: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "section_id": _normalize_str(prueba.get("section_id")),
        "section_title": _normalize_str(prueba.get("section_title")),
        "test_name": _normalize_str(prueba.get("test_name")),
        "test_type": _normalize_str(prueba.get("test_type")),
        "condiciones_cromatograficas": _normalize_condiciones(prueba.get("condiciones_cromatograficas")),
        "soluciones": _sanitize(_as_list(prueba.get("soluciones"))),
        "procedimiento": _normalize_procedimiento(prueba.get("procedimiento")),
        "calculos": _normalize_calculos(prueba.get("calculos")),
        "tabla_parametros": _sanitize(prueba.get("tabla_parametros")),
        "criterio_aceptacion": _normalize_criterio(prueba.get("criterio_aceptacion")),
        "equipos": _sanitize(_as_list(prueba.get("equipos"))),
        "reactivos": _sanitize(_as_list(prueba.get("reactivos"))),
        "referencias": _sanitize(_as_list(prueba.get("referencias"))),
    }


def _build_method_context(method_data: Dict[str, Any]) -> Dict[str, Any]:
    """Arma el contexto para docxtpl a partir del nodo data del JSON."""
    context: Dict[str, Any] = {}

    for field in ["tipo_metodo", "nombre_producto", "numero_metodo", "version_metodo", "codigo_producto", "objetivo"]:
        context[field] = _normalize_str(method_data.get(field))

    alcance = method_data.get("alcance_metodo") or {}
    context["alcance_metodo"] = {
        "texto_alcance": _normalize_str(alcance.get("texto_alcance")),
        "lista_productos_alcance": _sanitize(_as_list(alcance.get("lista_productos_alcance"))),
    }

    context["definiciones"] = _sanitize(_as_list(method_data.get("definiciones")))
    context["recomendaciones_seguridad"] = _sanitize(_as_list(method_data.get("recomendaciones_seguridad")))
    context["materiales"] = _sanitize(_as_list(method_data.get("materiales")))
    context["equipos"] = _sanitize(_as_list(method_data.get("equipos")))
    context["anexos"] = _sanitize(_as_list(method_data.get("anexos")))
    context["autorizaciones"] = _sanitize(_as_list(method_data.get("autorizaciones")))
    context["documentos_soporte"] = _sanitize(_as_list(method_data.get("documentos_soporte")))
    context["historico_cambios"] = _sanitize(_as_list(method_data.get("historico_cambios")))

    pruebas_raw = method_data.get("pruebas") or []
    context["pruebas"] = [_normalize_prueba(prueba) for prueba in pruebas_raw if isinstance(prueba, dict)]

    # Fallback: agregar 'prueba' vacia para referencias fuera del loop en la plantilla
    context["prueba"] = {
        "section_id": "",
        "section_title": "",
        "test_name": "",
        "test_type": "",
        "condiciones_cromatograficas": _normalize_condiciones(None),
        "soluciones": [],
        "procedimiento": _normalize_procedimiento(None),
        "calculos": _normalize_calculos(None),
        "tabla_parametros": None,
        "criterio_aceptacion": _normalize_criterio(None),
        "equipos": [],
        "reactivos": [],
        "referencias": [],
    }

    return context


def _load_json_payload(files: dict[str, Any], path: str) -> Optional[dict[str, Any]]:
    """Carga un payload JSON desde el filesystem virtual."""
    entry = files.get(path)
    if entry is None:
        return None

    if isinstance(entry, dict):
        if "data" in entry and isinstance(entry["data"], dict):
            return entry["data"]
        if isinstance(entry.get("content"), str):
            try:
                return json.loads(entry["content"])
            except json.JSONDecodeError:
                logger.warning(f"Error parseando JSON desde 'content' en {path}")
                return None
        return entry

    if isinstance(entry, str):
        try:
            return json.loads(entry)
        except json.JSONDecodeError:
            logger.warning(f"Error parseando JSON string en {path}")
            return None

    return None


def _validate_docx(path: Path) -> None:
    """Valida rapidamente que el DOCX generado no este corrupto (zip legible)."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise ValueError(f"Archivo DOCX corrupto: entrada dañada {bad}")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Archivo DOCX corrupto generado en {path}") from exc


def _render_docx_template(
    template_path: Path,
    context: Dict[str, Any],
    output_dir: Path,
    filename_prefix: str = "method",
    timestamp: Optional[str] = None,
) -> Path:
    """Renderiza una plantilla DOCX usando docxtpl/Jinja2."""
    if DocxTemplate is None:
        raise RuntimeError("docxtpl no esta instalado. No es posible renderizar el DOCX.")

    tpl_path = Path(template_path)
    if not tpl_path.exists():
        raise FileNotFoundError(f"Plantilla no encontrada: {tpl_path}")

    doc = DocxTemplate(str(tpl_path))
    cleaned_context = _sanitize(context)

    if UndefinedError is not None:
        try:
            doc.render(cleaned_context)
        except UndefinedError as err:
            missing = re.findall(r"'([^']+)'\s+is\s+undefined", str(err))
            raise ValueError(f"Faltan variables en el contexto: {missing}") from err
    else:
        doc.render(cleaned_context)

    output_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"{filename_prefix}_{ts}.docx"
    doc.save(str(out_path))
    _validate_docx(out_path)
    logger.info("Documento generado en: %s", out_path)
    return out_path


@tool(description=RENDER_METHOD_DOCX_TOOL_DESCRIPTION)
def render_method_docx(
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    method_path: str = METHOD_DEFAULT_PATH,
    template_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Command:
    """
    Renderiza el metodo analitico consolidado en un documento DOCX usando la plantilla.
    """
    logger.info("Iniciando 'render_method_docx'")

    source_files = dict(state.get("files", {}) or {})

    # Cargar el metodo desde el filesystem virtual
    method_data = _load_json_payload(source_files, method_path)
    if method_data is None:
        msg = f"No se encontro el metodo en {method_path}. Asegurate de ejecutar consolidate_new_method primero."
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Resolver rutas de plantilla y salida
    tpl_path = Path(template_path) if template_path else TEMPLATE_DEFAULT_PATH
    out_dir = Path(output_dir) if output_dir else OUTPUT_DEFAULT_DIR

    if not tpl_path.exists():
        msg = f"Plantilla no encontrada: {tpl_path}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Construir contexto para la plantilla
    try:
        context = _build_method_context(method_data)
    except Exception as e:
        msg = f"Error construyendo contexto para la plantilla: {e}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Renderizar el documento
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = _render_docx_template(
            template_path=tpl_path,
            context=context,
            output_dir=out_dir,
            filename_prefix="method",
            timestamp=timestamp,
        )
    except Exception as e:
        msg = f"Error renderizando el documento DOCX: {e}"
        logger.error(msg)
        return Command(update={"messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)]})

    # Registrar la ruta del documento generado en el filesystem virtual
    docx_info = {
        "path": str(output_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_method": method_path,
        "template_used": str(tpl_path),
    }

    files_update = source_files.copy()
    files_update["/new/rendered_docx_info.json"] = {
        "content": json.dumps(docx_info, ensure_ascii=False, indent=2),
        "data": docx_info,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    # Extraer info del metodo para el mensaje
    nombre_producto = method_data.get("nombre_producto", "N/A")
    numero_metodo = method_data.get("numero_metodo", "N/A")
    num_pruebas = len(method_data.get("pruebas", []))

    tool_message = (
        f"Documento DOCX generado exitosamente.\n"
        f"- Producto: {nombre_producto}\n"
        f"- Metodo: {numero_metodo}\n"
        f"- Pruebas renderizadas: {num_pruebas}\n"
        f"- Archivo: {output_path}"
    )
    logger.info(tool_message)

    return Command(
        update={
            "files": files_update,
            "messages": [ToolMessage(content=tool_message, tool_call_id=tool_call_id)],
        }
    )
