from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.security import decode_access_token
from app.db.database import get_session
from app.models.user import User
from app.services.auth_service import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        raw_user_id = payload.get("user_id") or payload.get("sub")
        if raw_user_id is None:
            raise ValueError("Token is missing user identity")
        user_id = UUID(str(raw_user_id))
    except (ValueError, TypeError):
        raise unauthorized

    user = get_user_by_id(session, user_id)
    if user is None:
        raise unauthorized

    return user
