"""Le singole fasi della pipeline.

Ogni funzione è una fase. La convenzione:
- fasi [codice] sono deterministiche e non toccano l'LLM;
- fasi [LLM] usano il client ma hanno SEMPRE un fallback deterministico e un guardrail
  (contatore/soglia/tetto) così non possono andare in loop o fallire in modo fatale.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import prompts
from ..llm import OllamaClient
from ..models import Author, Paper, ThematicCluster, ThematicMap
from ..ranking import (
    aggregate_authors,
    score_papers,
    split_foundational_frontier,
)
from ..sources.openalex import OpenAlexClient


# =========================================================================
# Fase 1 — Espansione query  [LLM + guardrail]
# =========================================================================
def expand_query(
    llm: OllamaClient, topic: str, language: str, max_terms: int
) -> List[str]:
    fallback = [topic]

    def _valid(x: Any) -> bool:
        return isinstance(x, list) and all(isinstance(i, str) for i in x)

    result = llm.generate_json(
        prompts.expand_query(topic, language),
        system=prompts.SYSTEM,
        fallback=fallback,
        validator=_valid,
    )
    terms = result if isinstance(result, list) else fallback

    # Guardrail deterministico: normalizza, dedup, includi sempre l'originale, tetto.
    cleaned: List[str] = []
    seen = set()
    for t in [topic] + terms:
        if not isinstance(t, str):
            continue
        t = t.strip()
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            cleaned.append(t)
    return cleaned[:max_terms]


# =========================================================================
# Fase 2 — Recupero  [codice, deterministico]
# =========================================================================
def retrieve(
    oa: OpenAlexClient, queries: List[str], per_query: int
) -> List[Paper]:
    by_id: Dict[str, Paper] = {}
    for q in queries:
        for p in oa.search_works(q, limit=per_query):
            existing = by_id.get(p.id)
            if existing is None:
                by_id[p.id] = p
            else:
                # dedup: tieni la copia col source_query più informativo
                if not existing.source_query:
                    existing.source_query = p.source_query
    return list(by_id.values())


# =========================================================================
# Fase 3 — Valutazione copertura  [LLM + guardrail: max cicli]
# =========================================================================
def assess_and_maybe_broaden(
    llm: OllamaClient,
    oa: OpenAlexClient,
    topic: str,
    papers: List[Paper],
    queries: List[str],
    per_query: int,
    max_cycles: int,
    max_terms: int,
) -> List[Paper]:
    """Guardrail chiave: al massimo `max_cycles` giri, poi si procede comunque.

    Il contatore è lato codice, NON a giudizio dell'LLM: è il punto più a rischio di
    loop infinito e va bloccato duramente.
    """
    cycles = 0
    while cycles < max_cycles:
        sample = [p.title for p in papers[:15]]
        verdict = llm.generate_json(
            prompts.assess_coverage(topic, len(papers), sample),
            system=prompts.SYSTEM,
            fallback={"verdict": "ok", "extra_terms": []},
        )
        v = (verdict or {}).get("verdict", "ok")
        extra = (verdict or {}).get("extra_terms", []) or []

        if v == "ok" or not extra:
            break

        # Aggiungi nuovi termini e recupera ancora (broaden). "narrow" lo trattiamo
        # come "ok" perché restringere lato query è rischioso: meglio ranking a valle.
        new_terms = [t for t in extra if isinstance(t, str) and t.strip()][:max_terms]
        if not new_terms:
            break
        added = retrieve(oa, new_terms, per_query)
        known = {p.id for p in papers}
        gained = [p for p in added if p.id not in known]
        papers.extend(gained)
        cycles += 1
        if not gained:  # nessun nuovo risultato: inutile insistere
            break
    return papers


# =========================================================================
# Fase 4 — Ranking  [codice, deterministico]
# =========================================================================
def rank(papers: List[Paper]) -> List[Paper]:
    ranked = score_papers(papers)
    split_foundational_frontier(ranked)
    return ranked


# =========================================================================
# Fase 5+7 — Loop iterativo Ricerca + Sintesi  [LLM + guardrail duri]
# =========================================================================
def research_and_synthesize(
    llm: OllamaClient,
    oa: OpenAlexClient,
    topic: str,
    ranked_papers: List[Paper],
    language: str,
    *,
    seed_papers: int,
    max_iterations: int,
    max_papers: int,
    snowball_depth: int,
    saturation_min_new: int,
    on_step: Optional[Any] = None,
) -> ThematicMap:
    """Il cuore del sistema: legge, aggiorna la mappa tematica, individua gap, segue
    citazioni mirate, ripete finché satura o esaurisce il budget.

    Guardrail (tutti lato codice, non negoziabili dall'LLM):
      - max_iterations: tetto sul numero di giri
      - max_papers: tetto totale di paper processati
      - snowball_depth: profondità massima nel grafo citazioni
      - saturation_min_new: se un giro aggiunge meno di N paper nuovi -> stop
      - la mappa tematica persiste tra i giri (stato strutturato, non testo libero)
    """
    tmap = ThematicMap()
    all_by_id: Dict[str, Paper] = {p.id: p for p in ranked_papers}
    processed: set = set()

    # Il primo batch: i seed top-ranked.
    batch = ranked_papers[:seed_papers]

    for iteration in range(max_iterations):
        # Batch effettivo: solo paper non ancora processati, entro il budget totale.
        batch = [p for p in batch if p.id not in processed]
        remaining = max_papers - len(processed)
        if remaining <= 0 or not batch:
            break
        batch = batch[:remaining]

        if on_step:
            on_step(iteration + 1, len(batch), len(processed))

        # --- [LLM] leggi + aggiorna mappa + trova cosa espandere ---
        result = llm.generate_json(
            prompts.synthesize_iteration(topic, tmap, batch, language),
            system=prompts.SYSTEM,
            fallback=None,
        )

        for p in batch:
            processed.add(p.id)
            tmap.covered_paper_ids.append(p.id)

        # --- [codice] integra il risultato nella mappa (con fallback robusto) ---
        expand_ids: List[str] = []
        saturated = False
        if isinstance(result, dict):
            _merge_into_map(tmap, result, valid_ids=set(all_by_id.keys()))
            expand_ids = [
                i for i in (result.get("expand_paper_ids") or [])
                if isinstance(i, str)
            ]
            saturated = bool(result.get("saturated"))
        else:
            # Fallback: se l'LLM ha fallito del tutto, registra almeno i titoli.
            _fallback_merge(tmap, batch)

        tmap.iteration = iteration + 1

        # --- Criterio di stop: LLM dice saturo E lo confermiamo col budget ---
        if saturated:
            break

        # --- [codice] Snowballing mirato: segui le citazioni dei paper scelti ---
        next_batch: List[Paper] = []
        current_depth = min(p.depth for p in batch) if batch else 0
        if current_depth < snowball_depth:
            new_papers = _snowball(oa, expand_ids, all_by_id, depth=current_depth + 1)
            # aggiorna il catalogo globale e prepara il prossimo batch
            for np_ in new_papers:
                if np_.id not in all_by_id:
                    all_by_id[np_.id] = np_
                    next_batch.append(np_)

        # Rank del nuovo batch così i più promettenti vengono letti prima.
        next_batch = score_papers(next_batch)

        # --- Guardrail saturazione: pochi nuovi paper => stop ---
        if len(next_batch) < saturation_min_new:
            break

        batch = next_batch

    return tmap


def _snowball(
    oa: OpenAlexClient,
    expand_ids: List[str],
    known: Dict[str, Paper],
    depth: int,
) -> List[Paper]:
    """Recupera i vicini nel grafo citazioni per i paper indicati dall'LLM.

    Per ogni paper: sia i lavori citati (referenced_works, uscenti) sia i lavori che lo
    citano (entranti). Deterministico: le chiamate API non sono decisioni dell'LLM.
    """
    found: Dict[str, Paper] = {}

    # Citazioni uscenti: id già presenti nei referenced_works dei paper scelti.
    outgoing_ids: List[str] = []
    for pid in expand_ids:
        seed = known.get(pid)
        if seed:
            outgoing_ids.extend(seed.referenced_works[:20])
    outgoing_ids = [i for i in outgoing_ids if i and i not in known]
    for p in oa.get_works_by_ids(list(dict.fromkeys(outgoing_ids))[:40]):
        p.depth = depth
        found[p.id] = p

    # Citazioni entranti: chi cita i paper scelti (i più citati).
    for pid in expand_ids[:5]:
        for p in oa.get_citing_works(pid, limit=15):
            if p.id not in known and p.id not in found:
                p.depth = depth
                found[p.id] = p

    return list(found.values())


def _merge_into_map(tmap: ThematicMap, result: Dict[str, Any], valid_ids: set) -> None:
    """Rimpiazza cluster/findings/gaps con la versione aggiornata dell'LLM.

    L'LLM riceve la mappa precedente e restituisce quella aggiornata: qui la
    sostituiamo, filtrando i paper_ids inesistenti (rete di sicurezza anti-invenzione).
    """
    clusters = result.get("clusters")
    if isinstance(clusters, list) and clusters:
        new_clusters = []
        for c in clusters:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            pids = [i for i in (c.get("paper_ids") or []) if i in valid_ids]
            new_clusters.append(
                ThematicCluster(
                    name=str(c["name"])[:120],
                    summary=str(c.get("summary", ""))[:500],
                    paper_ids=pids,
                )
            )
        if new_clusters:
            tmap.clusters = new_clusters

    findings = result.get("key_findings")
    if isinstance(findings, list) and findings:
        tmap.key_findings = [str(f)[:400] for f in findings if str(f).strip()][:20]

    gaps = result.get("open_gaps")
    if isinstance(gaps, list) and gaps:
        tmap.open_gaps = [str(g)[:400] for g in gaps if str(g).strip()][:20]


def _fallback_merge(tmap: ThematicMap, batch: List[Paper]) -> None:
    """Se l'LLM fallisce, non perdere il giro: registra i paper in un cluster grezzo."""
    generic = next((c for c in tmap.clusters if c.name == "Da rivedere"), None)
    if generic is None:
        generic = ThematicCluster(name="Da rivedere",
                                  summary="Paper recuperati ma non sintetizzati.")
        tmap.clusters.append(generic)
    generic.paper_ids.extend(p.id for p in batch)


# =========================================================================
# Fase 7b — Panoramica discorsiva  [LLM]
# =========================================================================
def write_overview(
    llm: OllamaClient, topic: str, tmap: ThematicMap, language: str
) -> str:
    text = llm.generate(
        prompts.final_overview(topic, tmap, language),
        system=prompts.SYSTEM,
    )
    if text and text.strip():
        return text.strip()
    # Fallback: costruisci una panoramica minima dai dati strutturati.
    parts = []
    if tmap.key_findings:
        parts.append("Cosa si sa: " + " ".join(tmap.key_findings))
    if tmap.open_gaps:
        parts.append("Lacune aperte: " + " ".join(tmap.open_gaps))
    return "\n\n".join(parts) or "(sintesi non disponibile)"


# =========================================================================
# Fase 8 — Auto-verifica  [LLM + rete di sicurezza deterministica]
# =========================================================================
def verify(
    llm: OllamaClient, overview: str, valid_ids: List[str]
) -> List[str]:
    result = llm.generate_json(
        prompts.verify_claims(overview, valid_ids),
        system=prompts.SYSTEM,
        fallback={"issues": [], "confidence": "media"},
    )
    issues = (result or {}).get("issues", []) or []
    notes = [str(i) for i in issues if str(i).strip()]
    conf = (result or {}).get("confidence", "media")
    if not notes:
        notes.append(f"Nessun problema evidente rilevato (confidenza: {conf}).")
    else:
        notes.insert(0, f"Confidenza complessiva della sintesi: {conf}.")
    return notes


# =========================================================================
# Autori — arricchimento opzionale  [codice + API]
# =========================================================================
def enrich_authors(
    oa: OpenAlexClient, authors: List[Author], top_n: int
) -> List[Author]:
    for a in authors[:top_n]:
        if not a.id:
            continue
        info = oa.enrich_author(a.id)
        if info:
            a.h_index = info.get("h_index")
            a.works_count = info.get("works_count")
            a.institution = info.get("institution", "")
    return authors
