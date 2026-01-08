import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

import base64
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, List, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from mistralai import Mistral

from src.graph.state import DeepAgentState

logger = logging.getLogger(__name__)

DEFAULT_DPI = 200
DEFAULT_HEADER_PERCENT = 0.12
DEFAULT_MARGIN_PX = 5
DEFAULT_MIN_CONFIDENCE = 0.3
DEFAULT_BASE_PATH = "/proposed_method"


def _extract_source_file_name(pdf_path: str) -> str:
    """Extrae el nombre del archivo fuente de una ruta de PDF.
    
    Ejemplo: 'D:/docs/ANEXO NAPROXENO.pdf' -> 'ANEXO NAPROXENO'
    """
    return Path(pdf_path).stem


def _pdf_to_images(pdf_path: str, dpi: int = DEFAULT_DPI) -> List[np.ndarray]:
    """Convert PDF pages to images."""
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


def _detect_vertical_divider(img: np.ndarray, y_start: int = 0) -> Tuple[int, float]:
    """Detect an approximate vertical divider between the two columns."""
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
) -> Tuple[np.ndarray, np.ndarray, dict]:
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
) -> Tuple[List[np.ndarray], List[np.ndarray], List[dict]]:
    left_columns: List[np.ndarray] = []
    right_columns: List[np.ndarray] = []
    metadatas: List[dict] = []

    for img in images:
        left, right, meta = _split_page_columns(img, header_percent=header_percent, margin=margin)
        left_columns.append(left)
        right_columns.append(right)
        metadatas.append(meta)
    return left_columns, right_columns, metadatas


def _columns_to_pdf(images: List[np.ndarray], jpeg_quality: int = 85) -> Optional[str]:
    """Save a list of images as a temporary PDF and return its path.
    
    Uses JPEG compression to reduce file size for API limits.
    """
    if not images:
        return None

    doc = fitz.open()
    try:
        for img in images:
            height, width = img.shape[:2]
            page = doc.new_page(width=width, height=height)
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            success, buffer = cv2.imencode(".jpg", img, encode_params)
            if not success:
                continue
            rect = fitz.Rect(0, 0, width, height)
            page.insert_image(rect, stream=buffer.tobytes())

        pdf_bytes = doc.tobytes(deflate=True)
    finally:
        doc.close()

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, pdf_bytes)
    finally:
        os.close(fd)
    
    file_size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
    logger.info("PDF temporal creado: %.2f MB (%d páginas)", file_size_mb, len(images))
    
    return tmp_path


def _encode_pdf(pdf_path: str) -> Optional[str]:
    try:
        with open(pdf_path, "rb") as pdf_file:
            return base64.b64encode(pdf_file.read()).decode("utf-8")
    except Exception as exc:
        logger.error("Error encoding PDF %s: %s", pdf_path, exc)
        return None


def _collect_markdown_from_pages(ocr_response: Any) -> str:
    pages = None
    if hasattr(ocr_response, "pages"):
        pages = getattr(ocr_response, "pages", None)
    if pages is None and isinstance(ocr_response, dict):
        pages = ocr_response.get("pages")

    if not pages:
        return ""

    parts: List[str] = []
    for page in pages:
        markdown = None
        if hasattr(page, "markdown"):
            markdown = getattr(page, "markdown", None)
        elif isinstance(page, dict):
            markdown = page.get("markdown")

        if markdown:
            text = markdown.strip()
            if text:
                parts.append(text)

    return "\n\n".join(parts).strip()


def _extract_markdown_with_ocr(pdf_path: str, max_retries: int = 3) -> str:
    base64_pdf = _encode_pdf(pdf_path)
    if not base64_pdf:
        return ""

    pdf_size_mb = len(base64_pdf) * 3 / 4 / (1024 * 1024)
    logger.info("PDF temporal para OCR: %.2f MB (base64: %.2f MB)", pdf_size_mb, len(base64_pdf) / (1024 * 1024))

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise EnvironmentError("Defina MISTRAL_API_KEY en el entorno o en el archivo .env")

    client = Mistral(api_key=api_key, timeout_ms=900000)
    
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info("Intento OCR %d/%d...", attempt + 1, max_retries)
            response = client.ocr.process(
                model="mistral-ocr-latest",
                document={
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{base64_pdf}",
                },
                include_image_base64=False,
            )
            return _collect_markdown_from_pages(response)
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            if "disconnect" in error_msg or "timeout" in error_msg or "connection" in error_msg or "response" in error_msg:
                wait_time = (2 ** attempt) * 10
                logger.warning(
                    "Intento %d/%d fallido (OCR): %s. Reintentando en %ds...",
                    attempt + 1, max_retries, e, wait_time
                )
                time.sleep(wait_time)
            else:
                raise
    
    raise last_error or Exception("OCR falló después de todos los reintentos")


def _safe_json_dumps(payload: dict) -> str:
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception:
        logger.exception("No se pudo serializar el payload a JSON.")
        return "{}"


@tool(
    description=(
        "Extrae la columna derecha (metodo propuesto) de un PDF Side-by-Side, "
        "la convierte a PDF y ejecuta OCR de Mistral para obtener el markdown completo. "
        "Guarda el resultado en /proposed_method/method_metadata_TOC.json."
    )
)
def sbs_proposed_column_to_pdf_md(
    dir_document: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    if not dir_document:
        message = "No se proporciono la ruta del documento a procesar."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    resolved_path = Path(dir_document)
    if not resolved_path.exists() or resolved_path.suffix.lower() != ".pdf":
        message = f"El documento {dir_document} no existe o no es un PDF."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    images = _pdf_to_images(str(resolved_path), dpi=DEFAULT_DPI)
    if not images:
        message = "No se pudieron generar imagenes a partir del PDF proporcionado."
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})

    _, right_columns, split_meta = _split_all_pages(
        images, header_percent=DEFAULT_HEADER_PERCENT, margin=DEFAULT_MARGIN_PX
    )
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
        markdown = _extract_markdown_with_ocr(temp_pdf_path)
    except Exception as exc:
        logger.error("Error ejecutando OCR para %s: %s", dir_document, exc)
        message = f"No se pudo extraer markdown con OCR: {exc}"
        return Command(update={"messages": [ToolMessage(message, tool_call_id=tool_call_id)]})
    finally:
        try:
            os.unlink(temp_pdf_path)
        except OSError:
            pass

    # Extraer source_file_name del nombre del PDF
    source_file_name = _extract_source_file_name(str(resolved_path))
    document_name = f"{DEFAULT_BASE_PATH}/method_metadata_TOC_{source_file_name}.json"
    
    stored_data = {
        "markdown_completo": markdown,
        "source_file_name": source_file_name,
    } if markdown else {"source_file_name": source_file_name}
    
    files = dict(state.get("files", {}))
    files[document_name] = {
        "content": _safe_json_dumps(stored_data),
        "data": stored_data,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    warning_note = ""
    if low_confidence:
        warning_note = f" Separacion con baja confianza en paginas: {low_confidence}."

    final_message = (
        f"Markdown del metodo propuesto guardado en {document_name}.{warning_note}\n"
        f"source_file_name: '{source_file_name}' (usar este valor en las siguientes herramientas)"
    )
    if markdown:
        final_message += f"\nTotal caracteres: {len(markdown)}."
    else:
        final_message += "\nNo se obtuvo texto de OCR."

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(final_message, tool_call_id=tool_call_id)],
        }
    )
