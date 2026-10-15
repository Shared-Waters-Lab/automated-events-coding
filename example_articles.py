from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, Field


class Output(BaseModel):

    type: str
    entity_pair: str
    irmo: str
    coder_summary: str

class Article(BaseModel):

    name: str
    text: str
    num_basin: int
    num_event: int
    num_action: int
    output: Output

SIMPLE_COMMON1 = Article(
    name="ETOS_194 (QC_010)",
    text="""\

    """.strip()
)