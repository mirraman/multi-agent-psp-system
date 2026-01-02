from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour
import requests

class PspAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"
		self.esmfold_api_url = "https://api.esmatlas.com/foldSequence/v1/pdb/"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"PspAgent {self.jid} started")

	async def handle_predict_structure(self, agent_msg):
		job_id = agent_msg.job_id
		sequence = agent_msg.payload.get("sequence")

		response = requests.post(
			self.esmfold_api_url, 
			data=sequence,
			headers={"Content-Type": "text/plain"},
			)
		
		if response.status_code == 200:
			pdb_text = response.text
	# TODO: extract confidence scores from pdb_text (optional for now)

			msg = self.create_message(
				to=self.coordinator_jid,
				msg_type="response",
				action="structure_predicted",
				payload={"results": {"pdb": pdb_text, "confidence": None}},
				job_id=job_id,
			)
			await self.send(msg)
		
		else: 
			print(f"ESMFold API request failed: {response.status_code}")

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, psp_agent):
		super().__init__()
		self.psp_agent = psp_agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.psp_agent.parse_message(msg)
			if agent_msg.action == "predict_structure":
				await self.psp_agent.handle_predict_structure(agent_msg)