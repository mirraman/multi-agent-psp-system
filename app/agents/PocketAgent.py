"""
PocketAgent.py
--------------
Runs fpocket on one or more predicted structures, filters pockets by local
pLDDT confidence, computes an ensemble-aware composite druggability score using
REAL STRUCTURAL ALIGNMENT (TM-align), and returns ranked pocket data.

Pipeline position:
    SynthesisAgent → CoordinatorAgent → PocketAgent → CoordinatorAgent → OutputAgent

Message actions:
    Receives:  "detect_pockets"
    Sends:     "pockets_detected"
"""

import logging
from typing import Any, Dict, List, Optional, Set

from spade.behaviour import CyclicBehaviour

from app.agents.BaseAgent import BaseAgent
from app.utils.fpocket_runner import run_fpocket
from app.utils.structure_alignment import align_structures, invert_residue_mapping

logger = logging.getLogger("psp.pocket_agent")

# Minimum local pLDDT (mean over pocket residues) to consider a pocket reliable
PLDDT_CONFIDENCE_THRESHOLD = 70.0
CONSENSUS_JACCARD_THRESHOLD = 0.5   # after structural alignment


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
        # Backward compatibility
        if not models_payload and payload.get("pdb_text"):
            models_payload = {"best_model": payload.get("pdb_text", "")}

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
                    logger.error("[%s] fpocket failed for %s: %s", job_id, model_name, model_errors[model_name])
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
                    models_payload,          # ← NEW: needed for TM-align
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
    models_payload: Dict[str, str],          # ← NEW: full PDB texts for alignment
    job_id: str,
    best_model: str = "esmfold",
    fallback_plddt_mean: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Enrich raw fpocket output with pLDDT filtering + REAL STRUCTURAL ALIGNMENT (TM-align).
    """
    enriched: List[Dict[str, Any]] = []
    filtered_count = 0
    consensus_residue_sets: Set = set()

    per_model_enriched: Dict[str, List[Dict[str, Any]]] = {}

    # === STEP 1: Run fpocket on every model (unchanged) ===
    for model_name, model_pockets in pockets_by_model.items():
        model_enriched: List[Dict[str, Any]] = []
        for pocket in model_pockets:
            residues: List[int] = pocket.get("residues", [])
            plddt_values = [plddt_per_residue[r] for r in residues if r in plddt_per_residue]
            local_plddt = sum(plddt_values) / len(plddt_values) if plddt_values else (
                fallback_plddt_mean if fallback_plddt_mean is not None else
                85.0 if model_name == "experimental" else 0.0
            )

            confident = local_plddt >= PLDDT_CONFIDENCE_THRESHOLD
            druggability = pocket.get("druggability_score", 0.0)

            enriched_pocket = {
                "model_name": model_name,
                "pocket_id": pocket["pocket_id"],
                "rank": pocket["pocket_id"],
                "residues": residues,
                "volume": pocket.get("volume", 0.0),
                "druggability_score": round(druggability, 4),
                "hydrophobicity": round(pocket.get("hydrophobicity", 0.0), 4),
                "alpha_sphere_count": pocket.get("alpha_sphere_count", 0),
                "local_plddt_mean": round(local_plddt, 2),
                "confident": confident,
                "ensemble_agreement": {"seen_in_models": [model_name], "jaccard_similarity": 0.0, "tm_score_ref": 0.0, "consensus": False},
                "composite_score": 0.0,
                "filter_reason": None if confident else "low_plddt_confidence",
            }
            model_enriched.append(enriched_pocket)
            if not confident:
                filtered_count += 1
        per_model_enriched[model_name] = model_enriched

    # === STEP 2: STRUCTURAL ALIGNMENT (NEW) ===
    ref_name = best_model if best_model in pockets_by_model else list(pockets_by_model.keys())[0]
    ref_pdb_text = models_payload.get(ref_name, "")

    alignments: Dict[str, Dict] = {ref_name: {"residue_mapping": {r: r for r in range(9999)}}}
    for model_name in list(pockets_by_model.keys()):
        if model_name == ref_name:
            continue
        pdb_text = models_payload.get(model_name, "")
        if pdb_text:
            try:
                alignments[model_name] = align_structures(ref_pdb_text, pdb_text, ref_name, model_name)
            except Exception as e:
                logger.warning("[%s] Alignment failed for %s → %s: %s", job_id, ref_name, model_name, e)
                alignments[model_name] = {"residue_mapping": {}, "tm_score": 0.0}

    # mobile (model) residue numbers → reference numbering (align_structures maps ref → mobile)
    mobile_to_ref: Dict[str, Dict[int, int]] = {
        mn: invert_residue_mapping(alignments[mn]["residue_mapping"]) for mn in alignments
    }

    def _pocket_residues_in_ref(mn: str, residues: List[int]) -> Set[int]:
        if mn == ref_name:
            return set(residues)
        inv = mobile_to_ref[mn]
        return {inv[r] for r in residues if r in inv}

    # === STEP 3: Cross-model consensus in reference residue space ===
    for model_name, model_pockets in per_model_enriched.items():
        for pocket in model_pockets:
            residues_a = _pocket_residues_in_ref(model_name, pocket.get("residues", []))
            seen_in_models = {model_name}
            best_jaccard = 0.0

            for other_model in alignments:
                if other_model == model_name:
                    continue

                for other_pocket in per_model_enriched[other_model]:
                    residues_b = _pocket_residues_in_ref(other_model, other_pocket.get("residues", []))
                    if not residues_b:
                        continue
                    sim = jaccard_similarity(residues_a, residues_b)
                    if sim > best_jaccard:
                        best_jaccard = sim
                    if sim >= CONSENSUS_JACCARD_THRESHOLD:
                        seen_in_models.add(other_model)
                        break

            is_consensus = len(seen_in_models) > 1
            if is_consensus:
                consensus_residue_sets.add(frozenset(residues_a))

            tm_score = alignments.get(list(seen_in_models)[-1], {}).get("tm_score", 0.0)

            pocket["ensemble_agreement"] = {
                "seen_in_models": sorted(seen_in_models),
                "jaccard_similarity": round(best_jaccard, 4),
                "tm_score_ref": round(tm_score, 3),
                "consensus": is_consensus,
            }

            # Stronger bonus for real structural agreement
            druggability = float(pocket.get("druggability_score", 0.0))
            local_plddt = float(pocket.get("local_plddt_mean", 0.0))
            if local_plddt <= 0 and fallback_plddt_mean is not None:
                local_plddt = float(fallback_plddt_mean)
            composite = druggability * (local_plddt / 100.0) * (1 + 0.5 * best_jaccard)
            pocket["composite_score"] = round(composite, 4)

    # Global re-ranking
    enriched.extend([p for pockets in per_model_enriched.values() for p in pockets])
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