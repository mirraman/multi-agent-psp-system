import asyncio
import spade

from app.agents.CoordinatorAgent import CoordinatorAgent
from app.agents.DataAgentSpade import DataAgentSpade
from app.agents.PspAgent import PspAgent
from app.agents.ProcessingAgentSpade import ProcessingAgentSpade
from app.agents.SynthesisAgent import SynthesisAgent
from app.agents.OutputAgentSpade import OutputAgentSpade


# Agent credentials
PASSWORD = "secret123"

AGENTS = [
    ("coordinator@localhost", CoordinatorAgent),
    ("data_agent@localhost", DataAgentSpade),
    ("psp_agent@localhost", PspAgent),
    ("processing_agent@localhost", ProcessingAgentSpade),
    ("synthesis_agent@localhost", SynthesisAgent),
    ("output_agent@localhost", OutputAgentSpade),
]


async def main():
    agents = []
    
    # Start all agents
    for jid, AgentClass in AGENTS:
        agent = AgentClass(jid, PASSWORD)
        await agent.start(auto_register=True)
        agents.append(agent)
        print(f"Started: {jid}")
    
    print("\nAll agents started")
    
    # Get coordinator to start a job
    coordinator = agents[0]
    
    # Test with a protein accession
    job_id = await coordinator.start_job("accession", "P69905")
    print(f"Started job: {job_id}")
    
    # Wait for job to complete
    print("Waiting for job to complete...")
    for _ in range(60):  # Wait up to 60 seconds
        await asyncio.sleep(1)
        job = coordinator.jobs.get(job_id)
        if job:
            print(f"  Status: {job['status']}")
            if job["status"] == "completed":
                print(f"\nJob completed! Output: {job['output_results']}")
                break
            elif job["status"] == "error":
                print(f"\nJob failed!")
                break
    
    print("\nStopping agents...")
    for agent in agents:
        await agent.stop()
    
    print("Done!")


if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)

