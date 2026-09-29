"""Shared list-response pieces: `{"data": [...], "meta": {"total", "limit", "offset"}}`."""

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

MAX_PAGE_SIZE = 100

Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
