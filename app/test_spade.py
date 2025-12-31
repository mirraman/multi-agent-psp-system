import spade

class TestAgent(spade.agent.Agent):
    async def setup(self):
        print(f"Agent {self.jid} started")

async def main():
    agent = TestAgent("test@localhost", "password")
    await agent.start(auto_register=True)
    print("Agent running...")
    await spade.wait_until_finished(agent)

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)