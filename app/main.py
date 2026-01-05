import os
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
from contextlib import asynccontextmanager

from app.utils.db import MongoConnection, insert_task, get_protein_result

logger = logging.getLogger("psp.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    try:
        await MongoConnection.init(mongo_uri)
        print("Connected to MongoDB via FastAPI")
    except Exception as e:
        print(f"Failed to connect to Mongo: {e}")
    yield
    await MongoConnection.close()

app = FastAPI(lifespan=lifespan)

@app.post("/submit/{input_value}")
async def submit_job(input_value: str) -> Dict[str, str]:
    """
    Submit a protein structure prediction job.
    
    Accepts:
    - Accession ID (e.g., P12345)
    - FASTA sequence (e.g., MQIFVKTLT...)
    
    Auto-detects input type.
    """
    if MongoConnection.db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    # Auto-detect input type
    # If starts with '>' or contains only amino acid letters, it's FASTA
    # Otherwise, assume it's an accession ID
    input_type = "fasta" if (input_value.startswith(">") or 
                             all(c in "ACDEFGHIKLMNPQRSTVWY" for c in input_value.upper())) else "accession"
    
    task_doc = {
        "type": "protein_structure_pipeline",
        "input_type": input_type,
        "input_value": input_value,
        "status": "pending",  
        "created_at": str(datetime.now())
    }
    
    job_id = await insert_task(task_doc)
    
    logger.info(f"Job registered: {job_id} for {input_type}: {input_value[:50]}...")
    return {
        "job_id": job_id, 
        "status": "queued",
        "input_type": input_type,
        "message": f"Job submitted to CoordinatorAgent ({input_type})"
    }

@app.get("/status/{accession}")
async def get_status(accession: str) -> Dict[str, Any]:
   
    if MongoConnection.db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
        
    result = await get_protein_result(accession)
    if result:
        return {"status": "completed", "data": result}
    

    return {"status": "processing_or_not_found"}