from pydantic import BaseModel
from typing import Dict, Any

class AnalysisRequest(BaseModel):
    image_base64: str

class AnalysisResponse(BaseModel):
    verdict: bool
    analysis: Dict[str, Any]
    warnings: str = None
