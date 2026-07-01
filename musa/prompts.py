"""Tutti i prompt dell'LLM in un unico modulo, così sono facili da rivedere e migliorare.

Convenzioni:
- Prompt corti e concreti (i modelli locali piccoli si perdono su prompt lunghi).
- Quando serve JSON, lo schema è mostrato esplicitamente e si chiede SOLO JSON.
- Ogni funzione restituisce una stringa già pronta da passare al client.
"""
from __future__ import annotations

from typing import List

from .models import Paper, ThematicMap

# System prompt usato se il modello NON è il "musa" custom (che ce l'ha già dentro).
SYSTEM = (
    "Sei Musa, un assistente alla ricerca accademica. Ragioni e riassumi SOLO sui "
    "dati forniti nel prompt. Non inventare mai paper, autori, citazioni o numeri: se "
    "un dato non c'è, dillo. Distingui evidenza forte da debole. Quando si chiede JSON, "
    "rispondi con SOLO JSON valido, senza testo attorno."
)


# --- Fase 1: espansione query --------------------------------------------
def expand_query(topic: str, language: str = "it") -> str:
    return f"""Un ricercatore vuole la letteratura più importante su questo argomento:
"{topic}"

Genera termini di ricerca efficaci per interrogare un database accademico (OpenAlex).
Includi: il termine principale, sinonimi, termini tecnici correlati, e le versioni in
inglese (l'inglese è la lingua della letteratura scientifica). Evita termini troppo
generici o ambigui.

Rispondi con SOLO un array JSON di stringhe, massimo 8 elementi. Esempio di formato:
["term one", "synonym", "related technical term"]"""


# --- Fase 3: valutazione copertura ---------------------------------------
def assess_coverage(topic: str, n_results: int, sample_titles: List[str]) -> str:
    titles = "\n".join(f"- {t}" for t in sample_titles[:15])
    return f"""Argomento cercato: "{topic}"
Numero di risultati trovati: {n_results}
Campione di titoli trovati:
{titles}

Valuta la copertura della ricerca. La maggior parte dei titoli è pertinente
all'argomento? I risultati sono troppo pochi, troppi off-topic, o adeguati?

Rispondi con SOLO questo JSON:
{{"verdict": "ok" | "broaden" | "narrow",
  "reason": "spiegazione breve",
  "extra_terms": ["eventuali", "nuovi", "termini", "da", "aggiungere"]}}
Se verdict è "ok", extra_terms può essere vuoto."""


# --- Fase 5+7: loop iterativo ricerca + sintesi --------------------------
def _format_papers_for_reading(papers: List[Paper], max_abstract: int = 600) -> str:
    blocks = []
    for i, p in enumerate(papers):
        abs_txt = (p.abstract or "").strip()
        if len(abs_txt) > max_abstract:
            abs_txt = abs_txt[:max_abstract] + "…"
        if not abs_txt:
            abs_txt = "(abstract non disponibile)"
        blocks.append(
            f"[{p.id}] {p.title} ({p.year or 's.d.'}, cit={p.cited_by_count})\n"
            f"Abstract: {abs_txt}"
        )
    return "\n\n".join(blocks)


def synthesize_iteration(
    topic: str,
    tmap: ThematicMap,
    new_papers: List[Paper],
    language: str = "it",
) -> str:
    """Prompt del loop: legge nuovi paper, AGGIORNA la mappa tematica, trova gap."""
    lang = "italiano" if language == "it" else "inglese"
    papers_txt = _format_papers_for_reading(new_papers)
    context = tmap.as_prompt_context()
    return f"""Argomento della rassegna: "{topic}"

SINTESI COSTRUITA FINORA:
{context}

NUOVI PAPER DA INTEGRARE (usa gli identificatori tra [ ] per citarli):
{papers_txt}

Compito: AGGIORNA la sintesi integrando i nuovi paper con quanto già sai. Non ripartire
da zero: espandi e correggi. Rispondi in {lang}. Ogni affermazione deve riferirsi a
uno o più identificatori di paper reali tra quelli forniti.

Rispondi con SOLO questo JSON:
{{
  "clusters": [
    {{"name": "nome tema", "summary": "1-2 frasi", "paper_ids": ["W..."]}}
  ],
  "key_findings": ["cosa si sa, con [W...] a supporto"],
  "open_gaps": ["lacune o controversie aperte, con [W...] se pertinente"],
  "expand_paper_ids": ["W... dei paper i cui riferimenti vale la pena esplorare"],
  "saturated": true | false
}}
"expand_paper_ids": scegli al massimo 5 paper davvero centrali o che aprono un tema poco
coperto. "saturated": true se i nuovi paper non aggiungono quasi nulla di nuovo."""


# --- Sintesi discorsiva finale -------------------------------------------
def final_overview(topic: str, tmap: ThematicMap, language: str = "it") -> str:
    lang = "italiano" if language == "it" else "inglese"
    context = tmap.as_prompt_context()
    return f"""Argomento: "{topic}"

Ecco la sintesi strutturata costruita leggendo la letteratura:
{context}

Scrivi una PANORAMICA discorsiva in {lang} (3-5 paragrafi) che spieghi a un ricercatore
"cosa si sa" di più importante sull'argomento: i filoni principali, i punti fermi, e le
tensioni o lacune aperte. Sii rigoroso e concreto, basati solo sulla sintesi qui sopra.
Non usare JSON: scrivi prosa. Non inventare nulla che non sia già nella sintesi."""


# --- Fase 8: auto-verifica -----------------------------------------------
def verify_claims(overview: str, valid_ids: List[str]) -> str:
    ids_txt = ", ".join(valid_ids[:80])
    return f"""Questo è un testo di sintesi della letteratura:
---
{overview}
---

Gli identificatori di paper REALMENTE disponibili sono: {ids_txt}

Controlla il testo. Ci sono affermazioni fattuali forti che NON sono supportate da
nessun paper reale, o che sembrano inventate (numeri, nomi, risultati specifici non
ancorati)? Elenca solo i problemi concreti, non i dettagli di stile.

Rispondi con SOLO questo JSON:
{{"issues": ["descrizione del problema 1", "..."], "confidence": "alta" | "media" | "bassa"}}
Se non trovi problemi, issues sia un array vuoto e confidence "alta"."""
