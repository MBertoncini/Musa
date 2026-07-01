"""Entry point da terminale.

Uso:
    python -m musa.cli "argomento di ricerca" [opzioni]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime

from .config import Config
from .pipeline import Orchestrator
from .render import render_markdown

try:
    from rich.console import Console
    from rich.panel import Panel
    _console = Console()
except ImportError:  # rich è opzionale
    _console = None


def _say(msg: str, style: str = "") -> None:
    if _console:
        _console.print(msg, style=style)
    else:
        print(msg)


def _progress(phase: str, msg: str) -> None:
    tag = f"[{phase}]"
    if _console:
        color = {"ok": "green", "!": "red"}.get(phase, "cyan")
        _console.print(f"[{color}]{tag}[/{color}] {msg}")
    else:
        print(f"{tag} {msg}")


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

    if not cfg.openalex.get("mailto"):
        _say("Suggerimento: imposta 'openalex.mailto' in config.yaml per rate limit "
             "più stabili (polite pool).", style="yellow")

    _say(Panel(f"Musa — dossier su: [bold]{args.topic}[/bold]") if _console
         else f"=== Musa — dossier su: {args.topic} ===")

    orch = Orchestrator(cfg, progress=_progress)

    err = orch.preflight()
    if err:
        _say(err, style="red")
        orch.close()
        return 2

    try:
        dossier = orch.run(args.topic, verify=not args.no_verify, fresh=args.fresh)
    except KeyboardInterrupt:
        _say("\nInterrotto.", style="red")
        orch.close()
        return 130
    finally:
        pass

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

    _say(f"\nDossier salvato in: [bold]{out_path}[/bold]" if _console
         else f"\nDossier salvato in: {out_path}", style="green")
    _say(f"{dossier.stats.get('n_papers', 0)} paper · "
         f"{dossier.stats.get('n_authors', 0)} autori · "
         f"{dossier.stats.get('elapsed_s', '?')}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
