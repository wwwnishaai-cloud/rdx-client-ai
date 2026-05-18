from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from server.config import settings
from database.models import Base


async_engine = create_async_engine(settings.database_url, echo=False, pool_size=10)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[AI-DB] Database tables created/verified.")

    async with async_engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('api_provider', 'opencode')
            ON CONFLICT (setting_key) DO NOTHING;
        """))
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('api_base_url', :url)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"url": settings.api_base_url})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('default_api_key', :key)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"key": settings.default_api_key})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('default_model', :model)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"model": settings.default_model})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('max_tokens', :val)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"val": str(settings.max_tokens)})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('temperature', :val)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"val": str(settings.temperature)})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('allow_user_keys', :val)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"val": "true" if settings.allow_user_keys else "false"})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('rate_limit_free', :val)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"val": str(settings.rate_limit_free)})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('rate_limit_premium', :val)
            ON CONFLICT (setting_key) DO NOTHING;
        """), {"val": str(settings.rate_limit_premium)})
        await conn.execute(text("""
            INSERT INTO ai_settings (setting_key, setting_value)
            VALUES ('force_user_key', 'true')
            ON CONFLICT (setting_key) DO NOTHING;
        """))
    print("[AI-DB] Default settings inserted.")
