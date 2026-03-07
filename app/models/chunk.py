from pydantic import BaseModel


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    case_id: str
    page: int
    text: str
    chunk_index: int
    char_start: int
    char_end: int
