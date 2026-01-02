from datetime import datetime, UTC
from typing import Any, Dict


class OutputAgent:
    def __init__(self) -> None:
        pass

    def run(self, accession: str, raw_data: Dict[str, Any], processed_data: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = datetime.now(UTC).isoformat()

        output_doc: Dict[str, Any] = {
            "accession": accession,
            "timestamp": timestamp,
            "uniprot": raw_data.get("uniprot"),
            "pdb": raw_data.get("pdb"),
            "alphafold": raw_data.get("alphafold"),
            "metrics": processed_data,
        }

        return output_doc


