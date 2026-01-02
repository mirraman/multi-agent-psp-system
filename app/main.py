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

@app.post("/submit/{accession}")
async def submit_job(accession: str) -> Dict[str, str]:

    if MongoConnection.db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    task_doc = {
        "type": "protein_structure_pipeline",
        "input_value": accession,
        "status": "pending",  
        "created_at": str(datetime.now())
    }
    
    job_id = await insert_task(task_doc)
    
    logger.info(f"Job registered: {job_id} for {accession}")
    return {
        "job_id": job_id, 
        "status": "queued", 
        "message": "Job submitted to CoordinatorAgent"
    }

@app.get("/status/{accession}")
async def get_status(accession: str) -> Dict[str, Any]:
   
    if MongoConnection.db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
        
    result = await get_protein_result(accession)
    if result:
        return {"status": "completed", "data": result}
    

    return {"status": "processing_or_not_found"}