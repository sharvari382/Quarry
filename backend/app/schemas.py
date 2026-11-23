"""Request/response models. Inputs are strictly bounded so oversized payloads fail fast."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name is required")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    created_at: datetime


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_filename: str
    table_name: str
    row_count: int
    column_count: int
    size_bytes: int
    columns: list = Field(validation_alias="schema_json")
    quality: dict = Field(validation_alias="quality_json")
    created_at: datetime


class UploadOut(BaseModel):
    datasets: list[DatasetOut]
    errors: list[str]


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int


class ConversationCreate(BaseModel):
    dataset_ids: list[str] = Field(default_factory=list, max_length=10)
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    dataset_ids: list[str] | None = Field(default=None, max_length=10)
    title: str | None = Field(default=None, min_length=1, max_length=200)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    artifacts: dict
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    dataset_ids: list
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question is empty")
        return v


class SqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=8000)
    dataset_ids: list[str] = Field(min_length=1, max_length=10)
