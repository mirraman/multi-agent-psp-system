import os
import json
from datetime import datetime, UTC
from typing import Any, Dict

from app.agents.BaseAgent import BaseAgent
from spade.behaviour import CyclicBehaviour


class OutputAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = "coordinator@localhost"
		self.output_dir = "./data/outputs"

	async def setup(self):
		behaviour = MessageHandlerBehaviour(self)
		self.add_behaviour(behaviour)
		os.makedirs(self.output_dir, exist_ok=True)
		print(f"OutputAgent {self.jid} started")

	async def handle_generate_output(self, agent_msg):
		job_id = agent_msg.job_id
		accession = agent_msg.payload.get("accession", job_id)
		raw_data = agent_msg.payload.get("raw_data", {})
		psp_results = agent_msg.payload.get("psp_results", {})
		processing_results = agent_msg.payload.get("processing_results", {})
		synthesis_results = agent_msg.payload.get("synthesis_results", {})
		analysis_results = agent_msg.payload.get("analysis_results", {})
		pocket_results = agent_msg.payload.get("pocket_results") or {}

		output_path = self._generate_output(
			accession, raw_data, psp_results, processing_results,
			synthesis_results, analysis_results, pocket_results
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
		analysis_results: Dict[str, Any],
		pocket_results: Dict[str, Any] = None,
	) -> str:
		timestamp = datetime.now(UTC).isoformat()

		output_doc = {
			"accession": accession,
			"timestamp": timestamp,
			"uniprot": raw_data.get("uniprot"),
			"pdb": raw_data.get("pdb"),
			"esmfold": psp_results,
			"metrics": processing_results,
			"synthesis": synthesis_results,
			"analysis": analysis_results,
			"pockets": pocket_results or {},
		}

		json_path = os.path.join(self.output_dir, f"{accession}.json")
		with open(json_path, "w") as f:
			json.dump(output_doc, f, indent=2)

		pdb_text = psp_results.get("esmfold", {}).get("pdb", "")
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
		analysis = output_doc.get("analysis") or {}
		psp_results = output_doc.get("esmfold") or {}
		pockets = output_doc.get("pockets") or {}

		best_model = synthesis.get("best_model", "esmfold")
		pdb_text = ""
		source_display = "Unknown Source"
		
		if best_model == "colabfold_modal":
			modal_data = psp_results.get("colabfold_modal", {})
			pdb_text = modal_data.get("pdb", "")
			source_display = "ColabFold/Modal (cloud)"
		else:
			esmfold_data = psp_results.get("esmfold", {})
			pdb_text = esmfold_data.get("pdb", "")
			source_display = "ESMFold Prediction"
			
		pdb_escaped = pdb_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
		
		esmfold_plddt = metrics.get("esmfold_plddt_mean")
		esmfold_plddt_str = f"{esmfold_plddt:.2f}" if isinstance(esmfold_plddt, (int, float)) else "N/A"

		models_compared = analysis.get("models_compared", [])
		pairwise_rmsd = analysis.get("pairwise_rmsd", {})
		consensus_conf = analysis.get("consensus_confidence")
		has_consensus = analysis.get("has_consensus", False)
		analysis_summary = analysis.get("summary", "No structural comparison performed.")
		
		rmsd_rows = ""
		for pair, rmsd_val in pairwise_rmsd.items():
			pair_display = pair.replace("_vs_", " vs ")
			rmsd_rows += f'<div class="metric"><span>{pair_display}</span><span class="metric-value">{rmsd_val} A</span></div>'
		
		consensus_str = f"{consensus_conf:.2f}" if isinstance(consensus_conf, (int, float)) else "N/A"
		consensus_status = "Yes" if has_consensus else "No"

		# ── Pocket html ───────────────────────────────────────────────────────
		pocket_data = output_doc.get("pockets") or {}
		pocket_list = pocket_data.get("pockets", [])
		pocket_summary_data = pocket_data.get("pocket_summary", {})
		total_pockets = pocket_summary_data.get("total_detected", 0)
		high_conf_count = pocket_summary_data.get("high_confidence", 0)
		filtered_count = pocket_summary_data.get("filtered_low_plddt", 0)

		pocket_rows = ""
		for p in pocket_list:
			confident = p.get("confident", False)
			badge_color = "#00ff88" if confident else "#ff9900"
			badge_text = "&#10003; Confident" if confident else "&#9888; Low pLDDT"
			res_count = len(p.get("residues", []))
			pocket_rows += (
				f'<tr>'
				f'<td>#{p.get("rank", p.get("pocket_id", "?"))}</td>'
				f'<td>{p.get("volume", 0):.1f} &#8491;&#179;</td>'
				f'<td>{p.get("druggability_score", 0):.3f}</td>'
				f'<td>{p.get("local_plddt_mean", 0):.1f}</td>'
				f'<td>{p.get("composite_score", 0):.3f}</td>'
				f'<td>{res_count}</td>'
				f'<td><span style="color:{badge_color};font-weight:bold;">{badge_text}</span></td>'
				f'</tr>'
			)

		filtered_note = (
			f'<p style="color:#ff9900;margin-top:0.75rem;font-size:0.85rem;">'
			f'&#9888; {filtered_count} pocket(s) filtered — local pLDDT below 70.</p>'
		) if filtered_count > 0 else ""

		if total_pockets > 0:
			pocket_card_html = (
				f'<div class="card full-width">'
				f'<h2>&#128300; Binding Pockets ({high_conf_count} high-confidence of {total_pockets} detected)</h2>'
				f'<table class="pocket-table">'
				f'<thead><tr><th>Rank</th><th>Volume</th><th>Druggability</th>'
				f'<th>Local pLDDT</th><th>Composite Score</th><th>Residues</th><th>Status</th></tr></thead>'
				f'<tbody>{pocket_rows}</tbody>'
				f'</table>'
				f'{filtered_note}'
				f'</div>'
			)
		else:
			pocket_card_html = (
				'<div class="card full-width">'
				'<h2>&#128300; Binding Pockets</h2>'
				'<p style="color:#888;padding:1rem 0;">No pockets detected — '
				'fpocket may not be available in this environment, or the structure has no detectable binding sites.</p>'
				'</div>'
			)

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
            position: relative;
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
        .pocket-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }}
        .pocket-table th {{
            text-align: left;
            padding: 0.5rem 0.75rem;
            border-bottom: 2px solid rgba(0,217,255,0.4);
            color: #00d9ff;
            font-weight: 600;
        }}
        .pocket-table td {{
            padding: 0.5rem 0.75rem;
            border-bottom: 1px solid rgba(255,255,255,0.07);
        }}
        .pocket-table tr:last-child td {{ border-bottom: none; }}
        .pocket-table tr:hover td {{ background: rgba(255,255,255,0.04); }}
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
                    <span class="metric-value">{esmfold_plddt_str}</span>
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
                <h2>Ensemble Analysis</h2>
                <div class="metric">
                    <span>Models Compared</span>
                    <span class="metric-value">{', '.join(models_compared) if models_compared else 'N/A'}</span>
                </div>
                <div class="metric">
                    <span>Consensus Reached</span>
                    <span class="metric-value">{consensus_status}</span>
                </div>
                <div class="metric">
                    <span>Consensus Confidence</span>
                    <span class="metric-value">{consensus_str}</span>
                </div>
                {rmsd_rows}
                <div class="summary">
                    {analysis_summary}
                </div>
            </div>

			{pocket_card_html}

            <div class="card full-width">
                <h2>3D Structure ({source_display})</h2>
                <div id="viewer" class="viewer"></div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            let element = document.getElementById('viewer');
            let viewer = $3Dmol.createViewer(element, {{
                backgroundColor: '#0a0a15'
            }});
            
            let pdbData = `{pdb_escaped}`;
            
            if (pdbData && pdbData.trim()) {{
                viewer.addModel(pdbData, 'pdb');
                viewer.setStyle({{}}, {{cartoon: {{color: 'spectrum'}}}});
                viewer.zoomTo();
                viewer.render();
            }} else {{
                element.innerHTML = '<p style="padding:2rem;color:#888;">No structure available</p>';
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

