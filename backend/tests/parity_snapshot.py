"""Compare a saved game result with a reference game."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def snapshot(raw, forecast, negotiation_report, newspaper, illustration_sha256):
    return {
        **{key: raw[key] for key in ("status", "total_cost", "total_money", "deficit",
                                     "consensus_reached", "voting_summary")},
        "conditions": raw["state"]["levers"],
        "finances": raw["state"]["players"],
        "demands": raw["state"]["demands"],
        "turns": [{"turn": turn["turn"], "phase": turn["phase"], "speaker": turn["speaker"],
                   "target": turn.get("target"), "last_call": turn.get("is_last_call", False),
                   "status": turn["action"]["status"], "speech": turn["action"]["message"],
                   "applied": turn["action"].get("applied", [])} for turn in raw["history"]],
        "forecast": forecast,
        "newspaper": newspaper,
        "negotiation_report_sha256": hashlib.sha256(negotiation_report.encode("utf-8")).hexdigest(),
        "illustration_sha256": illustration_sha256,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("case")
    parser.add_argument("actual_snapshot", type=Path)
    args = parser.parse_args()
    expected = json.loads(args.references.read_text(encoding="utf-8"))["cases"][args.case]["expected"]
    actual = json.loads(args.actual_snapshot.read_text(encoding="utf-8"))
    expected_lines, actual_lines = [json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2).splitlines()
                                    for item in (expected, actual)]
    if expected_lines != actual_lines:
        print("\n".join(difflib.unified_diff(expected_lines, actual_lines, fromfile="Reference", tofile="Actual")))
        raise SystemExit(1)
    print(f"{args.case}: reference and actual snapshots match")


if __name__ == "__main__":
    main()
