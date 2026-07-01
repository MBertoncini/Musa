"""La pipeline 'agente su binari': fasi fisse, autonomia LLM solo dove serve giudizio."""

from .orchestrator import Orchestrator, ProgressCallback

__all__ = ["Orchestrator", "ProgressCallback"]
