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
<title>{ACCESSION} — {PROTEIN_NAME} Structure Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://3dmol.org/build/3Dmol-min.js"></script>
<style>
:root {
  --bg: #050810;
  --surface: #0d1117;
  --surface2: #161b27;
  --border: rgba(255,255,255,0.07);
  --text: #e2e8f0;
  --muted: #64748b;
  --accent: #f97316;
  --accent2: #22d3ee;
  --green: #4ade80;
  --red: #fb7185;
  --mono: 'Space Mono', monospace;
  --sans: 'DM Sans', sans-serif;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.6;
  min-height: 100vh;
}

/* HEADER */
.header {
  padding: 2rem 2.5rem 1.5rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 2rem;
}
.header-left { flex: 1; }
.accession {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--accent);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin-bottom: 0.3rem;
}
.protein-name {
  font-size: 1.8rem;
  font-weight: 600;
  color: #fff;
  letter-spacing: -0.02em;
  margin-bottom: 0.2rem;
}
.protein-sub {
  font-size: 0.85rem;
  color: var(--muted);
  font-family: var(--mono);
}
.header-badges {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
  padding-top: 0.3rem;
}
.badge {
  font-family: var(--mono);
  font-size: 0.65rem;
  padding: 0.3rem 0.7rem;
  border-radius: 3px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-weight: 700;
}
.badge-model { background: rgba(249,115,22,0.15); color: var(--accent); border: 1px solid rgba(249,115,22,0.3); }
.badge-consensus { background: rgba(74,222,128,0.12); color: var(--green); border: 1px solid rgba(74,222,128,0.25); }
.badge-pockets { background: rgba(34,211,238,0.12); color: var(--accent2); border: 1px solid rgba(34,211,238,0.25); }

/* STATS BAR */
.stats-bar {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  border-bottom: 1px solid var(--border);
}
.stat {
  padding: 1.2rem 1.5rem;
  border-right: 1px solid var(--border);
  position: relative;
}
.stat:last-child { border-right: none; }
.stat-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: var(--muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  font-family: var(--mono);
  color: #fff;
  letter-spacing: -0.02em;
}
.stat-value.orange { color: var(--accent); }
.stat-value.cyan { color: var(--accent2); }
.stat-value.green { color: var(--green); }
.stat-unit {
  font-size: 0.7rem;
  color: var(--muted);
  margin-top: 0.1rem;
  font-family: var(--mono);
}

/* MAIN LAYOUT */
.main {
  display: grid;
  grid-template-columns: 1fr 340px;
  height: calc(100vh - 200px);
  min-height: 520px;
}

/* 3D VIEWER */
.viewer-panel {
  position: relative;
  border-right: 1px solid var(--border);
  background: #03050a;
}
#viewer {
  width: 100%;
  height: 100%;
}
.viewer-overlay {
  position: absolute;
  top: 1rem;
  left: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  pointer-events: none;
}
.viewer-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: rgba(255,255,255,0.4);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.pocket-legend {
  position: absolute;
  bottom: 1rem;
  left: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  pointer-events: none;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--mono);
  font-size: 0.6rem;
  color: rgba(255,255,255,0.6);
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* SIDEBAR */
.sidebar {
  overflow-y: auto;
  background: var(--surface);
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.section {
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border);
}
.section-title {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: var(--muted);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 0.9rem;
}

/* MODEL SELECTOR */
.model-tabs {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 1rem;
}
.model-tab {
  flex: 1;
  padding: 0.4rem 0.5rem;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  text-align: center;
  font-family: var(--mono);
  font-size: 0.58rem;
  color: var(--muted);
  transition: all 0.15s;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.model-tab.active {
  background: rgba(249,115,22,0.12);
  border-color: rgba(249,115,22,0.4);
  color: var(--accent);
}

/* RMSD */
.rmsd-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.8rem;
}
.rmsd-item:last-child { border-bottom: none; }
.rmsd-label { color: var(--muted); font-family: var(--mono); font-size: 0.7rem; text-transform: lowercase; }
.rmsd-val {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 0.85rem;
}
.rmsd-bar {
  height: 3px;
  background: var(--surface2);
  border-radius: 2px;
  margin-top: 0.3rem;
  overflow: hidden;
}
.rmsd-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s ease;
}

/* POCKET LIST */
.pocket-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
  border-radius: 4px;
  padding-left: 0.4rem;
}
.pocket-item:last-child { border-bottom: none; }
.pocket-item:hover { background: rgba(255,255,255,0.03); }
.pocket-item.active { background: rgba(249,115,22,0.06); }
.pocket-color {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.pocket-info { flex: 1; min-width: 0; }
.pocket-title {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.pocket-consensus-badge {
  font-size: 0.55rem;
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
  background: rgba(74,222,128,0.15);
  color: var(--green);
  font-family: var(--mono);
  letter-spacing: 0.05em;
}
.pocket-meta {
  font-size: 0.65rem;
  color: var(--muted);
  margin-top: 0.15rem;
  font-family: var(--mono);
}
.pocket-score {
  font-family: var(--mono);
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--accent);
  flex-shrink: 0;
}

/* CONSENSUS VISUAL */
.consensus-visual {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.model-pill {
  flex: 1;
  padding: 0.4rem;
  border-radius: 4px;
  text-align: center;
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.model-pill.active-model {
  background: rgba(249,115,22,0.15);
  border: 1px solid rgba(249,115,22,0.3);
  color: var(--accent);
}
.model-pill.compared {
  background: rgba(34,211,238,0.08);
  border: 1px solid rgba(34,211,238,0.2);
  color: var(--accent2);
}

/* BOTTOM SECTION */
.bottom-bar {
  padding: 0.75rem 2.5rem;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
  font-family: var(--mono);
  font-size: 0.6rem;
  color: var(--muted);
}
.bottom-bar span { letter-spacing: 0.05em; }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="accession">UniProt · {ACCESSION}</div>
    <div class="protein-name">{PROTEIN_NAME}</div>
    <div class="protein-sub">{PROTEIN_SUB}</div>
  </div>
  <div class="header-badges">
    <span class="badge badge-model">{BEST_MODEL} · {BEST_QUALITY_BADGE}</span>
    <span class="badge badge-consensus">{CONSENSUS_POCKETS} consensus pockets</span>
    <span class="badge badge-pockets">{MODELS_COUNT}-model ensemble</span>
  </div>
</div>

<div class="stats-bar">
  <div class="stat">
    <div class="stat-label">Best Model</div>
    <div class="stat-value orange" style="font-size:1rem;margin-top:4px;">{BEST_MODEL}</div>
    <div class="stat-unit">{BEST_QUALITY_BADGE}</div>
  </div>
  <div class="stat">
    <div class="stat-label">ESMFold pLDDT</div>
    <div class="stat-value">{ESMFOLD_PLDDT}</div>
    <div class="stat-unit">confidence</div>
  </div>
  <div class="stat">
    <div class="stat-label">Avg RMSD</div>
    <div class="stat-value cyan">{AVG_RMSD}</div>
    <div class="stat-unit">Å across {MODELS_COUNT} models</div>
  </div>
  <div class="stat">
    <div class="stat-label">Total Pockets</div>
    <div class="stat-value">{TOTAL_POCKETS}</div>
    <div class="stat-unit">{HIGH_CONF_POCKETS} high-confidence</div>
  </div>
  <div class="stat">
    <div class="stat-label">Consensus Pockets</div>
    <div class="stat-value green">{CONSENSUS_POCKETS}</div>
    <div class="stat-unit">cross-model match</div>
  </div>
  <div class="stat">
    <div class="stat-label">Top Druggability</div>
    <div class="stat-value orange">{TOP_DRUGGABILITY}</div>
    <div class="stat-unit">Jaccard {TOP_JACCARD}</div>
  </div>
</div>

<div class="main">
  <div class="viewer-panel">
    <div id="viewer"></div>
    <div class="viewer-overlay">
      <div class="viewer-label">{BEST_MODEL} · {ACCESSION}</div>
    </div>
    <div class="pocket-legend" id="legend"></div>
  </div>

  <div class="sidebar">
    <div class="section">
      <div class="section-title">Ensemble Models</div>
      <div class="consensus-visual">
{MODELS_PILLS}
      </div>
    </div>

    <div class="section">
      <div class="section-title">Pairwise RMSD</div>
{RMSD_ROWS}
    </div>

    <div class="section">
      <div class="section-title">Top Binding Pockets</div>
      <div id="pocket-list"></div>
    </div>
  </div>
</div>

<div class="bottom-bar">
  <span>Generated · {GENERATED_DATE}</span>
  <span>PSP Pipeline · ESMFold + AlphaFold DB + Experimental · fpocket</span>
  <span>{PDB_COUNT} experimental PDB structures</span>
</div>

<script>
const pocketData = {POCKET_DATA_JSON};

// Build pocket list
const list = document.getElementById('pocket-list');
const legend = document.getElementById('legend');
pocketData.forEach((p, i) => {
  const item = document.createElement('div');
  item.className = 'pocket-item';
  item.id = 'pk-' + i;
  item.innerHTML = `
    <div class="pocket-color" style="background:${p.color}"></div>
    <div class="pocket-info">
      <div class="pocket-title">
        Pocket #${p.rank} · ${p.model_name}
        ${p.consensus ? '<span class="pocket-consensus-badge">✓ CONSENSUS</span>' : ''}
      </div>
      <div class="pocket-meta">Vol ${p.volume.toFixed(0)}Å³ · pLDDT ${p.plddt.toFixed(1)} · Jaccard ${p.jaccard.toFixed(2)}</div>
    </div>
    <div class="pocket-score">${parseFloat(p.composite).toFixed(3)}</div>
  `;
  list.appendChild(item);

  // legend
  if (i < 5) {
    const li = document.createElement('div');
    li.className = 'legend-item';
    li.innerHTML = `<div class="legend-dot" style="background:${p.color}"></div><span>#${p.rank} · ${parseFloat(p.druggability).toFixed(3)}</span>`;
    legend.appendChild(li);
  }
});

// 3Dmol
document.addEventListener('DOMContentLoaded', function() {
  const el = document.getElementById('viewer');
  const viewer = $3Dmol.createViewer(el, { backgroundColor: '#03050a' });

  const pdbData = `{PDB_DATA}`;

  viewer.addModel(pdbData, 'pdb');
  viewer.setStyle({}, { cartoon: { color: '#1e293b', opacity: 0.85 } });

  pocketData.forEach((p, i) => {
    viewer.addStyle(
      { resi: p.residues },
      { sphere: { color: p.color, radius: 0.55, opacity: 0.82 } }
    );
  });

  viewer.zoomTo();
  viewer.render();

  // Click to highlight
  document.querySelectorAll('.pocket-item').forEach((el, i) => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.pocket-item').forEach(e => e.classList.remove('active'));
      el.classList.add('active');
      viewer.setStyle({}, { cartoon: { color: '#1e293b', opacity: 0.5 } });
      pocketData.forEach((p, j) => {
        viewer.addStyle(
          { resi: p.residues },
          { sphere: { color: j === i ? p.color : '#1e293b', radius: j === i ? 0.7 : 0.3, opacity: j === i ? 1.0 : 0.2 } }
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


