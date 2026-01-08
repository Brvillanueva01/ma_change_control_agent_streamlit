import warnings

# Silenciar warnings de Pydantic sobre NotRequired y FileData de deepagents
warnings.filterwarnings(
    "ignore",
    message=".*NotRequired.*",
    category=UserWarning,
    module="pydantic.*"
)

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Dict, Optional, Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC
from src.prompts.tool_llm_calls_prompts import TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT, TEST_SOLUTION_STRUCTURED_EXTRACTION_HUMAN_PROMPT
from src.models.structured_test_model import TestSolutions

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3

DEFAULT_BASE_PATH = "/actual_method"

# Mapeo de base_path a carpeta temporal correspondiente
TEMP_DIR_MAPPING = {
    "/actual_method": "/temp_actual_method",
    "/proposed_method": "/temp_proposed_method",
}


# LLM para Herramientas
llm_model = init_chat_model(model="openai:gpt-5-mini")


@retry(
    stop=stop_after_attempt(MAX_LLM_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.RemoteProtocolError, httpx.ReadTimeout, ConnectionError)),
    reraise=True,
)
def _invoke_structured_llm(structured_model, messages):
    """Invoca el LLM con retry automático para errores de conexión."""
    logger.debug("Invocando LLM para extracción estructurada...")
    return structured_model.invoke(messages)

def _get_temp_dir(base_path: str) -> str:
    """Obtiene la carpeta temporal correspondiente al base_path."""
    base = (base_path or DEFAULT_BASE_PATH).rstrip("/")
    return TEMP_DIR_MAPPING.get(base, f"/temp{base}")


def _extract_source_file_name(path: str) -> str:
    """Extrae el nombre del archivo fuente de una ruta de markdown.
    
    Ejemplo: '/actual_method/test_solution_markdown_MA 100000346.json' -> 'MA 100000346'
    """
    import re
    # Buscar patrón test_solution_markdown_{nombre}.json
    match = re.search(r'test_solution_markdown_(.+)\.json$', path)
    if match:
        return match.group(1)
    # Fallback: usar el nombre del archivo sin extensión
    filename = path.rsplit('/', 1)[-1]
    return filename.rsplit('.', 1)[0]


@tool(description=TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC)
def test_solution_structured_extraction(
    id: int,
    source_file_name: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    base_path: str = DEFAULT_BASE_PATH,
) -> Command:
    """
    Extrae y estructura una prueba/solución individual del markdown.
    
    Args:
        id: Índice de la prueba en el archivo markdown
        source_file_name: Nombre del archivo de origen (sin extensión)
        base_path: Ruta base (/actual_method o /proposed_method)
    """
    base = (base_path or DEFAULT_BASE_PATH).rstrip("/")
    temp_dir = _get_temp_dir(base_path)
    markdown_doc = f"{base}/test_solution_markdown_{source_file_name}.json"

    files = dict(state.get("files", {}))
    test_solution_markdown = files.get(markdown_doc)
    if not test_solution_markdown:
        message = f"No se encontró el archivo de markdown: {markdown_doc}"
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )
    
    test_solution_markdown_data = test_solution_markdown.get("data") or {}
    if not test_solution_markdown_data:
        message = f"El archivo {markdown_doc} no contiene datos válidos."
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    items = test_solution_markdown_data.get("items") or []
    target_item: Optional[Dict[str, Any]] = None

    if isinstance(items, list):
        target_item = next(
            (
                item
                for item in items
                if isinstance(item, dict) and item.get("id") == id
            ),
            None,
        )
        if target_item is None and 0 <= id < len(items):
            candidate = items[id]
            if isinstance(candidate, dict):
                target_item = candidate
    elif isinstance(items, dict):
        target_item = items.get(id) or items.get(str(id))

    if not target_item:
        message = (
            "No se encontró el markdown asociado a la prueba/solución con id "
            f"{id}."
        )
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    test_solution_string = json.dumps(target_item, indent=2, ensure_ascii=False)
    
    structured_model = llm_model.with_structured_output(TestSolutions)
    messages = [
        SystemMessage(
            content=TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT
        ),
        HumanMessage(
            content=TEST_SOLUTION_STRUCTURED_EXTRACTION_HUMAN_PROMPT.format(
                test_solution_string=test_solution_string
            )
        )
    ]
    
    # Usar función con retry para manejar errores de conexión
    test_solution_input = _invoke_structured_llm(structured_model, messages)
    test_solution_input = test_solution_input.model_dump()

    # Validación: asegurar que solo haya un test (el LLM a veces duplica)
    if "tests" in test_solution_input and isinstance(test_solution_input["tests"], list):
        if len(test_solution_input["tests"]) > 1:
            logger.warning(
                f"LLM generó {len(test_solution_input['tests'])} tests, tomando solo el primero."
            )
            test_solution_input["tests"] = [test_solution_input["tests"][0]]

    test_solution_input["source_id"] = id
    test_solution_input["source_file_name"] = source_file_name
    
    # Guardar en carpeta temporal: /temp_{base_path}/{source_file_name}/{id}.json
    structured_file_path = f"{temp_dir}/{source_file_name}/{id}.json"

    content_str = json.dumps(test_solution_input, indent=2, ensure_ascii=False)
    files[structured_file_path] = {
        "content": content_str.split("\n"),
        "data": test_solution_input,
        "modified_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_message = (
        f"Generé la solución de prueba estructurada para '{source_file_name}' id={id}. "
        f"Archivo temporal: {structured_file_path}"
    )
    logger.info(summary_message)

    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(summary_message, tool_call_id=tool_call_id)
            ],
        }
    )
