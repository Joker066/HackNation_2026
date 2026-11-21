# TODO

## Next
- [x] **Discord live test** (2026-11-21): token reset, bot on the demo server; `/sprawdz`, @mention and
      DM work; scenario G passed (same verdict −0.8 and same Demagog source on web and Discord);
      scenario J passed (API down → "błąd techniczny", no verdict); 2,000-character limit unit-tested.
- [ ] Set `DISCORD_INVITE_URL` (non-expiring invite for the jury) so the web page shows the join button.
- [x] **EUvsDisinfo connector** (scenario I): search known disinformation cases per claim; show
      matches as `source_warnings` / `context_only` evidence (weight 0, never decides a verdict).
- [x] **Answer quality, round 1**: questions → statements; recency only for time-sensitive claims;
      announced decisions are factual (not predictions); fact-check ratings translated by code;
      abstentions name the source that would be needed; score hidden for "misleading"; at most
      2 EUvsDisinfo notes per claim.
- [x] **30-case test set** (`eval/cases.jsonl`, `eval/run_eval.py`). Latest (Haiku, effort low):
      macro-F1 0.91, accuracy 90%, citation coverage 100%, abstention 100%, injection 100%,
      median 5.2 s, $0.001/check. Effort `medium` measured: F1 0.90, 8.1 s, +34% cost → keep `low`.
- [ ] **Answer quality, round 2** (remaining failures):
  - "Czy CERT ostrzega…?" sometimes still marked time-sensitive → 4-week-old advisory weighs 0.51;
  - Google Fact Check queries vary between runs → a known Demagog check is sometimes not found;
  - fact-checks of related variants of a claim count only as context (e.g. "biolabs").
- [ ] Eval: scenarios F (screenshot), H (repeat question) and J (forced outage, live) are not in the set;
      manually spot-check that quotes really support the claims (task metric "poprawność cytowania").

## Later
- [ ] **Licences** (compliance risk): add a licence column/basis to `corpus/sources.csv`; decide
      full texts vs excerpts in `corpus/text_sources/`; document retention and deletion.
- [ ] Docker (`docker compose up`) and deployment to an EU-hosted server for the judging period.
- [ ] **Scam message detection** (e.g. "mam Twojego wnuka, przelej 10 tys."):
  - corpus: police/CERT prevention pages on "metoda na wnuczka", "na policjanta", fake
    kidnapping, BLIK scams (fixed-URL crawler);
  - claim extraction flags messages that demand urgent money/data, threaten or impersonate;
  - show a warning quoting the matching police/CERT source + fixed safety advice
    ("Nie przelewaj pieniędzy. Zadzwoń do bliskiej osoby na znany Ci numer. W razie zagrożenia: 112.");
    advice is not a verdict.
- [ ] Generic gov.pl news crawler (GIS, MSZ travel advice, fire service, MON) for more official evidence.
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
