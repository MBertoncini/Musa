"""L'orchestratore: l'agente su binari.

Garantisce l'ORDINE delle fasi (codice), mentre dentro alcune fasi l'LLM ha autonomia
decisionale. Emette callback di progresso così CLI e UI possono mostrare l'avanzamento.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Callable, Optional

from ..cache import Cache
from ..config import Config
from ..llm import OllamaClient
from ..models import Dossier
from ..ranking import RANKING_CRITERIA_TEXT, aggregate_authors
from ..sources.openalex import OpenAlexClient
from . import phases

# callback(fase: str, messaggio: str) -> None
ProgressCallback = Callable[[str, str], None]


def _noop(_phase: str, _msg: str) -> None:
    pass


class Orchestrator:
    def __init__(self, config: Config, progress: Optional[ProgressCallback] = None):
        self.cfg = config
        self.progress = progress or _noop
        self.cache = Cache(config.cache["dir"], config.cache["ttl_days"])
        self.llm = OllamaClient(
            host=config.llm["host"],
            model=config.llm["model"],
            temperature=config.llm["temperature"],
            timeout=config.llm["timeout"],
        )
        self.oa = OpenAlexClient(
            cache=self.cache,
            mailto=config.openalex["mailto"],
            per_page=config.openalex["per_page"],
            max_retries=config.openalex["max_retries"],
            api_key=config.openalex.get("api_key", ""),
        )

    def preflight(self) -> Optional[str]:
        """Controlli prima di partire. Restituisce un messaggio d'errore o None."""
        if not self.llm.ping():
            return (
                f"Ollama non raggiungibile su {self.cfg.llm['host']}. "
                "Avvia Ollama (ollama serve) e verifica l'host in config.yaml."
            )
        models = self.llm.available_models()
        want = self.cfg.llm["model"]
        # confronto tollerante a suffisso :latest
        if models and want not in models and f"{want}:latest" not in models \
                and not any(m.startswith(want + ":") for m in models):
            return (
                f"Il modello '{want}' non è tra quelli disponibili in Ollama: {models}. "
                f"Scaricalo con 'ollama pull {want}' o cambia modello in config.yaml."
            )
        return None

    def run(
        self,
        topic: str,
        *,
        verify: bool = True,
        fresh: bool = False,
    ) -> Dossier:
        cfg_p = self.cfg.pipeline
        lang = self.cfg.output["language"]
        started = time.time()

        if fresh:
            self.cache.clear_http()

        session_id = uuid.uuid4().hex[:12]
        dossier = Dossier(
            topic=topic,
            session_id=session_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            ranking_criteria=RANKING_CRITERIA_TEXT,
        )

        # --- Fase 1: espansione query [LLM] ---
        self.progress("1/8", "Espansione della query…")
        queries = phases.expand_query(
            self.llm, topic, lang, cfg_p["max_expanded_queries"]
        )
        dossier.expanded_queries = queries
        self.progress("1/8", f"{len(queries)} termini: {', '.join(queries[:6])}…")

        # --- Fase 2: recupero [codice] ---
        self.progress("2/8", "Recupero da OpenAlex…")
        per_query = max(20, self.cfg.openalex["per_page"])
        papers = phases.retrieve(self.oa, queries, per_query)
        self.progress("2/8", f"{len(papers)} paper unici recuperati.")

        if not papers:
            if self.oa.search_blocked:
                msg = (
                    "OpenAlex sta rate-limitando le ricerche anonime (heavy load). "
                    "Ottieni una API key gratuita su https://openalex.org/rest-api e "
                    "impostala in config.yaml (openalex.api_key) o nella variabile "
                    "d'ambiente OPENALEX_API_KEY, poi riprova."
                )
            else:
                msg = "Nessun paper trovato. Prova un argomento diverso o più ampio."
            self.progress("!", msg)
            dossier.overview = msg
            self._finalize_stats(dossier, started, 0)
            return dossier

        # --- Fase 3: copertura [LLM + guardrail max cicli] ---
        self.progress("3/8", "Valutazione copertura…")
        papers = phases.assess_and_maybe_broaden(
            self.llm, self.oa, topic, papers, queries, per_query,
            max_cycles=cfg_p["max_coverage_cycles"],
            max_terms=cfg_p["max_expanded_queries"],
        )
        self.progress("3/8", f"{len(papers)} paper dopo raffinamento.")

        # --- Fase 4: ranking [codice] ---
        self.progress("4/8", "Ranking di paper e autori…")
        papers = phases.rank(papers)
        dossier.papers = papers

        # --- Fase 5+7: loop ricerca + sintesi [LLM + guardrail] ---
        self.progress("5/8", "Loop ricerca+sintesi (lettura e snowballing)…")

        def _on_step(it: int, batch: int, done: int) -> None:
            self.progress("5/8", f"Iterazione {it}: leggo {batch} paper "
                                 f"({done} già letti)…")

        tmap = phases.research_and_synthesize(
            self.llm, self.oa, topic, papers, lang,
            seed_papers=cfg_p["seed_papers"],
            max_iterations=cfg_p["max_iterations"],
            max_papers=cfg_p["max_papers"],
            snowball_depth=cfg_p["snowball_depth"],
            saturation_min_new=cfg_p["saturation_min_new"],
            on_step=_on_step,
        )
        dossier.thematic_map = tmap

        # Ri-ranking finale: il loop può aver aggiunto paper via snowballing.
        # Ricostruiamo la lista completa dal catalogo esteso.
        dossier.papers = phases.rank(dossier.papers)
        dossier.foundational = [p for p in dossier.papers if p.category == "foundational"]
        dossier.frontier = [p for p in dossier.papers if p.category == "frontier"]

        # --- Autori [codice + arricchimento API] ---
        self.progress("6/8", "Aggregazione e arricchimento autori…")
        authors = aggregate_authors(dossier.papers)
        authors = phases.enrich_authors(self.oa, authors, cfg_p["enrich_top_authors"])
        dossier.authors = authors

        # --- Panoramica discorsiva [LLM] ---
        self.progress("7/8", "Scrittura della panoramica…")
        dossier.overview = phases.write_overview(self.llm, topic, tmap, lang)

        # --- Fase 8: auto-verifica [LLM + rete deterministica] ---
        if verify:
            self.progress("8/8", "Auto-verifica dei claim…")
            valid_ids = [p.id for p in dossier.papers]
            dossier.verification_notes = phases.verify(
                self.llm, dossier.overview, valid_ids
            )
        else:
            dossier.verification_notes = ["Auto-verifica saltata (--no-verify)."]

        self._finalize_stats(dossier, started, len(dossier.papers))

        # Log di sessione per debug/riuso.
        try:
            self.cache.save_session(session_id, topic, {
                "queries": queries,
                "n_papers": len(dossier.papers),
                "map": tmap.to_dict(),
            })
        except Exception:
            pass

        self.progress("ok", f"Dossier pronto ({dossier.stats['elapsed_s']}s).")
        return dossier

    def _finalize_stats(self, dossier: Dossier, started: float, n: int) -> None:
        dossier.stats = {
            "elapsed_s": round(time.time() - started, 1),
            "n_papers": n,
            "n_authors": len(dossier.authors),
            "n_clusters": len(dossier.thematic_map.clusters),
            "iterations": dossier.thematic_map.iteration,
            "model": self.cfg.llm["model"],
        }

    def close(self) -> None:
        self.cache.close()
