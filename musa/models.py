"""Modelli dati del dominio.

Sono dataclass semplici e serializzabili. Il resto della pipeline lavora su questi
oggetti, mai su dizionari grezzi delle API (che restano confinati nel modulo sources).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Paper:
    """Un lavoro accademico normalizzato dalla fonte dati."""
    id: str                      # id stabile (es. OpenAlex ID o DOI)
    title: str
    abstract: str = ""
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)   # nomi visualizzati
    author_ids: List[str] = field(default_factory=list)
    venue: str = ""
    doi: str = ""
    url: str = ""
    cited_by_count: int = 0
    fwci: Optional[float] = None            # field-weighted citation impact
    counts_by_year: Dict[int, int] = field(default_factory=dict)
    referenced_works: List[str] = field(default_factory=list)  # id citati (uscenti)
    open_access_url: str = ""

    # Campi calcolati dalla pipeline
    score: float = 0.0
    category: str = ""           # "foundational" | "frontier" | ""
    source_query: str = ""       # quale termine espanso l'ha trovato
    depth: int = 0               # 0 = seed, >0 = trovato via snowballing

    def short(self) -> str:
        who = self.authors[0] if self.authors else "?"
        if len(self.authors) > 1:
            who += " et al."
        return f"{who} ({self.year or 's.d.'}) — {self.title}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Author:
    """Un autore aggregato a partire dai paper recuperati."""
    id: str
    name: str
    paper_count: int = 0            # quanti paper sul tema in questo dossier
    total_citations: int = 0        # somma citazioni dei suoi paper nel set
    weighted_score: float = 0.0     # somma degli score dei suoi paper
    recent_papers: int = 0          # paper negli ultimi ~5 anni nel set
    h_index: Optional[int] = None   # arricchito da OpenAlex (opzionale)
    works_count: Optional[int] = None
    institution: str = ""
    top_paper: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThematicCluster:
    """Un raggruppamento tematico emerso dalla sintesi."""
    name: str
    summary: str = ""
    paper_ids: List[str] = field(default_factory=list)


@dataclass
class ThematicMap:
    """Stato persistente della sintesi tra le iterazioni del loop 5+7.

    È il "cervello" del loop: sopravvive alle iterazioni così il modello locale non
    riparte da zero ogni giro. Salvato come stato STRUTTURATO, non testo libero.
    """
    clusters: List[ThematicCluster] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)     # "cosa si sa"
    open_gaps: List[str] = field(default_factory=list)        # lacune / controversie
    covered_paper_ids: List[str] = field(default_factory=list)
    iteration: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clusters": [asdict(c) for c in self.clusters],
            "key_findings": self.key_findings,
            "open_gaps": self.open_gaps,
            "covered_paper_ids": self.covered_paper_ids,
            "iteration": self.iteration,
        }

    def as_prompt_context(self) -> str:
        """Rende la mappa compatta per reiniettarla nel prompt dell'iterazione dopo."""
        lines = []
        if self.clusters:
            lines.append("CLUSTER TEMATICI FINORA:")
            for c in self.clusters:
                lines.append(f"- {c.name}: {c.summary}")
        if self.key_findings:
            lines.append("COSA SI SA FINORA:")
            for k in self.key_findings:
                lines.append(f"- {k}")
        if self.open_gaps:
            lines.append("LACUNE/DOMANDE APERTE FINORA:")
            for g in self.open_gaps:
                lines.append(f"- {g}")
        return "\n".join(lines) if lines else "(nessuna sintesi ancora)"


@dataclass
class Dossier:
    """Il prodotto finale, pronto per essere reso in Markdown."""
    topic: str
    session_id: str
    created_at: str
    expanded_queries: List[str] = field(default_factory=list)
    papers: List[Paper] = field(default_factory=list)        # rankati
    foundational: List[Paper] = field(default_factory=list)
    frontier: List[Paper] = field(default_factory=list)
    authors: List[Author] = field(default_factory=list)
    thematic_map: ThematicMap = field(default_factory=ThematicMap)
    overview: str = ""            # sintesi discorsiva "cosa si sa"
    verification_notes: List[str] = field(default_factory=list)
    ranking_criteria: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)
