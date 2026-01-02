from app.agents.base_agent import BaseAgent
from app.agents.data_agent import DataAgent
from spade.behaviour import CyclicBehaviour

class DataAgentSpade(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.data_agent = DataAgent()
		self.coordinator_jid = "coordinator@localhost"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		print(f"DataAgentSpade {self.jid} started")

	async def handle_fetch_data(self, agent_msg):
		job_id = agent_msg.job_id
		input_type = agent_msg.payload.get("input_type")
		input_value = agent_msg.payload.get("input_value")

		data = self.data_agent.run(input_value)

		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="data_fetched",
			payload={"data": data},
			job_id=job_id,
		)
		await self.send(msg)

class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, data_agent_spade):
		super().__init__()
		self.data_agent_spade = data_agent_spade

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.data_agent_spade.parse_message(msg)
			if agent_msg.action == "fetch_data":
				await self.data_agent_spade.handle_fetch_data(agent_msg)