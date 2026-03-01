"""
PocketAgent.py
--------------
Runs fpocket on the best predicted structure, filters pockets by local pLDDT
confidence, computes a composite druggability score, and returns ranked pocket
data to the CoordinatorAgent.

Pipeline position:
    SynthesisAgent → CoordinatorAgent → PocketAgent → CoordinatorAgent → OutputAgent

Message actions:
    Receives:  "detect_pockets"
    Sends:     "pockets_detected"

Payload received:
    {
        "pdb_text": str,               # PDB string of the best model
        "plddt_per_residue": dict,     # str(res_num) -> float (0-100)
        "best_model_source": str       # for logging
    }

Payload sent:
    {
        "pockets": [...],              # see PocketData schema below
        "pocket_summary": {...}
    }
"""

import logging
from typing import Any, Dict, List

from spade.behaviour import CyclicBehaviour

from app.agents.BaseAgent import BaseAgent
from app.utils.fpocket_runner import run_fpocket

logger = logging.getLogger("psp.pocket_agent")

# Minimum local pLDDT (mean over pocket residues) to consider a pocket reliable
PLDDT_CONFIDENCE_THRESHOLD = 70.0


class PocketAgent(BaseAgent):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.coordinator_jid = "coordinator@localhost"

    async def setup(self):
        self.add_behaviour(MessageHandlerBehaviour(self))
        print(f"PocketAgent {self.jid} started")

    async def handle_detect_pockets(self, agent_msg):
        job_id = agent_msg.job_id
        payload = agent_msg.payload

        pdb_text: str = payload.get("pdb_text", "")
        # plddt_per_residue keys are strings (JSON-safe); convert to int for lookup
        raw_plddt: dict = payload.get("plddt_per_residue", {})
        plddt_per_residue: Dict[int, float] = {
            int(k): float(v) for k, v in raw_plddt.items()
        }
        best_model_source: str = payload.get("best_model_source", "unknown")

        logger.info("[%s] PocketAgent: running fpocket on %s structure", job_id, best_model_source)

        if not pdb_text:
            logger.warning("[%s] PocketAgent: no PDB text provided, skipping", job_id)
            result_payload = _empty_pocket_result("No PDB text provided")
        else:
            fpocket_result = run_fpocket(pdb_text)

            if not fpocket_result["success"]:
                logger.error("[%s] fpocket failed: %s", job_id, fpocket_result.get("error"))
                result_payload = _empty_pocket_result(fpocket_result.get("error", "fpocket error"))
            else:
                raw_pockets: List[Dict[str, Any]] = fpocket_result["pockets"]
                result_payload = _process_pockets(raw_pockets, plddt_per_residue, job_id)

        msg = self.create_message(
            to=self.coordinator_jid,
            msg_type="response",
            action="pockets_detected",
            payload=result_payload,
            job_id=job_id,
        )
        await self.send(msg)
        logger.info(
            "[%s] PocketAgent: sent %d pockets (%d filtered by low pLDDT)",
            job_id,
            result_payload["pocket_summary"]["high_confidence"],
            result_payload["pocket_summary"]["filtered_low_plddt"],
        )


def _process_pockets(
    raw_pockets: List[Dict[str, Any]],
    plddt_per_residue: Dict[int, float],
    job_id: str,
) -> Dict[str, Any]:
    """
    Enrich raw fpocket output with pLDDT filtering and composite scoring.

    Each enriched pocket gets:
        local_plddt_mean    — mean pLDDT of pocket-lining residues
        confident           — bool: True if local_plddt_mean >= PLDDT_CONFIDENCE_THRESHOLD
        composite_score     — druggability_score × (local_plddt_mean / 100)
        filter_reason       — None or "low_plddt_confidence"
    """
    enriched: List[Dict[str, Any]] = []
    filtered_count = 0

    for pocket in raw_pockets:
        residues: List[int] = pocket.get("residues", [])

        # Compute local pLDDT over pocket residues
        plddt_values = [
            plddt_per_residue[r] for r in residues if r in plddt_per_residue
        ]
        if plddt_values:
            local_plddt = sum(plddt_values) / len(plddt_values)
        else:
            # No pLDDT data for this pocket's residues — treat as low confidence
            local_plddt = 0.0
            logger.debug(
                "[%s] Pocket %d: no pLDDT data for residues %s",
                job_id,
                pocket["pocket_id"],
                residues[:5],
            )

        confident = local_plddt >= PLDDT_CONFIDENCE_THRESHOLD
        druggability = pocket.get("druggability_score", 0.0)
        composite = druggability * (local_plddt / 100.0)

        enriched_pocket = {
            "pocket_id": pocket["pocket_id"],
            "rank": pocket["pocket_id"],          # will re-rank below
            "residues": residues,
            "volume": pocket.get("volume", 0.0),
            "druggability_score": round(druggability, 4),
            "hydrophobicity": round(pocket.get("hydrophobicity", 0.0), 4),
            "alpha_sphere_count": pocket.get("alpha_sphere_count", 0),
            "local_plddt_mean": round(local_plddt, 2),
            "confident": confident,
            "composite_score": round(composite, 4),
            "filter_reason": None if confident else "low_plddt_confidence",
        }
        enriched.append(enriched_pocket)

        if not confident:
            filtered_count += 1

    # Sort by composite score descending, re-assign rank
    enriched.sort(key=lambda p: p["composite_score"], reverse=True)
    for i, p in enumerate(enriched, start=1):
        p["rank"] = i

    high_confidence = [p for p in enriched if p["confident"]]

    return {
        "pockets": enriched,
        "pocket_summary": {
            "total_detected": len(enriched),
            "high_confidence": len(high_confidence),
            "filtered_low_plddt": filtered_count,
        },
    }


def _empty_pocket_result(reason: str) -> Dict[str, Any]:
    return {
        "pockets": [],
        "pocket_summary": {
            "total_detected": 0,
            "high_confidence": 0,
            "filtered_low_plddt": 0,
            "skipped_reason": reason,
        },
    }


class MessageHandlerBehaviour(CyclicBehaviour):
    def __init__(self, agent):
        super().__init__()
        self.agent = agent

    async def run(self):
        msg = await self.receive(timeout=10)
        if msg:
            agent_msg = self.agent.parse_message(msg)
            if agent_msg.action == "detect_pockets":
                await self.agent.handle_detect_pockets(agent_msg)
