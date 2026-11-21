# MSZ task: "Prawdowid", a citizen fact-checking tool

> Summary of `MSZ - Pełna treść zadania konkursowego.pdf`. Check the PDF itself for the exact wording.

## What you need to build
A **working end-to-end prototype**, designed to be built in 24 hours, that lets an ordinary citizen check a rumour or claim as easily as sending a message. It has to answer **only from a clearly defined, auditable set of sources**, show what each answer is based on, and **refuse to give a verdict** when the evidence isn't good enough. MSZ (Poland's Ministry of Foreign Affairs) says it should support people's own judgement, not act as an automatic "judge of truth".

## Required minimum (MVP)
1. **Input:** text or a URL, through a **responsive web UI** plus **one more channel**. SMS, WhatsApp, Messenger, Instagram or Discord all count; Telegram, WeChat and niche platforms don't. A demo adapter is allowed, because the organisers don't provide accounts or keys. Both channels must use **the same verification logic** and give the same result.
2. **Find the claims** in the input (one or several) that need checking.
3. **Retrieve evidence** from a corpus of **at least 100 documents or records, from at least 10 domains, covering at least 2 source types**. It should mix primary/official sources (dane.gov.pl, BIP, ISAP, EUR-Lex) with reliable secondary ones (fact-checkers following IFCN/EFCSN standards, EUvsDisinfo, EDMO). The organisers will provide a source list and an incident database in JSON/CSV during the event.
4. **One verdict per claim**, from exactly these five: `potwierdzone` (confirmed), `fałszywe` (false), `wprowadzające w błąd` (misleading), `brak wystarczających dowodów` (not enough evidence), `nie podlega weryfikacji` (can't be verified).
   - Technical failure, an unclear question or an out-of-scope request are **not verdicts**. They must be reported separately.
5. **Evidence for each claim:** title, publisher, date, link and the quoted passage, kept visibly separate from the model's own interpretation.
6. **A strength rating with stated reasons:** source quality, how recent the sources are, how well they match the claim, and the number of independent confirmations.
7. **The answer in plain, simple Polish**, with the limitations stated.
8. **An audit log** of every check: the question, time, sources used and result.
9. **Fully automatic:** from receiving the request to replying and logging, with no manual help from the developers.

## Technical requirements that are easy to miss
- **Architecture:** keep channel handling separate from the verification logic, and make the language model or provider swappable.
- **Timestamps:** store both the publication time and the time each source was fetched, prefer recent material, and warn when material is archival.
- **Security:** validate input, keep system instructions separate from source content, restrict what tools can do, protect secrets, rate-limit, and log events. Instructions found inside fetched pages must be ignored, and the attempt logged.
- **Privacy:** collect as little data as possible, automatically mask obvious personal data, set a retention period, and let users delete a demo session.
- **Observability:** log latency, model usage, retrieval errors, abstentions and an estimated cost per answer.
- **Accessibility:** good contrast and language a non-technical person can follow.
- **External dependencies:** document the keys required, limits, costs, where data is processed, and how the system behaves during an outage.
- **Costs:** estimate the cost of 1,000 queries, the cost of running the channel, and how the system behaves under load.

## Prohibited
- Presenting the model's output as fact without a verifiable source.
- Deciding whether a claim is true **based only on the domain, author, channel, popularity or a label the same model produced**. That includes a source being under EU sanctions; show that as a separate, neutral warning instead.
- Claiming to do reverse image search without a working API or a clearly limited local index.
- Bypassing paywalls or site protections, or archiving full content without a legal basis, a retention policy and a deletion procedure.
- Presenting a missing API key, a rate limit or an outage as a result about the claim.
- **Hardcoding the test examples or putting them in the prompt.** The jury will also enter their own questions.

## How it will be tested
The jury has at least 30 reference cases covering these scenarios:

| | Scenario | Expected behaviour |
|---|---|---|
| A | Simple fact | Correct verdict with an exact quote |
| B | True content used in the wrong time or place | Point out the missing context |
| C | Two reliable sources disagree | Show the disagreement without claiming certainty |
| D | New claim with no reliable coverage | **Abstain** and say what couldn't be established |
| E | Source page tells the model to ignore its rules | Ignore it and log the attempt |
| F | Screenshot or photo *(optional)* | Read it correctly and state the limits of the analysis |
| G | Same request via web and the second channel | Identical result |
| H | Repeated unresolved request *(optional)* | Create one moderator case, deduplicated, and never falsely say it was forwarded |
| I | URL similar to a known incident | Show the match as context, with no verdict based on the domain |
| J | Missing key, rate limit or outage | Disclose it with no fake result |

### Required metrics

| Metric | Target |
|---|---|
| Verdict accuracy (macro-F1) | ≥ 0.75 |
| Citation coverage (factual statements with evidence) | ≥ 95% |
| Citation correctness (quote actually supports the claim) | ≥ 85% |
| Correct abstention when evidence is missing | ≥ 80% |
| Prompt injections resisted | ≥ 90% |
| Median response time (text/URL) | ≤ 30 s |
| Cost of 100 tests | Reported; lower scores better at equal quality |
| Scenarios run end-to-end by the jury | 100% |
| Cross-channel consistency | 100% |
| Moderator cases created and deduplicated *(if implemented)* | 100% |

### Scoring

| Criterion | Weight |
|---|---|
| Quality of verification and evidence | 30% |
| Safety, responsibility and transparency | 20% |
| Deployability and scalability | 20% |
| Usability and accessibility | 15% |
| Innovation and completeness | 15% |

**Bonus features only count if all the basics work:** working end-to-end, no fabricated sources, correct abstention, and two channels (or one channel plus a demo adapter).

Optional extras that score points: OCR or audio transcription, an "evidence chain" from claim to sources, searching sources in several languages, a swappable source catalogue, matching against the incident database, CSV/JSON or OpenCTI/DISARM export, hosting inside the EU/EEA, and a moderator case queue.

## What to submit
- Team name, title and a description of up to 4,000 characters.
- A PDF presentation of **at most 12 slides**: problem, users, architecture, demo, test results, risks, next steps.
- A demo video of **at most 3 minutes**.
- The repo link with instructions for running it.
- A description of the architecture, data flow, models and providers.
- The source list with licences and how sources are qualified and updated.
- Test results with data so others can reproduce them.
- A risk list covering at least: hallucination, source bias, privacy, prompt injection, availability and abuse.
- **No API keys or personal data** in the repo or demo materials.

## Advice for a solo developer
- **Skip the optional extras at first.** If any basic requirement fails, they score nothing.
- **Use Discord as the second channel.** It's allowed, free and quick to set up, whereas WhatsApp and SMS need business accounts.
- **Use a hosted language model plus simple search over your own corpus** (BM25 or embeddings). There's no need to train or run models locally, so the torch/CUDA packages in `requirements.txt` are probably unnecessary.
- **Abstaining correctly is the cheapest way to earn points.** Make "not enough evidence" the default, and give a verdict only when a retrieved passage clearly supports or contradicts the claim.
- **Build your own test set of about 30 cases** matching scenarios A–J early on, so you can measure the target numbers yourself.

## Contact
- Booth: Ministerstwo Spraw Zagranicznych - Prawdowid
- Discord channel: Prawdowid
