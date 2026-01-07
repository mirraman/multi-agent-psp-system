from typing import Dict
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from app.agents.BaseAgent import BaseAgent
from app.ModalApp import predict_structure_remote
import asyncio

class ModalAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"
		self.active_calls = {} 

	async def setup(self):
		self.add_behaviour(MessageHandlerBehaviour(self))
		self.add_behaviour(CheckModalJobsBehaviour(period=5))
		print(f"ModalAgent {self.jid} started - Connected to Modal Cloud")

	async def handle_predict(self, msg):
		job_id = msg.job_id
		sequence = msg.payload.get("sequence")
		
		print(f"[{job_id}] ModalAgent: Spawning remote AlphaFold job...")
		
		try:
			function_call = predict_structure_remote.spawn(sequence, job_id)
			
			self.active_calls[job_id] = function_call
			print(f"[{job_id}] Started Modal Job ID: {function_call.object_id}")
			
		except Exception as e:
			print(f"[{job_id}] Failed to spawn Modal job: {e}")
			# TODO: Send error back to coordinator

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "predict_alphafold_modal":
				await self.agent.handle_predict(agent_msg)

class CheckModalJobsBehaviour(PeriodicBehaviour):
	async def run(self):
		if not self.agent.active_calls:
			return

		for job_id, call in list(self.agent.active_calls.items()):
			try:
				result = call.get(timeout=0)
				
				print(f"[{job_id}] Modal Job Finished!")
				
				if result.get("status") == "success":
					pdb_content = result.get("pdb_content")
					payload = {
						"results": {
							"colabfold_modal": {
								"pdb": pdb_content,
								"source": "Modal_Cloud_ColabFold",
								"confidence": "Unknown" 
							}
						},
						"models_used": ["colabfold_modal"],
						"errors": {}
					}
					print(f"[{job_id}] Modal Success")
				else:
					payload = {
						"results": {},
						"models_used": [],
						"errors": {"colabfold_modal": result.get("error", "Unknown Error")}
					}
					print(f"[{job_id}] Modal Failed: {result.get('error')}")

				msg = self.agent.create_message(
					to=self.agent.coordinator_jid,
					msg_type="response",
					action="structure_predicted", 
					payload=payload,
					job_id=job_id
				)
				await self.agent.send(msg)
				
				del self.agent.active_calls[job_id]
				
			except TimeoutError:
				pass
			except Exception as e:
				print(f"[{job_id}] Error checking Modal status: {e}")
				del self.agent.active_calls[job_id]
