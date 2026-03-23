from typing import Any, Dict
from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour
from app.utils.structure_alignment import align_structures


class AnalysisAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"AnalysisAgent {self.jid} started")

	async def handle_analyze(self, agent_msg):
		job_id = agent_msg.job_id
		raw_data = agent_msg.payload.get("raw_data", {})
		psp_results = agent_msg.payload.get("psp_results", {})
		processing_results = agent_msg.payload.get("processing_results", {})

		analysis = self._analyze_structures(raw_data, psp_results, processing_results)

		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="analyzed",
			payload={"analysis": analysis},
			job_id=job_id,
		)
		await self.send(msg)


	def _analyze_structures(
		self,
		raw_data: Dict[str, Any],
		psp_results: Dict[str, Any],
		processing_results: Dict[str, Any]
	) -> Dict[str, Any]:
		_ = (raw_data, processing_results)

		analysis: Dict[str, Any] = {
			"models_compared": [],
			"pairwise_rmsd": {},
			"pairwise_tm_score": {},
			"consensus_confidence": None,
			"has_consensus": False,
			"summary": "",
		}

		structures = {}
		
		esmfold_data = psp_results.get("esmfold", {})
		esmfold_pdb = esmfold_data.get("pdb", "")
		if esmfold_pdb and esmfold_pdb.strip():
			structures["esmfold"] = esmfold_pdb
		
		modal_data = psp_results.get("colabfold_modal", {})
		modal_pdb = modal_data.get("pdb", "")
		if modal_pdb:
			structures["colabfold_modal"] = modal_pdb

		alphafold_data = psp_results.get("alphafold_db", {})
		alphafold_pdb = alphafold_data.get("pdb", "")
		if alphafold_pdb and alphafold_pdb.strip():
			structures["alphafold_db"] = alphafold_pdb

		exp_data = psp_results.get("experimental", {})
		exp_pdb = exp_data.get("pdb", "")
		if exp_pdb and exp_pdb.strip():
			structures["experimental"] = exp_pdb

		model_names = list(structures.keys())
		analysis["models_compared"] = model_names

		if len(model_names) < 2:
			analysis["summary"] = (
				f"Only {len(model_names)} structure(s) available. "
				f"Cannot compute structural alignment. Available: {model_names}"
			)
			return analysis

		valid_models = list(structures.keys())
		tm_values = []
		rmsd_values = []

		for i, name1 in enumerate(valid_models):
			for name2 in valid_models[i+1:]:
				try:
					alignment = align_structures(
						structures[name1],
						structures[name2],
						name1=name1,
						name2=name2,
					)
				except Exception as exc:
					print(f"Failed to align {name1} vs {name2}: {exc}")
					continue

				key = f"{name1}_vs_{name2}"
				tm_score = float(alignment.get("tm_score", 0.0))
				rmsd = float(alignment.get("rmsd", 0.0))

				analysis["pairwise_tm_score"][key] = round(tm_score, 3)
				analysis["pairwise_rmsd"][key] = round(rmsd, 2)
				tm_values.append(tm_score)
				rmsd_values.append(rmsd)

		if tm_values:
			avg_tm = sum(tm_values) / len(tm_values)
			avg_rmsd = sum(rmsd_values) / len(rmsd_values) if rmsd_values else 0.0
			analysis["consensus_confidence"] = round(avg_tm, 3)
			analysis["has_consensus"] = bool(avg_tm >= 0.5)
			analysis["summary"] = (
				f"Compared {len(valid_models)} structures. "
				f"Avg TM-score: {avg_tm:.3f}, Avg RMSD: {avg_rmsd:.2f}A. "
				f"{'Consensus reached.' if analysis['has_consensus'] else 'No consensus.'}"
			)
		else:
			analysis["summary"] = (
				f"Found {len(model_names)} structures but failed to compute TM-align metrics."
			)

		return analysis

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "analyze":
				await self.agent.handle_analyze(agent_msg)
