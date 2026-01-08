import uuid
from datetime import datetime
from app.agents.BaseAgent import BaseAgent, AgentMessage
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from app.utils.db import MongoConnection

class CoordinatorAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)

		self.jobs = {}
		self.db_job_mapping = {}  

		self.data_agent_jid = "data_agent@localhost"
		self.psp_agent_jid = "psp_agent@localhost"
		self.processing_agent_jid = "processing_agent@localhost"
		self.synthesis_agent_jid = "synthesis_agent@localhost"
		self.output_agent_jid = "output_agent@localhost"
		self.modal_agent_jid = "modal_agent@localhost"

	async def start_job(self, input_type: str, input_value: str, db_job_id: str = None, options: dict = None): 
		job_id = db_job_id or str(uuid.uuid4())

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
			"db_job_id": db_job_id,  
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
		
		check_db_behaviour = CheckDatabaseForJobsBehaviour(period=5)
		self.add_behaviour(check_db_behaviour)

		print(f"CoordinatorAgent {self.jid} started")



	async def handle_response(self, agent_msg: AgentMessage):
		job_id = agent_msg.job_id
		action = agent_msg.action

		job = self.jobs.get(job_id)
		if not job:
			print(f"Job {job_id} not found")
			return

		if action == "data_fetched":
			print(f"[{job_id}] Data collection complete! Moving to prediction")
			job["raw_data"] = agent_msg.payload.get("data")
			job["status"] = "predicting_structure"

			sequence = job["raw_data"].get("uniprot", {}).get("sequence", "")

			# TEST MODE: Force Modal for everything > 0 then to change to 400
			if len(sequence) > 0:
				print(f"[{job_id}] Sequence length {len(sequence)} > 400. Routing to Modal Agent (ColabFold).")
				msg = self.create_message(
					to=self.modal_agent_jid,
					msg_type="request",
					action="predict_colabfold_modal",
					payload={"sequence": sequence},
					job_id=job_id,
				)
				await self.send(msg)
			else: 
				print(f"[{job_id}] Sequence length {len(sequence)} <= 400. Routing to PSP Agent (ESMFold).")
				msg = self.create_message(
					to=self.psp_agent_jid,
					msg_type="request",
					action="predict_structure",
					payload={"sequence": sequence},
					job_id=job_id,
				)
				await self.send(msg)
		elif action == "structure_predicted":
			job["psp_results"] = agent_msg.payload.get("results", {})
			job["models_used"] = agent_msg.payload.get("models_used", [])
			job["psp_errors"] = agent_msg.payload.get("errors", {})
			job["status"] = "processing"
			
			if job["models_used"]:
				print(f"[{job_id}] Received predictions from: {job['models_used']}")
			if job["psp_errors"]:
				print(f"[{job_id}] Warning: Some models failed: {list(job['psp_errors'].keys())}")
			
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
			
			db_job_id = job.get("db_job_id")
			if MongoConnection.db is not None:
				if db_job_id:
					try:
						from bson import ObjectId
						await MongoConnection.db.tasks.update_one(
							{"_id": ObjectId(db_job_id)},
							{"$set": {"status": "completed", "output_path": job["output_results"]}}
						)
					except Exception as e:
						print(f"Failed to update task status: {e}")
				
				final_output = {
					"accession": job["input_value"],
					"status": "completed",
					"timestamp": str(datetime.now()),
					"output_path": job["output_results"],
					"metrics": job.get("processing_results"),
					"synthesis": job.get("synthesis_results"),
					"uniprot": job["raw_data"].get("uniprot"),
					"psp_results": job.get("psp_results"),  
					"models_used": job.get("models_used", []),
					"psp_errors": job.get("psp_errors", {})
				}
				await MongoConnection.db.protein_results.update_one(
					{"accession": job["input_value"]},
					{"$set": final_output},
					upsert=True
				)
				print(f"Saved final results to DB for {job['input_value']}")


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, coordinator):
		super().__init__()
		self.coordinator = coordinator

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.coordinator.parse_message(msg)
			await self.coordinator.handle_response(agent_msg)

class CheckDatabaseForJobsBehaviour(PeriodicBehaviour):
	async def run(self):
		if MongoConnection.db is None:
			return
			
		pending_job = await MongoConnection.db.tasks.find_one_and_update(
			{"status": "pending"},
			{"$set": {"status": "processing"}}
		)
		
		if pending_job:
			accession = pending_job.get("input_value")
			input_type = pending_job.get("input_type", "accession")
			db_job_id = str(pending_job["_id"])
			print(f"Coordinator: Picked up job {db_job_id} for {accession} ({input_type})")
			
			await self.agent.start_job(
				input_type=input_type, 
				input_value=accession,
				db_job_id=db_job_id
			)