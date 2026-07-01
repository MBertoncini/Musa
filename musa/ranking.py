"""Ranking deterministico di paper e autori.

Prende posizione esplicita su cosa significa "importante", perché è lì che un
ricercatore giudica lo strumento. Nessuna decisione dell'LLM: solo matematica,
tracciabile e loggata nel dossier per trasparenza.

Idea sui paper: il conteggio grezzo di citazioni è ingannevole (i lavori recenti sono
per forza poco citati; c'è l'effetto Matteo). Combiniamo:
  - impatto normalizzato per campo/anno (FWCI di OpenAlex quando c'è),
  - citazioni grezze smorzate logaritmicamente,
  - un fattore di recenza,
  - la "velocità" recente di citazione (momentum).
E separiamo due liste: FONDAMENTALI STORICI vs FRONTIERA RECENTE.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List

from .models import Author, Paper

CURRENT_YEAR = datetime.now().year

# Testo bilingue: il criterio finisce nel report, quindi segue la lingua scelta.
RANKING_CRITERIA_TEXT = {
    "it": (
        "Score = 0.45·impatto_normalizzato(FWCI o citazioni/anno) "
        "+ 0.30·log(citazioni grezze) + 0.15·recenza + 0.10·momentum recente. "
        "I paper sono poi divisi in 'fondamentali storici' (alto impatto assoluto, più "
        "datati) e 'frontiera recente' (ultimi ~4 anni, alto impatto normalizzato). "
        "Nota: tutte le metriche di citazione hanno bias noti e vanno lette come indizi."
    ),
    "en": (
        "Score = 0.45·normalized_impact(FWCI or citations/year) "
        "+ 0.30·log(raw citations) + 0.15·recency + 0.10·recent momentum. "
        "Papers are then split into 'historical foundational' (high absolute impact, "
        "older) and 'recent frontier' (last ~4 years, high normalized impact). "
        "Note: all citation metrics have known biases and should be read as hints."
    ),
}


def _norm(values: List[float]) -> Dict[int, float]:
    """Normalizzazione min-max su indici (robusta a liste costanti/vuote)."""
    if not values:
        return {}
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return {i: 0.5 for i in range(len(values))}
    return {i: (v - lo) / (hi - lo) for i, v in enumerate(values)}


def score_papers(papers: List[Paper]) -> List[Paper]:
    """Assegna `score` a ogni paper e li ordina in modo decrescente."""
    if not papers:
        return []

    raw_impact: List[float] = []
    raw_citations: List[float] = []
    raw_recency: List[float] = []
    raw_momentum: List[float] = []

    for p in papers:
        age = max(1, CURRENT_YEAR - (p.year or CURRENT_YEAR) + 1)
        # Impatto normalizzato: FWCI se disponibile, altrimenti citazioni/anno.
        # log1p comprime la coda pesante (FWCI/citazioni sono estremamente skewed):
        # senza, un singolo outlier appiattirebbe la normalizzazione di tutti gli altri.
        if p.fwci is not None:
            raw_impact.append(math.log1p(max(0.0, float(p.fwci))))
        else:
            raw_impact.append(math.log1p(p.cited_by_count / age))
        raw_citations.append(math.log1p(p.cited_by_count))
        # Recenza: 1.0 per quest'anno, decade dolcemente.
        raw_recency.append(1.0 / age)
        # Momentum: citazioni negli ultimi 3 anni.
        recent = sum(
            c for y, c in p.counts_by_year.items() if y >= CURRENT_YEAR - 3
        )
        raw_momentum.append(math.log1p(recent))

    n_impact = _norm(raw_impact)
    n_cit = _norm(raw_citations)
    n_rec = _norm(raw_recency)
    n_mom = _norm(raw_momentum)

    for i, p in enumerate(papers):
        p.score = (
            0.45 * n_impact.get(i, 0)
            + 0.30 * n_cit.get(i, 0)
            + 0.15 * n_rec.get(i, 0)
            + 0.10 * n_mom.get(i, 0)
        )

    papers.sort(key=lambda x: x.score, reverse=True)
    return papers


def split_foundational_frontier(
    papers: List[Paper], top_n: int = 10, frontier_years: int = 4
) -> None:
    """Etichetta i paper come 'foundational' o 'frontier' (muta in place).

    - Frontiera: pubblicati negli ultimi `frontier_years` anni, tra i più forti per
      impatto normalizzato.
    - Fondamentali: i più citati in assoluto, tipicamente più datati.
    """
    if not papers:
        return

    recent = [p for p in papers if (p.year or 0) >= CURRENT_YEAR - frontier_years]
    older = [p for p in papers if (p.year or 0) < CURRENT_YEAR - frontier_years]

    # Frontiera: tra i recenti, i top per score.
    for p in sorted(recent, key=lambda x: x.score, reverse=True)[:top_n]:
        p.category = "frontier"

    # Fondamentali: tra i più datati, i più citati in assoluto.
    for p in sorted(older, key=lambda x: x.cited_by_count, reverse=True)[:top_n]:
        p.category = "foundational"


def aggregate_authors(papers: List[Paper]) -> List[Author]:
    """Costruisce e ranka gli autori a partire dai paper del set.

    Oltre a citazioni totali, premia continuità e attività recente sul tema: un autore
    con più paper recenti forti sull'argomento specifico è spesso più rilevante di un
    big generico. h-index si aggiunge dopo (arricchimento opzionale via OpenAlex).
    """
    by_id: Dict[str, Author] = {}
    by_name: Dict[str, Author] = {}

    for p in papers:
        pairs = zip(
            p.author_ids or [""] * len(p.authors),
            p.authors,
        )
        for aid, name in pairs:
            key = aid or name
            if not key:
                continue
            author = by_id.get(aid) if aid else by_name.get(name)
            if author is None:
                author = Author(id=aid, name=name)
                if aid:
                    by_id[aid] = author
                by_name[name] = author
            elif aid and not author.id:
                # Backfill: l'autore era comparso prima senza id, ora ne ha uno valido.
                author.id = aid
                by_id[aid] = author
            author.paper_count += 1
            author.total_citations += p.cited_by_count
            author.weighted_score += p.score
            if (p.year or 0) >= CURRENT_YEAR - 5:
                author.recent_papers += 1
            if not author.top_paper or p.score > 0:
                # tieni come "top_paper" quello con score più alto visto finora
                if not author.top_paper:
                    author.top_paper = p.short()

    authors = list({a.id or a.name: a for a in by_name.values()}.values())

    # Score composito dell'autore: peso ai paper, alle citazioni e alla recenza.
    def author_score(a: Author) -> float:
        return (
            a.weighted_score
            + 0.5 * math.log1p(a.total_citations)
            + 0.3 * a.recent_papers
        )

    authors.sort(key=author_score, reverse=True)
    return authors
