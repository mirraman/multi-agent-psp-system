"""
fpocket_runner.py
-----------------
Utility that runs the fpocket binary on a PDB string and returns structured
pocket data. fpocket is a C binary installed in the Docker image — it works
on files, not stdin, so we use NamedTemporaryFile throughout.

Pocket properties parsed from fpocket's *_info.txt output:
  - pocket_id        : int   — pocket rank (1 = best per fpocket scoring)
  - score            : float — fpocket druggability score (0–1 range, higher = more druggable)
  - volume           : float — pocket volume in Å³
  - hydrophobicity   : float — hydrophobicity score
  - alpha_sphere_count : int — number of alpha spheres (proxy for pocket size)
  - residues         : List[int] — residue sequence numbers lining the pocket
"""

import os
import re
import glob
import subprocess
import tempfile
import shutil
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("psp.fpocket")


def _parse_info_txt(info_path: str) -> List[Dict[str, Any]]:
    """
    Parse fpocket's *_info.txt file.
    Each pocket block looks like:

        Pocket 1 :
            Score :                 0.542
            Druggability Score :    0.612
            Volume :                  412.300
            ...
    """
    pockets: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    with open(info_path, "r") as f:
        for line in f:
            line = line.strip()

            # New pocket block header: "Pocket N :"
            m = re.match(r"^Pocket\s+(\d+)\s*:", line)
            if m:
                if current is not None:
                    pockets.append(current)
                current = {
                    "pocket_id": int(m.group(1)),
                    "score": 0.0,
                    "druggability_score": 0.0,
                    "volume": 0.0,
                    "hydrophobicity": 0.0,
                    "alpha_sphere_count": 0,
                    "residues": [],
                }
                continue

            if current is None:
                continue

            # Parse known fields
            if re.match(r"^Score\s*:", line):
                try:
                    current["score"] = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
            elif re.match(r"^Druggability Score\s*:", line):
                try:
                    current["druggability_score"] = float(
                        line.split(":")[-1].strip()
                    )
                except ValueError:
                    pass
            elif re.match(r"^Volume\s*:", line):
                try:
                    current["volume"] = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
            elif re.match(r"^Hydrophobicity score\s*:", line):
                try:
                    current["hydrophobicity"] = float(
                        line.split(":")[-1].strip()
                    )
                except ValueError:
                    pass
            elif re.match(r"^Number of Alpha Spheres\s*:", line):
                try:
                    current["alpha_sphere_count"] = int(
                        line.split(":")[-1].strip()
                    )
                except ValueError:
                    pass

    if current is not None:
        pockets.append(current)

    return pockets


def _parse_pocket_pdb_residues(pocket_pdb_path: str) -> List[int]:
    """
    Extract residue sequence numbers from a pocket's individual PDB file.
    fpocket writes one PDB per pocket under <name>_out/pockets/pocket<N>_atm.pdb.
    We collect all unique residue numbers that line the pocket.
    """
    residues = set()
    try:
        with open(pocket_pdb_path, "r") as f:
            for line in f:
                if line.startswith(("ATOM", "HETATM")):
                    # PDB column 23-26 (0-indexed 22:26) = residue sequence number
                    try:
                        res_num = int(line[22:26].strip())
                        residues.add(res_num)
                    except (ValueError, IndexError):
                        continue
    except FileNotFoundError:
        logger.warning("Pocket PDB file not found: %s", pocket_pdb_path)
    return sorted(residues)


def run_fpocket(pdb_text: str) -> Dict[str, Any]:
    """
    Run fpocket on a PDB string and return structured pocket data.

    Args:
        pdb_text: Full PDB format string (as returned by ESMFold / ColabFold APIs)

    Returns:
        {
            "success": bool,
            "pockets": [
                {
                    "pocket_id": 1,
                    "score": 0.54,
                    "druggability_score": 0.61,
                    "volume": 412.3,
                    "hydrophobicity": 0.22,
                    "alpha_sphere_count": 48,
                    "residues": [45, 46, 47, 89, 90]
                },
                ...
            ],
            "error": str | None
        }
    """
    if not pdb_text or not pdb_text.strip():
        return {"success": False, "pockets": [], "error": "Empty PDB text"}

    # Check fpocket is available
    if not shutil.which("fpocket"):
        logger.error("fpocket binary not found in PATH")
        return {
            "success": False,
            "pockets": [],
            "error": "fpocket not found. Ensure it is installed in the Docker image.",
        }

    tmp_dir = tempfile.mkdtemp(prefix="fpocket_")
    try:
        pdb_path = os.path.join(tmp_dir, "input.pdb")
        with open(pdb_path, "w") as f:
            f.write(pdb_text)

        result = subprocess.run(
            ["fpocket", "-f", pdb_path],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=tmp_dir,
        )

        if result.returncode != 0:
            logger.error("fpocket failed: %s", result.stderr)
            return {
                "success": False,
                "pockets": [],
                "error": f"fpocket exited with code {result.returncode}: {result.stderr[:500]}",
            }

        # fpocket creates <basename>_out/ directory next to the input file
        out_dir = os.path.join(tmp_dir, "input_out")
        if not os.path.isdir(out_dir):
            return {
                "success": False,
                "pockets": [],
                "error": "fpocket output directory not found after run",
            }

        # Parse pocket properties from the info txt
        info_files = glob.glob(os.path.join(out_dir, "*_info.txt"))
        if not info_files:
            return {
                "success": True,
                "pockets": [],
                "error": None,  # ran OK but found no pockets
            }

        pockets = _parse_info_txt(info_files[0])

        # Enrich each pocket with its constituent residues
        pockets_dir = os.path.join(out_dir, "pockets")
        for pocket in pockets:
            pid = pocket["pocket_id"]
            # fpocket names individual pocket files: pocket<N>_atm.pdb
            atm_pdb = os.path.join(pockets_dir, f"pocket{pid}_atm.pdb")
            pocket["residues"] = _parse_pocket_pdb_residues(atm_pdb)

        logger.info("fpocket: found %d pockets", len(pockets))
        return {"success": True, "pockets": pockets, "error": None}

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "pockets": [],
            "error": "fpocket timed out after 120s",
        }
    except Exception as e:
        logger.exception("Unexpected error running fpocket")
        return {"success": False, "pockets": [], "error": str(e)}
    finally:
        # Always clean up the temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
