from collections import Counter
from typing import Any, Dict


class ProcessingAgent:
    def __init__(self) -> None:
        pass

    def run(self, data: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {}

        # --- Sequence metrics ---
        sequence: str = (data.get("uniprot") or {}).get("sequence", "")
        if sequence:
            results["sequence_length"] = len(sequence)
            results["amino_acid_composition"] = dict(Counter(sequence))

        # --- AlphaFold metrics ---
        # fetch_alphafold returns keys: confidence_metrics (or pLDDT mean/min/max if parsed),
        # and potentially plddt_mean/min/max when derived from PDB text.
        af_data: Dict[str, Any] = data.get("alphafold") or {}
        if af_data:
            # Prefer a single confidence value if available
            conf = af_data.get("confidence") or af_data.get("confidence_metrics") or af_data.get("plddt_mean")
            if conf is not None:
                results["alphafold_confidence"] = conf

            # Fractions may or may not exist in current fetcher output; include if provided upstream
            frac_conf = af_data.get("fraction_confident")
            if frac_conf is not None:
                results["fraction_confident"] = frac_conf
            frac_vhigh = af_data.get("fraction_very_high")
            if frac_vhigh is not None:
                results["fraction_very_high"] = frac_vhigh

        # --- Optional: PDB metrics ---
        pdb_list = data.get("pdb") or []
        results["pdb_count"] = len(pdb_list)
        if pdb_list:
            # Simple derived metrics: count by experimental_method and best resolution
            method_counts: Dict[str, int] = {}
            best_resolution = None
            for entry in pdb_list:
                meta = (entry or {}).get("metadata") or {}
                method = meta.get("experimental_method") or "UNKNOWN"
                method_counts[method] = method_counts.get(method, 0) + 1
                res = meta.get("resolution")
                if isinstance(res, (int, float)):
                    if best_resolution is None or res < best_resolution:
                        best_resolution = res
            results["pdb_method_counts"] = method_counts
            if best_resolution is not None:
                results["pdb_best_resolution"] = best_resolution

        return results


if __name__ == "__main__":
    from backend.app.services.DataService import DataAgent

    da = DataAgent()
    raw_data = da.run("P69905")
    pa = ProcessingAgent()
    processed = pa.run(raw_data)
    print(processed)


