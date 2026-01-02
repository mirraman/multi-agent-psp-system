import asyncio
import os
import spade

from app.agents.CoordinatorAgent import CoordinatorAgent
from app.agents.DataAgentSpade import DataAgentSpade
from app.agents.PspAgent import PspAgent
from app.agents.ProcessingAgentSpade import ProcessingAgentSpade
from app.agents.SynthesisAgent import SynthesisAgent
from app.agents.OutputAgentSpade import OutputAgentSpade
from app.utils.db import MongoConnection

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
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    try:
        await MongoConnection.init(mongo_uri)
        print(f"Connected to MongoDB: {mongo_uri}")
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
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
    
    await MongoConnection.close()
    print("Done!")


if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)

