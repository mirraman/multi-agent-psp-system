from typing import Any, Dict, List, Optional

from app.utils.fetchers import fetch_uniprot, fetch_pdb, fetch_alphafold, fetch_pubmed


class DataAgent:
    def __init__(self) -> None:
        self.uniprot_client = fetch_uniprot
        self.pdb_client = fetch_pdb
        self.alphafold_client = fetch_alphafold
        self.pubmed_client = fetch_pubmed

    def run(
        self,
        accession: str,
        include_pubmed: bool = False,
        pubmed_api_key: Optional[str] = None,
        pubmed_retmax: int = 5,
    ) -> Dict[str, Any]:
        uniprot_data: Dict[str, Any] = self.uniprot_client(accession)

        pdb_results: List[Dict[str, Any]] = []
        for pdb_id in uniprot_data.get("pdb_ids", []):
            try:
                pdb_results.append(self.pdb_client(pdb_id))
            except Exception as _:
                continue

        alphafold_data: Dict[str, Any] = self.alphafold_client(accession)

        pubmed_data: Optional[Dict[str, Any]] = None
        if include_pubmed:
            name = uniprot_data.get("name") or ""
            query = accession if not name else f"{accession} {name}"
            pubmed_data = self.pubmed_client(query, api_key=pubmed_api_key, retmax=pubmed_retmax)

        return {
            "accession": accession,
            "uniprot": {
                "name": uniprot_data.get("name"),
                "sequence": uniprot_data.get("sequence"),
                "pdb_ids": uniprot_data.get("pdb_ids", []),
                "alphafold_links": uniprot_data.get("alphafold_links", []),
            },
            "pdb": pdb_results,
            "alphafold": alphafold_data,
            "pubmed": pubmed_data,
        }