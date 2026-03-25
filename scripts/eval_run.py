"""
Evaluation script: submit 10 proteins in order, poll until all complete,
then print a structured result table.
"""
import time
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"

PROTEINS = [
    # Group 1 — Experimental expected
    {"accession": "P04637", "name": "TP53",           "group": "G1",  "expected": "experimental"},
    {"accession": "P00533", "name": "EGFR",           "group": "G1",  "expected": "experimental"},
    # Group 2 — AlphaFold DB expected
    {"accession": "P37840", "name": "Alpha-synuclein","group": "G2",  "expected": "alphafold_db"},
    {"accession": "Q99720", "name": "SIGMAR1",        "group": "G2",  "expected": "alphafold_db"},
    # Group 3 — ESMFold expected
    {"accession": "A0PK11", "name": "Clarin-2",         "group": "G3",  "expected": "esmfold"},
    {"accession": "A2RU14", "name": "TMEM218",          "group": "G3",  "expected": "esmfold"},
    {"accession": "Q9Y243", "name": "AKT3",           "group": "G3",  "expected": "esmfold"},
    # Group 4 — Stress tests
    {"accession": "P04049", "name": "RAF1",           "group": "G4",  "expected": "esmfold/modal"},
    {"accession": "P06280", "name": "α-Galactosidase A","group": "G4","expected": "experimental"},
    {"accession": "A6NI61", "name": "Myomaker",       "group": "G4",  "expected": "esmfold"},
]

def post_json(url, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())

def submit_jobs():
    jobs = []
    for p in PROTEINS:
        try:
            resp = post_json(f"{BASE_URL}/jobs", {"accession": p["accession"]})
            job_id = resp.get("job_id")
            print(f"  Submitted {p['accession']} ({p['name']}) → job_id={job_id}")
            jobs.append({**p, "job_id": job_id, "status": "queued"})
        except Exception as e:
            print(f"  ERROR submitting {p['accession']}: {e}")
            jobs.append({**p, "job_id": None, "status": "submission_error", "error": str(e)})
    return jobs

def poll_jobs(jobs, max_wait_secs=900, poll_interval=10):
    """Poll until all jobs complete or max_wait_secs is reached."""
    deadline = time.time() + max_wait_secs
    pending = {j["job_id"]: j for j in jobs if j["job_id"] is not None}
    results = {j["job_id"]: j for j in jobs if j["job_id"] is None}  # failed submissions

    while pending and time.time() < deadline:
        for job_id in list(pending.keys()):
            try:
                job_status = get_json(f"{BASE_URL}/jobs/{job_id}")
                status = job_status.get("status", "unknown")
                pending[job_id]["current_status"] = status
                print(f"  job {job_id} ({pending[job_id]['accession']}) → {status}")

                if status == "completed":
                    # Fetch result
                    result = get_json(f"{BASE_URL}/jobs/{job_id}/result")
                    pending[job_id]["result"] = result
                    results[job_id] = pending.pop(job_id)
                elif status == "failed":
                    pending[job_id]["result"] = None
                    pending[job_id]["error"] = job_status.get("error_message", "failed")
                    results[job_id] = pending.pop(job_id)
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    # still processing — not complete yet
                    pass
                else:
                    print(f"  HTTP {e.code} for job {job_id}")
            except Exception as e:
                print(f"  Poll error for job {job_id}: {e}")

        if pending:
            remaining = int(deadline - time.time())
            print(f"\n  {len(pending)} job(s) still running. Waiting {poll_interval}s... ({remaining}s left)")
            time.sleep(poll_interval)

    # Any still-pending jobs are timeout
    for job_id, job in pending.items():
        job["result"] = None
        job["error"] = "timeout"
        results[job_id] = job

    return list(results.values())

def extract_metrics(job):
    """Pull the key metrics from a completed job result."""
    r = job.get("result") or {}
    synthesis = r.get("synthesis") or {}
    metrics = r.get("metrics") or {}
    pockets = r.get("pockets") or {}
    analysis = r.get("analysis") or {}
    models_used = r.get("models_used") or []

    best_model = synthesis.get("best_model") or "—"
    best_model_source = synthesis.get("best_model_source") or "—"
    confidence = synthesis.get("confidence_score")
    scenario = synthesis.get("scenario") or "—"
    summary = synthesis.get("summary", "")[:100]

    pocket_summary = pockets.get("pocket_summary") or {}
    high_conf_pockets = pocket_summary.get("high_confidence", "—")
    total_pockets = pocket_summary.get("total_detected", pocket_summary.get("total", "—"))

    pairwise_rmsd = analysis.get("pairwise_rmsd") or {}
    rmsd_str = "; ".join(f"{k}: {v}Å" for k, v in pairwise_rmsd.items()) if pairwise_rmsd else "—"

    esmfold_plddt = metrics.get("esmfold_plddt_mean")
    pdb_res = metrics.get("pdb_best_resolution")
    af_plddt = metrics.get("alphafold_confidence") or metrics.get("alphafold_db_plddt_mean")

    exp_pdb_id = synthesis.get("experimental_pdb_id") or "—"

    return {
        "best_model": best_model,
        "best_model_source": best_model_source,
        "confidence": confidence,
        "scenario": scenario,
        "models_used": models_used,
        "esmfold_plddt": esmfold_plddt,
        "pdb_resolution": pdb_res,
        "af_plddt": af_plddt,
        "exp_pdb_id": exp_pdb_id,
        "high_conf_pockets": high_conf_pockets,
        "total_pockets": total_pockets,
        "pairwise_rmsd": rmsd_str,
        "summary": summary,
    }

def print_table(jobs_with_results):
    print("\n" + "="*120)
    print(f"{'#':<3} {'Grp':<4} {'Accession':<10} {'Name':<22} {'Expected':<15} {'Best Model':<20} {'Pdb/Res/pLDDT':<18} {'HC Pockets':<12} {'RMSD':<20} {'Match?'}")
    print("="*120)

    for i, job in enumerate(jobs_with_results, 1):
        acc = job["accession"]
        name = job["name"][:20]
        grp = job["group"]
        expected = job["expected"]
        status = job.get("current_status") or job.get("status", "?")
        error = job.get("error", "")

        if not job.get("result"):
            print(f"{i:<3} {grp:<4} {acc:<10} {name:<22} {expected:<15} {'FAILED/TIMEOUT':<20} status={status} err={error}")
            continue

        m = extract_metrics(job)

        # Determine quality detail string
        if m["pdb_resolution"] and isinstance(m["pdb_resolution"], (int, float)):
            quality = f"{m['pdb_resolution']}Å (res)"
        elif m["af_plddt"] and isinstance(m["af_plddt"], (int, float)):
            quality = f"pLDDT {m['af_plddt']:.1f} (AF)"
        elif m["esmfold_plddt"] and isinstance(m["esmfold_plddt"], (int, float)):
            quality = f"pLDDT {m['esmfold_plddt']:.1f} (ESM)"
        else:
            quality = str(m["confidence"] or "—")

        best = m["best_model"][:18]
        pockets = str(m["high_conf_pockets"])
        rmsd = m["pairwise_rmsd"][:18]
        # Match check — rough
        exp_lower = expected.lower().replace("/", "|")
        match = "✓" if (best.lower() in exp_lower or any(e in best.lower() for e in exp_lower.split("|"))) else "✗"

        print(f"{i:<3} {grp:<4} {acc:<10} {name:<22} {expected:<15} {best:<20} {quality:<18} {pockets:<12} {rmsd:<20} {match}")

    print("="*120)

def save_results(jobs_with_results, path="eval_results.json"):
    out = []
    for job in jobs_with_results:
        entry = {
            "accession": job["accession"],
            "name": job["name"],
            "group": job["group"],
            "expected_best_model": job["expected"],
            "job_id": job.get("job_id"),
            "status": job.get("current_status") or job.get("status"),
            "metrics": extract_metrics(job) if job.get("result") else None,
            "error": job.get("error"),
        }
        out.append(entry)
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nResults saved to {path}")
    return out

if __name__ == "__main__":
    print("=== PSP System Evaluation Run ===")
    print(f"Target: {BASE_URL}")
    print(f"Proteins: {len(PROTEINS)}")
    print()

    print("[1/3] Submitting jobs...")
    jobs = submit_jobs()
    print(f"\nSubmitted {sum(1 for j in jobs if j.get('job_id'))} / {len(jobs)} jobs")

    print("\n[2/3] Polling for results (max 15 min)...")
    jobs_done = poll_jobs(jobs, max_wait_secs=900, poll_interval=15)

    print("\n[3/3] Results Table:")
    print_table(jobs_done)

    saved = save_results(jobs_done, path="eval_results.json")
    print("\nDone.")
