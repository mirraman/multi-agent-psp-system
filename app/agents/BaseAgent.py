import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict

from spade.agent import Agent
from spade.message import Message
from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour


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


class SendBehaviour(OneShotBehaviour):
	def __init__(self, msg):
		super().__init__()
		self.msg = msg

	async def run(self):
		await self.send(self.msg)


class ActionMessageHandlerBehaviour(CyclicBehaviour):
	"""Generic message dispatcher for agents keyed by AgentMessage.action."""

	def __init__(
		self,
		owner: "BaseAgent",
		action_to_handler: Dict[str, str],
		default_handler: str = "",
		timeout: int = 10,
	):
		super().__init__()
		self.owner = owner
		self.action_to_handler = action_to_handler
		self.default_handler = default_handler
		self.timeout = timeout

	async def run(self):
		msg = await self.receive(timeout=self.timeout)
		if not msg or msg.body == "__ping__":
			return

		agent_msg = self.owner.parse_message(msg)
		handler_name = self.action_to_handler.get(agent_msg.action, self.default_handler)
		if not handler_name:
			return

		handler = getattr(self.owner, handler_name, None)
		if handler is None:
			return
		await handler(agent_msg)


class XmppKeepAliveBehaviour(PeriodicBehaviour):
	"""Send a self-addressed XMPP ping every 60s to prevent idle connection timeout."""
	async def run(self):
		try:
			msg = Message(to=str(self.agent.jid))
			msg.body = "__ping__"
			await self.send(msg)
		except Exception:
			pass


class BaseAgent(Agent):
	def __init__(self, jid: str, password: str):
		# verify_security=False tells aioxmpp to skip TLS certificate
		# verification, which is required when Prosody uses a self-signed cert.
		super().__init__(jid, password, verify_security=False)

	@staticmethod
	def agent_domain() -> str:
		return os.getenv("XMPP_DOMAIN", "xmpp")

	@classmethod
	def format_jid(cls, localpart: str) -> str:
		return f"{localpart}@{cls.agent_domain()}"

	async def setup(self):
		self.add_behaviour(XmppKeepAliveBehaviour(period=60))
		print(f"Agent {self.jid} started")

	async def send(self, msg):
		b = SendBehaviour(msg)
		self.add_behaviour(b)

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
