import json
from typing import Any, Dict, List, Optional, Tuple
import time
import logging

import requests


logger = logging.getLogger("psp.fetchers")


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

    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=20)
            break
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(0.5 * (2 ** attempt))
    else:
        raise RuntimeError(f"Request failed for {url}: {last_exc}") from last_exc

    if response.status_code != 200:
        body_text = None
        try:
            body_text = response.text
        except Exception:
            body_text = None
        logger.warning("Non-200 response", extra={"url": url, "status": response.status_code})
        raise HttpError(url, response.status_code, body_text)

    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200] if hasattr(response, "text") else ""
        raise RuntimeError(f"Failed to parse JSON from {url}: {preview}") from exc


def _get_text(url: str) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            break
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(0.5 * (2 ** attempt))
    else:
        raise RuntimeError(f"Request failed for {url}: {last_exc}") from last_exc

    if response.status_code != 200:
        body_text = None
        try:
            body_text = response.text
        except Exception:
            body_text = None
        logger.warning("Non-200 response", extra={"url": url, "status": response.status_code})
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

    return {
        "sequence": sequence,
        "name": name,
        "pdb_ids": pdb_ids,
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



def fetch_pubmed(query: str, api_key: Optional[str] = None, retmax: int = 10) -> Dict[str, Any]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    esearch_url = (
        f"{base}/esearch.fcgi?db=pubmed&retmode=json&retmax={retmax}&term={requests.utils.quote(query)}"
        + (f"&api_key={api_key}" if api_key else "")
    )
    try:
        esearch = _get_json(esearch_url)
    except HttpError as exc:  
        msg = str(exc)
        if api_key and exc.status_code == 400 and ("API key invalid" in msg or "api key invalid" in msg.lower()):
            esearch_url = f"{base}/esearch.fcgi?db=pubmed&retmode=json&retmax={retmax}&term={requests.utils.quote(query)}"
            esearch = _get_json(esearch_url)
        else:
            raise
    esr = esearch.get("esearchresult", {})
    id_list: List[str] = esr.get("idlist", [])
    count: int = int(esr.get("count", 0))

    articles: List[Dict[str, Any]] = []
    if id_list:
        ids = ",".join(id_list)
        esummary_url = (
            f"{base}/esummary.fcgi?db=pubmed&retmode=json&id={ids}"
            + (f"&api_key={api_key}" if api_key else "")
        )
        try:
            summary = _get_json(esummary_url)
        except HttpError as exc:
            msg = str(exc)
            if api_key and exc.status_code == 400 and ("API key invalid" in msg or "api key invalid" in msg.lower()):
                esummary_url = f"{base}/esummary.fcgi?db=pubmed&retmode=json&id={ids}"
                summary = _get_json(esummary_url)
            else:
                raise
        res = summary.get("result", {})
        for uid in res.get("uids", []):
            item = res.get(uid) or {}
            if not item:
                continue
            articles.append(
                {
                    "uid": uid,
                    "title": item.get("title"),
                    "pubdate": item.get("pubdate"),
                    "journal": item.get("fulljournalname") or item.get("source"),
                    "authors": [a.get("name") for a in item.get("authors", []) if a.get("name")],
                }
            )

    return {"count": count, "ids": id_list, "articles": articles}

