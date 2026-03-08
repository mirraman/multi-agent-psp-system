import io

from typing import Any, Dict, List, Optional, Tuple
from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour
from Bio.PDB import PDBParser, Superimposer


class AnalysisAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"

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

	def _parse_ca_atoms(self, pdb_text: str, model_name: str) -> List[Tuple[int, Any]]:
		parser = PDBParser(QUIET=True)
		structure = parser.get_structure(model_name, io.StringIO(pdb_text))

		ca_atoms = []
		for model in structure:
			for chain in model:
				for residue in chain:
					if "CA" in residue:
						ca_atoms.append((residue.id[1], residue["CA"]))
				break
			break

		return ca_atoms
	
	def _calculate_rmsd(self, atoms1: List[Tuple[int, Any]], atoms2: List[Tuple[int, Any]]) -> Optional[float]:
		
		atoms1_dict = {res_num: atom for res_num, atom in atoms1}
		atoms2_dict = {res_num: atom for res_num, atom in atoms2}

		common_residues = set(atoms1_dict.keys()) & set(atoms2_dict.keys())
		if len(common_residues) < 3:
			return None
		
		common_sorted = sorted(common_residues)
		fixed_atoms =  [atoms1_dict[r] for r in common_sorted]
		moving_atoms = [atoms2_dict[r] for r in common_sorted]

		super_imposer = Superimposer()
		super_imposer.set_atoms(fixed_atoms, moving_atoms)

		return super_imposer.rms


	def _analyze_structures(
		self,
		raw_data: Dict[str, Any],
		psp_results: Dict[str, Any],
		processing_results: Dict[str, Any]
	) -> Dict[str, Any]:

		analysis: Dict[str, Any] = {
			"models_compared": [],
			"pairwise_rmsd": {},
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
		


		model_names = list(structures.keys())
		analysis["models_compared"] = model_names

		if len(model_names) < 2:
			analysis["summary"] = f"Only {len(model_names)} structure(s) available. Cannot compute RMSD comparison. Available: {model_names}"
			return analysis

		ca_atoms = {}
		for name, pdb_string in structures.items():
			try: 
				ca_atoms[name] = self._parse_ca_atoms(pdb_string, name)
			except Exception as e:
				print(f"Failed to parse {name}: {e}")
				continue
		
		valid_models = list(ca_atoms.keys())
		rmsd_values = []

		for i, name1 in enumerate(valid_models):
			for name2 in valid_models[i+1:]:
				rmsd = self._calculate_rmsd(ca_atoms[name1], ca_atoms[name2])
				if rmsd is not None:
					key = f"{name1}_vs_{name2}"
					analysis["pairwise_rmsd"][key] = float(round(rmsd, 2))
					rmsd_values.append(float(rmsd))

		if rmsd_values: 
			avg_rmsd = sum(rmsd_values) / len(rmsd_values)
			analysis["consensus_confidence"] = float(max(0, 1 - (avg_rmsd / 10)))
			analysis["has_consensus"] = bool(avg_rmsd < 3.0)
			analysis["summary"] = f"Compared {len(valid_models)} structures. Avg RMSD: {avg_rmsd:.2f}A. {'Consensus reached.' if analysis['has_consensus'] else 'No consensus.'}"
		else:
			analysis["summary"] = f"Found {len(model_names)} structures but failed to compute RMSD."

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
