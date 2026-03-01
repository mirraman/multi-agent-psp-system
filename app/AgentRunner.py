import asyncio
import os
import spade

from app.agents.CoordinatorAgent import CoordinatorAgent
from app.agents.DataAgent import DataAgent
from app.agents.PspAgent import PspAgent
from app.agents.ProcessingAgent import ProcessingAgent
from app.agents.SynthesisAgent import SynthesisAgent
from app.agents.AnalysisAgent import AnalysisAgent
from app.agents.OutputAgent import OutputAgent
from app.agents.ModalAgent import ModalAgent
from app.agents.PocketAgent import PocketAgent
from app.utils.db import DatabaseConnection

PASSWORD = "secret123"

AGENTS = [
    ("coordinator@localhost", CoordinatorAgent),
    ("data_agent@localhost", DataAgent),
    ("psp_agent@localhost", PspAgent),
    ("processing_agent@localhost", ProcessingAgent),
    ("analysis_agent@localhost", AnalysisAgent),
    ("synthesis_agent@localhost", SynthesisAgent),
    ("pocket_agent@localhost", PocketAgent),
    ("output_agent@localhost", OutputAgent),
    ("modal_agent@localhost", ModalAgent),
]


async def main():
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://psp:psp@localhost:5432/psp_db")
    try:
        await DatabaseConnection.init(database_url)
        print(f"Connected to PostgreSQL: {database_url}")
    except Exception as e:
        print(f"PostgreSQL connection failed: {e}")
        print("Coordinator will not be able to poll for jobs from DB!")

    agents = []
    
    for jid, AgentClass in AGENTS:
        agent = AgentClass(jid, PASSWORD)
        await agent.start(auto_register=True)
        agents.append(agent)
        print(f"Started: {jid}")
    
    print("\nAll agents started. Waiting for jobs from database...")
    print("Submit jobs via FastAPI: POST /submit/{accession}")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    
    for agent in agents:
        await agent.stop()
    
    await DatabaseConnection.close()
    print("Done!")


if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)

