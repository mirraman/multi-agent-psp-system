import uuid
from app.agents.base_agent import BaseAgent, AgentMessage
from spade.behaviour import CyclicBehaviour

class CoordinatorAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)

		self.jobs = {}

		self.data_agent_jid = "data_agent@localhost"
		self.psp_agent_jid = "psp_agent@localhost"
		self.processing_agent_jid = "processing_agent@localhost"
		self.synthesis_agent_jid = "synthesis_agent@localhost"
		self.output_agent_jid = "output_agent@localhost"

	async def start_job(self, input_type: str, input_value: str, options: dict = None): 
		job_id = str(uuid.uuid4())

		self.jobs[job_id] = {
			"status": "fetching_data",
			"input_type": input_type,
			"input_value": input_value,
			"options": options or {},
			"raw_data": None,
			"psp_results": None,
			"processing_results": None,
			"synthesis_results": None,
			"output_results": None,
		}

		msg = self.create_message(
			to=self.data_agent_jid,
			msg_type="request",
			action="fetch_data",
			payload={"input_type": input_type, "input_value": input_value},
			job_id=job_id,
		)
		await self.send(msg)

		return job_id
	
	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"CoordinatorAgent {self.jid} started")

	async def handle_response(self, agent_msg: AgentMessage):
		job_id = agent_msg.job_id
		action = agent_msg.action

		job = self.jobs.get(job_id)
		if not job:
			print(f"Job {job_id} not found")
			return
		
		if action == "data_fetched":
			job["raw_data"] = agent_msg.payload.get("data")
			job["status"] = "predicting_structure"

			sequence = job["raw_data"].get("uniprot", {}).get("sequence", "")
			msg = self.create_message(
				to=self.psp_agent_jid,
				msg_type="request",
				action="predict_structure",
				payload={"sequence": sequence},
				job_id=job_id,
			)
			await self.send(msg)

		elif action == "structure_predicted":
			job["psp_results"] = agent_msg.payload.get("results")
			job["status"] = "processing"
			msg = self.create_message(
				to=self.processing_agent_jid,
				msg_type="request",
				action="process",
				payload={
					"raw_data": job["raw_data"],
					"psp_results": job["psp_results"],
				},
				job_id=job_id,
			)
			await self.send(msg)

		elif action == "processed":
			job["processing_results"] = agent_msg.payload.get("metrics")
			job["status"] = "synthesizing"
			msg = self.create_message(
				to=self.synthesis_agent_jid,
				msg_type="request",
				action="synthesize",
				payload={
					"raw_data": job["raw_data"],
					"psp_results": job["psp_results"],
					"processing_results": job["processing_results"],
				},
				job_id=job_id,
			)
			await self.send(msg)

		elif action == "synthesized":
			job["synthesis_results"] = agent_msg.payload.get("synthesis")
			job["status"] = "generating_output"
			accession = job["input_value"] if job["input_type"] == "accession" else job_id
			msg = self.create_message(
				to=self.output_agent_jid,
				msg_type="request",
				action="generate_output",
				payload={
					"accession": accession,
					"raw_data": job["raw_data"],
					"psp_results": job["psp_results"],
					"processing_results": job["processing_results"],
					"synthesis_results": job["synthesis_results"],
				},
				job_id=job_id,
			)
			await self.send(msg)

		elif action == "output_generated":
			job["output_results"] = agent_msg.payload.get("output_path")
			job["status"] = "completed"
			print(f"Job {job_id} completed: {job['output_results']}")


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, coordinator):
		super().__init__()
		self.coordinator = coordinator

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.coordinator.parse_message(msg)
			await self.coordinator.handle_response(agent_msg)
