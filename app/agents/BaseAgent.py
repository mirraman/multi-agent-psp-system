import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from spade.agent import Agent
from spade.message import Message

@dataclass
class AgentMessage:
	msg_type: str
	action: str
	payload: Dict[str, Any]
	job_id: str = ""

	def to_json(self) -> str:
		return json.dumps(asdict(self))

	@classmethod
	def from_json(cls, data: str) -> "AgentMessage":	
		obj = json.loads(data)
		return cls(
			msg_type=obj.get("msg_type", ""),
			action=obj.get("action", ""),
			payload=obj.get("payload", {}),
			job_id=obj.get("job_id", ""),
		)

class BaseAgent(Agent):

	async def setup(self):
		print(f"Agent {self.jid} started")

	async def send(self, msg):
		await self.client.send(msg)

	def create_message(
			self,
			to: str,
			msg_type: str,
			action: str,
			payload: Dict[str, Any],
			job_id: str = ""
	) -> Message:
		msg = Message(to=to)

		agent_msg = AgentMessage(
			msg_type=msg_type,
			action=action,
			payload=payload,
			job_id=job_id,
		)
		msg.body = agent_msg.to_json()

		return msg
	
	def parse_message(self, msg: Message) -> AgentMessage:
		return AgentMessage.from_json(msg.body)