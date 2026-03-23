"""Unit tests for PocketAgent pocket processing (composite score, consensus count)."""

from app.agents.PocketAgent import _process_pockets


def test_process_pockets_composite_and_consensus_dedup():
    pockets_by_model = {
        "esmfold": [
            {
                "pocket_id": 1,
                "residues": [10, 11, 12],
                "druggability_score": 0.8,
                "volume": 100.0,
                "hydrophobicity": 0.1,
                "alpha_sphere_count": 5,
            },
        ],
        "alphafold_db": [
            {
                "pocket_id": 1,
                "residues": [10, 11, 12],
                "druggability_score": 0.8,
                "volume": 100.0,
                "hydrophobicity": 0.1,
                "alpha_sphere_count": 5,
            },
        ],
    }
    plddt = {10: 80.0, 11: 80.0, 12: 80.0}
    out = _process_pockets(
        pockets_by_model,
        plddt,
        "test-job",
        best_model="esmfold",
        fallback_plddt_mean=None,
    )
    assert out["pocket_summary"]["consensus_pockets"] == 1  # one unique residue set with cross-model overlap
    pockets = sorted(out["pockets"], key=lambda p: p["model_name"])
    assert all(p["composite_score"] > 0 for p in pockets)


def test_fallback_plddt_restores_composite():
    pockets_by_model = {
        "experimental": [
            {
                "pocket_id": 1,
                "residues": [5, 6],
                "druggability_score": 0.5,
                "volume": 50.0,
                "hydrophobicity": 0.1,
                "alpha_sphere_count": 3,
            },
        ],
    }
    out = _process_pockets(
        pockets_by_model,
        {},
        "test-job",
        best_model="experimental",
        fallback_plddt_mean=75.0,
    )
    p = out["pockets"][0]
    assert p["local_plddt_mean"] == 75.0
    assert p["composite_score"] > 0
