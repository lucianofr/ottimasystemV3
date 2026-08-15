"""Schemas de tags OPC (RF-203): nome lógico, node_id, direção, tipo, EU e descrição."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["r", "w"]
DataType = Literal["float", "int", "bool"]


class TagCreate(BaseModel):
    connection_id: int
    name: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    direction: Direction
    data_type: DataType
    eu: str = ""
    description: str = ""


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    node_id: str | None = Field(default=None, min_length=1)
    direction: Direction | None = None
    data_type: DataType | None = None
    eu: str | None = None
    description: str | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    connection_id: int | None
    name: str
    node_id: str | None
    project_id: int | None
    direction: Direction
    data_type: DataType
    eu: str
    description: str
    created_at: datetime
    updated_at: datetime
