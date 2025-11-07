from src.prompts.sub_agent_prompts import *
from src.tools import *

legacy_migration_subagent = {
    "name": "legacy_migration_agent",
    "description": "Delega a este agente siempre que te entreguen un documento de método analítico legado. Este agente se encargará de ejecutar las herramientas requeridas para generar un json estructurado con el método analítico en el formato nuevo",
    "system_prompt": LEGACY_MIGRATION_AGENT_INSTRUCTIONS,
    "tools": [extract_legacy_sections, structure_specs_procs, consolidar_pruebas_procesadas],
    "model": "openai:gpt-5-mini"
}

change_control_subagent = {
    "name": "change_control_agent",
    "description": "Delega a este agente siempre que te entreguen un documento de control de cambios. Este agente se encargará de ejecutar las herramientas requeridas para generar un json estructurado con el método analítico en el formato nuevo",
    "system_prompt": CHANGE_CONTROL_AGENT_INSTRUCTIONS,
    "tools": [extract_annex_cc],
    "model": "openai:gpt-5-mini"
}

side_by_side_subagent = {
    "name": "side_by_side_agent",
    "description": "Delega a este agente siempre que te entreguen un documento de side by side. Este agente se encargará de ejecutar las herramientas requeridas para generar un json estructurado con el método analítico en el formato nuevo",
    "system_prompt": SIDE_BY_SIDE_AGENT_INSTRUCTIONS,
    "tools": [extract_annex_cc],
    "model": "openai:gpt-5-mini"
}

reference_methods_subagent = {
    "name": "reference_methods_agent",
    "description": "Delega a este agente siempre que te entreguen uno o varios documentos de métodos analíticos de referencia. Este agente se encargará de ejecutar las herramientas requeridas para generar un json estructurado con el método analítico en el formato nuevo",
    "system_prompt": REFERENCE_METHODS_AGENT_INSTRUCTIONS,
    "tools": [extract_annex_cc],
    "model": "openai:gpt-5-mini"
}
