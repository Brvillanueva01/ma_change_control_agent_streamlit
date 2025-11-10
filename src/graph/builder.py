from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from src.tools import *
from src.agents.sub_agents_config import *
from src.prompts.supervisor_prompts import *

# Create agent using create_react_agent directly
llm_model = init_chat_model(model="openai:gpt-4.1-mini", temperature=0.0)


sub_agents = [
    legacy_migration_subagent,
    change_control_subagent,
    side_by_side_subagent,
    reference_methods_subagent,
    change_implementation_agent
]

am_change_control_agent = create_deep_agent(
    #tools=[extract_legacy_sections,structure_specs_procs],
    system_prompt=INSTRUCTIONS_SUPERVISOR,
    subagents=sub_agents,
    model=llm_model#"openai:gpt-4.1-mini"
)
