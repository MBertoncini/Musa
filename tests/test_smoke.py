"""Test di smoke: verificano la logica deterministica senza rete né Ollama.

Esegui con:  python -m pytest -q   (oppure  python tests/test_smoke.py)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musa.config import Config
from musa.llm import _extract_json, _first_balanced
from musa.models import Dossier, Paper, ThematicMap
from musa.ranking import (
    aggregate_authors,
    score_papers,
    split_foundational_frontier,
)
from musa.render import render_markdown
from musa.sources.openalex import _reconstruct_abstract


def _sample_papers():
    return [
        Paper(id="W1", title="Foundational method", year=2005, cited_by_count=5000,
              authors=["Alice Rossi", "Bob Bianchi"],
              author_ids=["A1", "A2"], fwci=3.2,
              counts_by_year={2022: 100, 2023: 120, 2024: 90}),
        Paper(id="W2", title="Recent breakthrough", year=2024, cited_by_count=40,
              authors=["Alice Rossi"], author_ids=["A1"], fwci=8.5,
              counts_by_year={2024: 40}),
        Paper(id="W3", title="Mid tier work", year=2018, cited_by_count=300,
              authors=["Carla Verdi"], author_ids=["A3"], fwci=1.1,
              counts_by_year={2019: 30, 2020: 40}),
    ]


def test_extract_json_direct():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('[1, 2, 3]') == [1, 2, 3]


def test_extract_json_with_noise():
    raw = 'Ecco il risultato:\n```json\n{"verdict": "ok"}\n```\nspero vada bene'
    assert _extract_json(raw) == {"verdict": "ok"}


def test_extract_json_balanced_block():
    raw = 'garbage {"x": {"y": [1,2]}} more garbage'
    assert _extract_json(raw) == {"x": {"y": [1, 2]}}


def test_first_balanced_none():
    assert _first_balanced("no json here") is None


def test_extract_json_returns_none_on_bad():
    assert _extract_json("just some prose, nothing structured") is None


def test_reconstruct_abstract():
    inv = {"Hello": [0], "world": [1], "again": [2]}
    assert _reconstruct_abstract(inv) == "Hello world again"
    assert _reconstruct_abstract(None) == ""
    assert _reconstruct_abstract({}) == ""


def test_scoring_and_ordering():
    papers = score_papers(_sample_papers())
    assert all(hasattr(p, "score") for p in papers)
    # ordinamento decrescente
    scores = [p.score for p in papers]
    assert scores == sorted(scores, reverse=True)


def test_foundational_frontier_split():
    papers = score_papers(_sample_papers())
    split_foundational_frontier(papers, top_n=5)
    cats = {p.id: p.category for p in papers}
    # W2 è del 2024 -> frontiera; W1 è vecchio e citatissimo -> fondamentale
    assert cats["W2"] == "frontier"
    assert cats["W1"] == "foundational"


def test_author_aggregation():
    papers = score_papers(_sample_papers())
    authors = aggregate_authors(papers)
    names = [a.name for a in authors]
    assert "Alice Rossi" in names
    alice = next(a for a in authors if a.name == "Alice Rossi")
    assert alice.paper_count == 2   # appare in W1 e W2


def test_config_defaults():
    cfg = Config.load("nonexistent_config_xyz.yaml")
    assert cfg.llm["model"]
    assert cfg.pipeline["max_iterations"] >= 1


def test_render_markdown_minimal():
    papers = score_papers(_sample_papers())
    split_foundational_frontier(papers)
    d = Dossier(topic="test topic", session_id="abc", created_at="2026-01-01")
    d.papers = papers
    d.foundational = [p for p in papers if p.category == "foundational"]
    d.frontier = [p for p in papers if p.category == "frontier"]
    d.authors = aggregate_authors(papers)
    d.overview = "Una panoramica di prova."
    d.thematic_map = ThematicMap(key_findings=["si sa X"], open_gaps=["manca Y"])
    d.stats = {"n_papers": 3, "model": "gemma:2b"}
    md = render_markdown(d)
    assert "# Dossier di letteratura — test topic" in md
    assert "Paper fondamentali" in md
    assert "Autori di riferimento" in md
    assert "Lacune e domande aperte" in md


def test_render_markdown_english():
    papers = score_papers(_sample_papers())
    split_foundational_frontier(papers)
    d = Dossier(topic="test topic", session_id="abc", created_at="2026-01-01",
                language="en")
    d.papers = papers
    d.foundational = [p for p in papers if p.category == "foundational"]
    d.frontier = [p for p in papers if p.category == "frontier"]
    d.authors = aggregate_authors(papers)
    d.overview = "A test overview."
    d.thematic_map = ThematicMap(key_findings=["X is known"], open_gaps=["Y is missing"])
    d.stats = {"n_papers": 3, "model": "gemma:2b"}
    md = render_markdown(d)
    # Titolo e sezioni in inglese
    assert "# Literature dossier — test topic" in md
    assert "## Foundational papers" in md
    assert "## Reference authors" in md
    assert "## Gaps and open questions" in md
    assert "## Method and limits" in md
    # Nessun residuo italiano nell'impalcatura del report
    for it_only in ["Paper fondamentali", "Autori di riferimento",
                    "Lacune e domande aperte", "Metodo e limiti"]:
        assert it_only not in md
    # L'indice punta ad ancore coerenti con i titoli tradotti
    assert "[Foundational papers](#foundational-papers)" in md
    assert "[Method and limits](#method-and-limits)" in md


if __name__ == "__main__":
    # Runner minimale senza pytest.
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} test superati.")
