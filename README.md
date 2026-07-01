# Musa — Assistente locale alla ricerca di letteratura

Musa genera un **dossier di letteratura** su un argomento: i paper più importanti
(rankati per rilevanza), gli autori di riferimento e una **sintesi ragionata** di cosa
si sa e di quali sono le lacune aperte.

Tutto **gratuito** e **locale**: i dati arrivano da API accademiche aperte (OpenAlex),
il ragionamento e i riassunti da un modello **Ollama** che gira sulla tua macchina.
Nessun account, nessun cloud, nessuna chiave API obbligatoria.

## Idea chiave

L'LLM **non è il database**. Non gli si chiede mai "quali sono i paper importanti su X"
(allucinerebbe titoli e citazioni). L'LLM serve solo a **ragionare e riassumere** su dati
reali recuperati dalle API. È un **agente su binari**: una pipeline a fasi fisse dove il
codice garantisce l'ordine e la precisione numerica, e l'LLM decide solo dove serve
giudizio (come espandere la query, cosa approfondire, quando fermarsi).

## Architettura (pipeline a fasi)

```
0. Setup            [codice]   sessione + cache
1. Espansione query [LLM]      sinonimi, termini correlati, EN/IT
2. Recupero         [codice]   OpenAlex -> cache SQLite, dedup
3. Copertura        [LLM]      abbastanza risultati? allarga/restringi (max 2 cicli)
4. Ranking          [codice]   FWCI, citazioni normalizzate, recenza
5+7. Ricerca+Sintesi [LLM+codice] loop iterativo: leggi -> mappa tematica ->
                                 trova gap -> segui citazioni mirate -> ripeti
8. Auto-verifica    [LLM+codice] ogni claim ancorato a un paper reale?
9. Composizione     [codice]   dossier Markdown finale
```

Le fasi con autonomia dell'LLM hanno **sempre** un guardrail deterministico affianco
(contatore, soglia, tetto massimo), così l'agente non può andare in loop né consumare
risorse illimitate.

## Requisiti

- Python 3.10+
- [Ollama](https://ollama.com) installato e in esecuzione, con almeno un modello
  (es. `ollama pull gemma:2b`)
- Connessione a Internet (solo per interrogare OpenAlex)

> **Nota su OpenAlex e la API key.** Da qualche tempo OpenAlex, quando è sotto carico,
> blocca le ricerche anonime restituendo un errore 503 ("Anonymous search is temporarily
> rate-limited"). La soluzione è una **API key gratuita** (registrazione rapida su
> <https://openalex.org/rest-api>): impostala in `config.yaml` (`openalex.api_key`) o
> nella variabile d'ambiente `OPENALEX_API_KEY`. Il fetch dei metadati e lo snowballing
> (endpoint non-search) funzionano comunque senza chiave; è solo la ricerca iniziale per
> parole chiave a poter essere gated. Se manca la chiave e la ricerca è bloccata, Musa
> te lo dice con un messaggio chiaro invece di fallire in modo oscuro.

### Modelli piccoli, qualità della sintesi

Con modelli molto piccoli (`gemma:2b`, `gemma3:1b`) l'infrastruttura funziona ma la
sintesi è superficiale e a volte usa i titoli dei paper come nomi di cluster. Per
risultati di qualità da ricercatore usa un modello più capace (es. famiglia Qwen/Llama
da 7-14B) se l'hardware lo consente: cambia solo `llm.model` in `config.yaml`.

## Installazione

```bash
pip install -r requirements.txt

# (opzionale ma consigliato) crea il modello custom con system prompt specializzato
ollama create musa -f Modelfile
```

Copia e personalizza la configurazione:

```bash
cp config.example.yaml config.yaml
# imposta la tua email (per la "polite pool" di OpenAlex) e il modello Ollama
```

## Uso

### CLI

```bash
python run.py "reinforcement learning from human feedback"
# oppure
python -m musa.cli "microbiota intestinale e depressione" --out dossier.md
```

Opzioni utili:

```
--model gemma:2b        modello Ollama da usare
--max-papers 120        tetto di paper processati
--iterations 4          iterazioni max del loop ricerca+sintesi
--no-verify             salta la fase di auto-verifica (più veloce)
--fresh                 ignora la cache e riscarica tutto
```

### Interfaccia web (Streamlit)

```bash
streamlit run app.py
```

## Struttura del progetto

```
musa/
  config.py        caricamento configurazione + default
  models.py        dataclass: Paper, Author, ThematicMap, Dossier
  cache.py         cache SQLite (API-polite, re-run veloci)
  llm.py           client Ollama con parsing JSON robusto
  ranking.py       ranking deterministico di paper e autori
  prompts.py       tutti i prompt dell'LLM (in un solo posto)
  sources/
    openalex.py    client OpenAlex
  pipeline/
    orchestrator.py  l'agente su binari (mette in fila le fasi)
    phases.py        le singole fasi
  cli.py           entry point da terminale
app.py             interfaccia web Streamlit
Modelfile          definizione del modello Ollama custom
```

## Limiti noti

- La qualità della sintesi dipende dal modello Ollama: un modello 1-2B è veloce ma
  superficiale; con hardware adeguato usa modelli più grandi per risultati migliori.
- Le metriche di importanza (citazioni, h-index, FWCI) hanno bias noti: il dossier le
  usa come **indizi**, non come verità assolute, e lo dichiara.
- Il full-text non è ancora integrato: la sintesi lavora sugli abstract (Variante A).
  Il codice è predisposto per aggiungere il RAG full-text sui top paper in futuro.
