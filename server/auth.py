import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from server.config import settings
from database.models import AIUser, AISession
from database.migrations import get_session

security = HTTPBearer(auto_error=False)


async def verify_rdx_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.rdx_auth_secret,
            algorithms=['HS256']
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token expired'
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token'
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authorization header required'
        )
    return await verify_rdx_token(credentials.credentials)


async def get_or_create_ai_user(
    db: AsyncSession,
    rdx_user_id: str,
    username: str = None
) -> AIUser:
    result = await db.execute(
        select(AIUser).where(AIUser.rdx_user_id == rdx_user_id)
    )
    user = result.scalar_one_or_none()

    if user:
        if username and user.username != username:
            user.username = username
            await db.commit()
        return user

    user = AIUser(
        rdx_user_id=rdx_user_id,
        username=username or rdx_user_id
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


class OptionalAuth:
    async def __call__(self, credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            return None
        try:
            return await verify_rdx_token(credentials.credentials)
        except HTTPException:
            return None


optional_auth = OptionalAuth()
