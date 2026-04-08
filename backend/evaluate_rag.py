"""Simple benchmark runner for KRMU retrieval quality."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from rag_engine import rag_engine


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT_DIR / "datasets" / "krmu_eval_questions.json"


def _load_dataset(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _score_hit(question: str, expected_keywords: List[str], top_k: int) -> dict:
    result = rag_engine.evaluate_retrieval(question, top_k=top_k)
    top_text = " ".join(
        f"{item.get('metadata', {}).get('document_title', '')} {item.get('chunk_text', '')}"
        for item in result.get("results", [])
    ).lower()
    matched_keywords = [keyword for keyword in expected_keywords if keyword.lower() in top_text]
    return {
        "question": question,
        "matched_keywords": matched_keywords,
        "expected_keywords": expected_keywords,
        "hit": len(matched_keywords) > 0,
        "top_result": result.get("results", [{}])[0] if result.get("results") else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate KRMU retrieval benchmarks.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to benchmark JSON.")
    parser.add_argument("--top-k", type=int, default=5, help="How many chunks to inspect.")
    parser.add_argument("--fail-only", action="store_true", help="Print only failed benchmark items.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    items = _load_dataset(dataset_path)

    hits = 0
    for item in items:
        outcome = _score_hit(item["question"], item.get("expected_keywords", []), args.top_k)
        hits += int(outcome["hit"])
        if args.fail_only and outcome["hit"]:
            continue

        status = "PASS" if outcome["hit"] else "FAIL"
        top_result = outcome["top_result"] or {}
        title = top_result.get("metadata", {}).get("document_title", "No result")
        print(f"[{status}] {item['id']} - {item['question']}")
        print(f"       matched: {', '.join(outcome['matched_keywords']) or 'none'}")
        print(f"       top source: {title}")
        print()

    total = len(items)
    accuracy = (hits / total * 100) if total else 0.0
    print(f"Benchmarks passed: {hits}/{total} ({accuracy:.1f}%)")


if __name__ == "__main__":
    main()
