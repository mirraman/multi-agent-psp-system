from collections import Counter
from typing import Any, Dict

from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour


class ProcessingAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"ProcessingAgent {self.jid} started")

	async def handle_process(self, agent_msg):
		job_id = agent_msg.job_id
		raw_data = agent_msg.payload.get("raw_data", {})
		psp_results = agent_msg.payload.get("psp_results", {})

		metrics = self._calculate_metrics(raw_data, psp_results)

		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="processed",
			payload={"metrics": metrics},
			job_id=job_id,
		)
		await self.send(msg)

	def _calculate_metrics(self, raw_data: Dict[str, Any], psp_results: Dict[str, Any]) -> Dict[str, Any]:
		results: Dict[str, Any] = {}

		sequence = (raw_data.get("uniprot") or {}).get("sequence", "")
		if sequence:
			results["sequence_length"] = len(sequence)
			results["amino_acid_composition"] = dict(Counter(sequence))

		af_data = raw_data.get("alphafold") or {}
		if af_data:
			conf = af_data.get("confidence") or af_data.get("confidence_metrics") or af_data.get("plddt_mean")
			if conf is not None:
				results["alphafold_confidence"] = conf

			frac_conf = af_data.get("fraction_confident")
			if frac_conf is not None:
				results["fraction_confident"] = frac_conf

		pdb_list = raw_data.get("pdb") or []
		results["pdb_count"] = len(pdb_list)
		if pdb_list:
			method_counts: Dict[str, int] = {}
			best_resolution = None
			for entry in pdb_list:
				meta = (entry or {}).get("metadata") or {}
				method = meta.get("experimental_method") or "UNKNOWN"
				method_counts[method] = method_counts.get(method, 0) + 1
				res = meta.get("resolution")
				if isinstance(res, (int, float)):
					if best_resolution is None or res < best_resolution:
						best_resolution = res
			results["pdb_method_counts"] = method_counts
			if best_resolution is not None:
				results["pdb_best_resolution"] = best_resolution

		if psp_results:
			esmfold_data = psp_results.get("esmfold", {})
			if esmfold_data:
				pdb_text = esmfold_data.get("pdb", "")
				if pdb_text:
					results["esmfold_predicted"] = True
					plddt_mean, plddt_per_residue = self._extract_plddt_from_pdb(pdb_text)
					if plddt_mean is not None:
						results["esmfold_plddt_mean"] = plddt_mean
					if plddt_per_residue:
						# Store with string keys for JSON serialisation
						results["plddt_per_residue"] = {
							str(k): v for k, v in plddt_per_residue.items()
						}
			# Also capture ColabFold/Modal pLDDT if available
			modal_data = psp_results.get("colabfold_modal", {})
			modal_pdb = modal_data.get("pdb", "")
			if modal_pdb and "plddt_per_residue" not in results:
				plddt_mean, plddt_per_residue = self._extract_plddt_from_pdb(modal_pdb)
				if plddt_mean is not None:
					results["modal_plddt_mean"] = plddt_mean
				if plddt_per_residue:
					results["plddt_per_residue"] = {
						str(k): v for k, v in plddt_per_residue.items()
					}
		else:
			results["esmfold_predicted"] = False

		return results

	def _extract_plddt_from_pdb(self, pdb_text: str) -> tuple[float | None, dict[int, float]]:
		"""
		Parse pLDDT scores from the B-factor column of CA atoms in a PDB string.

		Returns:
			(mean_plddt, per_residue_dict)
			- mean_plddt: float average over all CA atoms, or None if no ATOM records found
			- per_residue_dict: mapping of residue_number (int) -> pLDDT (float, 0-100 scale)
		"""
		per_residue: dict[int, float] = {}
		for line in pdb_text.splitlines():
			if line.startswith("ATOM") and len(line) >= 66:
				atom_name = line[12:16].strip()
				if atom_name == "CA":
					try:
						res_num = int(line[22:26].strip())
						bfactor = float(line[60:66].strip())
						# Normalise to 0-100 scale if stored as 0-1
						if bfactor < 1.5:
							bfactor = bfactor * 100
						per_residue[res_num] = bfactor
					except ValueError:
						continue
		if per_residue:
			avg = sum(per_residue.values()) / len(per_residue)
			return avg, per_residue
		return None, {}


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "process":
				await self.agent.handle_process(agent_msg)

