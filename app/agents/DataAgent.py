from app.agents.BaseAgent import ActionMessageHandlerBehaviour, BaseAgent
from app.utils.fetchers import (
	fetch_uniprot,
	fetch_pdb,
	fetch_pubmed,
	fetch_alphafold_db_pdb,
	fetch_pdb_text,
)
from app.utils.open_targets import fetch_disease_targets
from typing import Any, Dict, List


class DataAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")

	async def setup(self):
		behaviour = ActionMessageHandlerBehaviour(
			self,
			action_to_handler={"fetch_data": "handle_fetch_data"},
		)
		self.add_behaviour(behaviour)
		print(f"DataAgent {self.jid} started")

	async def handle_fetch_data(self, agent_msg):
		job_id = agent_msg.job_id
		input_type = agent_msg.payload.get("input_type", "accession")
		input_value = agent_msg.payload.get("input_value")
		include_pubmed = agent_msg.payload.get("include_pubmed", False)

		print(f"[{job_id}] DataAgent: fetching data for {input_type}: {input_value[:80]}...")

		try:
			if input_type == "fasta":
				data = self._fetch_by_fasta(input_value)
			elif input_type == "disease":
				data = self._fetch_by_disease(input_value)
			else:
				data = self._fetch_by_accession(input_value, include_pubmed)

			msg = self.create_message(
				to=self.coordinator_jid,
				msg_type="response",
				action="data_fetched",
				payload={"data": data},
				job_id=job_id,
			)
		except Exception as e:
			error_msg = f"Data fetch failed ({input_type}:{input_value}): {e}"
			print(f"[{job_id}] {error_msg}")
			msg = self.create_message(
				to=self.coordinator_jid,
				msg_type="response",
				action="error",
				payload={"error": error_msg},
				job_id=job_id,
			)

		await self.send(msg)

	def _fetch_by_fasta(self, fasta_content: str) -> dict:
		"""Parse FASTA sequence directly — no external API calls."""
		lines = fasta_content.strip().split('\n')
		if lines[0].startswith('>'):
			header = lines[0][1:]
			sequence = ''.join(lines[1:])
		else:
			header = "Custom sequence"
			sequence = fasta_content.strip()

		return {
			"uniprot": {
				"name": header,
				"sequence": sequence,
				"pdb_ids": [],
			},
			"pdb": [],
			"pubmed": []
		}

	def _fetch_by_disease(self, disease_name: str) -> dict:
		"""
		Query Open Targets for disease-associated protein targets.
		Returns disease context + ranked target list.
		The CoordinatorAgent uses this to spawn per-protein sub-jobs.
		"""
		try:
			result = fetch_disease_targets(disease_name, limit=5)
			return {
				"disease_context": {
					"disease_id": result["disease_id"],
					"disease_name": result["disease_name"],
					"targets": result["targets"],
				},
				"uniprot": None,    # no single protein yet — coordinator spawns sub-jobs
				"pdb": [],
				"pubmed": [],
			}
		except RuntimeError as e:
			# Return error payload — CoordinatorAgent will handle gracefully
			return {
				"disease_context": None,
				"error": str(e),
				"uniprot": None,
				"pdb": [],
				"pubmed": [],
			}

	def _fetch_by_accession(self, accession: str, include_pubmed: bool = False) -> Dict[str, Any]:
		uniprot_data = fetch_uniprot(accession)

		pdb_results: List[Dict[str, Any]] = []
		for pdb_id in uniprot_data.get("pdb_ids", []):
			try:
				entry = fetch_pdb(pdb_id)
				entry["pdb_id"] = pdb_id
				pdb_results.append(entry)
			except Exception:
				continue

		experimental_best: Dict[str, Any] = {}
		best_res = None
		best_entry = None
		for entry in pdb_results:
			meta = (entry or {}).get("metadata") or {}
			res = meta.get("resolution")
			if isinstance(res, (int, float)):
				if best_res is None or res < best_res:
					best_res = res
					best_entry = entry
		if best_entry and best_entry.get("pdb_id"):
			try:
				pdb_text = fetch_pdb_text(best_entry["pdb_id"])
				if pdb_text and pdb_text.strip():
					experimental_best = {
						"pdb_id": best_entry["pdb_id"],
						"pdb_text": pdb_text,
						"resolution": best_res,
					}
			except Exception:
				pass

		alphafold_db: Dict[str, Any] = {}
		try:
			af = fetch_alphafold_db_pdb(accession)
			if af:
				alphafold_db = af
		except Exception as exc:
			print(f"[{accession}] DataAgent caught exception fetching AlphaFold DB: {exc}")

		pubmed_data = None
		if include_pubmed:
			name = uniprot_data.get("name") or ""
			query = accession if not name else f"{accession} {name}"
			pubmed_data = fetch_pubmed(query)

		return {
			"accession": accession,
			"uniprot": {
				"name": uniprot_data.get("name"),
				"sequence": uniprot_data.get("sequence"),
				"pdb_ids": uniprot_data.get("pdb_ids", []),
			},
			"pdb": pdb_results,
			"pubmed": pubmed_data,
			"experimental_best_pdb": experimental_best,
			"alphafold_db": alphafold_db,
		}
