from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from app.agents.BaseAgent import BaseAgent
import modal
import asyncio
import concurrent.futures
import os

class ModalAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")
		self.active_calls = {} 
		self.modal_app_name = os.getenv("MODAL_APP_NAME", "psp-colabfold-worker")
		self.modal_function_name = os.getenv("MODAL_FUNCTION_NAME", "predict_structure_remote")

	async def setup(self):
		self.add_behaviour(MessageHandlerBehaviour(self))
		self.add_behaviour(CheckModalJobsBehaviour(period=5))
		print(
			f"ModalAgent {self.jid} started - Connected to Modal Cloud "
			f"(app={self.modal_app_name}, fn={self.modal_function_name})"
		)

	async def handle_predict(self, msg):
		job_id = msg.job_id
		sequence = msg.payload.get("sequence")
		if not sequence:
			payload = {
				"results": {},
				"models_used": [],
				"errors": {"colabfold_modal": "No sequence provided for Modal prediction"},
			}
			msg = self.create_message(
				to=self.coordinator_jid,
				msg_type="response",
				action="structure_predicted",
				payload=payload,
				job_id=job_id,
			)
			await self.send(msg)
			return
		
		print(f"[{job_id}] ModalAgent: Spawning remote ColabFold job...")
		
		try:
			remote_func = modal.Function.from_name(self.modal_app_name, self.modal_function_name)
			function_call = await asyncio.wait_for(
				remote_func.spawn.aio(sequence, job_id),
				timeout=20,
			)
			
			self.active_calls[job_id] = function_call
			print(f"[{job_id}] Started Modal Job ID: {function_call.object_id}")
			
		except Exception as e:
			print(f"[{job_id}] Failed to spawn Modal job: {e}")
			payload = {
				"results": {},
				"models_used": [],
				"errors": {"colabfold_modal": str(e)}
			}
			msg = self.create_message(
				to=self.coordinator_jid,
				msg_type="response",
				action="structure_predicted",
				payload=payload,
				job_id=job_id,
			)
			await self.send(msg)

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "predict_colabfold_modal":
				await self.agent.handle_predict(agent_msg)

class CheckModalJobsBehaviour(PeriodicBehaviour):
	async def run(self):
		if not self.agent.active_calls:
			return

		for job_id, call in list(self.agent.active_calls.items()):
			try:
				result = await call.get.aio(timeout=0)
				
				print(f"[{job_id}] Modal Job Finished!")
				if not isinstance(result, dict):
					raise RuntimeError(f"Unexpected Modal result type: {type(result).__name__}")
				
				if result.get("status") == "success":
					pdb_content = result.get("pdb_content")
					if not pdb_content:
						raise RuntimeError("Modal returned success but missing pdb_content")
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
				
			except (concurrent.futures.TimeoutError, asyncio.TimeoutError, TimeoutError):
				pass
			except Exception as e:
				print(f"[{job_id}] Error checking Modal status: {e}")
				
				payload = {
					"results": {},
					"models_used": [],
					"errors": {"colabfold_modal": str(e)}
				}
				
				msg = self.agent.create_message(
					to=self.agent.coordinator_jid,
					msg_type="response",
					action="structure_predicted", 
					payload=payload,
					job_id=job_id
				)
				await self.agent.send(msg)
				
				del self.agent.active_calls[job_id]
