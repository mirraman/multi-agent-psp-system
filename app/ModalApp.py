import modal
import os

app = modal.App("psp-colabfold-worker")

image = (
    modal.Image.debian_slim()
    .apt_install("git", "wget", "aria2", "ffmpeg") 
    .pip_install(
        "colabfold[alphafold-minus-jax] @ git+https://github.com/sokrypton/ColabFold",
        "jax[cuda12_pip]",
        "dm-haiku",
        "biopython",
    )
)

@app.function(image=image, gpu="T4", timeout=600)
def predict_structure_remote(sequence: str, job_id: str):
	import os
	import tempfile
	import traceback
	from colabfold.batch import get_queries, run
	from colabfold.download import download_alphafold_params

	print(f"[{job_id}] Starting ColabFold for sequence length {len(sequence)}...")

	try:
		with tempfile.TemporaryDirectory() as tmp_dir:
			fasta_path = os.path.join(tmp_dir, "input.fasta")
			with open(fasta_path, "w") as f:
				f.write(f">sequence\n{sequence}")

			download_alphafold_params(tmp_dir)

			queries, is_complex = get_queries(fasta_path)

			run(
				queries=queries,
				result_dir=tmp_dir,
				data_dir=tmp_dir,
				use_templates=False,
				model_type="alphafold2_ptm",  
				msa_mode="single_sequence",   
				num_models=1,
				num_recycles=1,
			)

			for filename in os.listdir(tmp_dir):
				if filename.endswith(".pdb"):
					with open(os.path.join(tmp_dir, filename), "r") as pdb_file:
						pdb_content = pdb_file.read()
						return {"pdb_content": pdb_content, "status": "success"}
					
			return {"status": "failed", "error": "No PDB generated in result dir"}

	except Exception as e:
		print(f"Error executing ColabFold: {e}")
		return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()}