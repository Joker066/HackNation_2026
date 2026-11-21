# TODO

## Next
- [x] **Discord live test** (2026-11-21): token reset, bot on the demo server; `/sprawdz`, @mention and
      DM work; scenario G passed (same verdict −0.8 and same Demagog source on web and Discord);
      scenario J passed (API down → "błąd techniczny", no verdict); 2,000-character limit unit-tested.
- [x] `DISCORD_INVITE_URL` set (server "Tap & Check demo", #sprawdz); the web page shows the join button.
- [ ] Replace the invite with a **non-expiring** one: the current link expires on 2026-12-21.
- [x] **EUvsDisinfo connector** (scenario I): search known disinformation cases per claim; show
      matches as `source_warnings` / `context_only` evidence (weight 0, never decides a verdict).
- [x] **Answer quality, round 1**: questions → statements; recency only for time-sensitive claims;
      announced decisions are factual (not predictions); fact-check ratings translated by code;
      abstentions name the source that would be needed; score hidden for "misleading"; at most
      2 EUvsDisinfo notes per claim.
- [x] **30-case test set** (`eval/cases.jsonl`, `eval/run_eval.py`). Latest (Haiku, effort low):
      macro-F1 0.91, accuracy 90%, citation coverage 100%, abstention 100%, injection 100%,
      median 5.2 s, $0.001/check. Effort `medium` measured: F1 0.90, 8.1 s, +34% cost → keep `low`.
- [x] **Recency fix**: decay by how fast information goes stale (warnings hours, RCB snapshot 1 day,
      news/decisions 180 days, fact-checks/laws never) → macro-F1 0.93.
- [x] **Coverage: web-search fallback** on catalogue domains (+ media rows PAP, Polskie Radio, TVP Info,
      Rzeczpospolita, credibility 3, never stored); JSON-LD article text for JavaScript news pages
      → macro-F1 0.97, accuracy 97%, $0.004/check, median 7.2 s.
- [x] **Single input box** (model recognises the input kind; links in messages fetched by code).
- [x] **Screenshot / photo input** (scenario F) on web and Discord.
- [ ] **Answer quality, round 3** (remaining failures):
  - PGE scam message sometimes just under the threshold (−0.69);
  - Google Fact Check queries vary between runs → a known Demagog check is sometimes not found;
  - fact-checks of related variants of a claim count only as context (e.g. "biolabs").
- [ ] Eval: scenarios F (screenshot), H (repeat question) and J (forced outage, live) are not in the set;
      manually spot-check that quotes really support the claims (task metric "poprawność cytowania").

## Later
- [x] **Licences**: `licence` + `storage` columns in `corpus/sources.csv`; kgsok.pl excerpts only;
      retention (12 months for crawled full texts) and deletion (`scripts/purge_sources.py`);
      documented in `docs/sources.md`. Still to verify: EUvsDisinfo reuse terms.
- [x] Generic gov.pl crawler: 7 sections (fire service, MON, GIS, Infrastructure, RCB, MSWiA, KPRM),
      190 articles; corpus now 764 documents, 14 domains.
- [ ] MSZ travel advice: per-country embassy sites, info pages rendered by JavaScript (not crawlable
      as is); Wody Polskie navigation notices: 10 regional sites with different layouts.
- [ ] Docker (`docker compose up`) and deployment to an EU-hosted server for the judging period.
- [ ] **Scam message detection** (e.g. "mam Twojego wnuka, przelej 10 tys."):
  - corpus: police/CERT prevention pages on "metoda na wnuczka", "na policjanta", fake
    kidnapping, BLIK scams (fixed-URL crawler);
  - claim extraction flags messages that demand urgent money/data, threaten or impersonate;
  - show a warning quoting the matching police/CERT source + fixed safety advice
    ("Nie przelewaj pieniędzy. Zadzwoń do bliskiej osoby na znany Ci numer. W razie zagrożenia: 112.");
    advice is not a verdict.
- [ ] **Media sources** (`SourceType.media`, currently unused): add reliable news outlets (e.g. PAP,
      public broadcaster news, Reuters/AP Polish desks) as secondary evidence for general news that
      official sources and fact-checkers don't cover (e.g. "strajk we Włoszech", trade tariffs).
      Needs: catalogue rows with credibility (below official, around fact-checkers), licence check
      (excerpts only, no full articles), and a crawler or search API.
- [ ] Moderator cases for repeated unresolved questions (scenario H, optional).
- [ ] Submission: description (≤4000 chars), ≤12 slides, ≤3 min video, architecture, sources and
      licences, risks, cost of 1,000 queries.

## Done
- [x] v1: web page + API + Discord bot, 418 documents from 10 domains, real model checks.
