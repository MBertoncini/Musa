"""Client OpenAlex.

OpenAlex (https://openalex.org) è gratuito, senza chiave, con ~250M+ lavori. Usiamo la
"polite pool" passando `mailto` per rate limit più stabili.

Questo modulo è deterministico al 100%: recupera, normalizza in oggetti Paper/Author,
usa la cache. Nessuna decisione dell'LLM qui.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from ..cache import Cache
from ..models import Author, Paper

BASE = "https://api.openalex.org"

# Solo i campi che ci servono: meno banda, risposte più snelle.
WORK_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "cited_by_count",
        "fwci",
        "counts_by_year",
        "authorships",
        "primary_location",
        "open_access",
        "abstract_inverted_index",
        "referenced_works",
    ]
)


class OpenAlexClient:
    def __init__(self, cache: Cache, mailto: str = "", per_page: int = 50,
                 max_retries: int = 3, api_key: str = ""):
        self.cache = cache
        self.mailto = mailto
        self.api_key = api_key
        self.per_page = min(per_page, 200)
        self.max_retries = max_retries
        # Segnale sollevato quando la ricerca anonima è bloccata (503 da heavy load):
        # l'orchestratore lo usa per dare un messaggio azionabile all'utente.
        self.search_blocked = False
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": f"Musa/0.1 (research assistant; mailto:{mailto or 'n/a'})"}
        )

    # --- HTTP con cache e retry ------------------------------------------
    def _get(
        self, path: str, params: Dict[str, Any], is_search: bool = False
    ) -> Optional[Dict[str, Any]]:
        params = dict(params)
        if self.mailto:
            params["mailto"] = self.mailto
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{BASE}{path}?{urlencode(params)}"

        cached = self.cache.get(url)
        if cached is not None:
            return cached

        for attempt in range(self.max_retries):
            try:
                r = self.session.get(url, timeout=30)
                # 429 = rate limit, 503 = heavy load: entrambi -> backoff e retry
                if r.status_code in (429, 503):
                    if is_search and r.status_code == 503:
                        # La ricerca anonima è gated: segnala per un messaggio chiaro.
                        self.search_blocked = self.search_blocked or (not self.api_key)
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                data = r.json()
                self.cache.set(url, data)
                return data
            except requests.RequestException:
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(1 + attempt)
        return None

    # --- Ricerca lavori ---------------------------------------------------
    def search_works(self, query: str, limit: int = 50) -> List[Paper]:
        """Cerca lavori per una singola query testuale, ordinati per rilevanza."""
        papers: List[Paper] = []
        page = 1
        per_page = min(self.per_page, limit)
        while len(papers) < limit:
            data = self._get(
                "/works",
                {
                    "search": query,
                    "per_page": per_page,
                    "page": page,
                    "select": WORK_FIELDS,
                },
                is_search=True,
            )
            if not data or not data.get("results"):
                break
            for raw in data["results"]:
                p = self._to_paper(raw, source_query=query)
                if p:
                    papers.append(p)
                if len(papers) >= limit:
                    break
            if len(data["results"]) < per_page:
                break
            page += 1
        return papers

    def get_works_by_ids(self, ids: List[str]) -> List[Paper]:
        """Recupera lavori specifici dai loro OpenAlex ID (per lo snowballing)."""
        papers: List[Paper] = []
        # OpenAlex accetta filtri OR fino a ~50 id per volta
        short_ids = [self._short_id(i) for i in ids if i]
        for chunk_start in range(0, len(short_ids), 50):
            chunk = short_ids[chunk_start : chunk_start + 50]
            data = self._get(
                "/works",
                {
                    "filter": f"openalex_id:{'|'.join(chunk)}",
                    "per_page": 50,
                    "select": WORK_FIELDS,
                },
            )
            if not data:
                continue
            for raw in data.get("results", []):
                p = self._to_paper(raw, source_query="snowball")
                if p:
                    papers.append(p)
        return papers

    def get_citing_works(self, paper_id: str, limit: int = 25) -> List[Paper]:
        """Lavori che CITANO un dato paper (citazioni entranti)."""
        short = self._short_id(paper_id)
        data = self._get(
            "/works",
            {
                "filter": f"cites:{short}",
                "sort": "cited_by_count:desc",
                "per_page": min(limit, self.per_page),
                "select": WORK_FIELDS,
            },
        )
        if not data:
            return []
        out = []
        for raw in data.get("results", []):
            p = self._to_paper(raw, source_query="snowball")
            if p:
                out.append(p)
        return out

    def enrich_author(self, author_id: str) -> Dict[str, Any]:
        """Scarica metriche autore (h-index, works_count, istituzione)."""
        short = self._short_id(author_id)
        data = self._get(
            f"/authors/{short}",
            {"select": "id,display_name,works_count,summary_stats,"
                       "last_known_institutions"},
        )
        if not data:
            return {}
        stats = data.get("summary_stats") or {}
        insts = data.get("last_known_institutions") or []
        return {
            "h_index": stats.get("h_index"),
            "works_count": data.get("works_count"),
            "institution": insts[0].get("display_name", "") if insts else "",
        }

    # --- Normalizzazione --------------------------------------------------
    def _to_paper(self, raw: Dict[str, Any], source_query: str = "") -> Optional[Paper]:
        title = raw.get("title") or raw.get("display_name")
        if not title:
            return None
        authorships = raw.get("authorships") or []
        authors, author_ids = [], []
        for a in authorships:
            info = a.get("author") or {}
            name = info.get("display_name")
            if name:
                authors.append(name)
                author_ids.append(self._short_id(info.get("id", "")))
        loc = raw.get("primary_location") or {}
        source = loc.get("source") or {}
        oa = raw.get("open_access") or {}
        counts = {
            c["year"]: c["cited_by_count"]
            for c in (raw.get("counts_by_year") or [])
            if "year" in c
        }
        doi = (raw.get("doi") or "").replace("https://doi.org/", "")
        return Paper(
            id=self._short_id(raw.get("id", "")),
            title=title,
            abstract=_reconstruct_abstract(raw.get("abstract_inverted_index")),
            year=raw.get("publication_year"),
            authors=authors,
            author_ids=author_ids,
            venue=source.get("display_name", "") or "",
            doi=doi,
            url=raw.get("id", "") or (f"https://doi.org/{doi}" if doi else ""),
            cited_by_count=raw.get("cited_by_count", 0) or 0,
            fwci=raw.get("fwci"),
            counts_by_year=counts,
            referenced_works=[self._short_id(r) for r in
                              (raw.get("referenced_works") or [])],
            open_access_url=oa.get("oa_url", "") or "",
            source_query=source_query,
        )

    @staticmethod
    def _short_id(full: str) -> str:
        """Da 'https://openalex.org/W123' a 'W123' (idempotente)."""
        if not full:
            return ""
        return full.rstrip("/").split("/")[-1]


def _reconstruct_abstract(inv_index: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex fornisce l'abstract come indice invertito; lo ricostruiamo."""
    if not inv_index:
        return ""
    positions: Dict[int, str] = {}
    for word, idxs in inv_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return ""
    return " ".join(positions[i] for i in sorted(positions))
