import requests
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.predict_structure_task", bind=True, max_retries=2)
def predict_structure_task(self, sequence: str) -> dict:
 
    esmfold_api_url = "https://api.esmatlas.com/foldSequence/v1/pdb/"
    
    try:
        response = requests.post(
            esmfold_api_url,
            data=sequence,
            headers={"Content-Type": "text/plain"},
            timeout=120
        )
        
        if response.status_code == 200:
            return {"status": "success", "pdb_text": response.text}
        else:
            return {"status": "error", "code": response.status_code, "message": response.text[:200]}
            
    except requests.Timeout:
        return {"status": "error", "message": "ESMFold API timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@celery_app.task(name="app.tasks.fetch_alphafold_task")
def fetch_alphafold_task(accession: str) -> dict:
    """
    """
    url = f"https://www.alphafold.ebi.ac.uk/api/prediction/{accession}"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and data:
                return {"status": "success", "data": data[0]}
            return {"status": "success", "data": None}
        else:
            return {"status": "error", "code": response.status_code}
    except Exception as e:
        return {"status": "error", "message": str(e)}
