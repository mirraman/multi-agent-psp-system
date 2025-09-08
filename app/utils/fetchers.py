import json
from typing import Any, Dict, List, Optional, Tuple

import requests


class HttpError(Exception):

    def __init__(self, url: str, status_code: int, body: Optional[str] = None) -> None:
        message = f"HTTP {status_code} for {url}"
        if body:
            message = f"{message}: {body[:200]}" 
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.body = body


def _get_json(url: str) -> Any:

    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc

    if response.status_code != 200:
        body_text = None
        try:
            body_text = response.text
        except Exception:
            body_text = None
        raise HttpError(url, response.status_code, body_text)

    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200] if hasattr(response, "text") else ""
        raise RuntimeError(f"Failed to parse JSON from {url}: {preview}") from exc


def _get_text(url: str) -> str:
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc

    if response.status_code != 200:
        body_text = None
        try:
            body_text = response.text
        except Exception:
            body_text = None
        raise HttpError(url, response.status_code, body_text)

    return response.text


def _plddt_from_pdb_text(pdb_text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
   
    ca_values: List[float] = []
    all_values: List[float] = []

    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") and not line.startswith("HETATM"):
            continue
        atom_name = line[12:16].strip() if len(line) >= 16 else ""
        try:
            bfactor_str = line[60:66].strip()
            if not bfactor_str:
                continue
            bfactor_val = float(bfactor_str)
        except Exception:
            continue

        all_values.append(bfactor_val)
        if atom_name == "CA":
            ca_values.append(bfactor_val)

    values = ca_values if ca_values else all_values
    if not values:
        return None, None, None

    mean_val = sum(values) / len(values)
    return mean_val, min(values), max(values)


def fetch_uniprot(accession: str) -> Dict[str, Any]:
    url = f"https://rest.uniprot.org/uniprotkb/{accession}.json"
    data = _get_json(url)

    sequence: str = (
        (data.get("sequence") or {}).get("value") or ""
    )

    name: str = ""
    protein_desc = data.get("proteinDescription") or {}
    rec_name = (protein_desc.get("recommendedName") or {}).get("fullName") or {}
    if isinstance(rec_name, dict):
        name = rec_name.get("value") or ""

    db_refs: List[Dict[str, Any]] = data.get("dbReferences") or []
    pdb_ids: List[str] = [ref.get("id") for ref in db_refs if ref.get("type") == "PDB" and ref.get("id")]
    alphafold_links: List[str] = [ref.get("id") for ref in db_refs if ref.get("type") == "AlphaFoldDB" and ref.get("id")]

    return {
        "sequence": sequence,
        "name": name,
        "pdb_ids": pdb_ids,
        "alphafold_links": alphafold_links,
    }


def fetch_pdb(pdb_id: str) -> Dict[str, Any]:
    url = f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}"
    data = _get_json(url)

    # Commonly useful metadata fields
    struct = data.get("struct") or {}
    exptl = (data.get("exptl") or [{}])
    entry_info = data.get("rcsb_entry_info") or {}

    title: str = struct.get("title") or ""
    experimental_method: str = (exptl[0] or {}).get("method") or ""
    resolution: Optional[float] = None
    res_list = entry_info.get("resolution_combined") or []
    if isinstance(res_list, list) and res_list:
        resolution = res_list[0]

    metadata = {
        "title": title,
        "experimental_method": experimental_method,
        "resolution": resolution,
    }

    download_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    return {"metadata": metadata, "download_url": download_url}


def fetch_alphafold(accession: str) -> Dict[str, Any]:
    url = f"https://www.alphafold.ebi.ac.uk/api/prediction/{accession}"
    data = _get_json(url)

    if not isinstance(data, list) or not data:
        return {"pdb_url": None, "confidence_metrics": None, "pae_json_url": None, "pae_image_url": None}

    entry: Dict[str, Any] = data[0]
    pdb_url: Optional[str] = entry.get("pdbUrl")
    cif_url: Optional[str] = entry.get("cifUrl")
    pae_json_url: Optional[str] = entry.get("paeJsonUrl") or entry.get("paeUrl")
    pae_image_url: Optional[str] = entry.get("paeImageUrl")

    confidence_metrics = entry.get("plddt") or entry.get("confidence")

    plddt_mean: Optional[float] = None
    plddt_min: Optional[float] = None
    plddt_max: Optional[float] = None
    if not confidence_metrics and pdb_url:
        try:
            pdb_text = _get_text(pdb_url)
            plddt_mean, plddt_min, plddt_max = _plddt_from_pdb_text(pdb_text)
        except Exception:
            pass

    result: Dict[str, Any] = {
        "pdb_url": pdb_url,
        "cif_url": cif_url,
        "pae_json_url": pae_json_url,
        "pae_image_url": pae_image_url,
        "confidence_metrics": confidence_metrics,
    }

    if plddt_mean is not None:
        result.update({
            "plddt_mean": plddt_mean,
            "plddt_min": plddt_min,
            "plddt_max": plddt_max,
        })

    return result


