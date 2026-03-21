from unittest.mock import patch

from app.utils import fpocket_runner


def test_run_fpocket_empty_pdb():
    out = fpocket_runner.run_fpocket("")
    assert out["success"] is False
    assert "Empty" in (out.get("error") or "")


def test_run_fpocket_missing_binary():
    with patch.object(fpocket_runner.shutil, "which", return_value=None):
        out = fpocket_runner.run_fpocket("ATOM      1  N   ALA A   1\n")
        assert out["success"] is False
        assert "fpocket" in (out.get("error") or "").lower()
