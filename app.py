"""Interfaccia web locale (Streamlit).

Avvio:  streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import datetime

import streamlit as st

from musa.config import Config
from musa.meander import random_meander
from musa.pipeline import Orchestrator
from musa.render import render_markdown

st.set_page_config(page_title="Musa — Ricerca letteratura", page_icon="🏛️",
                   layout="wide")

# --- Tema "Grecia antica": marmo, oro, blu Egeo, greca/meandro ---
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _asset(name: str) -> str:
    try:
        with open(os.path.join(ASSETS, name), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


AVATAR_SVG = _asset("musa_avatar.svg")

# Greca (meandro) generata proceduralmente: diversa a ogni sessione ma sempre
# in stile greco antico. Salvata in session_state così resta stabile tra i
# rerun della stessa sessione. Vedi musa/meander.py.
if "meander" not in st.session_state:
    st.session_state["meander"] = random_meander()
_MEANDER_OBJ = st.session_state["meander"]
_MEANDER = _MEANDER_OBJ.data_uri
_MEANDER_H = _MEANDER_OBJ.height

GREEK_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=EB+Garamond:ital@0;1&display=swap');

:root {{
  --marble:#F6F0E2; --marble2:#EDE4CE; --ink:#2A2622;
  --aegean:#1F6F8B; --gold:#B8901F;
}}

.stApp {{
  background: radial-gradient(1200px 520px at 50% -12%, #FBF7EC 0%, var(--marble) 55%, var(--marble2) 100%);
  color: var(--ink);
  font-family: 'EB Garamond', Georgia, serif;
}}

h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
  font-family: 'Cinzel', serif !important;
  letter-spacing: .04em;
  color: #23404F !important;
}}

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #F1E9D6, #E5DABE);
  border-right: 2px solid var(--gold);
}}
[data-testid="stSidebar"] * {{ color: #2A2622; }}

.stButton > button {{
  font-family: 'Cinzel', serif; letter-spacing: .06em;
  background: linear-gradient(180deg, #2A83A2, #1F6F8B);
  color: #FBF7EC; border: 1px solid var(--gold); border-radius: 2px;
  box-shadow: 0 2px 0 #14515F;
}}
.stButton > button:hover {{
  background: linear-gradient(180deg, #2F92B4, #22809F);
  color: #fff; border-color: #E9CD75;
}}

[data-testid="stMetric"] {{
  background: rgba(255,255,255,.55); border: 1px solid #D9CBA6;
  border-radius: 4px; padding: 10px 12px;
}}

.musa-hero {{ display: flex; align-items: center; gap: 22px; padding: 4px 0 2px; }}
.musa-hero .avatar {{ width: 108px; height: 108px; flex: 0 0 auto; line-height: 0;
  filter: drop-shadow(0 4px 8px rgba(0,0,0,.18)); }}
.musa-hero .avatar svg {{ width: 100%; height: 100%; display: block; }}
.musa-hero h1 {{ margin: 0; font-size: 2.5rem; line-height: 1.05; }}
.musa-hero .grk {{ color: var(--gold); font-size: 1.05rem; letter-spacing: .18em;
  font-family: 'Cinzel', serif; }}
.musa-hero .sub {{ font-style: italic; color: #5B5346; margin-top: 4px; font-size: 1.03rem; }}

.meander {{ height: {_MEANDER_H}px; margin: 8px 0 14px;
  background-image: url("{_MEANDER}");
  background-repeat: repeat-x; background-position: center; opacity: .9; }}

.sidebar-muse {{ text-align: center; margin: -6px 0 8px; }}
.sidebar-muse svg {{ width: 88px; height: 88px;
  filter: drop-shadow(0 3px 6px rgba(0,0,0,.15)); }}
</style>
"""

st.markdown(GREEK_CSS, unsafe_allow_html=True)

st.markdown(
    f"""
<div class="musa-hero">
  <div class="avatar">{AVATAR_SVG}</div>
  <div>
    <div class="grk">ΜΟΥΣΑ</div>
    <h1>Musa</h1>
    <div class="sub">La tua Musa ispiratrice — ricerca di letteratura con dati OpenAlex
      e LLM Ollama, gratis e in locale.</div>
  </div>
</div>
<div class="meander"></div>
""",
    unsafe_allow_html=True,
)

# --- Sidebar: configurazione ---
with st.sidebar:
    st.markdown(f'<div class="sidebar-muse">{AVATAR_SVG}</div>', unsafe_allow_html=True)
    st.header("Impostazioni")
    cfg = Config.load()

    model = st.text_input(
        "Modello Ollama", cfg.llm["model"],
        help="Nome del modello LLM servito da Ollama in locale (es. `llama3`, "
             "`musa`). Deve corrispondere a un modello già scaricato con "
             "`ollama pull` o creato dal Modelfile. Usato per generare la sintesi "
             "e verificare i claim.",
    )
    mailto = st.text_input(
        "Email (OpenAlex polite pool)", cfg.openalex["mailto"],
        help="La tua email viene inviata a OpenAlex per accedere al *polite pool*: "
             "richieste più veloci e affidabili, nessun costo. Non è obbligatoria "
             "ma fortemente consigliata. Non viene condivisa con altri servizi.",
    )
    lang = st.selectbox(
        "Lingua sintesi", ["it", "en"],
        index=0 if cfg.output["language"] == "it" else 1,
        help="Lingua in cui verrà scritto il dossier finale: italiano (`it`) o "
             "inglese (`en`). Non influisce sulla lingua dei paper cercati.",
    )
    max_papers = st.slider(
        "Paper max", 30, 300, cfg.pipeline["max_papers"], step=10,
        help="Numero massimo di paper scaricati da OpenAlex e analizzati. Valori "
             "più alti danno una copertura più ampia ma rallentano la pipeline e "
             "consumano più contesto dell'LLM.",
    )
    iterations = st.slider(
        "Iterazioni loop", 1, 8, cfg.pipeline["max_iterations"],
        help="Quante volte la pipeline affina la ricerca (raffina query, aggiunge "
             "paper, riscrive la sintesi). Più iterazioni migliorano la qualità ma "
             "aumentano i tempi di esecuzione.",
    )
    verify = st.checkbox(
        "Auto-verifica dei claim", value=True,
        help="Se attivo, l'LLM ricontrolla ogni affermazione del dossier confron"
             "tandola con i paper citati, segnalando quelle non supportate. "
             "Migliora l'affidabilità ma aggiunge una fase in più.",
    )
    fresh = st.checkbox(
        "Ignora cache (riscarica)", value=False,
        help="Se attivo, ignora i dati salvati in `.musa_cache` e riscarica tutto "
             "da OpenAlex. Utile per avere risultati aggiornati; lascialo disatti"
             "vato per rieseguire più velocemente la stessa ricerca.",
    )

    cfg.llm["model"] = model
    cfg.openalex["mailto"] = mailto
    cfg.output["language"] = lang
    cfg.pipeline["max_papers"] = max_papers
    cfg.pipeline["max_iterations"] = iterations

topic = st.text_input("Argomento di ricerca",
                      placeholder="es. reinforcement learning from human feedback")

col_run, col_info = st.columns([1, 3])
run = col_run.button("Genera dossier", type="primary", use_container_width=True)

if run and topic.strip():
    orch = Orchestrator(cfg)
    err = orch.preflight()
    if err:
        st.error(err)
        orch.close()
        st.stop()

    status = st.status("Avvio pipeline…", expanded=True)
    log_area = status.empty()
    _log_lines = []

    def progress(phase: str, msg: str) -> None:
        _log_lines.append(f"**[{phase}]** {msg}")
        log_area.markdown("\n\n".join(_log_lines[-12:]))

    orch.progress = progress

    try:
        dossier = orch.run(topic, verify=verify, fresh=fresh)
        status.update(label="Dossier pronto!", state="complete", expanded=False)
    except Exception as exc:  # noqa: BLE001
        status.update(label="Errore", state="error")
        st.exception(exc)
        orch.close()
        st.stop()

    md = render_markdown(dossier)
    orch.close()

    # Metriche in cima
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Paper", dossier.stats.get("n_papers", 0))
    c2.metric("Autori", dossier.stats.get("n_authors", 0))
    c3.metric("Cluster tematici", dossier.stats.get("n_clusters", 0))
    c4.metric("Tempo (s)", dossier.stats.get("elapsed_s", "?"))

    st.download_button(
        "⬇️ Scarica dossier (.md)",
        data=md.encode("utf-8"),
        file_name=f"{datetime.now():%Y%m%d-%H%M}_dossier.md",
        mime="text/markdown",
    )

    st.divider()
    st.markdown(md)

elif run:
    st.warning("Inserisci un argomento.")
