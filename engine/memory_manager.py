from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AIUser, AISession, AIMessage, AIMemory


class MemoryManager:
    HISTORY_LIMIT = 50
    MEMORY_SUMMARY_INTERVAL_HOURS = 24

    async def get_or_create_session(
        self,
        db: AsyncSession,
        user_id: int,
        session_token: str,
        platform: str,
        platform_user_id: Optional[str] = None,
    ) -> AISession:
        result = await db.execute(
            select(AISession).where(AISession.session_token == session_token)
        )
        session = result.scalar_one_or_none()

        if session:
            session.last_active = datetime.utcnow()
            await db.commit()
            return session

        session = AISession(
            user_id=user_id,
            session_token=session_token,
            platform=platform,
            platform_user_id=platform_user_id,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def save_message(
        self,
        db: AsyncSession,
        session: AISession,
        role: str,
        content: str,
        platform: str,
        model_used: Optional[str] = None,
        tokens_used: int = 0,
    ) -> AIMessage:
        message = AIMessage(
            session_id=session.id,
            role=role,
            content=content,
            platform=platform,
            model_used=model_used,
            tokens_used=tokens_used,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message

    async def get_recent_history(
        self,
        db: AsyncSession,
        user_id: int,
        limit: int = 10,
        platform: Optional[str] = None,
    ) -> list[dict]:
        query = (
            select(AIMessage)
            .join(AISession)
            .where(AISession.user_id == user_id, AISession.is_active == True)
        )
        if platform:
            query = query.where(AIMessage.platform == platform)

        query = query.order_by(AIMessage.created_at.desc()).limit(limit)
        result = await db.execute(query)
        messages = result.scalars().all()

        return [
            {"role": m.role, "content": m.content, "platform": m.platform}
            for m in reversed(messages)
        ]

    async def get_full_history(
        self,
        db: AsyncSession,
        user_id: int,
        platform: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        query = (
            select(AIMessage)
            .join(AISession)
            .where(AISession.user_id == user_id, AISession.is_active == True)
        )
        if platform:
            query = query.where(AIMessage.platform == platform)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar()

        query = query.order_by(AIMessage.created_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        messages = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "platform": m.platform,
                    "model_used": m.model_used,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in reversed(messages)
            ],
        }

    async def clear_session(
        self, db: AsyncSession, session_token: str
    ) -> bool:
        result = await db.execute(
            select(AISession).where(AISession.session_token == session_token)
        )
        session = result.scalar_one_or_none()
        if not session:
            return False

        await db.execute(
            delete(AIMessage).where(AIMessage.session_id == session.id)
        )
        session.is_active = False
        await db.commit()
        return True

    async def save_memory(
        self, db: AsyncSession, user_id: int, summary: str
    ) -> AIMemory:
        memory = AIMemory(user_id=user_id, summary=summary)
        db.add(memory)
        await db.commit()
        await db.refresh(memory)
        return memory

    async def get_memories(
        self, db: AsyncSession, user_id: int, limit: int = 5
    ) -> list[dict]:
        result = await db.execute(
            select(AIMemory)
            .where(AIMemory.user_id == user_id)
            .order_by(AIMemory.created_at.desc())
            .limit(limit)
        )
        memories = result.scalars().all()
        return [
            {
                "id": m.id,
                "summary": m.summary,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ]

    async def get_usage_stats(
        self, db: AsyncSession, user_id: int, since: Optional[datetime] = None
    ) -> dict:
        if not since:
            since = datetime.utcnow() - timedelta(days=1)

        result = await db.execute(
            select(func.count(), func.coalesce(func.sum(AIMessage.tokens_used), 0))
            .select_from(AIMessage)
            .join(AISession)
            .where(
                AISession.user_id == user_id,
                AIMessage.role == 'user',
                AIMessage.created_at >= since,
            )
        )
        count, tokens = result.one()
        return {
            "messages_count": count,
            "tokens_used": tokens,
            "since": since.isoformat(),
        }


memory_manager = MemoryManager()
