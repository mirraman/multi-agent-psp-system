from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from celery.result import AsyncResult
from app.tasks import predict_structure_task


class PspAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"
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
		
		print(f"[{job_id}] PspAgent: Delegating prediction to Celery...")
		
		task = predict_structure_task.delay(sequence)
		self.pending_tasks[job_id] = task.id


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
				print(f"[{job_id}] PspAgent: Celery task finished!")
				
				result_data = async_result.result
				del self.agent.pending_tasks[job_id]
				
				if result_data.get("status") == "success":
					payload = {
						"results": {
							"pdb": result_data.get("pdb_text"),
							"source": "ESMFold_Celery"
						}
					}
				else:
					payload = {"error": result_data.get("error")}
				
				msg = self.agent.create_message(
					to=self.agent.coordinator_jid,
					msg_type="response",
					action="structure_predicted",
					payload=payload,
					job_id=job_id,
				)
				await self.agent.send(msg)
