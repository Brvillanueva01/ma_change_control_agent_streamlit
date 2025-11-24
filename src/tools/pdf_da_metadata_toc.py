import base64
import json
import logging
import os
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from mistralai import Mistral
from mistralai.extra import response_format_from_pydantic_model
from pydantic import BaseModel
from PyPDF2 import PdfReader, PdfWriter
from langsmith import traceable

from src.graph.state import DeepAgentState
from src.models.analytical_method_models import MetodoAnaliticoDA, MetodoAnaliticoCompleto
from src.prompts.tool_description_prompts import PDF_DA_METADATA_TOC_TOOL_DESC

logger = logging.getLogger(__name__)

TEST_METADATA_TOC_DOC_NAME = "/actual_method/method_metadata_TOC.json"

# ============================================================
# Utilidades PDF
# ============================================================

@contextmanager
def _prepare_pdf_document(document_path: str):
    """Ensure the provided document path points to an existing PDF file."""
    if not document_path:
        raise ValueError("No se proporcionÃ³ la ruta del documento a procesar.")

    resolved_path = Path(document_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"El documento {document_path} no existe.")

    suffix = resolved_path.suffix.lower()
    if suffix == ".pdf":
        yield str(resolved_path)
        return

    raise ValueError(
        f"Formato de archivo no soportado para {document_path}. Solo se permiten PDF."
    )


def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            return len(reader.pages)
    except Exception as e:
        logger.error(f"Error counting pages in {pdf_path}: {e}")
        return 0


def split_pdf_into_chunks(
    pdf_path: str, max_pages_per_chunk: int = 8, chunk_overlap_pages: int = 2
) -> List[str]:
    """Split PDF into chunks of pages with overlap and temporary files."""
    chunk_files: List[str] = []
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return []

        overlap = max(chunk_overlap_pages, 0)
        chunk_size = max(max_pages_per_chunk, 1)
        step = max(chunk_size - overlap, 1)

        for start in range(0, total_pages, step):
            end = min(start + chunk_size, total_pages)
            chunk_writer = PdfWriter()
            for page_idx in range(start, end):
                chunk_writer.add_page(reader.pages[page_idx])

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as chunk_pdf:
                chunk_writer.write(chunk_pdf)
                chunk_files.append(chunk_pdf.name)

        return chunk_files
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Error splitting PDF into chunks: {e}")
        for chunk_file in chunk_files:
            try:
                os.unlink(chunk_file)
            except OSError:
                pass
        return []


def encode_pdf(pdf_path: str) -> Optional[str]:
    """Encode the pdf to base64."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            return base64.b64encode(pdf_file.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Error encoding PDF {pdf_path}: {e}")
        return None


def process_chunk(
    pdf_path: str,
    extraction_model: Type[BaseModel],
    chunk_retry_backoff_seconds: int = 5,
    chunk_retry_attempts: int = 3,
):
    """Process a single PDF chunk with Mistral OCR + Document Annotation."""
    base64_pdf = encode_pdf(pdf_path)
    if not base64_pdf:
        return None

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Defina MISTRAL_API_KEY en el entorno o en el archivo .env"
        )
    ocr_client = Mistral(api_key=api_key, timeout_ms=300000)

    request_params: Dict[str, Any] = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{base64_pdf}",
        },
        "include_image_base64": False,
    }

    if extraction_model:
        try:
            request_params["document_annotation_format"] = (
                response_format_from_pydantic_model(extraction_model)
            )
        except Exception as exc:
            logger.warning(
                f"No se pudo generar schema pydantic para {pdf_path}: {exc}"
            )

    last_exception: Optional[Exception] = None
    total_attempts = max(chunk_retry_attempts, 1)

    for attempt in range(1, total_attempts + 1):
        try:
            return ocr_client.ocr.process(**request_params)
        except Exception as exc:
            last_exception = exc
            if attempt >= total_attempts:
                break
            wait_seconds = chunk_retry_backoff_seconds * attempt
            logger.warning(
                f"Retrying chunk {pdf_path} after error: {exc}. "
                f"Intento {attempt}/{chunk_retry_attempts} en {wait_seconds}s"
            )
            time.sleep(wait_seconds)

    logger.error(f"Error processing chunk {pdf_path}: {last_exception}")
    return None

# ============================================================
# Utilidades de merge / normalizaciÃ³n
# ============================================================

def _merge_list_items(target_list: list, source_list: list, *, field_name: Optional[str] = None):
    """Mergea listas cuidando duplicados y combinando elementos dict similares."""

    for item in source_list:
        if item in (None, [], {}, ""):
            continue

        if isinstance(item, dict):
            existing = next(
                (t for t in target_list if isinstance(t, dict) and t == item), None
            )
            if existing is not None:
                _merge_chunk_data(existing, item)
                continue

        if item not in target_list:
            target_list.append(item)


def _merge_chunk_data(target: dict, source: dict):
    """Mergea datos de un chunk con el diccionario consolidado."""
    for key, value in source.items():
        if value in (None, [], {}, ""):
            continue

        if key not in target or target[key] in (None, [], {}):
            target[key] = value
            continue

        target_value = target[key]

        if isinstance(target_value, list) and isinstance(value, list):
            _merge_list_items(target_value, value, field_name=key)
        elif isinstance(target_value, dict) and isinstance(value, dict):
            _merge_chunk_data(target_value, value)
        elif isinstance(target_value, str) and isinstance(value, str):
            # Preferir el texto mÃ¡s largo
            if len(value.strip()) > len(target_value.strip()):
                target[key] = value
        else:
            target[key] = value


def _resolve_attr(source: Any, attr: str):
    """Helper para leer un atributo tanto de dicts como de objetos."""
    if isinstance(source, dict):
        return source.get(attr)
    return getattr(source, attr, None)


def _is_empty_value(value: Any) -> bool:
    """Determina si el valor se considera vacï¿½ï¿½o para efectos de resumen."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _model_instance_to_dict(
    model_instance: Union[BaseModel, Dict[str, Any], None]
) -> Dict[str, Any]:
    """Serializa cualquier instancia de modelo consolidado en un dict."""
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


def _build_full_model_with_markdown(
    model_instance: Any, markdown_completo: str
) -> Optional[Union[MetodoAnaliticoCompleto, Dict[str, Any]]]:
    """
    Integra el markdown completo dentro del payload resultante y lo valida contra
    `MetodoAnaliticoCompleto`. Si la validación falla, devuelve el dict crudo.
    """
    payload = _model_instance_to_dict(model_instance)

    if markdown_completo is not None:
        payload["markdown_completo"] = markdown_completo

    if not payload:
        if markdown_completo:
            return {"markdown_completo": markdown_completo}
        return None

    try:
        return MetodoAnaliticoCompleto(**payload)
    except Exception as exc:
        logger.warning(
            "No se pudo crear MetodoAnaliticoCompleto, se devuelve dict plano: %s", exc
        )
        return payload


def _build_annotation_summary(model_instance: Any) -> str:
    """Genera un resumen amigable del contenido procesado."""
    if model_instance is None:
        return "No se pudo generar metadata para el método analítico."

    payload = _model_instance_to_dict(model_instance)
    full_markdown = payload.get("full_markdown") or ""

    populated_fields = [
        key
        for key, value in payload.items()
        if key != "full_markdown" and not _is_empty_value(value)
    ]

    summary_lines = [
        f"Campos de metadata poblados: {len(populated_fields)}.",
    ]
    if populated_fields:
        preview = ", ".join(populated_fields[:6])
        summary_lines.append(f"Principales: {preview}.")

    summary_lines.append(f"Markdown consolidado: {len(full_markdown)} caracteres.")
    return "\n".join(summary_lines)


# ============================================================
# Procesamiento de documento (chunking + OCR)
# ============================================================

@traceable
def process_document(
    pdf_path: str,
    extraction_model: Type[BaseModel],
    max_pages_per_chunk: int = 8,
    chunk_overlap_pages: int = 0,
) -> List[Any]:
    """Process PDF with automatic chunking if needed."""
    total_pages = get_pdf_page_count(pdf_path)
    logger.info("Processing PDF %s with %s pages", pdf_path, total_pages)
    if total_pages == 0:
        logger.error("Skipping %s: could not read any pages", pdf_path)
        return []

    if total_pages <= max_pages_per_chunk:
        result = process_chunk(
            pdf_path,
            extraction_model,
            chunk_retry_backoff_seconds=5,
            chunk_retry_attempts=3,
        )
        return [result] if result else []

    chunk_files = split_pdf_into_chunks(
        pdf_path,
        max_pages_per_chunk=max_pages_per_chunk,
        chunk_overlap_pages=chunk_overlap_pages,
    )
    if not chunk_files:
        return []

    indexed_results: List[Tuple[int, Any]] = []

    try:
        max_workers = max(1, min(4, len(chunk_files)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    process_chunk,
                    chunk_file,
                    extraction_model,
                    5,
                    3,
                ): (idx, chunk_file)
                for idx, chunk_file in enumerate(chunk_files)
            }

            for future in as_completed(future_map):
                idx, chunk_file = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.error("Error processing chunk %s: %s", chunk_file, exc)
                    continue
                if result:
                    indexed_results.append((idx, result))
    finally:
        for chunk_file in chunk_files:
            try:
                os.unlink(chunk_file)
            except Exception as e:
                logger.warning("Could not delete temporary file %s: %s", chunk_file, e)

    indexed_results.sort(key=lambda item: item[0])
    return [result for _, result in indexed_results]

def consolidate_chunks_data(
    chunk_responses: List[Any],
    document_name: str,
    extraction_model: Type[BaseModel],
):
    """Consolida los document_annotation de todos los chunks y crea una instancia del modelo Pydantic."""
    try:
        if not chunk_responses:
            logger.warning("No chunks to process for %s", document_name)
            return None

        all_chunk_data: Dict[str, Any] = {}

        for i, response in enumerate(chunk_responses):
            if not response:
                continue

            annotation_data = None
            if hasattr(response, "document_annotation"):
                annotation_data = response.document_annotation
            elif isinstance(response, dict) and "document_annotation" in response:
                annotation_data = response["document_annotation"]

            if annotation_data:
                try:
                    if isinstance(annotation_data, str):
                        chunk_data = json.loads(annotation_data)
                    elif isinstance(annotation_data, dict):
                        chunk_data = annotation_data
                    else:
                        chunk_data = json.loads(str(annotation_data))

                    _merge_chunk_data(all_chunk_data, chunk_data)
                    logger.debug("Merged chunk %s data", i + 1)

                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("Error parsing chunk %s annotation: %s", i + 1, e)

        if all_chunk_data and extraction_model:
            try:
                model_instance = extraction_model(**all_chunk_data)
                logger.info(
                    "Created %s instance for %s", extraction_model.__name__, document_name
                )
                return model_instance
            except Exception as e:
                logger.error("Error creating model instance for %s: %s", document_name, e)
                return all_chunk_data

        logger.warning("No valid data to create model instance for %s", document_name)
        return None

    except Exception as e:
        logger.error("Error consolidating chunks for %s: %s", document_name, e)
        return None

# ============================================================
# Utilidades para markdown segmentado por pruebas
# ============================================================

def _collect_full_markdown_from_chunks(chunk_responses: List[Any]) -> str:
    """Concatena el markdown de todos los chunks en orden."""
    if not chunk_responses:
        return ""

    def _iter_markdown_sections(payload: Any):
        """Itera recursivamente las secciones de markdown presentes en la respuesta."""
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

# ============================================================
# Herramienta de procesamiento del documento
# ============================================================

@tool(description=PDF_DA_METADATA_TOC_TOOL_DESC)
def pdf_da_metadata_toc(
    dir_method: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    document_name = TEST_METADATA_TOC_DOC_NAME

    # 1. Procesar PDF
    try:
        with _prepare_pdf_document(dir_method) as pdf_document_path:
            chunk_responses = process_document(
                pdf_path=pdf_document_path,
                extraction_model=MetodoAnaliticoDA,
                max_pages_per_chunk=8,
            )
    except Exception as exc:
        logger.error("Error procesando el documento %s: %s", document_name, exc)
        raise

    # 2. Consolidar chunks -> modelo pydantic / dict
    model_instance = consolidate_chunks_data(
        chunk_responses, document_name, MetodoAnaliticoDA
    )

    # 4. Construir markdown completo
    full_markdown = _collect_full_markdown_from_chunks(chunk_responses)

    # 5. Construir modelo completo con markdown
    full_model_instance = _build_full_model_with_markdown(
        model_instance, full_markdown
    )

    logger.info("Completed processing %s", document_name)
    summary_message = _build_annotation_summary(full_model_instance)

    files = dict(state.get("files", {}))

    # 6. Guardar JSON estructurado del metodo completo
    if full_model_instance:
        serialized_data = _model_instance_to_dict(full_model_instance)
        full_json_string = json.dumps(
            serialized_data, indent=2, ensure_ascii=False
        )
        files[document_name] = {
            "content": full_json_string,
            "data": serialized_data,
        }
    else:
        files[document_name] = {
            "content": "{}",
            "data": {},
        }


    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(summary_message, tool_call_id=tool_call_id)
            ],
        }
    )
