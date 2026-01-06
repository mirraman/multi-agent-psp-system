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
		Handles 3 scenarios with graceful degradation:
		A) ESMFold succeeds + AlphaFold DB available → Compare and choose best
		B) Partial success → Use what we have (ESMFold OR AlphaFold DB)
		C) Total failure → Use experimental PDB or report failure
		
		Decision hierarchy:
		1. ESMFold prediction (pLDDT > 70)
		2. AlphaFold DB (confidence > 90)
		3. Best available option
		4. Experimental PDB (last resort)
		"""
		synthesis: Dict[str, Any] = {
			"best_model": None,
			"best_model_source": None,
			"confidence_score": None,
			"summary": "",
			"scenario": None,
			"available_structures": [],
		}
		
		# Collect all available metrics
		alphafold_db_conf = processing_results.get("alphafold_confidence")
		esmfold_plddt = processing_results.get("esmfold_plddt_mean")
		pdb_count = processing_results.get("pdb_count", 0)
		best_resolution = processing_results.get("pdb_best_resolution")
		
		# Build availability list for logging
		available = []
		if esmfold_plddt:
			available.append(f"ESMFold (pLDDT: {esmfold_plddt:.1f})")
		if alphafold_db_conf:
			available.append(f"AlphaFold DB (confidence: {alphafold_db_conf})")
		if pdb_count > 0:
			available.append(f"Experimental PDB ({pdb_count} structures)")
		
		synthesis["available_structures"] = available
		
		# Scenario detection
		has_esmfold = esmfold_plddt is not None
		has_alphafold_db = alphafold_db_conf is not None
		
		# SCENARIO A: Both ESMFold and AlphaFold DB available
		if has_esmfold and has_alphafold_db:
			synthesis["scenario"] = "both_success"
			# Priority: ESMFold if good quality, otherwise AlphaFold DB
			if esmfold_plddt > 70:
				synthesis["best_model"] = "esmfold"
				synthesis["best_model_source"] = "ESMFold prediction"
				synthesis["confidence_score"] = esmfold_plddt
				synthesis["summary"] = f"Both sources available. Using ESMFold prediction (pLDDT: {esmfold_plddt:.1f}) - fresh prediction prioritized."
			elif alphafold_db_conf > 90:
				synthesis["best_model"] = "alphafold_db"
				synthesis["best_model_source"] = "AlphaFold DB"
				synthesis["confidence_score"] = alphafold_db_conf
				synthesis["summary"] = f"ESMFold quality low, using AlphaFold DB (confidence: {alphafold_db_conf})."
			else:
				# Use best available even if below ideal thresholds
				if esmfold_plddt > alphafold_db_conf:
					synthesis["best_model"] = "esmfold"
					synthesis["best_model_source"] = "ESMFold prediction"
					synthesis["confidence_score"] = esmfold_plddt
					synthesis["summary"] = f"Using ESMFold (pLDDT: {esmfold_plddt:.1f}) over AlphaFold DB ({alphafold_db_conf})."
				else:
					synthesis["best_model"] = "alphafold_db"
					synthesis["best_model_source"] = "AlphaFold DB"
					synthesis["confidence_score"] = alphafold_db_conf
					synthesis["summary"] = f"Using AlphaFold DB (confidence: {alphafold_db_conf}) over ESMFold ({esmfold_plddt:.1f})."
		
		# SCENARIO B: Partial success (only one source available)
		elif has_esmfold or has_alphafold_db:
			synthesis["scenario"] = "partial_success"
			
			if esmfold_plddt and esmfold_plddt > 70:
				synthesis["best_model"] = "esmfold"
				synthesis["best_model_source"] = "ESMFold prediction"
				synthesis["confidence_score"] = esmfold_plddt
				synthesis["summary"] = f"AlphaFold DB unavailable, using ESMFold prediction (pLDDT: {esmfold_plddt:.1f})."
			
			elif alphafold_db_conf and alphafold_db_conf > 90:
				synthesis["best_model"] = "alphafold_db"
				synthesis["best_model_source"] = "AlphaFold DB"
				synthesis["confidence_score"] = alphafold_db_conf
				synthesis["summary"] = f"ESMFold failed, using AlphaFold DB (confidence: {alphafold_db_conf})."
			
			# Use best available even if below threshold
			elif esmfold_plddt:
				synthesis["best_model"] = "esmfold"
				synthesis["best_model_source"] = "ESMFold prediction"
				synthesis["confidence_score"] = esmfold_plddt
				synthesis["summary"] = f"Using ESMFold (pLDDT: {esmfold_plddt:.1f}) - best available option."
			
			elif alphafold_db_conf:
				synthesis["best_model"] = "alphafold_db"
				synthesis["best_model_source"] = "AlphaFold DB"
				synthesis["confidence_score"] = alphafold_db_conf
				synthesis["summary"] = f"Using AlphaFold DB (confidence: {alphafold_db_conf}) - ESMFold unavailable."
		
		# SCENARIO C: Total failure - use experimental PDB as last resort
		else:
			synthesis["scenario"] = "total_failure"
			if pdb_count > 0 and best_resolution:
				synthesis["best_model"] = "experimental"
				synthesis["best_model_source"] = "Experimental PDB"
				synthesis["confidence_score"] = best_resolution
				synthesis["summary"] = f"ESMFold and AlphaFold DB failed. Using experimental structure (resolution: {best_resolution}Å)."
			else:
				synthesis["best_model"] = "none"
				synthesis["summary"] = "Total failure: No structure available (ESMFold failed, AlphaFold DB empty, no experimental PDB)."
		
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

