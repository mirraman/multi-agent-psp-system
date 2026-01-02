import os
import json
from datetime import datetime, UTC
from typing import Any, Dict

from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour


class OutputAgentSpade(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"
		self.output_dir = "./data/outputs"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		os.makedirs(self.output_dir, exist_ok=True)
		print(f"OutputAgentSpade {self.jid} started")

	async def handle_generate_output(self, agent_msg):
		job_id = agent_msg.job_id
		accession = agent_msg.payload.get("accession", job_id)
		raw_data = agent_msg.payload.get("raw_data", {})
		psp_results = agent_msg.payload.get("psp_results", {})
		processing_results = agent_msg.payload.get("processing_results", {})
		synthesis_results = agent_msg.payload.get("synthesis_results", {})

		output_path = self._generate_output(
			accession, raw_data, psp_results, processing_results, synthesis_results
		)

		msg = self.create_message(
			to=self.coordinator_jid,
			msg_type="response",
			action="output_generated",
			payload={"output_path": output_path},
			job_id=job_id,
		)
		await self.send(msg)

	def _generate_output(
		self,
		accession: str,
		raw_data: Dict[str, Any],
		psp_results: Dict[str, Any],
		processing_results: Dict[str, Any],
		synthesis_results: Dict[str, Any],
	) -> str:
		timestamp = datetime.now(UTC).isoformat()

		output_doc = {
			"accession": accession,
			"timestamp": timestamp,
			"uniprot": raw_data.get("uniprot"),
			"pdb": raw_data.get("pdb"),
			"alphafold": raw_data.get("alphafold"),
			"esmfold": psp_results,
			"metrics": processing_results,
			"synthesis": synthesis_results,
		}

		json_path = os.path.join(self.output_dir, f"{accession}.json")
		with open(json_path, "w") as f:
			json.dump(output_doc, f, indent=2)

		pdb_text = psp_results.get("pdb", "")
		if pdb_text:
			pdb_path = os.path.join(self.output_dir, f"{accession}_esmfold.pdb")
			with open(pdb_path, "w") as f:
				f.write(pdb_text)

		html_path = os.path.join(self.output_dir, f"{accession}.html")
		self._generate_html_report(html_path, output_doc)

		return json_path

	def _generate_html_report(self, html_path: str, output_doc: Dict[str, Any]) -> None:
		accession = output_doc.get("accession", "Unknown")
		uniprot = output_doc.get("uniprot") or {}
		metrics = output_doc.get("metrics") or {}
		synthesis = output_doc.get("synthesis") or {}
		psp_results = output_doc.get("esmfold") or {}

		pdb_text = psp_results.get("pdb", "")
		pdb_escaped = pdb_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

		html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PSP Report: {accession}</title>
    <script src="https://3dmol.org/build/3Dmol-min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 2rem;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{ color: #888; margin-bottom: 2rem; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }}
        .card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .card h2 {{
            font-size: 1.2rem;
            margin-bottom: 1rem;
            color: #00d9ff;
        }}
        .viewer {{
            width: 100%;
            height: 400px;
            border-radius: 8px;
            overflow: hidden;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .metric:last-child {{ border-bottom: none; }}
        .metric-value {{ color: #00ff88; font-weight: bold; }}
        .summary {{
            background: rgba(0,217,255,0.1);
            border-left: 4px solid #00d9ff;
            padding: 1rem;
            margin-top: 1rem;
            border-radius: 0 8px 8px 0;
        }}
        .full-width {{ grid-column: 1 / -1; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{accession}</h1>
        <p class="subtitle">{uniprot.get('name', 'Protein Structure Prediction Report')}</p>

        <div class="grid">
            <div class="card">
                <h2>Sequence Info</h2>
                <div class="metric">
                    <span>Length</span>
                    <span class="metric-value">{metrics.get('sequence_length', 'N/A')} aa</span>
                </div>
                <div class="metric">
                    <span>PDB Structures</span>
                    <span class="metric-value">{metrics.get('pdb_count', 0)}</span>
                </div>
                <div class="metric">
                    <span>AlphaFold Confidence</span>
                    <span class="metric-value">{metrics.get('alphafold_confidence', 'N/A')}</span>
                </div>
                <div class="metric">
                    <span>ESMFold pLDDT</span>
                    <span class="metric-value">{metrics.get('esmfold_plddt_mean', 'N/A'):.1f if isinstance(metrics.get('esmfold_plddt_mean'), (int, float)) else 'N/A'}</span>
                </div>
            </div>

            <div class="card">
                <h2>Synthesis Result</h2>
                <div class="metric">
                    <span>Best Model</span>
                    <span class="metric-value">{synthesis.get('best_model_source', 'N/A')}</span>
                </div>
                <div class="metric">
                    <span>Confidence Score</span>
                    <span class="metric-value">{synthesis.get('confidence_score', 'N/A')}</span>
                </div>
                <div class="summary">
                    {synthesis.get('summary', 'No summary available.')}
                </div>
            </div>

            <div class="card full-width">
                <h2>3D Structure (ESMFold Prediction)</h2>
                <div id="viewer" class="viewer"></div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            let viewer = $3Dmol.createViewer('viewer', {{
                backgroundColor: 'rgba(0,0,0,0)'
            }});
            
            let pdbData = `{pdb_escaped}`;
            
            if (pdbData && pdbData.trim()) {{
                viewer.addModel(pdbData, 'pdb');
                viewer.setStyle({{}}, {{cartoon: {{color: 'spectrum'}}}});
                viewer.zoomTo();
                viewer.render();
            }} else {{
                document.getElementById('viewer').innerHTML = '<p style="padding:2rem;color:#888;">No structure available</p>';
            }}
        }});
    </script>
</body>
</html>"""

		with open(html_path, "w") as f:
			f.write(html)


class MessageHandlerBehaviour(CyclicBehaviour):
	def __init__(self, agent):
		super().__init__()
		self.agent = agent

	async def run(self):
		msg = await self.receive(timeout=10)
		if msg:
			agent_msg = self.agent.parse_message(msg)
			if agent_msg.action == "generate_output":
				await self.agent.handle_generate_output(agent_msg)

