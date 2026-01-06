from app.agents.BaseAgent import BaseAgent
from app.utils.fetchers import fetch_uniprot, fetch_pdb, fetch_alphafold, fetch_pubmed
from spade.behaviour import CyclicBehaviour
from typing import Any, Dict, List


class DataAgentSpade(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"DataAgentSpade {self.jid} started")

	async def handle_fetch_data(self, agent_msg):
		job_id = agent_msg.job_id
		input_type = agent_msg.payload.get("input_type", "accession")
		input_value = agent_msg.payload.get("input_value")
		include_pubmed = agent_msg.payload.get("include_pubmed", False)
		
		print(f"[{job_id}] DataAgent: fetching data for {input_type}: {input_value[:50]}...")
		
		if input_type == "fasta":
			data = self._fetch_by_fasta(input_value)
		else:
			data = self._fetch_by_accession(input_value, include_pubmed)
		
		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="data_fetched",
			payload={"data": data},
			job_id=job_id,
		)
		await self.send(msg)
	
	def _fetch_by_fasta(self, fasta_content: str) -> dict:
		"""
		Parse FASTA sequence directly without external API calls.
		For FASTA input, we skip UniProt/AlphaFold DB/PDB lookups.
		"""
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
				"alphafold_links": []
			},
			"pdb": [],
			"alphafold": {}, 
			"pubmed": []
		}
	
	def _fetch_by_accession(self, accession: str, include_pubmed: bool = False) -> Dict[str, Any]:
		uniprot_data = fetch_uniprot(accession)

		pdb_results: List[Dict[str, Any]] = []
		for pdb_id in uniprot_data.get("pdb_ids", []):
			try:
				pdb_results.append(fetch_pdb(pdb_id))
			except Exception:
				continue

		alphafold_data = fetch_alphafold(accession)

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
				"alphafold_links": uniprot_data.get("alphafold_links", []),
			},
			"pdb": pdb_results,
			"alphafold": alphafold_data,
			"pubmed": pubmed_data,
		}

	def _parse_fasta(self, fasta_content: str) -> Dict[str, Any]:
		lines = fasta_content.strip().split("\n")
		header = ""
		sequence_parts = []

		for line in lines:
			if line.startswith(">"):
				header = line[1:].strip()
			else:
				sequence_parts.append(line.strip())

		sequence = "".join(sequence_parts)

		return {
			"accession": header or "fasta_input",
			"uniprot": {
				"name": header,
				"sequence": sequence,
				"pdb_ids": [],
				"alphafold_links": [],
			},
			"pdb": [],
			"alphafold": {},
			"pubmed": None,
		}


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "fetch_data":
				await self.agent.handle_fetch_data(agent_msg)
