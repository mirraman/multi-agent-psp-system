import modal
import os
import shutil
from pathlib import Path

# 1. Volume for weights
vol = modal.Volume.from_name("colabfold-params", create_if_missing=True)

app = modal.App("psp-colabfold-worker")

CACHE_DIR = "/root/.cache/colabfold"

image = (
    modal.Image.micromamba(python_version="3.10")
    .apt_install("git", "wget", "aria2")
    # 2. Install SYSTEM tools via Micromamba (safe channels)
    .micromamba_install(
        "kalign2",
        "hhsuite",
        "openmm=7.7.0", 
        "pdbfixer",
        channels=["conda-forge", "bioconda"] 
    )
    # 3. ATOMIC PIP INSTALL (The Fix)
    # We pass ALL python dependencies in a single list.
    # This prevents pip from "upgrading" JAX in a later step.
    .pip_install(
        "jax==0.4.23",                       # HARD PIN: Last version with 'linear_util'
        "jaxlib==0.4.23+cuda12.cudnn89",     # HARD PIN: Matches JAX and Modal T4 GPU
        "dm-haiku==0.0.10",                  # HARD PIN: Exact requirement for ColabFold 1.5.5
        "biopython<1.82",                    # HARD PIN: Legacy API required
        "numpy<2",                           # SAFETY PIN: Numpy 2.0 breaks everything in bio-land
        "colabfold[alphafold-minus-jax] @ git+https://github.com/sokrypton/ColabFold@v1.5.5",
        find_links="https://storage.googleapis.com/jax-releases/jax_cuda_releases.html",
    )
)

def download_if_missing():
    """Checks if params exist in the Volume; downloads if missing."""
    param_path = Path(CACHE_DIR)
    test_file = param_path / "alphafold2_ptm_params" 
    
    if not test_file.exists():
        print("Parameters not found in Volume. Downloading now...")
        from colabfold.download import download_alphafold_params
        
        param_path.mkdir(parents=True, exist_ok=True)
        download_alphafold_params('alphafold2_ptm', param_path)
        vol.commit() 
        print("Download complete.")
    else:
        print("Parameters found in Volume.")

@app.function(
    image=image, 
    gpu="T4", 
    timeout=3600, 
    volumes={CACHE_DIR: vol}
)
def predict_structure_remote(sequence: str, job_id: str):
    import tempfile
    import traceback
    
    # Setup
    try:
        download_if_missing()
        from colabfold.batch import get_queries, run
    except Exception as e:
        return {"status": "failed", "error": f"Setup/Import failed: {e}", "traceback": traceback.format_exc()}

    print(f"[{job_id}] Starting ColabFold for len {len(sequence)}...")

    # Prediction
    try:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            fasta_path = tmp_dir / "input.fasta"
            
            with open(fasta_path, "w") as f:
                f.write(f">sequence\n{sequence}")

            queries, is_complex = get_queries(str(fasta_path))
            
            run(
                queries=queries,
                result_dir=tmp_dir,
                is_complex=is_complex,
                data_dir=Path(CACHE_DIR),
                use_templates=False,
                num_models=1,     
                num_recycles=3,  
                model_type="alphafold2_ptm",
            )

            # Output Extraction
            pdb_content = None
            for filename in os.listdir(str(tmp_dir)):
                if filename.endswith(".pdb") and "rank_1" in filename:
                    with open(tmp_dir / filename, "r") as f:
                        pdb_content = f.read()
                    break
            
            if not pdb_content:
                 for filename in os.listdir(str(tmp_dir)):
                    if filename.endswith(".pdb"):
                        with open(tmp_dir / filename, "r") as f:
                            pdb_content = f.read()
                        break

            if pdb_content:
                return {"pdb_content": pdb_content, "status": "success"}
            else:
                return {"status": "failed", "error": f"No PDB found. Dir content: {os.listdir(str(tmp_dir))}"}

    except Exception as e:
        print(f"Error executing ColabFold: {e}")
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()}