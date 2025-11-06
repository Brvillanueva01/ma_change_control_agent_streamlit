import logging

from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Literal, Optional, Type, Union, Any

from langgraph.types import Command
from langchain_core.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage, HumanMessage
from langgraph.prebuilt import InjectedState
from langchain.chat_models import init_chat_model

from uuid import UUID
import os
import tempfile
import shutil
from pathlib import Path
from docx2pdf import convert as docx_to_pdf_convert
from PyPDF2 import PdfReader, PdfWriter
from mistralai import Mistral
from mistralai.extra import response_format_from_pydantic_model
import time
import base64
import json
from contextlib import contextmanager

from src.prompts.tool_prompts import *
from src.models import *
from src.graph.state import DeepAgentState

logger = logging.getLogger(__name__)


# LLMs

structured_extraction_model = init_chat_model(model="openai:gpt-4.1-mini")

# Diccionarios de trabajo

structured_extraction_prompts = {
    "change_control": STRUCTURED_EXTRACTION_CHANGE_CONTROL,
    "side_by_side": STRUCTURED_EXTRACTION_SIDE_BY_SIDE,
    "reference_methods": STRUCTURED_EXTRACTION_REFERENCE_METHODS
}

extraction_models = {
    "change_control": ChangeControlModel,
    "side_by_side": SideBySideModel,
    "reference_methods": ExtractionModel,
}

filenames = {
    "change_control": "/new/change_control.json",
    "side_by_side": "/new/side_by_side.json",
    "reference_methods": "/new/reference_methods.json"
}

# Modelos de datos requeridos

class ChangeControlStrOutput(BaseModel):
    filename: str = Field(description="Nombre del archivo a almacenar.")
    summary: str = Field(description="Resumen en lenguaje natural del documento.")
    lista_cambios: List[str] = Field(description="Lista de cambios del método analítico estructurada.")

# Funciones de utilidad

## PDF preparation
@contextmanager
def _prepare_pdf_document(document_path: str):
    """Ensure the provided document is available as a PDF, converting DOCX files on the fly."""
    if not document_path:
        raise ValueError("No se proporcionó la ruta del documento a procesar.")

    resolved_path = Path(document_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"El documento {document_path} no existe.")

    suffix = resolved_path.suffix.lower()
    if suffix == ".pdf":
        yield str(resolved_path)
        return

    if suffix == ".docx":
        temp_dir = tempfile.mkdtemp(prefix="doc_annotation_")
        pdf_output_path = os.path.join(temp_dir, resolved_path.with_suffix(".pdf").name)
        try:
            try:
                from docx2pdf import convert as docx_to_pdf_convert
            except ImportError as exc:
                raise ImportError("La librería docx2pdf es requerida para convertir archivos DOCX a PDF.") from exc

            logger.info(f"Convirtiendo DOCX a PDF: {document_path}")
            docx_to_pdf_convert(str(resolved_path), pdf_output_path)

            if not os.path.exists(pdf_output_path):
                raise RuntimeError(f"No se generó el archivo PDF convertido para {document_path}.")

            yield pdf_output_path
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return

    raise ValueError(f"Formato de archivo no soportado para {document_path}. Solo se permiten PDF o DOCX.")

## Document Annotation
def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            return len(reader.pages)
    except Exception as e:
        logger.error(f"Error counting pages in {pdf_path}: {e}")
        return 0

def split_pdf_into_chunks(pdf_path: str, max_pages_per_chunk: int = 8, chunk_overlap_pages: int = 2) -> list[str]:
    """Split PDF into chunks of pages with overlap and temporary files."""
    chunk_files: list[str] = []
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

def encode_pdf(pdf_path: str) -> str:
    """Encode the pdf to base64."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            return base64.b64encode(pdf_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error encoding PDF {pdf_path}: {e}")
        return None

def process_chunk(pdf_path: str, extraction_model: Type[BaseModel], chunk_retry_backoff_seconds: int = 5, chunk_retry_attempts: int = 3):
    """Process a single PDF chunk with Mistral OCR."""
    base64_pdf = encode_pdf(pdf_path)
    if not base64_pdf:
        return None
    
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise EnvironmentError("Defina MISTRAL_API_KEY en el entorno o en el archivo .env")
    ocr_client = Mistral(api_key=api_key, timeout_ms=300000)

    request_params = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{base64_pdf}"
        },
        "include_image_base64": False,
    }

    if extraction_model:
        try:
            request_params["document_annotation_format"] = response_format_from_pydantic_model(extraction_model)
        except Exception as exc:
            logger.warning(f"No se pudo generar schema pydantic para {pdf_path}: {exc}")

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
                f"Retrying chunk {pdf_path} after error: {exc}. Intento {attempt}/{chunk_retry_attempts} en {wait_seconds}s"
            )
            time.sleep(wait_seconds)

    logger.error(f"Error processing chunk {pdf_path}: {last_exception}")
    return None

def process_document(
    pdf_path: str,
    extraction_model: Type[BaseModel],
    max_pages_per_chunk: int = 8,
    chunk_overlap_pages: int = 2,
) -> list:
    """Process PDF with automatic chunking if needed."""
    total_pages = get_pdf_page_count(pdf_path)
    logger.info(f"Processing PDF {pdf_path} with {total_pages} pages")
    if total_pages == 0:
        logger.error(f"Skipping {pdf_path}: could not read any pages")
        return []
    
    if total_pages <= max_pages_per_chunk:
        # Process directly if within limit
        result = process_chunk(pdf_path, extraction_model, chunk_retry_backoff_seconds=5, chunk_retry_attempts=3)
        return [result] if result else []
    
    # Split into chunks and process each
    chunk_files = split_pdf_into_chunks(
        pdf_path,
        max_pages_per_chunk=max_pages_per_chunk,
        chunk_overlap_pages=chunk_overlap_pages,
    )
    results = []
    
    try:
        for i, chunk_file in enumerate(chunk_files):
            logger.info(f"Processing chunk {i+1}/{len(chunk_files)}")
            result = process_chunk(chunk_file, extraction_model, chunk_retry_backoff_seconds=5, chunk_retry_attempts=3)
            if result:
                results.append(result)
    finally:
        # Clean up temporary files
        for chunk_file in chunk_files:
            try:
                os.unlink(chunk_file)
            except Exception as e:
                logger.warning(f"Could not delete temporary file {chunk_file}: {e}")
    
    return results

def _merge_list_items(target_list: list, source_list: list):
    """Mergea listas cuidando duplicados y combinando elementos dict similares."""
    for item in source_list:
        if item in (None, [], {}, ""):
            continue

        if isinstance(item, dict):
            existing = next((t for t in target_list if isinstance(t, dict) and t == item), None)
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
            _merge_list_items(target_value, value)
        elif isinstance(target_value, dict) and isinstance(value, dict):
            _merge_chunk_data(target_value, value)
        elif isinstance(target_value, str) and isinstance(value, str):
            # Prefer the longer text to keep additional context
            if len(value.strip()) > len(target_value.strip()):
                target[key] = value
        else:
            target[key] = value

def consolidate_chunks_data(chunk_responses: list, document_name: str, extraction_model: type[BaseModel]):
    """Consolida los document_annotation de todos los chunks y crea una instancia del modelo Pydantic."""
    try:
        if not chunk_responses:
            logger.warning(f"No chunks to process for {document_name}")
            return None
        
        # Consolidar todos los datos de los chunks
        all_chunk_data = {}
        
        for i, response in enumerate(chunk_responses):
            if not response:
                continue
                
            # Extraer document_annotation del chunk
            annotation_data = None
            if hasattr(response, 'document_annotation'):
                annotation_data = response.document_annotation
            elif isinstance(response, dict) and 'document_annotation' in response:
                annotation_data = response['document_annotation']
            
            if annotation_data:
                try:
                    # Convertir a dict si es necesario
                    if isinstance(annotation_data, str):
                        chunk_data = json.loads(annotation_data)
                    elif isinstance(annotation_data, dict):
                        chunk_data = annotation_data
                    else:
                        chunk_data = json.loads(str(annotation_data))
                    
                    # Mergear datos del chunk con el consolidado
                    _merge_chunk_data(all_chunk_data, chunk_data)
                    logger.debug(f"Merged chunk {i+1} data")
                    
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Error parsing chunk {i+1} annotation: {e}")
        
        # Crear instancia del modelo Pydantic con los datos consolidados
        if all_chunk_data and extraction_model:
            try:
                model_instance = extraction_model(**all_chunk_data)
                logger.info(f"Created {extraction_model.__name__} instance for {document_name}")
                return model_instance
            except Exception as e:
                logger.error(f"Error creating model instance for {document_name}: {e}")
                # Fallback: retornar los datos raw
                return all_chunk_data
        
        logger.warning(f"No valid data to create model instance for {document_name}")
        return None
        
    except Exception as e:
        logger.error(f"Error consolidating chunks for {document_name}: {e}")
        return None

def _get_summary_object(model_instance: Union[BaseModel, Dict[str, Any], None], structured_extraction_prompt: str, document_type: Literal["change_control", "side_by_side", "reference_methods"]) -> Summary:
    """Get the summary text from the model instance or raw dict."""
    
    extracted_content: Dict[str, Any] = model_instance.model_dump()

    if document_type == "change_control":
        relevant_context = model_instance.descripcion_cambio
        try:
            if not relevant_context:
                raise ValueError("No se extrajeron datos del documento.")

            structured_model = structured_extraction_model.with_structured_output(ChangeControlStrOutput)

            summary_and_filename = structured_model.invoke([
                HumanMessage(
                    content=structured_extraction_prompt.format(
                        metadata_content=relevant_context
                    )
                )
            ])

            return summary_and_filename
        except Exception as exc:
            logger.warning("Fallo al generar resumen estructurado: %s", exc)
            serialized = json.dumps(extracted_content, ensure_ascii=False, default=str)
            return ChangeControlStrOutput(
                filename="No se extrajeron datos del documento.json",
                summary=serialized[:1000] + "..." if len(serialized) > 1000 else serialized,
                lista_cambios=[]  # Usa la lista de STRINGS
            )
    
    elif document_type == "side_by_side":
        return model_instance.metodo_modificacion_propuesta.model_dump()

    elif document_type == "reference_methods":
        return model_instance.pruebas.model_dump()

def _model_instance_to_dict(model_instance: Union[BaseModel, Dict[str, Any], None]) -> Dict[str, Any]:
    """Serialize the consolidated model output so it can be stored as JSON."""
    if model_instance is None:
        return {}

    if isinstance(model_instance, BaseModel):
        return model_instance.model_dump()

    if isinstance(model_instance, dict):
        return model_instance

    if isinstance(model_instance, str):
        try:
            return json.loads(model_instance)
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return {"data": model_instance}

    return {"data": json.loads(str(model_instance)) if isinstance(model_instance, str) else str(model_instance)}

@tool(description=EXTRACT_STRUCTURED_DATA_PROMPT_TOOL_DESC)
def extract_annex_cc(
    dir_document: str, 
    document_type: Literal["change_control", "side_by_side", "reference_methods"],
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    # Filename
    document_name = filenames[document_type]

    # Extraction Model
    extraction_model = extraction_models[document_type]

    # Prompt
    structured_extraction_prompt = structured_extraction_prompts[document_type]
    
    # Document Processing
    try:
        with _prepare_pdf_document(dir_document) as pdf_document_path:
            chunk_responses = process_document(pdf_path=pdf_document_path, extraction_model=extraction_model, max_pages_per_chunk=8)
    except Exception as exc:
        logger.error(f"Error procesando el documento {document_name}: {exc}")
        raise

    # Consolidate Chunks
    model_instance = consolidate_chunks_data(chunk_responses, document_name, extraction_model)

    logger.info(f"Completed processing {document_name}")

    # 1. Llama a la nueva función que devuelve el objeto Summary
    summary_object = _get_summary_object(model_instance, structured_extraction_prompt, document_type)

    # 2. Prepara el estado 'files'
    files = state.get("files", {})

    # 3. Guarda el JSON gigante en formato estructurado y string para herramientas de lectura
    if model_instance:
        serialized_data = _model_instance_to_dict(model_instance)
        full_json_string = json.dumps(serialized_data, indent=2, ensure_ascii=False)
        files[document_name] = {
            "content": full_json_string,
            "data": serialized_data,
        }
    else:
        files[document_name] = {
            "content": "{}",
            "data": {},
        }  # Guarda un JSON vacío si falla
    
    return Command(
        update={
            "files": files, # Esto ahora guarda AMBOS archivos en el estado
            "messages": [
                # Devuelve solo el resumen legible por humanos al LLM
                ToolMessage(f"Documento {document_name} procesado exitosamente.", tool_call_id=tool_call_id)
            ],
        }
    )
