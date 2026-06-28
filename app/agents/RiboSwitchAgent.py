from app.agents.BaseAgent import ActionMessageHandlerBehaviour, BaseAgent
from spade.behaviour import PeriodicBehaviour
from celery.result import AsyncResult
from app.tasks import design_riboswitch


class RiboSwitchAgent(BaseAgent):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.coordinator_jid = self.format_jid("coordinator")
        self.pending_tasks = {}

    async def setup(self):
        msg_handler = ActionMessageHandlerBehaviour(
            self,
            action_to_handler={"design_riboswitch": "handle_design_riboswitch"},
        )
        self.add_behaviour(msg_handler)

        task_checker = CheckCeleryTasksBehaviour(period=5)
        self.add_behaviour(task_checker)

        print(f"RiboSwitchAgent {self.jid} started")

    async def handle_design_riboswitch(self, agent_msg):
        job_id = agent_msg.job_id
        payload = agent_msg.payload

        print(f"[{job_id}] RiboSwitchAgent: Launching riboswitch design...")

        task = design_riboswitch.delay(
            structure_on=payload.get("structure_on"),
            structure_off=payload.get("structure_off"),
            population=payload.get("population", 100),
            generations=payload.get("generations", 50),
            mutation_rate=payload.get("mutation_rate", 0.1),
            seed=payload.get("seed"),
            bp_distance_obj=payload.get("bp_distance_obj", True),
        )
        self.pending_tasks[job_id] = task.id

        print(f"[{job_id}] Launched riboswitch design task: {task.id}")


class CheckCeleryTasksBehaviour(PeriodicBehaviour):
    async def run(self):
        if not self.agent.pending_tasks:
            return

        for job_id, task_id in list(self.agent.pending_tasks.items()):
            async_result = AsyncResult(task_id)

            if async_result.ready():
                print(f"[{job_id}] RiboSwitchAgent: design task finished!")

                try:
                    result_data = async_result.result
                except Exception as e:
                    print(f"[{job_id}] Celery task raised an exception: {e}")
                    result_data = {"status": "error", "error": str(e)}

                del self.agent.pending_tasks[job_id]

                if result_data.get("status") == "success":
                    msg = self.agent.create_message(
                        to=self.agent.coordinator_jid,
                        msg_type="response",
                        action="riboswitch_designed",
                        payload=result_data,
                        job_id=job_id,
                    )
                    print(f"[{job_id}] Riboswitch design succeeded")
                else:
                    error = result_data.get("error", "Unknown error")
                    msg = self.agent.create_message(
                        to=self.agent.coordinator_jid,
                        msg_type="response",
                        action="error",
                        payload={"error": error},
                        job_id=job_id,
                    )
                    print(f"[{job_id}] Riboswitch design failed: {error}")

                await self.agent.send(msg)
