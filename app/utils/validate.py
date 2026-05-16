from typing import Any, Dict, List, Set, Tuple


def validate_pocket(predicted_residues: List[int], known_residues: List[int], tolerance: int = 2) -> Dict[str, Any]:
    """
    Compare predicted pocket residues against a known binding site with residue
    tolerance (abs(pred-known) <= tolerance).
    Returns one-to-one matches plus precision/recall/F1.
    """
    predicted: Set[int] = set(int(r) for r in predicted_residues)
    known: Set[int] = set(int(r) for r in known_residues)

    if tolerance < 0:
        tolerance = 0

    unmatched_known: Set[int] = set(known)
    matched_pairs: List[Tuple[int, int]] = []

    # Greedy one-to-one matching: each known residue can match at most one predicted residue.
    for p in sorted(predicted):
        candidates = [k for k in unmatched_known if abs(p - k) <= tolerance]
        if not candidates:
            continue

        best_k = min(candidates, key=lambda k: (abs(p - k), k))
        unmatched_known.remove(best_k)
        matched_pairs.append((p, best_k))

    matched_predicted: Set[int] = {p for p, _ in matched_pairs}
    matched_known: Set[int] = {k for _, k in matched_pairs}

    tp = len(matched_pairs)
    fp = max(0, len(predicted) - tp)
    fn = max(0, len(known) - tp)

    precision = (tp / (tp + fp)) if (tp + fp) else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "predicted_count": len(predicted),
        "known_count": len(known),
        "matched_predicted_count": tp,
        "matched_known_count": tp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matched_predicted": sorted(matched_predicted),
        "matched_known": sorted(matched_known),
    }


def extract_best_predicted_residues(result: Dict[str, Any]) -> List[int]:
    """
    Pick the best predicted pocket from a stored result payload.
    Preference:
      1) highest-ranked confident pocket
      2) highest-ranked pocket
    """
    pockets_payload = result.get("pockets") or {}
    pockets = pockets_payload.get("pockets", []) if isinstance(pockets_payload, dict) else []
    if not pockets:
        return []

    sorted_pockets = sorted(pockets, key=lambda p: p.get("rank", 10_000))
    confident = [p for p in sorted_pockets if p.get("confident")]
    chosen = confident[0] if confident else sorted_pockets[0]
    residues = chosen.get("residues") or []
    return [int(r) for r in residues]
