"""Run the evaluation set and compute the task's metrics.

Usage (from the repository root):
    .venv/bin/python eval/run_eval.py [--cases eval/cases.jsonl]

Each case: {"id", "scenario", "input", "expected", optional "expect_security_event",
"expect_source_warning"}. The case's result is the verdict of its FIRST claim (the claim the
question is about); for multi-claim messages, any claim matching also counts as a hit.

Metrics (task section 6):
- verdict accuracy and macro-F1 over the verdict classes present in the set
- citation coverage: decided claims (confirmed/false/misleading) that have >= 1 evidence item
- citation correctness: quotes are verified verbatim against the source in code (reported)
- abstention: share of no-evidence cases answered "brak wystarczających dowodów"
- injection resistance: injection cases with a logged security event and an unaffected verdict
- latency (median, max) and cost of the run
Results are saved to eval/results/<timestamp>.json so they can be reproduced and compared.
"""

import argparse
import json
import logging
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.main import services  # noqa: E402
from app.pipeline.run import run_check  # noqa: E402
from app.schemas import CheckRequest  # noqa: E402

DECIDED = {"potwierdzone", "fałszywe", "wprowadzające_w_błąd"}
SESSION = "eval-run"


def macro_f1(pairs: list[tuple[str, str]]) -> float:
    labels = sorted({e for e, _ in pairs})
    scores = []
    for label in labels:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        fp = sum(1 for e, p in pairs if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(REPO / "eval" / "cases.jsonl"))
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    cost_before = services.audit.metrics()["total_cost_usd"] or 0.0
    rows = []
    for case in cases:
        started = time.monotonic()
        resp = run_check(services, CheckRequest(text=case["input"], channel="eval", session_id=SESSION))
        latency = time.monotonic() - started
        verdicts = [c.verdict.value for c in resp.claims]
        first = verdicts[0] if verdicts else f"status:{resp.status.value}"
        row = {
            "id": case["id"],
            "scenario": case["scenario"],
            "expected": case["expected"],
            "predicted": first,
            "all_verdicts": verdicts,
            "hit": case["expected"] == first or case["expected"] in verdicts,
            "score": resp.claims[0].score if resp.claims else None,
            "evidence": len(resp.claims[0].evidence) if resp.claims else 0,
            "decided_without_evidence": sum(1 for c in resp.claims if c.verdict.value in DECIDED and not c.evidence),
            "decided": sum(1 for c in resp.claims if c.verdict.value in DECIDED),
            "security_events": len(resp.security_events),
            "source_warnings": sum(len(c.source_warnings) for c in resp.claims),
            "latency_s": round(latency, 1),
            "status": resp.status.value,
        }
        if case.get("expect_security_event"):
            row["injection_ok"] = row["security_events"] > 0 and row["hit"]
        if case.get("expect_source_warning"):
            row["warning_ok"] = row["source_warnings"] > 0
        rows.append(row)
        mark = "✓" if row["hit"] else "✗"
        print(f"{mark} {case['id']:3} {case['scenario']:32} expected {case['expected']:28} got {first:28} "
              f"score={row['score']} ev={row['evidence']} {row['latency_s']}s")

    cost = (services.audit.metrics()["total_cost_usd"] or 0.0) - cost_before
    services.audit.delete_session(SESSION)

    decided = sum(r["decided"] for r in rows)
    abst = [r for r in rows if r["expected"] == "brak_wystarczających_dowodów"]
    inj = [r for r in rows if "injection_ok" in r]
    warn = [r for r in rows if "warning_ok" in r]
    latencies = [r["latency_s"] for r in rows]
    summary = {
        "cases": len(rows),
        "accuracy": round(sum(r["hit"] for r in rows) / len(rows), 3),
        "macro_f1": round(macro_f1([(r["expected"], r["predicted"]) for r in rows]), 3),
        "citation_coverage": round(1 - sum(r["decided_without_evidence"] for r in rows) / decided, 3) if decided else None,
        "citation_correctness": "quotes verified verbatim in code (unverifiable quotes are dropped)",
        "abstention_rate": round(sum(r["predicted"] == "brak_wystarczających_dowodów" for r in abst) / len(abst), 3) if abst else None,
        "injection_resistance": round(sum(r["injection_ok"] for r in inj) / len(inj), 3) if inj else None,
        "incident_warning_rate": round(sum(r["warning_ok"] for r in warn) / len(warn), 3) if warn else None,
        "latency_median_s": statistics.median(latencies),
        "latency_max_s": max(latencies),
        "cost_usd": round(cost, 4),
        "cost_per_check_usd": round(cost / len(rows), 5),
        "model": services.settings.llm_model,
        "confusion": Counter(f"{r['expected']} -> {r['predicted']}" for r in rows if not r["hit"]),
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))

    out = REPO / "eval" / "results" / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
