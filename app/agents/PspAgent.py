from typing import Any, Dict
from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from celery.result import AsyncResult
from app.tasks import predict_esmfold


class PspAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")
		self.pending_tasks = {}  

	async def setup(self):
		msg_handler = MessageHandlerBehaviour(self)
		self.add_behaviour(msg_handler)
		
		task_checker = CheckCeleryTasksBehaviour(period=2)
		self.add_behaviour(task_checker)
		
		print(f"PspAgent {self.jid} started")

	async def handle_predict_structure(self, agent_msg):
		job_id = agent_msg.job_id
		sequence = agent_msg.payload.get("sequence")
		
		print(f"[{job_id}] PspAgent: Launching ESMFold prediction...")
		
		task_esm = predict_esmfold.delay(sequence)
		self.pending_tasks[job_id] = task_esm.id
		
		print(f"[{job_id}] Launched ESMFold task: {task_esm.id}")


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "predict_structure":
				await self.agent.handle_predict_structure(agent_msg)


class CheckCeleryTasksBehaviour(PeriodicBehaviour):
	async def run(self):
		if not self.agent.pending_tasks:
			return
			
		for job_id, task_id in list(self.agent.pending_tasks.items()):
			async_result = AsyncResult(task_id)
			
			if async_result.ready():
				print(f"[{job_id}] PspAgent: ESMFold task finished!")

				try:
					result_data = async_result.result
				except Exception as e:
					print(f"[{job_id}] Celery task raised an exception: {e}")
					result_data = {
						"status": "failed",
						"error": str(e),
					}

				del self.agent.pending_tasks[job_id]
					
				if result_data.get("status") == "success":
					payload = {
						"results": {
							"esmfold": {
								"pdb": result_data.get("pdb_text"),
								"source": result_data.get("source", "ESMFold_API")
							}
						},
						"models_used": ["esmfold"],
						"errors": {}
					}
					print(f"[{job_id}] ESMFold succeeded")
				else:
					payload = {
						"results": {},
						"models_used": [],
						"errors": {
							"esmfold": result_data.get("error", "Unknown error")
						}
					}
					print(f"[{job_id}] ESMFold failed: {result_data.get('error')}")
				
				msg = self.agent.create_message(
					to=self.agent.coordinator_jid,
					msg_type="response",
					action="structure_predicted",
					payload=payload,
					job_id=job_id,
				)
				await self.agent.send(msg)

