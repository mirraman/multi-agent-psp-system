import modal
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# 1. Volume for weights
vol = modal.Volume.from_name("colabfold-params", create_if_missing=True)
MODAL_APP_NAME = os.getenv("MODAL_APP_NAME", "psp-colabfold-worker")
app = modal.App(MODAL_APP_NAME)

CACHE_DIR = "/root/.cache/colabfold"
RUN_TIMEOUT_SECONDS = 900

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
    import signal

    def _ts() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _log(stage: str, extra: str = "") -> None:
        elapsed = time.monotonic() - start_time
        suffix = f" | {extra}" if extra else ""
        print(f"[{job_id}] [{_ts()}] +{elapsed:.2f}s {stage}{suffix}")

    class _RunTimeout:
        def __init__(self, seconds: int):
            self.seconds = seconds
            self._prev_handler = None

        def _handler(self, signum, frame):
            raise TimeoutError(f"colabfold.run exceeded {self.seconds}s internal timeout")

        def __enter__(self):
            self._prev_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, self._handler)
            signal.alarm(self.seconds)

        def __exit__(self, exc_type, exc_val, exc_tb):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, self._prev_handler)
    
    # Setup
    start_time = time.monotonic()
    try:
        _log("pre-download params")
        download_if_missing()
        _log("post-download params")
        from colabfold.batch import get_queries, run
        _log("post-import colabfold.batch")
    except Exception as e:
        _log("setup/import failed", str(e))
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
            _log("prepared queries", f"is_complex={is_complex}")
            
            _log("pre-run", f"timeout={RUN_TIMEOUT_SECONDS}s")
            with _RunTimeout(RUN_TIMEOUT_SECONDS):
                run(
                    queries=queries,
                    result_dir=tmp_dir,
                    is_complex=is_complex,
                    data_dir=Path(CACHE_DIR),
                    use_templates=False,
                    num_models=1,
                    num_recycles=1,
                    max_seq=128,
                    max_extra_seq=256,
                    model_type="alphafold2_ptm",
                )
            _log("post-run")

            file_entries = []
            for p in sorted(tmp_dir.rglob("*")):
                rel = str(p.relative_to(tmp_dir))
                if p.is_file():
                    file_entries.append(f"{rel} ({p.stat().st_size}B)")
                else:
                    file_entries.append(f"{rel}/")
            _log("post-run file listing", ", ".join(file_entries) if file_entries else "<empty>")

            # Output Extraction
            pdb_content = None
            expected_pdbs = sorted(tmp_dir.rglob("*.pdb"))
            expected_cifs = sorted(tmp_dir.rglob("*.cif"))
            _log(
                "verify outputs",
                (
                    f"pdb_files={[str(p.relative_to(tmp_dir)) for p in expected_pdbs]} "
                    f"cif_files={[str(p.relative_to(tmp_dir)) for p in expected_cifs]}"
                ),
            )

            preferred_pdb = None
            for p in expected_pdbs:
                lower_name = p.name.lower()
                if "rank_001" in lower_name or "rank_1" in lower_name:
                    preferred_pdb = p
                    break
            if preferred_pdb is None and expected_pdbs:
                preferred_pdb = expected_pdbs[0]

            if preferred_pdb is not None:
                with open(preferred_pdb, "r") as f:
                    pdb_content = f.read()

            if pdb_content:
                _log("before return payload", f"status=success pdb_len={len(pdb_content)}")
                return {"pdb_content": pdb_content, "status": "success"}
            else:
                _log("before return payload", "status=failed no pdb extracted")
                return {
                    "status": "failed",
                    "error": (
                        "No PDB found in ColabFold output. "
                        f"PDB files: {[str(p.relative_to(tmp_dir)) for p in expected_pdbs]}; "
                        f"CIF files: {[str(p.relative_to(tmp_dir)) for p in expected_cifs]}; "
                        f"Dir content: {file_entries}"
                    ),
                }

    except Exception as e:
        print(f"Error executing ColabFold: {e}")
        _log("before return payload", f"status=failed exception={e}")
        return {"status": "failed", "error": str(e), "traceback": traceback.format_exc()}