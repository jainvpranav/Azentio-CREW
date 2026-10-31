"""
Score classification accuracy against data_gen/output/ground_truth.json.

Run with:
    venv/Scripts/python.exe -m eval.score

Requires the demo files (data_gen/output/*) to already be uploaded and
classified in the running app's database. BUILD_PLAN.md section 7: "eval/
score.py prints per-category precision/recall vs ground truth."
"""
import json
import os
from collections import defaultdict

from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Transaction, Classification

GROUND_TRUTH_PATH = os.path.join(os.path.dirname(__file__), "..", "data_gen", "output", "ground_truth.json")


def load_ground_truth(path: str = GROUND_TRUTH_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_predictions(session: Session) -> dict:
    """key '<filename>#<row_index>' -> predicted category (current classification only)"""
    documents = {d.id: d.filename for d in session.exec(select(Document)).all()}
    predictions = {}

    for txn in session.exec(select(Transaction)).all():
        # Note: duplicate-marked rows are intentionally still scored here -
        # classification runs independently of dedup, and the ground truth
        # keys every row in every uploaded file, overlaps included.
        classification = session.exec(
            select(Classification)
            .where(Classification.txn_id == txn.id)
            .where(Classification.is_current == True)
        ).first()
        if not classification:
            continue
        filename = documents.get(txn.document_id)
        if not filename:
            continue
        predictions[f"{filename}#{txn.row_index}"] = classification.category.value

    return predictions


def compute_score(session: Session, ground_truth: dict = None) -> dict:
    ground_truth = ground_truth if ground_truth is not None else load_ground_truth()
    predictions = load_predictions(session)

    total = correct = missing = 0
    per_category = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    mistakes = []

    for key, expected in ground_truth.items():
        total += 1
        predicted = predictions.get(key)

        if predicted is None:
            missing += 1
            per_category[expected]["fn"] += 1
            mistakes.append({"key": key, "expected": expected, "predicted": None})
            continue

        if predicted == expected:
            correct += 1
            per_category[expected]["tp"] += 1
        else:
            per_category[expected]["fn"] += 1
            per_category[predicted]["fp"] += 1
            mistakes.append({"key": key, "expected": expected, "predicted": predicted})

    report = {}
    for category, stats in per_category.items():
        tp, fp, fn = stats["tp"], stats["fp"], stats["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        report[category] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}

    return {
        "accuracy": correct / total if total else None,
        "correct": correct,
        "total": total,
        "missing": missing,
        "per_category": report,
        "mistakes": mistakes,
    }


def print_report(result: dict) -> None:
    acc = result["accuracy"]
    if acc is None:
        print("No ground truth found.")
        return

    print(f"Classification accuracy on test set: {acc:.1%} ({result['correct']}/{result['total']})")
    if result["missing"]:
        print(f"  {result['missing']} ground-truth transactions not found in DB "
              f"(upload + classify the demo files first)")
    print()
    print(f"{'Category':<22} {'Precision':>10} {'Recall':>10} {'F1':>8} {'Support':>8}")
    for category in sorted(result["per_category"]):
        s = result["per_category"][category]
        print(f"{category:<22} {s['precision']:>10.1%} {s['recall']:>10.1%} {s['f1']:>8.1%} {s['support']:>8}")

    if result["mistakes"]:
        print(f"\nMisclassifications ({len(result['mistakes'])}):")
        for m in result["mistakes"]:
            print(f"  {m['key']:<45} expected={m['expected']:<20} predicted={m['predicted']}")


def main():
    with Session(engine) as session:
        result = compute_score(session)
    print_report(result)


if __name__ == "__main__":
    main()
