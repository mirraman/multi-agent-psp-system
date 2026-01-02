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
		Pick the best structure model and generate a summary.
		
		Decision logic:
		1. If AlphaFold confidence > 90, use AlphaFold
		2. Else if ESMFold pLDDT > 70, use ESMFold
		3. Else if experimental PDB exists, use best resolution PDB
		4. Else use whatever is available
		"""
		synthesis: Dict[str, Any] = {
			"best_model": None,
			"best_model_source": None,
			"confidence_score": None,
			"summary": "",
			"available_structures": [],
		}

		# Check available structures
		alphafold_conf = processing_results.get("alphafold_confidence")
		esmfold_plddt = processing_results.get("esmfold_plddt_mean")
		pdb_count = processing_results.get("pdb_count", 0)
		best_resolution = processing_results.get("pdb_best_resolution")

		available = []
		if alphafold_conf:
			available.append(f"AlphaFold (confidence: {alphafold_conf})")
		if esmfold_plddt:
			available.append(f"ESMFold (pLDDT: {esmfold_plddt:.1f})")
		if pdb_count > 0:
			available.append(f"Experimental PDB ({pdb_count} structures, best res: {best_resolution})")

		synthesis["available_structures"] = available

		# Decision logic
		if alphafold_conf and alphafold_conf > 90:
			synthesis["best_model"] = "alphafold"
			synthesis["best_model_source"] = "AlphaFold DB"
			synthesis["confidence_score"] = alphafold_conf
			synthesis["summary"] = f"Using AlphaFold structure with high confidence ({alphafold_conf})."

		elif esmfold_plddt and esmfold_plddt > 70:
			synthesis["best_model"] = "esmfold"
			synthesis["best_model_source"] = "ESMFold prediction"
			synthesis["confidence_score"] = esmfold_plddt
			synthesis["summary"] = f"Using ESMFold prediction with good pLDDT ({esmfold_plddt:.1f})."

		elif pdb_count > 0 and best_resolution:
			synthesis["best_model"] = "experimental"
			synthesis["best_model_source"] = "Experimental PDB"
			synthesis["confidence_score"] = best_resolution
			synthesis["summary"] = f"Using experimental structure with resolution {best_resolution}A."

		elif alphafold_conf:
			synthesis["best_model"] = "alphafold"
			synthesis["best_model_source"] = "AlphaFold DB"
			synthesis["confidence_score"] = alphafold_conf
			synthesis["summary"] = f"Using AlphaFold structure (confidence: {alphafold_conf})."

		elif esmfold_plddt:
			synthesis["best_model"] = "esmfold"
			synthesis["best_model_source"] = "ESMFold prediction"
			synthesis["confidence_score"] = esmfold_plddt
			synthesis["summary"] = f"Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f})."

		else:
			synthesis["best_model"] = "none"
			synthesis["summary"] = "No reliable structure available."

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

