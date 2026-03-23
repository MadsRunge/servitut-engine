from uuid import UUID

from sqlmodel import Session, select

from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(session: Session, email: str) -> User | None:
    normalized = normalize_email(email)
    stmt = select(User).where(User.email == normalized)
    return session.exec(stmt).first()


def get_user_by_id(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def create_user(session: Session, email: str, password: str, role: str = "user") -> User:
    user = User(
        email=normalize_email(email),
        hashed_password=get_password_hash(password),
        role=role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(session, email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def build_access_token(user: User) -> str:
    user_id = str(user.id)
    return create_access_token({"sub": user_id, "user_id": user_id, "email": user.email})
