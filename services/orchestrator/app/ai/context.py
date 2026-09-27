"""Assembles the system prompt from prompts.py text and a MemoryContext.

Only the context builder's escaped block is ever inserted; raw records never are.
Prompt wording lives in prompts.py.
"""

from app.ai.prompts import MEMORY_PREAMBLE, NO_MEMORY_NOTE, SYSTEM_PROMPT
from app.memory.context_builder import MemoryContext


def build_system_prompt(memory: MemoryContext) -> str:
    if not memory.included_ids:
        return f"{SYSTEM_PROMPT}\n\n{NO_MEMORY_NOTE}"
    return f"{SYSTEM_PROMPT}\n\n{MEMORY_PREAMBLE}\n\n{memory.text}"
