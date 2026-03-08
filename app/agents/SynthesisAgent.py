from typing import Any, Dict, Optional

from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour


class SynthesisAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
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
		processing_results: Dict[str, Any]
	) -> Dict[str, Any]:
		"""
		**LIFEGUARD LOGIC - HYBRID APPROACH**

		Decision hierarchy:
		1. ColabFold/Modal (large proteins routed here, >400aa)
		2. ESMFold (primary prediction for shorter proteins)
		3. Experimental PDB (last resort)
		"""
		synthesis: Dict[str, Any] = {
			"best_model": None,
			"best_model_source": None,
			"confidence_score": None,
			"summary": "",
			"scenario": None,
			"available_structures": [],
		}

		esmfold_plddt = processing_results.get("esmfold_plddt_mean")
		pdb_count = processing_results.get("pdb_count", 0)
		best_resolution = processing_results.get("pdb_best_resolution")

		modal_data = psp_results.get("colabfold_modal", {})
		has_modal = bool(modal_data.get("pdb"))
		has_esmfold = esmfold_plddt is not None

		available = []
		if has_modal:
			available.append("ColabFold/Modal (cloud prediction)")
		if has_esmfold:
			available.append(f"ESMFold (pLDDT: {esmfold_plddt:.1f})")
		if pdb_count > 0:
			available.append(f"Experimental PDB ({pdb_count} structures)")

		synthesis["available_structures"] = available

		if has_modal:
			synthesis["best_model"] = "colabfold_modal"
			synthesis["best_model_source"] = "ColabFold/Modal (cloud)"
			synthesis["confidence_score"] = "High (Computed)"
			synthesis["summary"] = "Using ColabFold prediction from Modal Cloud. Prioritized for accuracy on large/complex proteins (>400aa)."
			synthesis["scenario"] = "modal_success"

		elif has_esmfold:
			synthesis["scenario"] = "esmfold_success"
			synthesis["best_model"] = "esmfold"
			synthesis["best_model_source"] = "ESMFold prediction"
			synthesis["confidence_score"] = esmfold_plddt
			if esmfold_plddt > 70:
				synthesis["summary"] = f"Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f}) — high confidence."
			else:
				synthesis["summary"] = f"Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f}) — moderate confidence, interpret with care."

		else:
			synthesis["scenario"] = "total_failure"
			if pdb_count > 0 and best_resolution:
				synthesis["best_model"] = "experimental"
				synthesis["best_model_source"] = "Experimental PDB"
				synthesis["confidence_score"] = best_resolution
				synthesis["summary"] = f"ESMFold failed. Falling back to experimental structure (resolution: {best_resolution}Å)."
			else:
				synthesis["best_model"] = "none"
				synthesis["summary"] = "Total failure: No structure available (ESMFold failed, no experimental PDB)."

		return synthesis

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "synthesize":
				await self.agent.handle_synthesize(agent_msg)
