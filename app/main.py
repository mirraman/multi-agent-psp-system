import argparse
import json
from typing import Any, Dict

from app.utils.fetchers import fetch_uniprot, fetch_pdb, fetch_alphafold


def main() -> None:
    parser = argparse.ArgumentParser(description="Protein data fetch CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    uni = sub.add_parser("uniprot", help="Fetch UniProt entry by accession")
    uni.add_argument("accession", type=str)

    pdb = sub.add_parser("pdb", help="Fetch PDB metadata by ID")
    pdb.add_argument("pdb_id", type=str)

    af = sub.add_parser("alphafold", help="Fetch AlphaFold prediction by UniProt accession")
    af.add_argument("accession", type=str)

    args = parser.parse_args()

    try:
        if args.cmd == "uniprot":
            result: Dict[str, Any] = fetch_uniprot(args.accession)
        elif args.cmd == "pdb":
            result = fetch_pdb(args.pdb_id)
        elif args.cmd == "alphafold":
            result = fetch_alphafold(args.accession)
        else:
            parser.error("Unknown command")
            return
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        raise

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


