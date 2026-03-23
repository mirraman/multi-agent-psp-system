"""
PocketAgent.py
--------------
Runs fpocket on one or more predicted structures, filters pockets by local
pLDDT confidence, computes an ensemble-aware composite druggability score, and
returns ranked pocket data to the CoordinatorAgent.

Pipeline position:
    SynthesisAgent → CoordinatorAgent → PocketAgent → CoordinatorAgent → OutputAgent

Message actions:
    Receives:  "detect_pockets"
    Sends:     "pockets_detected"

Payload received:
    {
        "models": {                    # model name -> PDB string
            "esmfold": str,
            "colabfold_modal": str
        },
        "best_model": str,
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
from typing import Any, Dict, List, Optional, Set

from spade.behaviour import CyclicBehaviour

from app.agents.BaseAgent import BaseAgent
from app.utils.fpocket_runner import run_fpocket

logger = logging.getLogger("psp.pocket_agent")

# Minimum local pLDDT (mean over pocket residues) to consider a pocket reliable
PLDDT_CONFIDENCE_THRESHOLD = 70.0
CONSENSUS_JACCARD_THRESHOLD = 0.5


class PocketAgent(BaseAgent):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.coordinator_jid = self.format_jid("coordinator")

    async def setup(self):
        self.add_behaviour(MessageHandlerBehaviour(self))
        print(f"PocketAgent {self.jid} started")

    async def handle_detect_pockets(self, agent_msg):
        job_id = agent_msg.job_id
        payload = agent_msg.payload

        models_payload: Dict[str, str] = payload.get("models", {}) or {}
        # Backward compatibility with older payload shape.
        if not models_payload and payload.get("pdb_text"):
            models_payload = {"best_model": payload.get("pdb_text", "")}

        # plddt_per_residue keys are strings (JSON-safe); convert to int for lookup
        raw_plddt: dict = payload.get("plddt_per_residue", {})
        plddt_per_residue: Dict[int, float] = {
            int(k): float(v) for k, v in raw_plddt.items()
        }
        best_model_source: str = payload.get("best_model_source", "unknown")
        best_model: str = payload.get("best_model", "esmfold")
        fallback_plddt = payload.get("fallback_plddt_mean")
        if not isinstance(fallback_plddt, (int, float)):
            fallback_plddt = None

        model_names = [name for name, pdb in models_payload.items() if pdb]
        logger.info("[%s] PocketAgent: running fpocket on models=%s", job_id, model_names or [best_model_source])

        if not model_names:
            logger.warning("[%s] PocketAgent: no PDB text provided in any model, skipping", job_id)
            result_payload = _empty_pocket_result("No PDB text provided")
        else:
            pockets_by_model: Dict[str, List[Dict[str, Any]]] = {}
            model_errors: Dict[str, str] = {}
            for model_name, pdb_text in models_payload.items():
                if not pdb_text:
                    continue
                fpocket_result = run_fpocket(pdb_text)

                if not fpocket_result["success"]:
                    model_errors[model_name] = fpocket_result.get("error", "fpocket error")
                    logger.error(
                        "[%s] fpocket failed for %s: %s",
                        job_id,
                        model_name,
                        model_errors[model_name],
                    )
                    continue

                pockets_by_model[model_name] = fpocket_result["pockets"]

            if not pockets_by_model:
                reason = "All fpocket runs failed"
                if model_errors:
                    reason = f"{reason}: {model_errors}"
                result_payload = _empty_pocket_result(reason)
            else:
                result_payload = _process_pockets(
                    pockets_by_model,
                    plddt_per_residue,
                    job_id,
                    best_model=best_model,
                    fallback_plddt_mean=fallback_plddt,
                )
                if model_errors:
                    result_payload["model_errors"] = model_errors

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
    pockets_by_model: Dict[str, List[Dict[str, Any]]],
    plddt_per_residue: Dict[int, float],
    job_id: str,
    best_model: str = "esmfold",
    fallback_plddt_mean: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Enrich raw fpocket output with pLDDT filtering and composite scoring.

    Each enriched pocket gets:
        local_plddt_mean    — mean pLDDT of pocket-lining residues
        confident           — bool: True if local_plddt_mean >= PLDDT_CONFIDENCE_THRESHOLD
        ensemble_agreement  — cross-model overlap metadata
        composite_score     — druggability × (pLDDT / 100) × (1 + 0.3 × jaccard_bonus)
        filter_reason       — None or "low_plddt_confidence"
    """
    enriched: List[Dict[str, Any]] = []
    filtered_count = 0
    consensus_residue_sets: Set = set()

    per_model_enriched: Dict[str, List[Dict[str, Any]]] = {}

    for model_name, model_pockets in pockets_by_model.items():
        model_enriched: List[Dict[str, Any]] = []
        for pocket in model_pockets:
            residues: List[int] = pocket.get("residues", [])

            # Compute local pLDDT over pocket residues
            plddt_values = [
                plddt_per_residue[r] for r in residues if r in plddt_per_residue
            ]
            if plddt_values:
                local_plddt = sum(plddt_values) / len(plddt_values)
            else:
                # Experimental structures: B-factors may not match prediction numbering; use fallback mean.
                if fallback_plddt_mean is not None:
                    local_plddt = float(fallback_plddt_mean)
                elif best_model in ("experimental",) and model_name == "experimental":
                    local_plddt = 85.0
                else:
                    local_plddt = 0.0
                    logger.debug(
                        "[%s] %s pocket %d: no pLDDT data for residues %s",
                        job_id,
                        model_name,
                        pocket["pocket_id"],
                        residues[:5],
                    )

            confident = local_plddt >= PLDDT_CONFIDENCE_THRESHOLD
            druggability = pocket.get("druggability_score", 0.0)

            enriched_pocket = {
                "model_name": model_name,
                "pocket_id": pocket["pocket_id"],
                "rank": pocket["pocket_id"],  # will re-rank globally below
                "residues": residues,
                "volume": pocket.get("volume", 0.0),
                "druggability_score": round(druggability, 4),
                "hydrophobicity": round(pocket.get("hydrophobicity", 0.0), 4),
                "alpha_sphere_count": pocket.get("alpha_sphere_count", 0),
                "local_plddt_mean": round(local_plddt, 2),
                "confident": confident,
                "ensemble_agreement": {
                    "seen_in_models": [model_name],
                    "jaccard_similarity": 0.0,
                    "consensus": False,
                },
                "composite_score": 0.0,
                "filter_reason": None if confident else "low_plddt_confidence",
            }
            model_enriched.append(enriched_pocket)
            if not confident:
                filtered_count += 1
        per_model_enriched[model_name] = model_enriched

    # Cross-model pocket overlap (Jaccard over residue sets).
    model_names = list(per_model_enriched.keys())
    for model_name in model_names:
        for pocket in per_model_enriched[model_name]:
            residues_a: Set[int] = set(pocket.get("residues", []))
            seen_in_models = {model_name}
            best_jaccard = 0.0

            for other_model in model_names:
                if other_model == model_name:
                    continue
                overlaps_in_model = []
                for other_pocket in per_model_enriched[other_model]:
                    residues_b: Set[int] = set(other_pocket.get("residues", []))
                    sim = jaccard_similarity(residues_a, residues_b)
                    overlaps_in_model.append(sim)
                if overlaps_in_model:
                    max_sim = max(overlaps_in_model)
                    best_jaccard = max(best_jaccard, max_sim)
                    if max_sim >= CONSENSUS_JACCARD_THRESHOLD:
                        seen_in_models.add(other_model)

            is_consensus = len(seen_in_models) > 1
            if is_consensus:
                consensus_residue_sets.add(frozenset(residues_a))
            pocket["ensemble_agreement"] = {
                "seen_in_models": sorted(seen_in_models),
                "jaccard_similarity": round(best_jaccard, 4),
                "consensus": is_consensus,
            }

            druggability = float(pocket.get("druggability_score", 0.0))
            local_plddt = float(pocket.get("local_plddt_mean", 0.0))
            if local_plddt <= 0.0 and fallback_plddt_mean is not None:
                local_plddt = float(fallback_plddt_mean)
                pocket["local_plddt_mean"] = round(local_plddt, 2)
            jaccard_bonus = best_jaccard
            composite = druggability * (local_plddt / 100.0) * (1 + 0.3 * jaccard_bonus)
            pocket["composite_score"] = round(composite, 4)

    for pockets in per_model_enriched.values():
        enriched.extend(pockets)

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
            "consensus_pockets": len(consensus_residue_sets),
            "models_processed": list(pockets_by_model.keys()),
        },
    }


def jaccard_similarity(residues_a: Set[int], residues_b: Set[int]) -> float:
    intersection = residues_a & residues_b
    union = residues_a | residues_b
    return (len(intersection) / len(union)) if union else 0.0


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
