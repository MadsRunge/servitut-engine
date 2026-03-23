from uuid import UUID, uuid4

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True, nullable=False)
    email: str = Field(index=True, unique=True, nullable=False)
    hashed_password: str
    role: str = Field(default="user", nullable=False)


class UserCreate(SQLModel):
    email: str
    password: str
    role: str = "user"


class UserOut(SQLModel):
    id: UUID
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)
