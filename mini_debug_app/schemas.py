from pydantic import BaseModel


class ErrorInput(BaseModel):
    error_content: str


class ErrorAnalysisOutput(BaseModel):
    error_info: dict
    analysis: str
    fix_suggestion: str
