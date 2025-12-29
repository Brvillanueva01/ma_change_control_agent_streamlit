import json
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Tuple, Union

import cv2
import fitz  # PyMuPDF
import numpy as np
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from src.graph.state import DeepAgentState
from src.models.side_by_side_model import SideBySideModel, SideBySideModelCompleto
from src.tools.pdf_da_metadata_toc import process_document

logger = logging.getLogger(__name__)

DEFAULT_DPI = 200
DEFAULT_HEADER_PERCENT = 0.12
DEFAULT_MARGIN_PX = 5
DEFAULT_MIN_CONFIDENCE = 0.3
PROPOSED_METADATA_DOC_NAME = "/proposed_method/method_metadata_TOC.json"
PROPOSED_METADATA_METRICS_DOC_NAME = "/proposed_method/method_metadata_metrics.json"


def _pdf_to_images(pdf_path: str, dpi: int = DEFAULT_DPI) -> List[np.ndarray]:
    """Convierte un PDF a una lista de imágenes (numpy arrays)."""
    images: List[np.ndarray] = []
    doc = fitz.open(pdf_path)
    for page in doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None:
            images.append(img)
    doc.close()
    return images


def _detect_vertical_divider(img: np.ndarray, y_start: int = 0) -> tuple[int, float]:
    """Detecta la línea vertical aproximada que divide las dos columnas."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    content = gray[y_start:, :]
    content_height = content.shape[0]
    if content_height < 100:
        return width // 2, 0.1

    edges = cv2.Canny(content, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=100,
        minLineLength=int(content_height * 0.3),
        maxLineGap=20,
    )

    vertical_lines: List[int] = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if abs(x2 - x1) < 10 and abs(y2 - y1) > content_height * 0.3:
                avg_x = (x1 + x2) // 2
                if width * 0.35 < avg_x < width * 0.65:
                    vertical_lines.append(avg_x)

    if vertical_lines:
        return int(np.median(vertical_lines)), min(len(vertical_lines) / 5.0, 1.0)

    binary = cv2.threshold(content, 200, 255, cv2.THRESH_BINARY)[1]
    projection = np.sum(binary, axis=0)
    center_region = projection[int(width * 0.35) : int(width * 0.65)]
    if len(center_region) > 0:
        min_idx = int(np.argmin(center_region))
        return int(width * 0.35) + min_idx, 0.5

    return width // 2, 0.3


def _split_page_columns(
    img: np.ndarray, header_percent: float = DEFAULT_HEADER_PERCENT, margin: int = DEFAULT_MARGIN_PX
) -> tuple[np.ndarray, np.ndarray, dict]:
    height, width = img.shape[:2]
    header_end = int(height * header_percent)
    divider_x, confidence = _detect_vertical_divider(img, header_end)
    left = img[header_end:, : max(divider_x - margin, 0)]
    right = img[header_end:, min(divider_x + margin, width) :]
    metadata = {
        "divider_x": divider_x,
        "confidence": confidence,
        "header_end": header_end,
        "left_shape": left.shape[:2],
        "right_shape": right.shape[:2],
    }
    return left, right, metadata


def _split_all_pages(
    images: List[np.ndarray],
    header_percent: float = DEFAULT_HEADER_PERCENT,
    margin: int = DEFAULT_MARGIN_PX,
) -> tuple[List[np.ndarray], List[np.ndarray], List[dict]]:
    left_columns: List[np.ndarray] = []
    right_columns: List[np.ndarray] = []
    metadatas: List[dict] = []

    for img in images:
        left, right, meta = _split_page_columns(img, header_percent=header_percent, margin=margin)
        left_columns.append(left)
        right_columns.append(right)
        metadatas.append(meta)
    return left_columns, right_columns, metadatas


def _columns_to_pdf(images: List[np.ndarray]) -> Optional[str]:
    """Guarda una lista de imágenes como un PDF temporal y devuelve su ruta."""
    if not images:
        return None

    doc = fitz.open()
    try:
        for img in images:
            height, width = img.shape[:2]
            page = doc.new_page(width=width, height=height)
            success, buffer = cv2.imencode(".png", img)
            if not success:
                continue
            rect = fitz.Rect(0, 0, width, height)
            page.insert_image(rect, stream=buffer.tobytes())

        # Obtenemos los bytes del PDF en memoria y luego escribimos al archivo.
        # Esto evita problemas de permisos en Windows con doc.save().
        pdf_bytes = doc.tobytes()
    finally:
        doc.close()

    # Escribimos los bytes al archivo temporal después de cerrar el documento.
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, pdf_bytes)
    finally:
        os.close(fd)
    return tmp_path


def _model_instance_to_dict(model_instance: Union[BaseModel, Dict[str, Any], None]) -> Dict[str, Any]:
    """Serializa instancias Pydantic/dict en un dict estándar."""
    if model_instance is None:
        return {}

    if isinstance(model_instance, BaseModel):
        return model_instance.model_dump()

    if isinstance(model_instance, dict):
        return dict(model_instance)

    if isinstance(model_instance, str):
        try:
            return json.loads(model_instance)
        except json.JSONDecodeError:
            return {"data": model_instance}

    return {"data": str(model_instance)}


def _merge_list_items(target_list: list, source_list: list) -> None:
    """Mergea listas cuidando duplicados y mezclando dicts recursivamente."""
    for item in source_list:
        if item in (None, [], {}, ""):
            continue

        if isinstance(item, dict):
            existing = next(
                (t for t in target_list if isinstance(t, dict) and t == item),
                None,
            )
            if existing is not None:
                _merge_chunk_data(existing, item)
                continue

        if item not in target_list:
            target_list.append(item)


def _merge_chunk_data(target: dict, source: dict) -> None:
    """Mergea contenido de un chunk con el acumulado global."""
    for key, value in source.items():
        if value in (None, [], {}, ""):
            continue

        if key not in target or target[key] in (None, [], {}):
            target[key] = value
            continue

        target_value = target[key]
        if isinstance(target_value, list) and isinstance(value, list):
            _merge_list_items(target_value, value)
        elif isinstance(target_value, dict) and isinstance(value, dict):
            _merge_chunk_data(target_value, value)
        elif isinstance(target_value, str) and isinstance(value, str):
            if len(value.strip()) > len(target_value.strip()):
                target[key] = value
        else:
            target[key] = value


def _resolve_attr(source: Any, attr: str):
    """Lee atributos tanto de dicts como de objetos."""
    if isinstance(source, dict):
        return source.get(attr)
    return getattr(source, attr, None)


def _collect_full_markdown_from_chunks(chunk_responses: List[Any]) -> str:
    """Concatena el markdown presente en todos los chunks."""
    if not chunk_responses:
        return ""

    def _iter_markdown_sections(payload: Any):
        if payload in (None, "", [], {}):
            return

        markdown_value = _resolve_attr(payload, "markdown")
        if isinstance(markdown_value, str):
            text = markdown_value.strip()
            if text:
                yield text
        elif isinstance(markdown_value, (list, tuple)):
            for nested in markdown_value:
                yield from _iter_markdown_sections(nested)
        elif markdown_value not in (None, "", [], {}):
            yield from _iter_markdown_sections(markdown_value)

        pages = _resolve_attr(payload, "pages")
        if isinstance(pages, list):
            for page in pages:
                yield from _iter_markdown_sections(page)

        output_items = _resolve_attr(payload, "output")
        if isinstance(output_items, list):
            for item in output_items:
                yield from _iter_markdown_sections(item)

    parts: List[str] = []
    for response in chunk_responses:
        for markdown_text in _iter_markdown_sections(response):
            if markdown_text:
                parts.append(markdown_text)

    if not parts:
        return ""
    return "\n\n".join(parts).strip()


def _normalize_heading_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _looks_like_primary_heading(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 5 or len(stripped) > 80:
        return False
    letters = [ch for ch in stripped if ch.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    if upper_ratio < 0.55:
        return False
    if stripped.count(".") > 1:
        return False
    return True


def _filter_primary_headings(headings: Optional[List[str]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    filtered: List[str] = []
    excluded: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()

    for idx, raw_heading in enumerate(headings or []):
        heading = (raw_heading or "").strip()
        if not heading:
            excluded.append({"index": idx, "heading": raw_heading, "reason": "empty"})
            continue

        normalized = _normalize_heading_text(heading)
        if not normalized:
            excluded.append({"index": idx, "heading": raw_heading, "reason": "normalization_failed"})
            continue

        if not _looks_like_primary_heading(heading):
            excluded.append({"index": idx, "heading": raw_heading, "reason": "not_primary_heading"})
            continue

        if normalized in seen_keys:
            excluded.append({"index": idx, "heading": raw_heading, "reason": "duplicate"})
            continue

        seen_keys.add(normalized)
        filtered.append(heading)

    return filtered, excluded


def _consolidate_side_by_side_data(
    chunk_responses: List[Any], document_name: str
) -> Tuple[Optional[Union[SideBySideModel, Dict[str, Any]]], Dict[str, Any]]:
    """Consolida las anotaciones de los chunks usando el modelo SideBySideModel."""
    if not chunk_responses:
        logger.warning("No chunks to process for %s", document_name)
        return None, {
            "chunks_total": 0,
            "chunks_with_annotation": 0,
            "chunk_parse_errors": [],
        }

    all_chunk_data: Dict[str, Any] = {}
    metrics: Dict[str, Any] = {
        "chunks_total": len(chunk_responses),
        "chunks_with_annotation": 0,
        "chunk_parse_errors": [],
    }

    for idx, response in enumerate(chunk_responses):
        if not response:
            continue

        annotation_data = None
        if hasattr(response, "document_annotation"):
            annotation_data = response.document_annotation
        elif isinstance(response, dict) and "document_annotation" in response:
            annotation_data = response["document_annotation"]

        if not annotation_data:
            continue

        metrics["chunks_with_annotation"] += 1

        try:
            if isinstance(annotation_data, str):
                chunk_data = json.loads(annotation_data)
            elif isinstance(annotation_data, dict):
                chunk_data = annotation_data
            else:
                chunk_data = json.loads(str(annotation_data))

            _merge_chunk_data(all_chunk_data, chunk_data)
        except (json.JSONDecodeError, TypeError) as exc:
            error_message = f"chunk_{idx + 1}: {exc}"
            metrics["chunk_parse_errors"].append(error_message)
            logger.warning("Error parsing chunk %s annotation: %s", idx + 1, exc)

    if not all_chunk_data:
        logger.warning("No valid data to create model instance for %s", document_name)
        return None, metrics

    raw_toc = all_chunk_data.get("tabla_de_contenidos")
    metrics["toc_entries_before_filter"] = len(raw_toc or [])
    filtered_toc, excluded_toc = _filter_primary_headings(raw_toc)
    metrics["toc_entries_after_filter"] = len(filtered_toc)
    metrics["toc_excluded_entries"] = excluded_toc
    all_chunk_data["tabla_de_contenidos"] = filtered_toc or None

    try:
        return SideBySideModel(**all_chunk_data), metrics
    except Exception as exc:
        logger.error("Error creating SideBySideModel for %s: %s", document_name, exc)
        return all_chunk_data, metrics


def _build_full_model_with_markdown(
    model_instance: Any, markdown_completo: str
) -> Optional[Union[SideBySideModelCompleto, Dict[str, Any]]]:
    """Integra el markdown consolidado dentro del payload resultante."""
    payload = _model_instance_to_dict(model_instance)

    if markdown_completo:
        payload["markdown_completo"] = markdown_completo

    if not payload:
        if markdown_completo:
            return {"markdown_completo": markdown_completo}
        return None

    try:
        return SideBySideModelCompleto(**payload)
    except Exception as exc:
        logger.warning(
            "No se pudo crear SideBySideModelCompleto, se devuelve dict plano: %s",
            exc,
        )
        return payload


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _build_annotation_summary(model_instance: Any) -> str:
    """Genera un resumen de campos poblados y longitud del markdown."""
    if model_instance is None:
        return "No se pudo generar metadata para el método propuesto."

    payload = _model_instance_to_dict(model_instance)
    markdown_content = payload.get("markdown_completo") or ""

    populated_fields = [
        key
        for key, value in payload.items()
        if key != "markdown_completo" and not _is_empty_value(value)
    ]

    summary_lines = [f"Campos de metadata poblados: {len(populated_fields)}."]
    if populated_fields:
        preview = ", ".join(populated_fields[:6])
        summary_lines.append(f"Principales: {preview}.")

    summary_lines.append(f"Markdown consolidado: {len(markdown_content)} caracteres.")
    return " ".join(summary_lines)


def _build_processing_metrics(
    total_pages: int,
    split_metadata: List[dict],
    low_confidence_pages: List[int],
    consolidation_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Arma un payload con métricas de separación y consolidación."""
    avg_divider = None
    divider_values = [meta.get("divider_x") for meta in split_metadata if meta.get("divider_x")]
    if divider_values:
        avg_divider = sum(divider_values) / len(divider_values)

    metrics = {
        "total_pages": total_pages,
        "low_confidence_pages": low_confidence_pages,
        "column_split_metadata": split_metadata,
        "avg_divider_x": avg_divider,
    }
    metrics.update({"consolidation": consolidation_metrics})
    return metrics


@tool(
    description=(
        "Extrae la columna derecha (método propuesto) de un PDF Side-by-Side, "
        "la convierte en PDF y ejecuta Document Annotation para obtener markdown y TOC. "
        "Guarda el resultado en /proposed_method/method_metadata_TOC.json."
    )
)
def sbs_proposed_column_to_pdf_md(
    dir_document: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    if not dir_document:
        message = "No se proporcionó la ruta del documento a procesar."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    resolved_path = Path(dir_document)
    if not resolved_path.exists() or resolved_path.suffix.lower() != ".pdf":
        message = f"El documento {dir_document} no existe o no es un PDF."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    files = dict(state.get("files", {}))

    images = _pdf_to_images(str(resolved_path), dpi=DEFAULT_DPI)
    if not images:
        message = "No se pudieron generar imágenes a partir del PDF proporcionado."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    _, right_columns, split_meta = _split_all_pages(
        images, header_percent=DEFAULT_HEADER_PERCENT, margin=DEFAULT_MARGIN_PX
    )
    total_pages = len(right_columns)
    low_confidence = [
        idx + 1
        for idx, meta in enumerate(split_meta)
        if meta.get("confidence", 1.0) < DEFAULT_MIN_CONFIDENCE
    ]
    temp_pdf_path = _columns_to_pdf(right_columns)

    if not temp_pdf_path:
        message = "No se pudo construir el PDF temporal de la columna propuesta."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    try:
        chunk_responses = process_document(
            pdf_path=temp_pdf_path,
            extraction_model=SideBySideModel,
            max_pages_per_chunk=8,
        )
        model_instance, consolidation_metrics = _consolidate_side_by_side_data(
            chunk_responses, PROPOSED_METADATA_DOC_NAME
        )
        full_markdown = _collect_full_markdown_from_chunks(chunk_responses)
        full_model_instance = _build_full_model_with_markdown(model_instance, full_markdown)
        summary_message = _build_annotation_summary(full_model_instance)
        serialized_data = _model_instance_to_dict(full_model_instance) if full_model_instance else {}
    finally:
        try:
            os.unlink(temp_pdf_path)
        except OSError:
            pass

    warning_note = ""
    if low_confidence:
        warning_note = f" Baja confianza al separar páginas: {low_confidence}"

    stored_data = serialized_data if serialized_data else {}
    files[PROPOSED_METADATA_DOC_NAME] = {
        "content": _safe_json_dumps(stored_data),
        "data": stored_data,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }
    metrics_payload = _build_processing_metrics(
        total_pages=total_pages,
        split_metadata=split_meta,
        low_confidence_pages=low_confidence,
        consolidation_metrics=consolidation_metrics,
    )
    files[PROPOSED_METADATA_METRICS_DOC_NAME] = {
        "content": _safe_json_dumps(metrics_payload),
        "data": metrics_payload,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    final_message = (
        f"Markdown y TOC del método propuesto guardados en {PROPOSED_METADATA_DOC_NAME}."
        f"{warning_note} Métricas adicionales en {PROPOSED_METADATA_METRICS_DOC_NAME}."
    )
    if summary_message:
        final_message += f" Resumen: {summary_message}"

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(final_message, tool_call_id=tool_call_id)],
        }
    )


def _safe_json_dumps(payload: dict) -> str:
    """Serializa a JSON con ensure_ascii False y manejo defensivo."""
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:  # pragma: no cover - defensivo
        logger.exception("No se pudo serializar el payload a JSON.")
        return "{}"
