"""Compare rule and AI ranking on reviewed, synthetic matching examples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.worker.ai import OpenAIClient, activity_card, ai_status, analyze_report
from services.worker.engine import extract_events, parse_schedule, rank_activities


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", action="store_true", help="Call the configured OpenAI models as well")
    parser.add_argument("--reranker", choices=("llm", "cross_encoder"),
                        help="Override the configured AI reranker for this comparison")
    parser.add_argument("--cases", type=Path, default=ROOT / "data/samples/matching-eval.jsonl")
    args = parser.parse_args()
    fixture = ROOT / "data/samples/pump-station.xer"
    activities, relationships, _ = parse_schedule(fixture.read_text(), fixture.name)
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    client = OpenAIClient() if args.ai else None
    reranker = args.reranker or ai_status()["reranker"]
    vectors = None
    if client:
        vectors = dict(zip((activity["external_id"] for activity in activities),
                           client.embed([activity_card(activity) for activity in activities])))
    results = {"rules": {"top1": 0, "top3": 0, "kind": 0}}
    if client:
        results["ai"] = {"top1": 0, "top3": 0, "kind": 0, "errors": 0, "reranker": reranker}
    for case in cases:
        event = extract_events(case["report"], case["date"])[0]
        rules = rank_activities(event, activities)
        results["rules"]["top1"] += rules[0]["activity_id"] == case["expected_task_id"]
        results["rules"]["top3"] += case["expected_task_id"] in [item["activity_id"] for item in rules[:3]]
        results["rules"]["kind"] += event["kind"] == case["expected_kind"]
        if client:
            try:
                ai_events = analyze_report(case["report"], case["date"], "", "", activities,
                                           relationships, vectors, client, reranker)
                ai_event = ai_events[0]
                ranked = ai_event["candidates"]
                results["ai"]["top1"] += ranked[0]["activity_id"] == case["expected_task_id"]
                results["ai"]["top3"] += case["expected_task_id"] in [item["activity_id"] for item in ranked[:3]]
                results["ai"]["kind"] += ai_event["kind"] == case["expected_kind"]
            except Exception as exc:
                results["ai"]["errors"] += 1
                ranked = []
                print(f"AI error for {case['expected_task_id']}: {type(exc).__name__}: {exc}")
        print(f"{case['expected_task_id']}: rules={rules[0]['activity_id']}" +
              (f", ai={ranked[0]['activity_id'] if ranked else 'error'}" if client else ""))
    print(json.dumps({"cases": len(cases), "correct_counts": results}, indent=2))


if __name__ == "__main__":
    main()
