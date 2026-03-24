import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set


def align_structures(
    pdb1_text: str,
    pdb2_text: str,
    name1: str = "ref",
    name2: str = "mobile",
) -> Dict[str, Any]:
    """Align two PDB structures with TM-align and return mapping/statistics.

    Returns a dictionary with:
    - tm_score: TM-score in [0, 1]
    - rmsd: superposition RMSD (angstrom)
    - aligned_length: alignment length
    - residue_mapping: mapping from residues in structure1 to structure2
    - rotation/translation: rigid transform from structure2 onto structure1
    """
    try:
        from tmtools import tm_align
    except ImportError as exc:
        raise ImportError("Run: pip install tmtools biopython") from exc

    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / f"{name1}.pdb"
        p2 = Path(tmp) / f"{name2}.pdb"
        p1.write_text(pdb1_text, encoding="utf-8")
        p2.write_text(pdb2_text, encoding="utf-8")
        result = tm_align(p1, p2)

    mapping: Dict[int, int] = {}
    aligned_1 = getattr(result, "aligned_residues1", [])
    aligned_2 = getattr(result, "aligned_residues2", [])
    for idx, res1 in enumerate(aligned_1):
        res2 = aligned_2[idx]
        if res1 != "-" and res2 != "-":
            mapping[int(res1)] = int(res2)

    return {
        "tm_score": round(float(result.tm_score), 3),
        "rmsd": round(float(result.rmsd), 2),
        "aligned_length": int(result.aligned_length),
        "residue_mapping": mapping,
        "rotation": result.rotation.tolist(),
        "translation": result.translation.tolist(),
    }


def invert_residue_mapping(ref_to_mobile: Dict[int, int]) -> Dict[int, int]:
    """Invert ref→mobile mapping from :func:`align_structures` (mobile residue → ref)."""
    inv: Dict[int, int] = {}
    for ref_res, mob_res in ref_to_mobile.items():
        if mob_res not in inv:
            inv[mob_res] = ref_res
    return inv


def map_pocket_residues(residues: List[int], mapping: Dict[int, int]) -> Set[int]:
    """Map residue numbers that live in **reference** numbering through ref→mobile mapping."""
    return {mapping[r] for r in residues if r in mapping}
