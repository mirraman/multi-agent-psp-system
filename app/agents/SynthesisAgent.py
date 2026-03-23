import os
from typing import Any, Dict

from app.agents.BaseAgent import ActionMessageHandlerBehaviour, BaseAgent


def _float_env(name: str, default: float) -> float:
	try:
		return float(os.getenv(name, str(default)))
	except ValueError:
		return default


class SynthesisAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")

	async def setup(self):
		behaviour = ActionMessageHandlerBehaviour(
			self,
			action_to_handler={"synthesize": "handle_synthesize"},
		)
		self.add_behaviour(behaviour)
		print(f"SynthesisAgent {self.jid} started")

	async def handle_synthesize(self, agent_msg):
		job_id = agent_msg.job_id
		raw_data = agent_msg.payload.get("raw_data", {})
		psp_results = agent_msg.payload.get("psp_results", {})
		processing_results = agent_msg.payload.get("processing_results", {})
		synthesis = self._synthesize(raw_data, psp_results, processing_results)

		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="synthesized",
			payload={"synthesis": synthesis},
			job_id=job_id,
		)
		await self.send(msg)

	def _synthesize(
		self,
		raw_data: Dict[str, Any],
		psp_results: Dict[str, Any],
		processing_results: Dict[str, Any],
	) -> Dict[str, Any]:
		"""
		Quality-based hierarchy:
		1. High-resolution experimental PDB (resolution <= EXPERIMENTAL_PREFERRED_RESOLUTION_A)
		2. AlphaFold DB when mean pLDDT >= ALPHAFOLD_MIN_CONFIDENCE
		3. ColabFold/Modal (when available, typically long sequences)
		4. ESMFold
		5. Experimental PDB as fallback when predictions are missing
		"""
		exp_res_threshold = _float_env("EXPERIMENTAL_PREFERRED_RESOLUTION_A", 2.5)
		alphafold_min = _float_env("ALPHAFOLD_MIN_CONFIDENCE", 70.0)

		synthesis: Dict[str, Any] = {
			"best_model": None,
			"best_model_source": None,
			"confidence_score": None,
			"summary": "",
			"scenario": None,
			"available_structures": [],
			"experimental_pdb_id": None,
		}

		esmfold_plddt = processing_results.get("esmfold_plddt_mean")
		pdb_count = processing_results.get("pdb_count", 0)
		best_resolution = processing_results.get("pdb_best_resolution")
		af_confidence = processing_results.get("alphafold_confidence")
		if not isinstance(af_confidence, (int, float)):
			af_confidence = processing_results.get("alphafold_db_plddt_mean")

		modal_data = psp_results.get("colabfold_modal", {})
		has_modal = bool(modal_data.get("pdb"))
		has_esmfold = esmfold_plddt is not None
		exp_psp = psp_results.get("experimental", {})
		has_experimental_pdb = bool(exp_psp.get("pdb"))
		af_db = psp_results.get("alphafold_db", {})
		has_alphafold_db = bool(af_db.get("pdb"))

		available = []
		if has_modal:
			available.append("ColabFold/Modal (cloud prediction)")
		if has_esmfold:
			available.append(f"ESMFold (pLDDT: {esmfold_plddt:.1f})")
		if has_alphafold_db:
			af_s = af_confidence if isinstance(af_confidence, (int, float)) else "n/a"
			available.append(f"AlphaFold DB (mean pLDDT: {af_s})")
		if pdb_count > 0:
			available.append(f"Experimental PDB ({pdb_count} structures)")
		synthesis["available_structures"] = available

		exp_from_raw = raw_data.get("experimental_best_pdb") or {}
		exp_res_from_raw = exp_from_raw.get("resolution")

		def pick_experimental(reason: str) -> None:
			synthesis["best_model"] = "experimental"
			synthesis["best_model_source"] = "Experimental PDB"
			pid = exp_psp.get("pdb_id") or exp_from_raw.get("pdb_id")
			synthesis["experimental_pdb_id"] = pid
			res = best_resolution if isinstance(best_resolution, (int, float)) else exp_res_from_raw
			synthesis["confidence_score"] = res
			synthesis["scenario"] = "experimental_preferred"
			res_str = f"{res}Å" if isinstance(res, (int, float)) else "n/a"
			synthesis["summary"] = f"{reason} (PDB {pid or '?'}, resolution: {res_str})."

		# 1) High-quality experimental structure
		if (
			has_experimental_pdb
			and isinstance(best_resolution, (int, float))
			and best_resolution <= exp_res_threshold
		):
			pick_experimental("Using high-resolution experimental structure")
			return synthesis

		# 2) AlphaFold DB when confidence is acceptable
		if has_alphafold_db and isinstance(af_confidence, (int, float)) and af_confidence >= alphafold_min:
			synthesis["best_model"] = "alphafold_db"
			synthesis["best_model_source"] = "AlphaFold DB (EBI)"
			synthesis["confidence_score"] = round(float(af_confidence), 2)
			synthesis["scenario"] = "alphafold_db"
			synthesis["summary"] = (
				f"Using AlphaFold DB model (mean pLDDT: {af_confidence:.1f}) — "
				"experimental resolution insufficient or unavailable."
			)
			return synthesis

		# 3) Modal / ColabFold
		if has_modal:
			synthesis["best_model"] = "colabfold_modal"
			synthesis["best_model_source"] = "ColabFold/Modal (cloud)"
			synthesis["confidence_score"] = "High (Computed)"
			synthesis["summary"] = (
				"Using ColabFold prediction from Modal Cloud. Prioritized for accuracy on large/complex proteins."
			)
			synthesis["scenario"] = "modal_success"
			return synthesis

		# 4) ESMFold
		if has_esmfold:
			synthesis["scenario"] = "esmfold_success"
			synthesis["best_model"] = "esmfold"
			synthesis["best_model_source"] = "ESMFold prediction"
			synthesis["confidence_score"] = esmfold_plddt
			if esmfold_plddt > 70:
				synthesis["summary"] = f"Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f}) — high confidence."
			else:
				synthesis["summary"] = (
					f"Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f}) — moderate confidence, interpret with care."
				)
			return synthesis

		# 5) Experimental fallback
		if has_experimental_pdb:
			pick_experimental("Using experimental structure (predictions unavailable or low confidence)")
			return synthesis

		synthesis["scenario"] = "total_failure"
		synthesis["best_model"] = "none"
		synthesis["summary"] = "Total failure: No structure available."
		return synthesis
