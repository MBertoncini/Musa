"""Entry point da terminale — interfaccia "grecheggiante".

Uso:
    python -m musa.cli "argomento di ricerca" [opzioni]

L'interfaccia richiama il tema "Grecia antica" dell'app Streamlit: marmo, oro
e blu Egeo, con una greca (meandro) generata proceduralmente — sempre diversa
ma sempre in stile greco antico — la stessa che decora la web app. Vedi
``musa/meander.py`` (``random_meander_text``).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime

from .config import Config
from .meander import random_meander_text
from .pipeline import Orchestrator
from .render import render_markdown

# Su Windows lo stdout usa spesso cp1252 (soprattutto se rediretto): forziamo
# UTF-8 così i caratteri box-drawing della greca non fanno esplodere l'output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

# --- Palette del tema (coerente con app.py) ---
GOLD = "#B8901F"
AEGEAN = "#1F6F8B"
DEEP = "#23404F"
MUTED = "#5B5346"

try:
    from rich.box import DOUBLE
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _console: "Console | None" = Console()
except ImportError:  # rich è opzionale: fallback a print() semplice
    _console = None

# La greca resta stabile per tutta l'esecuzione (come in session_state lato web).
_BAND = random_meander_text()


def _say(msg, style: str = "") -> None:
    if _console:
        _console.print(msg, style=style)
    else:
        print(msg)


def _meander() -> None:
    """Stampa la fascia decorativa (greca) larga quanto il terminale."""
    if not _console:
        return
    for line in _BAND.band(_console.width):
        _console.print(Text(line, style=_BAND.color), no_wrap=True, crop=True)


def _header() -> None:
    """Intestazione: greca, titolo greco/latino, sottotitolo."""
    if not _console:
        print("=" * 60)
        print("MUSA — ricerca di letteratura (locale, gratis)")
        print("=" * 60)
        return

    _console.print()
    _meander()
    _console.print()
    _console.print(Text("ΜΟΥΣΑ", style=f"bold {GOLD}"), justify="center")
    _console.print(Text("M U S A", style=f"bold {AEGEAN}"), justify="center")
    _console.print(
        Text("La tua Musa ispiratrice — ricerca di letteratura", style=f"italic {MUTED}"),
        justify="center",
    )
    _console.print(
        Text("dati OpenAlex + LLM Ollama · gratis e in locale", style=f"italic {MUTED}"),
        justify="center",
    )
    _console.print()
    _meander()
    _console.print()


def _topic_panel(topic: str, cfg: Config, verify: bool) -> None:
    """Riquadro con l'argomento e un riassunto della configurazione."""
    verify_note = "sì" if verify else "no"
    summary = (
        f"modello [b]{cfg.llm['model']}[/b] · lingua [b]{cfg.output['language']}[/b] · "
        f"max [b]{cfg.pipeline['max_papers']}[/b] paper · "
        f"[b]{cfg.pipeline['max_iterations']}[/b] iterazioni · verifica [b]{verify_note}[/b]"
    )
    if not _console:
        plain = re.sub(r"\[/?b\]", "", summary)
        print(f"\n>>> Dossier su: {topic}")
        print(f"    {plain}\n")
        return

    body = Group(
        Text("Dossier su", style=f"{MUTED}", justify="center"),
        Text(topic, style=f"bold {DEEP}", justify="center"),
        Text(""),
        Text.from_markup(summary, style=MUTED, justify="center"),
    )
    _console.print(
        Panel(body, box=DOUBLE, border_style=GOLD, padding=(1, 3), expand=True)
    )
    _console.print()


def _progress(phase: str, msg: str) -> None:
    """Callback di avanzamento, a tema."""
    if not _console:
        print(f"[{phase}] {msg}")
        return
    symbols = {"ok": ("✓", "bold green"), "!": ("✗", "bold red")}
    sym, sym_style = symbols.get(phase, ("◆", AEGEAN))
    tag = "" if phase in ("ok", "!") else phase
    _console.print(
        Text.assemble(
            ("  ", ""),
            (f"{sym} ", sym_style),
            ((f"{tag}  ", f"bold {GOLD}") if tag else ("", "")),
            (msg, ""),
        )
    )


def _result_panel(out_path: str, dossier) -> None:
    """Riquadro finale con percorso del file e metriche (stile st.metric)."""
    stats = dossier.stats
    metrics = [
        ("Paper", stats.get("n_papers", 0)),
        ("Autori", stats.get("n_authors", 0)),
        ("Cluster", stats.get("n_clusters", 0)),
        ("Tempo (s)", stats.get("elapsed_s", "?")),
    ]
    if not _console:
        print("\nDossier salvato in:", out_path)
        print(" · ".join(f"{v} {k}" for k, v in metrics))
        return

    _console.print()
    _meander()
    _console.print()

    grid = Table.grid(expand=True, padding=(0, 2))
    for _ in metrics:
        grid.add_column(justify="center", ratio=1)
    grid.add_row(*[Text(str(v), style=f"bold {AEGEAN}") for _, v in metrics])
    grid.add_row(*[Text(k, style=MUTED) for k, _ in metrics])

    body = Group(
        Text("Dossier pronto", style=f"bold {GOLD}", justify="center"),
        Text(out_path, style=DEEP, justify="center"),
        Text(""),
        grid,
    )
    _console.print(Panel(body, box=DOUBLE, border_style=GOLD, padding=(1, 3)))


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:60] or "dossier"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="musa",
        description="Genera un dossier di letteratura su un argomento (locale, gratis).",
    )
    p.add_argument("topic", help="L'argomento di ricerca (tra virgolette).")
    p.add_argument("--config", help="Percorso a config.yaml.", default=None)
    p.add_argument("--model", help="Override del modello Ollama.")
    p.add_argument("--out", help="File Markdown di output.")
    p.add_argument("--max-papers", type=int, help="Tetto di paper processati.")
    p.add_argument("--iterations", type=int, help="Iterazioni max del loop 5+7.")
    p.add_argument("--lang", choices=["it", "en"], help="Lingua della sintesi.")
    p.add_argument("--no-verify", action="store_true", help="Salta l'auto-verifica.")
    p.add_argument("--fresh", action="store_true", help="Ignora la cache, riscarica.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    cfg = Config.load(args.config)
    # Override da CLI
    if args.model:
        cfg.llm["model"] = args.model
    if args.max_papers:
        cfg.pipeline["max_papers"] = args.max_papers
    if args.iterations:
        cfg.pipeline["max_iterations"] = args.iterations
    if args.lang:
        cfg.output["language"] = args.lang
    verify = not args.no_verify

    _header()

    if not cfg.openalex.get("mailto"):
        _say(
            "  ⚠ Suggerimento: imposta 'openalex.mailto' in config.yaml per rate "
            "limit più stabili (polite pool).",
            style="yellow",
        )

    _topic_panel(args.topic, cfg, verify)

    orch = Orchestrator(cfg, progress=_progress)

    err = orch.preflight()
    if err:
        _say(f"  ✗ {err}", style="bold red")
        orch.close()
        return 2

    try:
        dossier = orch.run(args.topic, verify=verify, fresh=args.fresh)
    except KeyboardInterrupt:
        _say("\n  ✗ Interrotto.", style="bold red")
        orch.close()
        return 130

    md = render_markdown(dossier)

    out_path = args.out
    if not out_path:
        os.makedirs(cfg.output["dir"], exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        out_path = os.path.join(
            cfg.output["dir"], f"{stamp}_{_slugify(args.topic)}.md"
        )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(md)

    orch.close()

    _result_panel(out_path, dossier)
    return 0


if __name__ == "__main__":
    sys.exit(main())
