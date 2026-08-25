"""
mini_debug_app: 独立DEBUG TOOLの入出力スキーマ

このモジュールは agents/debug/ (本番LangGraph Debug Agent) とは独立した
mini_debug_app専用のスキーマ定義。本番Debug Agentのスキーマ
(agents/debug/schema.py) は変更・参照しない。
"""

from pydantic import BaseModel, field_validator


class ErrorInput(BaseModel):
    error_content: str

    @field_validator("error_content")
    @classmethod
    def error_content_must_not_be_blank(cls, value: str) -> str:
        if value is None or not value.strip():
            raise ValueError("error_content must not be empty")
        return value


class ErrorAnalysisOutput(BaseModel):
    error_info: dict
    analysis: str
    fix_suggestion: str


class DebugResponse(BaseModel):
    """POST /debug/ のレスポンス全体。既存の {"error_analysis": {...}} 形式を維持する。"""

    error_analysis: ErrorAnalysisOutput
