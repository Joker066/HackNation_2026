# Tap & Check — project structure (draft for review)

> Prawdowid task (MSZ), HackNation 2026. Full task summary: [instruction.md](instruction.md).
> Tagline idea: *"Tap & Check – sprawdź, zanim udostępnisz."* ("Check before you share.")

## 1. Core idea

**The language model reads and writes; the rules decide.**

- The language model is used to: split the input into claims, judge whether a retrieved passage supports or contradicts a claim, and write the answer in plain Polish.
- The **verdict is computed by explicit, deterministic rules** from the evidence (stance, source tier, recency, number of independent sources). That makes "verdict strength from explicit premises" auditable, and the model can't invent a verdict on its own.
- **The default is to abstain.** Without matching evidence, the answer is `brak wystarczających dowodów` (not enough evidence).

## 2. Data flow

```
 Web UI ──┐                                 ┌── audit log (SQLite)
          ├─► API /check ─► Pipeline ───────┼── metrics (latency, cost, abstentions)
 Discord ─┘   (same code)                   └── moderator cases (optional)

 Pipeline:
  1. Ingest      validate input, fetch URL (if any), strip HTML, mask PII,
                 flag injection attempts
  2. Claims      LLM → JSON list of checkable claims (+ "opinion" / "prediction" flags)
  3. Retrieve    per claim: search the local corpus (BM25 + optional embeddings),
                 return the top-k passages with metadata
  4. Assess      LLM → per passage: supports / refutes / context / irrelevant
                 + exact quote; quote is verified in code to be a real substring
  5. Verdict     rule engine → one of 5 verdicts + strength score + reasons
  6. Compose     LLM → short Polish answer using ONLY the verified evidence;
                 sources are rendered from data, not from model text
  7. Log         question, time, sources, verdict, model usage, cost
```

## 3. Response contract (same for every channel)

```jsonc
{
  "request_id": "…",
  "status": "ok",            // ok | error | needs_clarification | out_of_scope
  "status_detail": null,     // e.g. "LLM provider unavailable" — never shown as a verdict
  "claims": [
    {
      "text": "…",
      "verdict": "potwierdzone", // potwierdzone | fałszywe | wprowadzające_w_błąd
                                 // | brak_wystarczających_dowodów | nie_podlega_weryfikacji
      "strength": "wysoka",      // wysoka | średnia | niska
      "reasons": ["2 niezależne źródła urzędowe", "źródła z ostatnich 30 dni"],
      "explanation": "…plain Polish…",
      "evidence": [
        {
          "stance": "supports",  // supports | refutes | context
          "title": "…", "publisher": "…", "published_at": "…",
          "retrieved_at": "…", "url": "…", "quote": "…exact fragment…",
          "source_type": "official", // official | factcheck | media | dataset
          "archival_warning": false
        }
      ],
      "limitations": "…what could not be established…",
      "source_warnings": []      // neutral notes, e.g. a known-incident match; never decide the verdict
    }
  ],
  "security_events": []          // e.g. "injection attempt ignored"
}
```

## 4. One evidence score per claim (`pipeline/scoring.py`, `pipeline/verdict.py`)

Every claim gets **one score = f(all features)**, from **−1** (sources refute) to **+1** (sources confirm).

| Feature | Level | How it enters the score |
|---|---|---|
| Credibility (1–5, `corpus/sources.csv`) | source | × credibility / 5 |
| Recency (age vs. `update_frequency` half-life: real-time 3 h, hourly 6 h, daily 3 d, weekly 30 d, event-driven 90 d, rarely never) | source | × 0.5^(age / half-life); only for claims about the present; undated = × 0.5 |
| Directness (passage states it explicitly or only implies it) | source | × 1.0 explicit / 0.7 implicit |
| Quote check (quote is verbatim in the source) | source | evidence dropped if not |
| Role (`context_only`, e.g. EUvsDisinfo) | source | × 0 (shown, never decisive) |
| Stance | claim | supports +, refutes − |
| Independence | claim | each publisher counts once |
| Supersession | claim | a publisher's latest statement replaces its earlier ones |

```
weight(source)   = min(credibility/5 × recency × directness × role, 0.95)
strength(source) = −ln(1 − weight)
balance          = Σ strength(supporting) − Σ strength(refuting)
score            = sign(balance) × (1 − e^−|balance|)
```

| Score / condition | Verdict |
|---|---|
| Claim is an opinion or prediction | `nie_podlega_weryfikacji` (no score) |
| Misleading context flagged, and evidence strength ≥ 0.7 | `wprowadzające_w_błąd` |
| score ≥ +0.7 | `potwierdzone` |
| score ≤ −0.7 | `fałszywe` |
| −0.7 < score < +0.7 | `brak_wystarczających_dowodów` (reason: nothing found / too weak / conflict) |

Strength of the verdict: |score| ≥ 0.9 high, ≥ 0.8 medium, otherwise low. `reasons` shows the score and each source's `credibility × recency × directness = weight`.

Worked examples:
- one fresh, explicit credibility-5 source → ±0.95 (decides); the same, only implied → ±0.7 (just decides)
- one credibility-3 fact-check → 0.6 (abstain); two independent ones → 0.84 (decide)
- official source 0.95 vs. a fact-check 0.6 → +0.88 (the stronger source wins, the other is shown)
- two equal fresh official sources disagree → ≈ 0 (abstain, both shown)
- IMGW issued a warning 6 h ago and lifted it 30 min ago → only the latest statement counts

Rules from the task that are enforced in code:
- Domain, author, popularity or sanction status **never** sets the verdict; at most they add a neutral `source_warning`.
- A quote that isn't an exact substring of the source is dropped.
- Errors, missing keys and rate limits produce `status: error`, never a verdict.

## 5. Tech stack

| Part | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + **FastAPI** | Simple, async, auto OpenAPI spec (a bonus point) |
| Frontend | **Single page** `web/index.html` (Tailwind + Lucide via CDN), served by FastAPI | No build step |
| Second channel | **Discord bot** (`discord.py`) | Allowed by the task, free, no business account; reliable for the jury demo |
| Search | **SQLite FTS5 / BM25** (crude Polish stemming) | No extra infrastructure; embeddings would be the next step |
| Live sources | **Google Fact Check API** (ClaimReview) + **EUvsDisinfo MCP** (`search` tool) | Fact-checks per claim; known disinformation narratives as context only |
| Web search fallback | Claude `web_search` tool, **allowlist = catalogue domains**; pages read by our fetcher | Only for undecided claims; coverage for current news; media never stored |
| Media input | Screenshots/photos read by the model (transcription + date + source), then the normal pipeline | Scenario F; image never stored; limits always disclosed |
| LLM | **Claude Haiku 5.5** (`claude-haiku-5-5`, effort `low`) behind a provider interface; `fake` provider for offline tests | ~$0.001 per check; `medium` effort measured: no quality gain, slower. Swappable (`LLM_PROVIDER`, `LLM_MODEL`) |
| Storage | **SQLite** (audit log, corpus index) + `corpus/text_sources/*.json` | One file per document: rebuildable offline, auditable |
| Packaging | **`start.sh`** (API + web + bot, first-run setup) | One command for the jury; Docker not done yet |

## 6. Directory layout

```
HackNation_2026/
├── start.sh                     # one command: API + web page + Discord bot
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI: /, /r/{id}, /api/check, /api/check/{id}, /api/warnings,
│   │   │                        #   /api/session/{id}, /api/health, /api/logs, /api/metrics
│   │   ├── config.py            # settings from env (.env, never committed)
│   │   ├── schemas.py           # response contract (Pydantic)
│   │   ├── net.py               # HTTP clients (forced IPv4: broken IPv6 on WSL2)
│   │   ├── pipeline/            # ingest → claims (LLM) → assess (LLM) → scoring → verdict → compose; run.py orchestrates
│   │   ├── llm/                 # provider interface, Claude provider, fake provider
│   │   ├── sources/             # google_factcheck.py, euvsdisinfo.py (live sources)
│   │   ├── security/            # pii.py, injection.py, ratelimit.py
│   │   └── store/               # corpus.py (FTS index, catalogue), text_sources.py, audit.py, db.py
│   ├── channels/discord_bot.py  # thin adapter → calls the API, formats the reply
│   ├── crawlers/                # framework + adapters: rcb, policja, cert, kgsok, umgdy; _template.py
│   ├── scripts/                 # build_index.py, seed_factchecks.py
│   └── tests/
├── corpus/
│   ├── sources.csv              # audited catalogue: claim types, credibility 1-5, role, update frequency
│   ├── factcheckers.csv         # fact-checker names and credibility, by website
│   ├── lista_źródeł.txt         # source list provided by the organisers (reference only)
│   └── text_sources/            # one JSON file per fetched document
├── eval/                        # cases.jsonl (30 cases), run_eval.py, results/
├── web/index.html               # web page (served by the API at /)
├── var/                         # local SQLite databases (gitignored)
└── README.md
```

## 7. Status

Done: skeleton, corpus (490+ documents, 10 domains, 2 source types), full pipeline, scoring, web page,
Discord bot (scenarios G and J tested live), safety and privacy basics, URL input, EUvsDisinfo
matching (scenario I), single input box (model recognises the input kind, links fetched by code),
screenshot input (scenario F), web-search fallback. 30-case evaluation (latest: macro-F1 0.97,
accuracy 97%, abstention 100%, injection 100%, median 7.2 s, $0.004 per check).
