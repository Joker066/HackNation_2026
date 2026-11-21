# Sources, licences and data handling

The system answers **only** from the audited source catalogue [`corpus/sources.csv`](../corpus/sources.csv).
A document can enter the corpus only if it matches a catalogue row; every answer cites the
publisher, date, link and a verbatim quote.

## Catalogue columns

| Column | Meaning |
|---|---|
| `credibility` | 1–5. 5 = the body legally responsible for the fact, publishing first-hand; 4 = official but general, regional or aggregating; 3 = secondary (fact-check aggregator, EUvsDisinfo). Fact-checkers get their own value in [`corpus/factcheckers.csv`](../corpus/factcheckers.csv) (IFCN/EFCSN signatories 4). |
| `role` | `evidence` or `context_only` (shown to the user, never decides a verdict: EUvsDisinfo). |
| `update_frequency` | How fast the source's information goes stale; sets the recency half-life in scoring. |
| `ingest_method` | `html` (crawled), `api`, `dynamic` (JavaScript app, not crawled), `blocked` (the site refuses automated access via robots.txt or a bot challenge; we do not circumvent it). |
| `licence` | Licence or legal basis stated by the publisher (checked 2026-11-21). |
| `storage` | What we keep: `full_text`, `excerpt` (opening of the article, ~700 characters), `metadata` (claim, rating, title, link), `none`. |

## Qualification rules

- **Add** a source if it is (a) the body legally responsible for the information, (b) another
  public authority, or (c) a fact-checker following IFCN/EFCSN standards; and its terms allow at
  least quoting with attribution.
- **Credibility** is assigned by the rule above, not by popularity or political orientation.
- **Exclude** a source if its licence forbids reuse, it loses accreditation, it repeatedly
  publishes factual errors, or it blocks automated access (we never bypass protections).
- A source's identity, credibility or sanction status never decides a verdict on its own; only
  verified quotes do (see `STRUCTURE.md`, section 4).

## Licences and what we store

| Sources | Licence / basis | Storage |
|---|---|---|
| gov.pl sections (RCB, GIS, MON, KG PSP, MSWiA, KPRM, Ministry of Infrastructure) | **CC BY-SA 4.0** (gov.pl terms of use) | full text |
| CERT Polska advisories (moje.cert.pl) | **CC BY-SA 4.0** (stated on the site) | full text |
| Police (policja.pl, regional *.policja.gov.pl) | no licence stated; public authority — public sector information, re-use under the Polish act on open data and re-use of public sector information (2021) | full text |
| Maritime Office Gdynia (umgdy.gov.pl) | "© 2021" notice; public authority — same basis as above | full text |
| Railway Protection Guard (kgsok.pl, part of PKP PLK S.A.) | © KG SOK, all rights reserved | **excerpt only** (+ link) |
| Fact-checks via Google Fact Check Tools API (Demagog, OKO.press, AFP, …) | ClaimReview metadata, published for reuse by search engines | **metadata only** (+ link to the full fact-check) |
| EUvsDisinfo (MCP API) | EU institutions' reuse policy, attribution (to verify) | excerpt (≤ 2,500 characters) |
| Media found by live web search (PAP, Polskie Radio, TVP Info, Rzeczpospolita, Polsat News, RMF24, Wirtualna Polska, Bankier.pl, Euronews, France 24, Notes from Poland, OKO.press; one outlet per ownership group, used only when own sources are insufficient) and other gov.pl sections | © publishers / CC BY-SA 4.0 | **not stored**: read once for a single check |

**Attribution.** Every answer shows the publisher, publication date and a link to the original.
The documents in `corpus/text_sources/` keep their original licence (CC BY-SA 4.0 for gov.pl and
CERT material); see [`corpus/text_sources/README.md`](../corpus/text_sources/README.md).

This is our reading of the publishers' terms, not legal advice; the "to verify" items should be
confirmed before a public deployment.

## Live web search (fallback)

When our own sources leave a claim at "brak wystarczających dowodów", the system searches the web
**only on the catalogue's domains** (allowlist built from `sources.csv`; rows with `ingest_method =
search` exist only for this). Our own fetcher reads the result pages; they go through the same
assessment, verbatim quote check and scoring. Media rows have credibility 3, so one article alone
never decides (two independent publishers can). Search results can confirm or refute, but cannot
by themselves mark a claim "misleading". Pages found this way are never stored. Cost: ~$0.01 per
search (only for undecided claims).

## Updates

- Crawlers (`backend/crawlers/`) fetch new articles and skip documents already saved; snapshot
  sources (RCB daily report) store one dated version per day.
- Fact-checks and EUvsDisinfo matches are fetched live per question and cached.
- `python -m scripts.build_index --rebuild` rebuilds the search index from the saved files.

## Retention and deletion

- **Full-text articles** stored by crawlers are deleted **12 months after publication**
  (`CORPUS_RETENTION_MONTHS`). `start.sh` applies this on every start.
- **Metadata and excerpts** (fact-checks, EUvsDisinfo, kgsok.pl) are kept until the source is removed.
- **User data** (the audit log of checks) is separate: personal data masked, deleted after 30 days
  (`RETENTION_DAYS`), and users can delete their own session.
- **Deletion on request** (e.g. by a publisher):
  ```bash
  cd backend
  ../.venv/bin/python -m scripts.purge_sources --catalog-id 28 --rebuild-index   # a whole source
  ../.venv/bin/python -m scripts.purge_sources --url https://… --rebuild-index    # one document
  ```
  and set the source's `storage` to `none` in `corpus/sources.csv` so it is not crawled again.
