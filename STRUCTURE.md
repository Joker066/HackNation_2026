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
| Frontend | Existing **Vite + React** in `frontend/` | Already set up |
| Second channel | **Discord bot** (`discord.py`) | Allowed by the task, free, no business account; reliable for the jury demo |
| Channel mock-up | **SMS demo page** in the web UI (bonus, step 9) | Shows the 70-character SMS reply + link that real citizens would get; real SMS is just another adapter later |
| Search | **SQLite FTS5 / BM25** first, embeddings later if time allows | No extra infrastructure |
| LLM | **Claude (`claude-opus-5-5`, effort `low`)** behind a provider interface; `fake` provider for offline dev/tests | Task requires a swappable model; an EU provider (e.g. Mistral) can be added as one more file |
| Storage | **SQLite** (audit log, cases, corpus) | One file, easy for the jury to run |
| Packaging | `docker-compose` (api + bot + frontend) | Jury can start it with one command |

Torch/CUDA are **not needed** — `requirements.txt` will be replaced with a lean list.

## 6. Directory layout

```
HackNation_2026/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI routes: /api/check, /api/check/{id}, /api/session/{id},
│   │   │                        #   /api/health, /api/logs, /api/metrics
│   │   ├── config.py            # settings from env (.env, never committed)
│   │   ├── schemas.py           # response contract (Pydantic)
│   │   ├── pipeline/
│   │   │   ├── ingest.py        # validation, safe URL fetch (SSRF guard), HTML→text
│   │   │   ├── claims.py        # claim extraction (LLM)
│   │   │   ├── assess.py        # stance per passage (LLM) + verbatim quote check (code)
│   │   │   ├── verdict.py       # deterministic rule engine
│   │   │   ├── compose.py       # Polish answer from templates + verified evidence
│   │   │   └── run.py           # orchestrator used by every channel
│   │   ├── llm/
│   │   │   ├── base.py          # LLMProvider interface + LLMError
│   │   │   ├── anthropic_provider.py
│   │   │   └── fake.py          # offline provider: always abstains
│   │   ├── security/
│   │   │   ├── pii.py           # mask emails, phones, PESEL, IBAN
│   │   │   ├── injection.py     # detect + log injection attempts
│   │   │   └── ratelimit.py
│   │   └── store/
│   │       ├── db.py            # SQLite connection helper
│   │       ├── corpus.py        # documents + FTS5 passages, catalogue check
│   │       └── audit.py         # check log, metrics, retention, session delete
│   ├── channels/
│   │   └── discord_bot.py       # thin adapter → calls the API, formats the reply
│   ├── scripts/
│   │   └── build_index.py       # corpus/records/*.jsonl → SQLite FTS index
│   └── tests/
├── corpus/
│   ├── sources.csv              # audited catalogue: claim types, credibility 1-5, role, update frequency
│   └── records/                 # collected documents as JSONL (one document per line)
├── var/                         # local SQLite databases (gitignored)
├── eval/
│   ├── cases.jsonl              # our own ~30 cases covering scenarios A–J
│   ├── run_eval.py              # computes macro-F1, citation coverage, abstention, latency, cost
│   └── results/                 # saved reports (for the submission)
├── frontend/                    # Vite + React web UI
├── docs/
│   ├── architecture.md
│   ├── sources.md               # sources, licences, qualification rules
│   └── risks.md                 # hallucination, bias, privacy, injection, availability, abuse
├── docker-compose.yml
├── .env.example
├── instruction.md
├── STRUCTURE.md
└── README.md                    # run instructions + submission summary
```

## 7. Build order

1. **Skeleton:** FastAPI `/check` returning the response contract with a fake pipeline; the web UI renders it.
2. **Corpus:** `sources.csv` + 100+ documents from 10+ domains, 2+ source types (official + fact-check); FTS index.
3. **Pipeline:** claims → retrieve → assess → verdict → compose, end to end on text input.
4. **Eval set:** write ~30 cases for A–J and run `run_eval.py`; tune the rules.
5. **Discord bot** using the same API; check that results match across channels.
6. **Safety and privacy:** PII masking, injection logging, rate limiting, session delete, error statuses.
7. **URL input** + archival warnings + incident-database matching (data arrives during the event).
8. **Submission:** README, docs, risks, cost estimate for 1,000 queries, slides, 3-minute video.
9. **Bonus, only if 1–8 are solid:** OCR for screenshots, moderator case queue, CSV/JSON export.

## 8. Decisions and open questions

Decided:
- **LLM:** Claude (`claude-opus-5-5`), swappable via `LLM_PROVIDER`.
- **Second channel:** Discord bot; SMS shown as a demo page (bonus).

Open:
- **Discord:** which server to test the bot on?
- **Corpus:** organisers published their source list (`lista_źródeł.txt` → `corpus/sources.csv`); next: crawler, Google Fact Check connector, EUvsDisinfo token.
- **Moderator cases** (scenario H) and **incident matching** (scenario I) are not built yet.
