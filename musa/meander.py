"""Generatore procedurale di greche (meandri) in stile greco antico.

Ogni chiamata a :func:`random_meander` produce una fascia decorativa diversa
— ma sempre "grecheggiante" — costruita da spirali quadre (il classico motivo
a chiave greca) disposte su binari orizzontali. Le dimensioni della fascia
restano pressoché costanti (altezza ~17 px) così da non rompere il layout.

Uso come modulo::

    from musa.meander import random_meander
    m = random_meander()          # dict: data_uri, height, width, meta
    st.markdown(f'<div style="height:{m["height"]}px;'
                f'background:url({m["data_uri"]}) repeat-x"></div>', ...)

Uso come script (anteprima di una galleria in HTML)::

    python -m musa.meander            # scrive meander_preview.html e lo apre
    python -m musa.meander 24         # genera 24 varianti
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Tuple
from urllib.parse import quote

# Palette coerente col tema "Grecia antica" dell'app: prevalenza d'oro/bronzo,
# con rari accenti blu Egeo o inchiostro. Mantiene lo "stesso stile" fra sessioni.
_PALETTE: List[Tuple[str, float]] = [
    ("#B8901F", 5.0),  # oro (colore principale del bordo dell'app)
    ("#9A7A18", 3.0),  # oro scuro
    ("#A87C2A", 2.5),  # bronzo
    ("#C8A63A", 2.0),  # oro chiaro
    ("#1F6F8B", 1.0),  # blu Egeo (accento)
    ("#2A2622", 0.6),  # inchiostro (accento)
]

_Point = Tuple[float, float]


@dataclass
class Meander:
    """Risultato della generazione: pronto per essere iniettato in CSS."""

    data_uri: str
    width: int
    height: int
    meta: dict = field(default_factory=dict)


def _square_spiral(arm: int, nseg: int) -> List[_Point]:
    """Polilinea di una spirale quadra (chiave greca), coordinate in celle, y in su.

    Parte da (0, 0) e sale: i lati seguono lo schema classico A, A, A-1, A-1,
    A-2, … avvolgendosi verso il centro, dove la linea termina con la
    caratteristica "codina" libera.
    """
    dirs = [(0, 1), (1, 0), (0, -1), (-1, 0)]  # su, destra, giù, sinistra
    pts: List[_Point] = [(0.0, 0.0)]
    x = y = 0.0
    cur = arm
    for i in range(nseg):
        if cur <= 0:
            break
        dx, dy = dirs[i % 4]
        x += dx * cur
        y += dy * cur
        pts.append((x, y))
        if i % 2 == 1:  # accorcia il lato ogni due segmenti → spirale
            cur -= 1
    return pts


def _pick_color(rng: random.Random) -> str:
    colors, weights = zip(*_PALETTE)
    return rng.choices(colors, weights=weights, k=1)[0]


def random_meander(seed: int | None = None) -> Meander:
    """Genera una greca casuale ma sempre in stile greco antico.

    ``seed`` opzionale per riproducibilità (test / anteprima); se ``None`` la
    fascia cambia a ogni chiamata.
    """
    rng = random.Random(seed)

    style = rng.choices(
        ["semplice", "fitta", "doppia"], weights=[4, 2, 3], k=1
    )[0]
    # Braccio piccolo (3-4 celle) per tenere le celle leggibili: la complessità
    # arriva dai numerosi avvolgimenti e dallo stile "doppia", non da celle minuscole.
    arm = rng.choice([3, 4, 4])                # altezza/larghezza della chiave
    nseg = rng.choice([6, 7, 8])               # numero di avvolgimenti (complessità)
    color = _pick_color(rng)
    flip = rng.random() < 0.5                   # specchia orizzontalmente la fascia

    # Unità (px per cella) scelta così che l'altezza della fascia resti ~19 px,
    # vicina a quella originale, indipendentemente dal braccio.
    target_h = rng.uniform(18.0, 20.0)
    vpad_cells = 0.9
    u = target_h / (arm + 2 * vpad_cells)
    stroke = round(min(1.6, max(0.9, u * 0.36)), 2)

    spiral = _square_spiral(arm, nseg)

    spacing = {"semplice": rng.choice([2, 3]),
               "fitta": 1,
               "doppia": rng.choice([1, 2])}[style]
    hook_x = spacing
    gap = rng.choice([1, 2])                     # solo per "doppia": vuoto fra i due ganci
    if style == "doppia":
        # Due chiavi per periodo, affiancate: una sale dal binario inferiore,
        # l'altra (specchiata) scende da quello superiore → non si sovrappongono.
        period_cells = 2 * spacing + 2 * arm + gap
    else:
        period_cells = hook_x + arm + spacing

    height_px = int(round((arm + 2 * vpad_cells) * u))
    width_px = int(round(period_cells * u))
    vpad = vpad_cells * u

    def to_px(pt: _Point, *, hx: float, flip_y: bool) -> _Point:
        cx, cy = pt
        gx = (hx + cx) * u
        # y in su → coordinate SVG (y in giù); baseline (cy=0) vicino al fondo
        gy = height_px - vpad - cy * u
        if flip_y:                      # gancio appeso al binario superiore
            gy = height_px - gy
        return (round(gx, 2), round(gy, 2))

    def polyline(hx: float, flip_y: bool) -> str:
        px = [to_px(p, hx=hx, flip_y=flip_y) for p in spiral]
        d = "M" + " L".join(f"{x},{y}" for x, y in px)
        return f'<path d="{d}" fill="none"/>'

    paths: List[str] = []

    # Binario inferiore (sempre presente): dà continuità orizzontale alla fascia.
    base_y = round(height_px - vpad, 2)
    paths.append(f'<path d="M0,{base_y} L{width_px},{base_y}" fill="none"/>')
    paths.append(polyline(hook_x, flip_y=False))

    if style == "doppia":
        # Binario superiore + seconda chiave specchiata, affiancata alla prima:
        # aspetto ricco "a doppio meandro", chiavi alternate su/giù senza sovrapporsi.
        top_y = round(vpad, 2)
        paths.append(f'<path d="M0,{top_y} L{width_px},{top_y}" fill="none"/>')
        paths.append(polyline(hook_x + arm + gap, flip_y=True))

    body = "".join(paths)
    transform = (
        f'transform="scale(-1,1) translate(-{width_px},0)" ' if flip else ""
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">'
        f'<g stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="square" stroke-linejoin="miter" {transform}>'
        f'{body}</g></svg>'
    )

    data_uri = "data:image/svg+xml;utf8," + quote(svg, safe="")
    return Meander(
        data_uri=data_uri,
        width=width_px,
        height=height_px,
        meta={"style": style, "arm": arm, "nseg": nseg, "color": color,
              "stroke": stroke, "flip": flip},
    )


# ---------------------------------------------------------------------------
# Variante per terminale (CLI): stessa greca, ma disegnata con caratteri box
# ---------------------------------------------------------------------------
# La versione SVG sopra serve al web (Streamlit). In un terminale non possiamo
# renderizzare SVG, quindi qui ricostruiamo lo *stesso* motivo — la chiave greca
# a spirale — su una griglia di caratteri Unicode box-drawing. Anche questa
# fascia è "sempre diversa ma sempre grecheggiante" e usa la stessa palette.

# (su, giù, sinistra, destra) -> carattere box-drawing
_BOX = {
    (0, 0, 0, 0): " ",
    (0, 0, 1, 0): "╴", (0, 0, 0, 1): "╶", (1, 0, 0, 0): "╵", (0, 1, 0, 0): "╷",
    (0, 0, 1, 1): "─", (1, 1, 0, 0): "│",
    (0, 1, 0, 1): "┌", (0, 1, 1, 0): "┐", (1, 0, 0, 1): "└", (1, 0, 1, 0): "┘",
    (1, 1, 0, 1): "├", (1, 1, 1, 0): "┤", (0, 1, 1, 1): "┬", (1, 0, 1, 1): "┴",
    (1, 1, 1, 1): "┼",
}
# Per lo specchiamento orizzontale servono i glifi con sinistra/destra invertite.
_MIRROR = str.maketrans("┌┐└┘├┤╴╶", "┐┌┘└┤├╶╴")


@dataclass
class TextMeander:
    """Greca per terminale: un *tile* (una porzione ripetibile) di righe."""

    lines: List[str]
    color: str  # esadecimale, pronto per rich (es. "#B8901F")
    meta: dict = field(default_factory=dict)

    @property
    def height(self) -> int:
        return len(self.lines)

    def band(self, width: int) -> List[str]:
        """Ripete il tile fino a coprire ``width`` colonne."""
        tile_w = len(self.lines[0]) if self.lines else 0
        if tile_w <= 0 or width <= 0:
            return list(self.lines)
        reps = width // tile_w + 1
        return [(line * reps)[:width] for line in self.lines]


def random_meander_text(seed: int | None = None) -> TextMeander:
    """Genera una greca da terminale, casuale ma sempre in stile greco antico."""
    rng = random.Random(seed)

    style = rng.choices(["semplice", "fitta", "doppia"], weights=[4, 2, 3], k=1)[0]
    arm = rng.choice([2, 3])                       # altezza/larghezza della chiave
    nseg = {2: 6, 3: 8}[arm]                        # avvolgimenti per una spirale piena
    color = _pick_color(rng)
    flip = rng.random() < 0.5

    spacing = {"semplice": rng.choice([2, 3]),
               "fitta": 1,
               "doppia": rng.choice([1, 2])}[style]
    gap = 1                                          # solo "doppia": vuoto fra i ganci
    if style == "doppia":
        period = 2 * arm + spacing + gap
    else:
        period = arm + spacing

    top = arm + 1                                    # riga più alta (1 cella di aria)
    rows = top + 1                                   # numero di righe di nodi
    # nodi[(col, riga_schermo)] = [su, giù, sinistra, destra]
    nodes: dict = {}

    def _node(col: int, row: int) -> list:
        return nodes.setdefault((col, row), [False, False, False, False])

    def _hedge(col: int, yu: int) -> None:          # lato orizzontale (col..col+1)
        row = top - yu
        _node(col, row)[3] = True                   # destra
        _node(col + 1, row)[2] = True               # sinistra

    def _vedge(col: int, yu: int) -> None:          # lato verticale (yu..yu+1)
        _node(col, top - yu)[0] = True              # su, dalla cella più in basso
        _node(col, top - yu - 1)[1] = True          # giù, dalla cella più in alto

    def _add_hook(base_col: int, points: List[_Point]) -> None:
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            c1, c2 = base_col + int(x1), base_col + int(x2)
            if y1 == y2:                             # segmento orizzontale
                for c in range(min(c1, c2), max(c1, c2)):
                    _hedge(c, int(y1))
            else:                                    # segmento verticale
                for y in range(int(min(y1, y2)), int(max(y1, y2))):
                    _vedge(c1, y)

    spiral = _square_spiral(arm, nseg)

    # Binario inferiore continuo su tutta la fascia (dà continuità orizzontale).
    for col in range(period):
        _hedge(col, 0)
    _node(0, top)[2] = True                          # chiudi il bordo sinistro del tile

    # Chiave che sale dal binario inferiore.
    _add_hook(0, spiral)

    if style == "doppia":
        # Binario superiore + chiave specchiata che scende, affiancata alla prima.
        for col in range(period):
            _hedge(col, top)
        _node(0, 0)[2] = True
        top_spiral = [(x, top - y) for x, y in spiral]
        _add_hook(arm + gap, top_spiral)

    lines: List[str] = []
    for row in range(rows):
        chars = [_BOX[tuple(_node(col, row))] for col in range(period)]
        line = "".join(chars)
        if flip:
            line = line[::-1].translate(_MIRROR)
        lines.append(line)

    while len(lines) > 1 and not lines[0].strip():   # via l'aria in eccesso in cima
        lines.pop(0)

    return TextMeander(
        lines=lines,
        color=color,
        meta={"style": style, "arm": arm, "nseg": nseg, "color": color,
              "flip": flip, "period": period},
    )


def _preview(n: int = 16) -> str:
    """Costruisce una pagina HTML con ``n`` varianti impilate (per ispezione)."""
    rows = []
    for i in range(n):
        m = random_meander()
        rows.append(
            f'<div class="row"><span class="tag">{m.meta["style"]} '
            f'arm={m.meta["arm"]} nseg={m.meta["nseg"]} {m.meta["color"]}</span>'
            f'<div class="band" style="height:{m.height}px;'
            f'background:url({m.data_uri}) repeat-x;"></div></div>'
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{background:#F6F0E2;font-family:Georgia,serif;padding:24px}"
        ".row{margin:14px 0}.tag{display:block;font-size:12px;color:#5B5346;"
        "margin-bottom:4px}.band{border-top:1px solid #D9CBA6;"
        "border-bottom:1px solid #D9CBA6}</style>"
        "<h2 style='font-family:Cinzel,serif;color:#23404F'>Musa — greche generate</h2>"
        + "".join(rows)
    )


if __name__ == "__main__":
    import sys
    import webbrowser
    from pathlib import Path

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    out = Path("meander_preview.html")
    out.write_text(_preview(count), encoding="utf-8")
    print(f"Scritte {count} greche in {out.resolve()}")
    try:
        webbrowser.open(out.resolve().as_uri())
    except Exception:  # noqa: BLE001
        pass
