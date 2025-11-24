import json
import logging
from typing import Annotated, Dict, Optional, Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from src.graph.state import DeepAgentState
from src.prompts.tool_description_prompts import TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC
from src.prompts.tool_llm_calls_prompts import TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT
from src.models.structured_test_model import TestSolutions

logger = logging.getLogger(__name__)

TEST_SOLUTION_MARKDOWN_DOC_NAME = "/actual_method/test_solution_markdown.json"
TEST_SOLUTION_STRUCTURED_DIR = "/actual_method/test_solution_structured"
TEST_SOLUTION_STRUCTURED_CONTENT = "/actual_method/test_solution_structured_content.json"


# LLM para Herramientas
llm_model = init_chat_model(model="openai:gpt-4o-mini", temperature=0)

@tool(description=TEST_SOLUTION_STRUCTURED_EXTRACTION_TOOL_DESC)
def test_solution_structured_extraction(
    id: int,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    
    files = dict(state.get("files", {}))
    test_solution_markdown = files.get(TEST_SOLUTION_MARKDOWN_DOC_NAME)
    if not test_solution_markdown:
        message = "No se encontró el archivo de markdown para la solución de prueba."
        logger.warning(message)
        return Command(
            update={
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )
    
    test_solution_markdown_data = test_solution_markdown.get("data") or {}
    if not test_solution_markdown_data:
        message = "No se encontró el archivo de markdown para la solución de prueba."
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
    test_solution_input = structured_model.invoke(
        [
            HumanMessage(
                content=TEST_SOLUTION_STRUCTURED_EXTRACTION_PROMPT.format(
                    test_solution_string=test_solution_string
                )
            )
        ]
    )
    test_solution_input = test_solution_input.model_dump()

    test_solution_input["source_id"] = id
    structured_file_path = f"{TEST_SOLUTION_STRUCTURED_DIR}/{id}.json"

    files[structured_file_path] = {
        "content": json.dumps(test_solution_input, indent=2, ensure_ascii=False),
        "data": test_solution_input,
    }

    summary_message = (
        "Generé la solución de prueba estructurada para el identificador: "
        f"{id}. Archivo: {structured_file_path}"
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
