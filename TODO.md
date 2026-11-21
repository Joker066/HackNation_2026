# TODO

## Next
- [x] **Discord live test** (2026-11-21): token reset, bot on the demo server; `/sprawdz`, @mention and
      DM work; scenario G passed (same verdict −0.8 and same Demagog source on web and Discord);
      scenario J passed (API down → "błąd techniczny", no verdict); 2,000-character limit unit-tested.
- [ ] Set `DISCORD_INVITE_URL` (non-expiring invite for the jury) so the web page shows the join button.
- [x] **EUvsDisinfo connector** (scenario I): search known disinformation cases per claim; show
      matches as `source_warnings` / `context_only` evidence (weight 0, never decides a verdict).
- [ ] **Answer quality**: too many "can't verify" answers and low |score|. Diagnose and fix
      retrieval, claim extraction and scoring.
- [ ] **30-case test set** (`eval/`): scenarios A–J + script for the required metrics
      (macro-F1, citation coverage/correctness, abstention, injection resistance, latency, cost).

## Later
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
