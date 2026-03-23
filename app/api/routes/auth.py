from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.user import User, UserCreate, UserOut
from app.services.auth_service import (
    authenticate_user,
    build_access_token,
    create_user,
    get_user_by_email,
)

router = APIRouter()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    session: Session = Depends(get_session),
):
    if get_user_by_email(session, payload.email) is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = create_user(
        session,
        email=payload.email,
        password=payload.password,
        role=payload.role,
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=build_access_token(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
