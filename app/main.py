import argparse
import json
from typing import Any, Dict
from contextlib import asynccontextmanager

import os
from fastapi import FastAPI
from fastapi import BackgroundTasks
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.utils.fetchers import fetch_uniprot, fetch_pdb, fetch_alphafold, fetch_pubmed
from app.agents.data_agent import DataAgent


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_uri = os.getenv("MONGODB_URI")
    if mongo_uri:
        try:
            from app.utils.db import MongoConnection

            await MongoConnection.init(mongo_uri)
        except Exception as exc:
            print(f"Mongo init skipped/failed: {exc}")
    try:
        yield
    finally:
        try:
            from app.utils.db import MongoConnection

            await MongoConnection.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/data/{accession}")
async def run_data_agent(accession: str, include_pubmed: bool = False, save: bool = False) -> Dict[str, Any]:
    agent = DataAgent()
    result = agent.run(accession, include_pubmed=include_pubmed, pubmed_api_key=os.getenv("PUBMED_API_KEY"))

    if save and os.getenv("MONGODB_URI"):
        try:
            from app.utils.db import MongoConnection, upsert_aggregate

            if not MongoConnection.db:
                await MongoConnection.init(os.getenv("MONGODB_URI"))
            await upsert_aggregate(accession, result)
        except Exception as exc:
            print(f"Aggregate save failed: {exc}")

    return result


 


def main() -> None:
    parser = argparse.ArgumentParser(description="Protein data fetch CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    uni = sub.add_parser("uniprot", help="Fetch UniProt entry by accession")
    uni.add_argument("accession", type=str)

    pdb = sub.add_parser("pdb", help="Fetch PDB metadata by ID")
    pdb.add_argument("pdb_id", type=str)

    af = sub.add_parser("alphafold", help="Fetch AlphaFold prediction by UniProt accession")
    af.add_argument("accession", type=str)

    pm = sub.add_parser("pubmed", help="Search PubMed for a query")
    pm.add_argument("query", type=str)
    pm.add_argument("--api-key", dest="api_key", type=str, default=os.getenv("PUBMED_API_KEY"))
    pm.add_argument("--retmax", type=int, default=5)

    agent = sub.add_parser("agent", help="Run DataAgent pipeline")
    agent.add_argument("accession", nargs="?", default="P69905")
    agent.add_argument("--include-pubmed", action="store_true")
    agent.add_argument("--api-key", dest="api_key", type=str, default=os.getenv("PUBMED_API_KEY"))
    agent.add_argument("--retmax", type=int, default=5)

    args = parser.parse_args()

    try:
        if args.cmd == "uniprot":
            result: Dict[str, Any] = fetch_uniprot(args.accession)
        elif args.cmd == "pdb":
            result = fetch_pdb(args.pdb_id)
        elif args.cmd == "alphafold":
            result = fetch_alphafold(args.accession)
        elif args.cmd == "pubmed":
            result = fetch_pubmed(args.query, api_key=args.api_key, retmax=args.retmax)
        elif args.cmd == "agent":
            agent = DataAgent()
            result = agent.run(
                args.accession,
                include_pubmed=args.include_pubmed,
                pubmed_api_key=args.api_key,
                pubmed_retmax=args.retmax,
            )
        else:
            parser.error("Unknown command")
            return
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        raise

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


