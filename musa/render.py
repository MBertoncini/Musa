"""Fase 9 — Composizione del dossier in Markdown.

Deterministico al 100%: template fisso, bibliografia costruita dai metadati reali.
"""
from __future__ import annotations

from typing import List

from .models import Author, Dossier, Paper


def _paper_line(p: Paper) -> str:
    authors = ", ".join(p.authors[:3])
    if len(p.authors) > 3:
        authors += " et al."
    bits = [f"**{p.title}**"]
    meta = []
    if authors:
        meta.append(authors)
    if p.year:
        meta.append(str(p.year))
    if p.venue:
        meta.append(f"*{p.venue}*")
    if meta:
        bits.append(" — " + ", ".join(meta))
    tail = [f"citazioni: {p.cited_by_count}"]
    if p.fwci is not None:
        tail.append(f"FWCI: {p.fwci:.2f}")
    tail.append(f"score: {p.score:.2f}")
    link = p.open_access_url or (f"https://doi.org/{p.doi}" if p.doi else p.url)
    line = f"- {' '.join(bits)}  \n  <sub>{' · '.join(tail)}"
    if link:
        line += f" · [link]({link})"
    line += "</sub>"
    return line


def _author_line(a: Author, rank: int) -> str:
    meta = [f"{a.paper_count} paper sul tema", f"{a.total_citations} citazioni (nel set)"]
    if a.h_index is not None:
        meta.append(f"h-index: {a.h_index}")
    if a.recent_papers:
        meta.append(f"{a.recent_papers} recenti")
    line = f"{rank}. **{a.name}**"
    if a.institution:
        line += f" — {a.institution}"
    line += f"  \n   <sub>{' · '.join(meta)}</sub>"
    return line


def render_markdown(d: Dossier) -> str:
    lines: List[str] = []
    A = lines.append

    A(f"# Dossier di letteratura — {d.topic}\n")
    A(f"*Generato da Musa il {d.created_at} · sessione `{d.session_id}` · "
      f"modello `{d.stats.get('model', '?')}`*\n")

    # Indice
    A("## Indice\n")
    A("1. [Panoramica](#panoramica)")
    A("2. [Paper fondamentali](#paper-fondamentali)")
    A("3. [Frontiera recente](#frontiera-recente)")
    A("4. [Autori di riferimento](#autori-di-riferimento)")
    A("5. [Mappa tematica](#mappa-tematica)")
    A("6. [Lacune e domande aperte](#lacune-e-domande-aperte)")
    A("7. [Note di verifica](#note-di-verifica)")
    A("8. [Metodo e limiti](#metodo-e-limiti)\n")

    # Panoramica
    A("## Panoramica\n")
    A(d.overview or "_(non disponibile)_")
    A("")

    # Fondamentali
    A("## Paper fondamentali\n")
    A("_Alto impatto assoluto, tipicamente i classici del campo._\n")
    found = d.foundational or [p for p in d.papers if p.category == "foundational"]
    if found:
        for p in found[:15]:
            A(_paper_line(p))
    else:
        A("_Nessun paper classificato come fondamentale._")
    A("")

    # Frontiera
    A("## Frontiera recente\n")
    A("_Lavori recenti ad alto impatto normalizzato: dove si muove il campo ora._\n")
    frontier = d.frontier or [p for p in d.papers if p.category == "frontier"]
    if frontier:
        for p in frontier[:15]:
            A(_paper_line(p))
    else:
        A("_Nessun paper recente in evidenza._")
    A("")

    # Autori
    A("## Autori di riferimento\n")
    if d.authors:
        for i, a in enumerate(d.authors[:15], start=1):
            A(_author_line(a, i))
    else:
        A("_Nessun autore aggregato._")
    A("")

    # Mappa tematica
    A("## Mappa tematica\n")
    tmap = d.thematic_map
    if tmap.clusters:
        for c in tmap.clusters:
            A(f"### {c.name}\n")
            A(c.summary or "_(nessuna sintesi)_")
            if c.paper_ids:
                refs = _resolve_refs(c.paper_ids, d.papers)
                if refs:
                    A("\nPaper: " + "; ".join(refs))
            A("")
    else:
        A("_Nessun cluster tematico prodotto._\n")

    if tmap.key_findings:
        A("### Cosa si sa (punti chiave)\n")
        for k in tmap.key_findings:
            A(f"- {k}")
        A("")

    # Lacune
    A("## Lacune e domande aperte\n")
    if tmap.open_gaps:
        for g in tmap.open_gaps:
            A(f"- {g}")
    else:
        A("_Nessuna lacuna esplicita individuata._")
    A("")

    # Verifica
    A("## Note di verifica\n")
    if d.verification_notes:
        for n in d.verification_notes:
            A(f"- {n}")
    else:
        A("_Verifica non eseguita._")
    A("")

    # Metodo
    A("## Metodo e limiti\n")
    A(f"**Termini di ricerca usati:** {', '.join(d.expanded_queries)}\n")
    A(f"**Criterio di ranking:** {d.ranking_criteria}\n")
    A(f"**Statistiche:** {d.stats.get('n_papers', 0)} paper analizzati, "
      f"{d.stats.get('n_authors', 0)} autori, "
      f"{d.stats.get('iterations', 0)} iterazioni di sintesi, "
      f"tempo {d.stats.get('elapsed_s', '?')}s.\n")
    A("**Limiti:** le metriche di citazione (conteggi, FWCI, h-index) hanno bias noti "
      "(effetto Matteo, penalizzazione dei lavori recenti, differenze tra campi) e "
      "vanno lette come indizi, non come verità. La sintesi è prodotta da un modello "
      "locale sugli abstract e può contenere imprecisioni: verifica sempre le fonti "
      "primarie prima di citare.\n")

    return "\n".join(lines)


def _resolve_refs(paper_ids: List[str], papers: List[Paper]) -> List[str]:
    index = {p.id: p for p in papers}
    out = []
    for pid in paper_ids[:8]:
        p = index.get(pid)
        if p:
            first = p.authors[0].split()[-1] if p.authors else "?"
            out.append(f"{first} {p.year or ''}".strip())
    return out
