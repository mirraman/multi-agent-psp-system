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
from app.agents.RiboSwitchAgent import RiboSwitchAgent
from app.utils.db import DatabaseConnection, get_database_url

AGENT_DOMAIN = os.getenv("XMPP_DOMAIN", "xmpp")
PASSWORD = os.getenv("XMPP_PASSWORD", "secret123")
AUTO_REGISTER = os.getenv("XMPP_AUTO_REGISTER", "1") == "1"

AGENTS = [
    (f"coordinator@{AGENT_DOMAIN}", CoordinatorAgent),
    (f"data_agent@{AGENT_DOMAIN}", DataAgent),
    (f"psp_agent@{AGENT_DOMAIN}", PspAgent),
    (f"processing_agent@{AGENT_DOMAIN}", ProcessingAgent),
    (f"analysis_agent@{AGENT_DOMAIN}", AnalysisAgent),
    (f"synthesis_agent@{AGENT_DOMAIN}", SynthesisAgent),
    (f"pocket_agent@{AGENT_DOMAIN}", PocketAgent),
    (f"output_agent@{AGENT_DOMAIN}", OutputAgent),
    (f"modal_agent@{AGENT_DOMAIN}", ModalAgent),
    (f"riboswitch_agent@{AGENT_DOMAIN}", RiboSwitchAgent),
]


async def main():
    database_url = get_database_url()
    try:
        await DatabaseConnection.init(database_url)
        print("Connected to PostgreSQL")
    except Exception as e:
        print(f"PostgreSQL connection failed: {e}")
        print("Exiting: agents cannot poll the job queue without PostgreSQL.")
        raise SystemExit(1) from e

    agents = []
    
    for jid, AgentClass in AGENTS:
        agent = AgentClass(jid, PASSWORD)
        await agent.start(auto_register=AUTO_REGISTER)
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
    spade.run(main())

