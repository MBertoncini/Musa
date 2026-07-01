"""Client Ollama con parsing JSON robusto e fallback.

Filosofia: i modelli locali piccoli sbagliano spesso il JSON. Questo modulo *non* si
fida mai ciecamente dell'output: prova il parsing diretto, poi l'estrazione del primo
blocco {...}/[...], e in ultima istanza restituisce un fallback fornito dal chiamante.
Così la pipeline non si rompe mai per colpa di una risposta malformata.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

import requests


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "gemma:2b",
        temperature: float = 0.2,
        timeout: int = 180,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    # --- Verifica disponibilità ------------------------------------------
    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def available_models(self) -> List[str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    # --- Generazione grezza ----------------------------------------------
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """Chiamata singola a /api/generate. Restituisce il testo grezzo."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        try:
            r = requests.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Chiamata a Ollama fallita: {exc}") from exc
        return r.json().get("response", "")

    # --- Generazione con output JSON validato ----------------------------
    def generate_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        fallback: Any = None,
        validator: Optional[Callable[[Any], bool]] = None,
        retries: int = 1,
    ) -> Any:
        """Come generate() ma garantisce un valore JSON parsato.

        Prova più volte; se tutto fallisce restituisce `fallback`. Se `validator` è
        dato, un risultato che non lo supera è trattato come fallimento.
        """
        last_raw = ""
        for attempt in range(retries + 1):
            try:
                raw = self.generate(prompt, system=system, json_mode=True)
            except LLMError:
                continue
            last_raw = raw
            parsed = _extract_json(raw)
            if parsed is not None:
                if validator is None or _safe_validate(validator, parsed):
                    return parsed
            # Al retry, rafforza l'istruzione
            prompt = (
                prompt
                + "\n\nATTENZIONE: rispondi con SOLO JSON valido, niente altro testo."
            )
        _log_bad_json(last_raw)
        return fallback


# --- Utilità di parsing ---------------------------------------------------
def _extract_json(text: str) -> Any:
    """Estrae un valore JSON da un testo che può contenere spazzatura attorno."""
    if not text:
        return None
    text = text.strip()
    # 1) parsing diretto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) rimuovi eventuali fences ```json ... ```
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass
    # 3) primo blocco bilanciato { ... } o [ ... ]
    block = _first_balanced(text)
    if block:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return None
    return None


def _first_balanced(text: str) -> Optional[str]:
    """Trova il primo oggetto/array JSON bilanciato nel testo."""
    start = None
    opener = None
    depth = 0
    for i, ch in enumerate(text):
        if start is None and ch in "{[":
            start = i
            opener = ch
            closer = "}" if ch == "{" else "]"
            depth = 1
            continue
        if start is not None:
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _safe_validate(validator: Callable[[Any], bool], value: Any) -> bool:
    try:
        return bool(validator(value))
    except Exception:
        return False


def _log_bad_json(raw: str) -> None:
    # Silenzioso di default; utile abilitarlo in debug.
    import os

    if os.environ.get("MUSA_DEBUG"):
        snippet = (raw or "")[:400].replace("\n", " ")
        print(f"[llm] JSON non parsabile, uso fallback. Grezzo: {snippet!r}")
