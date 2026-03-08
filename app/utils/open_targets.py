"""
open_targets.py
---------------
Queries the Open Targets Platform GraphQL API to get disease-associated
protein targets and map them to UniProt accessions.

API endpoint: https://api.platform.opentargets.org/api/v4/graphql

Flow:
    disease_name (str)
        → search for disease EFO ID
        → fetch top associated targets (gene symbols + scores)
        → map gene symbol → UniProt accession (via UniProt search)
        → return ranked target list
"""

import logging
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger("psp.open_targets")

GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"

# --------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------- #

def _graphql(query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a GraphQL query against Open Targets platform."""
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data.get("data", {})
    except requests.RequestException as e:
        raise RuntimeError(f"Open Targets API request failed: {e}") from e


def _search_disease(disease_name: str) -> Optional[Dict[str, Any]]:
    """
    Search for a disease by name and return the top hit.
    Returns: {"id": "EFO_0000249", "name": "Alzheimer's disease"} or None.
    """
    query = """
    query DiseaseSearch($query: String!) {
        search(queryString: $query, entityNames: ["disease"], page: {index: 0, size: 3}) {
            hits {
                id
                name
                entity
            }
        }
    }
    """
    data = _graphql(query, {"query": disease_name})
    hits = (data.get("search") or {}).get("hits", [])
    disease_hits = [h for h in hits if h.get("entity") == "disease"]
    if not disease_hits:
        return None
    return {"id": disease_hits[0]["id"], "name": disease_hits[0]["name"]}


def _fetch_associated_targets(disease_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch top protein targets associated with a disease.
    Returns list of {gene_symbol, target_id, score, name}.
    """
    query = """
    query DiseaseTargets($diseaseId: String!, $size: Int!) {
        disease(efoId: $diseaseId) {
            associatedTargets(page: {index: 0, size: $size}) {
                rows {
                    target {
                        id
                        approvedSymbol
                        approvedName
                        proteinAnnotations {
                            accessions
                        }
                    }
                    score
                }
            }
        }
    }
    """
    data = _graphql(query, {"diseaseId": disease_id, "size": limit})
    rows = (
        (data.get("disease") or {})
        .get("associatedTargets", {})
        .get("rows", [])
    )

    targets = []
    for row in rows:
        target = row.get("target", {})
        gene = target.get("approvedSymbol", "")
        name = target.get("approvedName", "")
        score = round(row.get("score", 0.0), 4)
        target_id = target.get("id", "")

        # Try to get UniProt accession directly from the annotation
        accessions: List[str] = (
            (target.get("proteinAnnotations") or {}).get("accessions", [])
        )
        # The first accession is typically the canonical UniProt entry
        uniprot_accession = accessions[0] if accessions else None

        if gene and score > 0:
            targets.append({
                "ensembl_id": target_id,
                "gene_symbol": gene,
                "name": name,
                "accession": uniprot_accession,
                "association_score": score,
            })

    return targets


def _resolve_accession_from_gene(gene_symbol: str) -> Optional[str]:
    """
    Fallback: query UniProt to find the canonical human accession for a gene.
    Used when Open Targets doesn't return protein annotations.
    """
    try:
        params = {
            "query": f"gene:{gene_symbol} AND organism_id:9606 AND reviewed:true",
            "format": "json",
            "size": 1,
            "fields": "accession",
        }
        resp = requests.get(UNIPROT_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0].get("primaryAccession")
    except Exception as e:
        logger.warning("UniProt gene lookup failed for %s: %s", gene_symbol, e)
    return None


# --------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------- #

def fetch_disease_targets(disease_name: str, limit: int = 5) -> Dict[str, Any]:
    """
    Main entry point. Given a disease name, return ranked protein targets
    with their UniProt accessions.

    Args:
        disease_name: Free-text disease name (e.g. "Alzheimer's disease")
        limit: Max number of targets to return (default 5)

    Returns:
        {
            "disease_id":   "EFO_0000249",
            "disease_name": "Alzheimer's disease",
            "targets": [
                {
                    "gene_symbol":       "MAPT",
                    "name":              "Microtubule-associated protein tau",
                    "accession":         "P10636",
                    "association_score": 0.95,
                },
                ...
            ]
        }

    Raises:
        RuntimeError: if the disease is not found or the API fails.
    """
    logger.info("Searching Open Targets for disease: %s", disease_name)

    disease = _search_disease(disease_name)
    if not disease:
        raise RuntimeError(
            f"Disease '{disease_name}' not found in Open Targets. "
            "Try a more specific name (e.g. 'Alzheimer disease', 'type 2 diabetes')."
        )

    logger.info("Found disease: %s (ID: %s)", disease["name"], disease["id"])

    raw_targets = _fetch_associated_targets(disease["id"], limit=limit)

    # Resolve missing accessions via UniProt fallback
    resolved = []
    for t in raw_targets:
        if not t["accession"]:
            t["accession"] = _resolve_accession_from_gene(t["gene_symbol"])
        if t["accession"]:  # only include targets we can actually run the pipeline on
            resolved.append(t)

    if not resolved:
        raise RuntimeError(
            f"No actionable protein targets found for '{disease_name}'. "
            "Open Targets returned targets but none could be mapped to UniProt accessions."
        )

    return {
        "disease_id": disease["id"],
        "disease_name": disease["name"],
        "targets": resolved,
    }
