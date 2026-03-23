"""
Integration: run real fpocket on a sample PDB (skipped if binary missing).
Uses vendored tmp_fpocket sample — same source as upstream fpocket tests.
"""

import shutil
from pathlib import Path

import pytest

from app.utils.fpocket_runner import run_fpocket

pytestmark = pytest.mark.integration

SAMPLE_PDB = (
    Path(__file__).resolve().parent.parent
    / "tmp_fpocket"
    / "data"
    / "sample"
    / "1UYD.pdb"
)


@pytest.mark.skipif(not shutil.which("fpocket"), reason="fpocket not on PATH")
@pytest.mark.skipif(not SAMPLE_PDB.is_file(), reason="sample PDB not found")
def test_run_fpocket_on_sample_1uyd():
    pdb_text = SAMPLE_PDB.read_text(encoding="utf-8", errors="replace")
    out = run_fpocket(pdb_text)
    assert out["success"] is True, out.get("error")
    assert isinstance(out["pockets"], list)
