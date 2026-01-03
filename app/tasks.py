import requests
from app.celery_app import celery_app

@celery_app.task(name="app.tasks.predict_structure_task")
def predict_structure_task(sequence: str):
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
            return {"status": "error", "error": f"API Error: {response.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
