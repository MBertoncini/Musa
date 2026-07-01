"""Caricamento e validazione della configurazione.

I default vivono qui, così il sistema funziona anche senza `config.yaml`. Un eventuale
`config.yaml` (o percorso passato esplicitamente) fa da override selettivo.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover
    yaml = None


DEFAULTS: Dict[str, Any] = {
    "llm": {
        "host": "http://localhost:11434",
        "model": "gemma:2b",
        "temperature": 0.2,
        "timeout": 180,
    },
    "openalex": {
        "mailto": "",
        "api_key": "",          # chiave gratuita: https://openalex.org/rest-api
        "per_page": 50,
        "max_retries": 3,
    },
    "cache": {
        "dir": ".musa_cache",
        "ttl_days": 30,
    },
    "pipeline": {
        "max_expanded_queries": 8,
        "max_coverage_cycles": 2,
        "seed_papers": 40,
        "max_papers": 120,
        "max_iterations": 4,
        "snowball_depth": 2,
        "saturation_min_new": 2,
        "deep_read_top": 12,
        "enrich_top_authors": 15,
    },
    "output": {
        "dir": "dossier",
        "language": "it",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Fonde `override` dentro `base` in modo ricorsivo (non muta gli input)."""
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


@dataclass
class Config:
    llm: Dict[str, Any] = field(default_factory=dict)
    openalex: Dict[str, Any] = field(default_factory=dict)
    cache: Dict[str, Any] = field(default_factory=dict)
    pipeline: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """Carica la config: default + eventuale file YAML.

        Se `path` è None cerca `config.yaml` nella cwd. Un file mancante non è un
        errore: si usano i default.
        """
        data = copy.deepcopy(DEFAULTS)
        candidate = path or "config.yaml"
        if os.path.isfile(candidate):
            if yaml is None:
                raise RuntimeError(
                    "PyYAML non installato ma è presente un config.yaml. "
                    "Esegui: pip install -r requirements.txt"
                )
            with open(candidate, "r", encoding="utf-8") as fh:
                user = yaml.safe_load(fh) or {}
            data = _deep_merge(data, user)

        # Override rapido da variabili d'ambiente (comodo per test/CI)
        if os.environ.get("MUSA_MODEL"):
            data["llm"]["model"] = os.environ["MUSA_MODEL"]
        if os.environ.get("MUSA_MAILTO"):
            data["openalex"]["mailto"] = os.environ["MUSA_MAILTO"]
        if os.environ.get("OPENALEX_API_KEY"):
            data["openalex"]["api_key"] = os.environ["OPENALEX_API_KEY"]

        return cls(**data)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "llm": self.llm,
            "openalex": self.openalex,
            "cache": self.cache,
            "pipeline": self.pipeline,
            "output": self.output,
        }
