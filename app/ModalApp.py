import modal
import os

app = modal.App("psp-colabfold-worker")

image = (
	modal.Image.from_registry("ghcr.io/colabfold/colabfold:latest")
	.apt_install("git")
	.pip_install("colabfold[alphafold-minus-jax] @ git+https://github.com/sokrypton/ColabFold")
    .pip_install("jax[cuda11_pip]")
)

@app.function(image=image, gpu="T4", timeout=600)
def predict_structure_remote(sequence: str, job_id: str):
	import os
	import tempfile
	from colabfold.batch import get_queries, run, set_model_weights
	from colabfold.download import download_alphafold_params

	print(f"[{job_id}] Starting ColabFold for sequence length {len(sequence)}...")

	with tempfile.TemporaryDirectory() as tmp_dir:
		fasta_path = os.path.join(tmp_dir, "input.fasta")
		with open(fasta_path, "w") as f:
			f.write(f">sequence\n{sequence}")

		download_alphafold_params(tmp_dir)

		queries, is_complex = get_queries(fasta_path)

		run(
			queries=queries,
			result_dir=tmp_dir,
			use_templates=False,
			model_order="single_sequence",
			model_type="auto",
			num_models=1,
			num_recycles=1,
		)

		for filename in os.listdir(tmp_dir):
			if filename.endswith(".pdb"):
				with open(os.path.join(tmp_dir, filename), "r") as pdb_file:
					pdb_content = pdb_file.read()
					return {"pdb_content": pdb_content, "status": "success"}
				
		return {"status": "failed", "error": "No PDB generated"}