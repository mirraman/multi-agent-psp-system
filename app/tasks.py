import requests
from app.celery_app import celery_app

# ========== PROTEIN STRUCTURE PREDICTION TASK ==========

@celery_app.task(name="app.tasks.predict_esmfold")
def predict_esmfold(sequence: str):
    """
    ESMFold structure prediction - Fast (~30-120s)
    
    Uses the ESMFold API to predict protein structure from sequence.
    Returns PDB format structure with pLDDT scores in B-factor column.
    """
    esmfold_api_url = "https://api.esmatlas.com/foldSequence/v1/pdb/"
    try:
        response = requests.post(
            esmfold_api_url, 
            data=sequence, 
            headers={"Content-Type": "text/plain"},
            timeout=120
        )
        if response.status_code == 200:
            return {
                "status": "success", 
                "pdb_text": response.text,
                "model": "esmfold",
                "source": "ESMFold_API"
            }
        else:
            return {
                "status": "error", 
                "error": f"ESMFold API returned status {response.status_code}",
                "error_type": "api_error",
                "model": "esmfold"
            }
    except requests.Timeout:
        return {
            "status": "error", 
            "error": "ESMFold API timeout after 120s",
            "error_type": "timeout",
            "model": "esmfold"
        }
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e),
            "error_type": "unknown",
            "model": "esmfold"
        }


# ========== LEGACY TASK (for backward compatibility) ==========

@celery_app.task(name="app.tasks.predict_structure_task")
def predict_structure_task(sequence: str):
    """
    Legacy task - redirects to predict_esmfold for backward compatibility.
    """
    return predict_esmfold(sequence)
