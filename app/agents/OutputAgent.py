import os
import json
from datetime import datetime, UTC
from typing import Any, Dict, List, Tuple

from app.agents.BaseAgent import ActionMessageHandlerBehaviour, BaseAgent

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ACCESSION} — {PROTEIN_NAME}</title>
<script src="https://3dmol.org/build/3Dmol-min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #050810;
  --surface: #0d1117;
  --border: rgba(255,255,255,0.07);
  --text: #e2e8f0;
  --muted: #64748b;
  --accent: #f97316;
  --green: #4ade80;
  --mono: 'SF Mono', 'Fira Code', monospace;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, sans-serif;
  font-size: 13px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.header {
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-shrink: 0;
}
.protein-name { font-size: 0.95rem; font-weight: 600; color: #fff; }
.accession { font-family: var(--mono); font-size: 0.65rem; color: var(--accent); letter-spacing: 0.1em; }
.main {
  display: grid;
  grid-template-columns: 1fr 280px;
  flex: 1;
  overflow: hidden;
}
.viewer-panel { position: relative; background: #03050a; }
#viewer { width: 100%; height: 100%; }
.viewer-tag {
  position: absolute; top: 0.6rem; left: 0.7rem;
  font-family: var(--mono); font-size: 0.55rem;
  color: rgba(255,255,255,0.3); letter-spacing: 0.08em; pointer-events: none;
}
.sidebar {
  border-left: 1px solid var(--border);
  background: var(--surface);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.sidebar-title {
  font-family: var(--mono); font-size: 0.58rem; color: var(--muted);
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.9rem 1rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
.pocket-item {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.55rem 1rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}
.pocket-item:hover { background: rgba(255,255,255,0.03); }
.pocket-item.active { background: rgba(249,115,22,0.06); }
.pocket-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.pocket-info { flex: 1; min-width: 0; }
.pocket-label { font-family: var(--mono); font-size: 0.68rem; color: #fff; }
.pocket-sub { font-size: 0.62rem; color: var(--muted); margin-top: 0.1rem; font-family: var(--mono); }
.pocket-score { font-family: var(--mono); font-size: 0.75rem; font-weight: 700; color: var(--accent); }
</style>
</head>
<body>

<div class="header">
  <div class="protein-name">{PROTEIN_NAME}</div>
  <div class="accession">{ACCESSION}</div>
</div>

<div class="main">
  <div class="viewer-panel">
    <div id="viewer"></div>
    <div class="viewer-tag">{BEST_MODEL} · {ACCESSION}</div>
  </div>
  <div class="sidebar">
    <div class="sidebar-title">Binding Pockets</div>
    <div id="pocket-list"></div>
  </div>
</div>

<script>
const pocketData = {POCKET_DATA_JSON};

const list = document.getElementById('pocket-list');
pocketData.forEach((p, i) => {
  const item = document.createElement('div');
  item.className = 'pocket-item';
  item.innerHTML = `
    <div class="pocket-dot" style="background:${p.color}"></div>
    <div class="pocket-info">
      <div class="pocket-label">#${p.rank} · ${p.model_name}</div>
      <div class="pocket-sub">Vol ${p.volume.toFixed(0)} Å³ · Drug ${parseFloat(p.druggability).toFixed(2)}</div>
    </div>
    <div class="pocket-score">${parseFloat(p.composite).toFixed(3)}</div>
  `;
  list.appendChild(item);
});

document.addEventListener('DOMContentLoaded', function() {
  const viewer = $3Dmol.createViewer(document.getElementById('viewer'), { backgroundColor: '#03050a' });
  viewer.addModel(`{PDB_DATA}`, 'pdb');
  viewer.setStyle({}, { cartoon: { color: '#1e293b', opacity: 0.85 } });
  pocketData.forEach(p => {
    viewer.addStyle({ resi: p.residues }, { sphere: { color: p.color, radius: 0.55, opacity: 0.82 } });
  });
  viewer.zoomTo();
  viewer.render();

  document.querySelectorAll('.pocket-item').forEach((el, i) => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.pocket-item').forEach(e => e.classList.remove('active'));
      el.classList.add('active');
      viewer.setStyle({}, { cartoon: { color: '#1e293b', opacity: 0.4 } });
      pocketData.forEach((p, j) => {
        viewer.addStyle(
          { resi: p.residues },
          { sphere: { color: p.color, radius: j === i ? 0.7 : 0.3, opacity: j === i ? 1.0 : 0.15 } }
        );
      });
      viewer.zoomTo({ resi: pocketData[i].residues });
      viewer.render();
    });
  });
});
</script>
</body>
</html>"""


def _resolve_structure_pdb_for_viewer(
	best_model: str,
	psp_results: Dict[str, Any],
	raw_data: Dict[str, Any],
) -> Tuple[str, str]:
	"""Return PDB text and display label for the synthesis best_model."""
	if best_model == "colabfold_modal":
		txt = (psp_results.get("colabfold_modal") or {}).get("pdb", "") or ""
		return txt, "ColabFold/Modal (cloud)"
	if best_model == "alphafold_db":
		txt = (psp_results.get("alphafold_db") or {}).get("pdb", "") or ""
		return txt, "AlphaFold DB (EBI)"
	if best_model == "experimental":
		exp = psp_results.get("experimental") or {}
		txt = exp.get("pdb", "") or ""
		if not txt:
			exp_alt = raw_data.get("experimental_best_pdb") or {}
			txt = exp_alt.get("pdb_text", "") or ""
		pid = exp.get("pdb_id") or (raw_data.get("experimental_best_pdb") or {}).get("pdb_id")
		label = f"Experimental PDB ({pid})" if pid else "Experimental PDB"
		return txt, label
	if best_model == "esmfold" or not best_model or best_model == "none":
		txt = (psp_results.get("esmfold") or {}).get("pdb", "") or ""
		if not txt and best_model != "none":
			txt = (psp_results.get("colabfold_modal") or {}).get("pdb", "") or ""
		if not txt:
			txt = (psp_results.get("alphafold_db") or {}).get("pdb", "") or ""
		return txt, "ESMFold prediction"
	return "", "Unknown Source"


class OutputAgent(BaseAgent):
	def __init__(self, jid: str, password: str):
		super().__init__(jid, password)
		self.coordinator_jid = self.format_jid("coordinator")
		self.output_dir = "./data/outputs"

	async def setup(self):
		behaviour = ActionMessageHandlerBehaviour(
			self,
			action_to_handler={"generate_output": "handle_generate_output"},
		)
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
			"raw_data": raw_data,
			"esmfold": psp_results,
			"metrics": processing_results,
			"synthesis": synthesis_results,
			"analysis": analysis_results,
			"pockets": pocket_results or {},
		}

		json_path = os.path.join(self.output_dir, f"{accession}.json")
		with open(json_path, "w") as f:
			json.dump(output_doc, f, indent=2)

		synth = synthesis_results or {}
		bm = synth.get("best_model", "esmfold")
		pdb_text, _src = _resolve_structure_pdb_for_viewer(bm, psp_results, raw_data)
		if pdb_text:
			suffix = bm if bm else "model"
			pdb_path = os.path.join(self.output_dir, f"{accession}_{suffix}.pdb")
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
		pocket_data = output_doc.get("pockets") or {}
		pocket_list = pocket_data.get("pockets", [])

		protein_name = uniprot.get("name", accession)
		protein_sub = f"{uniprot.get('full_name', 'Protein')} — {metrics.get('sequence_length', 0)} aa"
		
		best_model = synthesis.get("best_model", "esmfold")
		pdb_text, source_display = _resolve_structure_pdb_for_viewer(
			best_model, psp_results, output_doc.get("raw_data") or {}
		)
		pdb_escaped = pdb_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

		esmfold_plddt = metrics.get("esmfold_plddt_mean")
		esmfold_plddt_str = f"{esmfold_plddt:.2f}" if isinstance(esmfold_plddt, (int, float)) else "N/A"

		conf = synthesis.get("confidence_score")
		bm_key = (synthesis.get("best_model") or "").lower()

		def _best_quality_badge() -> str:
			"""Match SynthesisAgent: experimental uses Å resolution, not pLDDT."""
			if bm_key == "experimental":
				if isinstance(conf, (int, float)):
					return f"Resolution {float(conf):.2f} Å"
				return "Resolution n/a"
			if bm_key == "colabfold_modal":
				if isinstance(conf, str):
					return f"Confidence: {conf}"
				if isinstance(conf, (int, float)):
					return f"pLDDT {float(conf):.2f}"
				return "ColabFold/Modal"
			if isinstance(conf, (int, float)):
				return f"pLDDT {float(conf):.2f}"
			if conf is not None:
				return str(conf)
			return "pLDDT N/A"

		best_quality_badge = _best_quality_badge()

		models_compared = analysis.get("models_compared", [])
		consensus_conf = analysis.get("consensus_confidence")
		has_consensus = analysis.get("has_consensus", False)

		pocket_summary_data = pocket_data.get("pocket_summary", {})
		total_pockets = pocket_summary_data.get("total_detected", 0)
		high_conf_count = pocket_summary_data.get("high_confidence", 0)

		consensus_count = pocket_summary_data.get(
			"consensus_pockets",
			len([
				p
				for p in pocket_list
				if p.get("ensemble_agreement", {}).get("consensus", False)
			]),
		)
		top_druggability = max([p.get("druggability_score", 0) for p in pocket_list]) if pocket_list else 0
		top_jaccard = (
			max([
				p.get("ensemble_agreement", {}).get("jaccard_similarity", 0.0)
				for p in pocket_list
			])
			if pocket_list else 0.0
		)

		pairwise_rmsd = analysis.get("pairwise_rmsd", {})
		avg_rmsd = sum(pairwise_rmsd.values()) / len(pairwise_rmsd) if pairwise_rmsd else 0

		rmsd_rows = ""
		for pair, val in pairwise_rmsd.items():
			pair_display = pair.replace("_vs_", " vs ")
			w = min(100, int((val / 10.0) * 100))
			color = "#f97316" if val >= 3.0 else "#4ade80"
			rmsd_rows += f"""      <div class="rmsd-item">
        <div>
          <div class="rmsd-label">{pair_display}</div>
          <div class="rmsd-bar"><div class="rmsd-fill" style="width:{w}%;background:{color};"></div></div>
        </div>
        <div class="rmsd-val" style="color:{color};">{val}A</div>
      </div>\n"""

		models_pills = ""
		for m in models_compared:
			m_disp = m.replace("_", " ")
			cls = "active-model" if m == best_model else "compared"
			models_pills += f'        <div class="model-pill {cls}">{m_disp}</div>\n'

		def _rank_key(p: Dict[str, Any]) -> int:
			r = p.get("rank", p.get("pocket_id", 999))
			try:
				return int(r)
			except:
				return 999

		top_pockets = sorted(pocket_list, key=_rank_key)
		pockets_out = []
		colors_arr = ["#f97316", "#22d3ee", "#a78bfa", "#4ade80", "#fb7185", "#fbbf24", "#60a5fa", "#e879f9"]
		for i, p in enumerate(top_pockets):
			pockets_out.append({
				"rank": p.get("rank", i+1),
				"residues": p.get("residues", []),
				"color": colors_arr[i % len(colors_arr)],
				"druggability": p.get("druggability_score", 0),
				"composite": p.get("composite_score", 0),
				"volume": p.get("volume", 0),
				"plddt": p.get("local_plddt_mean", 0),
                                "consensus": p.get("ensemble_agreement", {}).get("consensus", False),
                                "jaccard": p.get("ensemble_agreement", {}).get("jaccard_similarity", 0.0),
				"model": p.get("model_name", "experimental"),
				"model_name": str(p.get("model_name", "experimental")).replace("_", " ").upper(),
				"tm_score": p.get("ensemble_agreement", {}).get("tm_score_ref", 0.0)
			})
		pocket_viz_json = json.dumps(pockets_out)

		# Prevent script injection
		pocket_viz_json = pocket_viz_json.replace("</", "<\\/")
		generated_date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
		pdb_count = metrics.get("pdb_count", 0)

		# Use the global HTML template
		html = HTML_TEMPLATE
		html = html.replace("{ACCESSION}", str(accession))
		html = html.replace("{PROTEIN_NAME}", str(protein_name))
		html = html.replace("{PROTEIN_SUB}", str(protein_sub))
		html = html.replace("{BEST_MODEL}", str(source_display))
		html = html.replace("{BEST_QUALITY_BADGE}", str(best_quality_badge))
		html = html.replace("{ESMFOLD_PLDDT}", str(esmfold_plddt_str))
		html = html.replace("{AVG_RMSD}", f"{avg_rmsd:.2f}")
		html = html.replace("{TOTAL_POCKETS}", str(total_pockets))
		html = html.replace("{HIGH_CONF_POCKETS}", str(high_conf_count))
		html = html.replace("{CONSENSUS_POCKETS}", str(consensus_count))
		html = html.replace("{TOP_DRUGGABILITY}", f"{top_druggability:.3f}")
		html = html.replace("{TOP_JACCARD}", f"{top_jaccard:.2f}")
		html = html.replace("{MODELS_COUNT}", str(len(models_compared)))
		html = html.replace("{MODELS_PILLS}", models_pills)
		html = html.replace("{RMSD_ROWS}", rmsd_rows)
		html = html.replace("{GENERATED_DATE}", generated_date)
		html = html.replace("{PDB_COUNT}", str(pdb_count))
		html = html.replace("{PDB_DATA}", pdb_escaped)
		html = html.replace("{POCKET_DATA_JSON}", pocket_viz_json)

		with open(html_path, "w") as f:
			f.write(html)


