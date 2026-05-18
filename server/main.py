import uuid
import json
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from server.config import settings
from server.auth import get_current_user, get_or_create_ai_user, optional_auth
from database.migrations import init_db, get_session
from database.models import AIUser, AISetting, AIDashboardAccess, AISession, AIMessage
from engine.chat_engine import ChatEngine, UserAPIKeyRequiredError
from engine.memory_manager import memory_manager

chat_engine = ChatEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="RDX Client AI Server",
    description="Text-based multi-platform AI server for RDX Auth",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


REQUEST_MODELS = {}

RQ = type('', (), {})()
RQ.ChatRequest = type('ChatRequest', (BaseModel,), {
    'message': (str, ...),
    'session_token': (Optional[str], None),
    'platform': (str, 'terminal'),
    'platform_user_id': (Optional[str], None),
    'model': (Optional[str], None),
    'user_api_key': (Optional[str], None),
    '__annotations__': {'message': str, 'session_token': Optional[str], 'platform': str, 'platform_user_id': Optional[str], 'model': Optional[str], 'user_api_key': Optional[str]}
})

RQ.SessionRequest = type('SessionRequest', (BaseModel,), {
    'platform': (str, 'terminal'),
    'platform_user_id': (Optional[str], None),
    '__annotations__': {'platform': str, 'platform_user_id': Optional[str]}
})

RQ.KeyRequest = type('KeyRequest', (BaseModel,), {
    'api_key': (str, ...),
    '__annotations__': {'api_key': str}
})

RQ.ModelRequest = type('ModelRequest', (BaseModel,), {
    'model': (str, ...),
    '__annotations__': {'model': str}
})

RQ.ConnectDiscordRequest = type('ConnectDiscordRequest', (BaseModel,), {
    'token': (str, ...),
    '__annotations__': {'token': str}
})

RQ.ConnectTelegramRequest = type('ConnectTelegramRequest', (BaseModel,), {
    'token': (str, ...),
    '__annotations__': {'token': str}
})

RQ.AdminSettingsRequest = type('AdminSettingsRequest', (BaseModel,), {
    'settings': (dict, ...),
    '__annotations__': {'settings': dict}
})

RQ.AccessGrantRequest = type('AccessGrantRequest', (BaseModel,), {
    'rdx_user_id': (str, ...),
    'permissions': (dict, ...),
    '__annotations__': {'rdx_user_id': str, 'permissions': dict}
})




@app.post("/api/chat")
async def chat_endpoint(
    req: RQ.ChatRequest,
    request: Request,
    user: dict = Depends(optional_auth),
    db: AsyncSession = Depends(get_session),
):
    if not user:
        rdx_user_id = f"anon_{uuid.uuid4().hex[:12]}"
        user_record = await get_or_create_ai_user(db, rdx_user_id, "Anonymous")
    else:
        rdx_user_id = user.get("sub") or user.get("id")
        username = user.get("username") or user.get("name") or rdx_user_id
        user_record = await get_or_create_ai_user(db, rdx_user_id, username)

    session_token = req.session_token or uuid.uuid4().hex
    session = await memory_manager.get_or_create_session(
        db,
        user_record.id,
        session_token,
        req.platform,
        req.platform_user_id,
    )

    await memory_manager.save_message(
        db, session, "user", req.message, req.platform
    )

    history = await memory_manager.get_recent_history(
        db, user_record.id, limit=10, platform=req.platform
    )

    messages_for_ai = [
        {"role": m["role"], "content": m["content"]}
        for m in history[:-1]
    ]
    messages_for_ai.append({"role": "user", "content": req.message})

    model_used = req.model or user_record.preferred_model

    async def generate():
        full_response = ""
        try:
            async for chunk in chat_engine.chat_stream(
                messages=messages_for_ai,
                db=db,
                user_api_key=req.user_api_key or user_record.api_key_encrypted,
                model=model_used,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except UserAPIKeyRequiredError as e:
            yield f"data: {json.dumps({'error': str(e), 'code': 'API_KEY_REQUIRED'})}\n\n"
            return

        await memory_manager.save_message(
            db, session, "assistant", full_response, req.platform, model_used
        )
        yield f"data: {json.dumps({'done': True, 'session_token': session_token})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/history")
@app.get("/api/history/{platform}")
async def get_history(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    result = await memory_manager.get_full_history(
        db, user_record.id, platform, page, per_page
    )
    return {"success": True, **result}


@app.post("/api/session/new")
async def new_session(
    req: RQ.SessionRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    session_token = uuid.uuid4().hex
    await memory_manager.get_or_create_session(
        db,
        user_record.id,
        session_token,
        req.platform,
        req.platform_user_id,
    )
    return {"success": True, "session_token": session_token}


@app.delete("/api/session/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    success = await memory_manager.clear_session(db, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "message": "Session cleared"}


@app.get("/api/memory")
async def get_memory(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    memories = await memory_manager.get_memories(db, user_record.id)
    return {"success": True, "memories": memories}


@app.get("/api/status")
async def server_status():
    return {
        "status": "online",
        "version": "2.0.0",
        "server": "RDX Client AI",
        "uptime": datetime.utcnow().isoformat(),
        "api_provider": "opencode",
        "default_model": settings.default_model,
    }


@app.get("/api/models")
async def list_models(
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    db: AsyncSession = Depends(get_session),
):
    models = await chat_engine.list_models(db, api_base_url=api_base_url, api_key=api_key)
    return {"success": True, "models": models}


@app.post("/api/model/switch")
async def switch_model(
    req: RQ.ModelRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    user_record.preferred_model = req.model
    await db.commit()
    return {"success": True, "message": f"Model switched to {req.model}"}


@app.post("/api/key/set")
async def set_api_key(
    req: RQ.KeyRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    from cryptography.fernet import Fernet
    if settings.is_encryption_configured:
        key = settings.encryption_key.encode()
        if len(key) < 32:
            key = key.ljust(32, b'\0')
        key = key[:32]
        import base64
        f = Fernet(base64.urlsafe_b64encode(key))
        user_record.api_key_encrypted = f.encrypt(req.api_key.encode()).decode()
    else:
        user_record.api_key_encrypted = req.api_key
    await db.commit()
    return {"success": True, "message": "API key saved"}


@app.get("/api/key/status")
async def key_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    has_key = bool(user_record.api_key_encrypted)
    return {
        "success": True,
        "has_key": has_key,
        "model": user_record.preferred_model,
        "is_premium": user_record.is_premium,
    }


@app.get("/api/settings")
async def get_settings(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(select(AISetting))
    settings_rows = result.scalars().all()
    settings_dict = {s.setting_key: s.setting_value for s in settings_rows}
    if 'default_api_key' in settings_dict:
        settings_dict['api_key'] = settings_dict['default_api_key']
    return {
        "success": True,
        "settings": settings_dict,
    }


@app.post("/api/settings")
async def update_settings(
    req: RQ.AdminSettingsRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    for key, value in req.settings.items():
        db_key = 'default_api_key' if key == 'api_key' else key
        result = await db.execute(
            select(AISetting).where(AISetting.setting_key == db_key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.setting_value = str(value)
            setting.updated_at = datetime.utcnow()
        else:
            setting = AISetting(setting_key=db_key, setting_value=str(value))
            db.add(setting)
    await db.commit()
    chat_engine.invalidate_cache()
    return {"success": True, "message": "Settings updated"}


@app.post("/api/access/grant")
async def grant_access(
    req: RQ.AccessGrantRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    target_user_id = req.rdx_user_id
    user_record = await get_or_create_ai_user(db, target_user_id)
    result = await db.execute(
        select(AIDashboardAccess).where(
            AIDashboardAccess.user_id == user_record.id
        )
    )
    access = result.scalar_one_or_none()
    if access:
        for key, value in req.permissions.items():
            if hasattr(access, key):
                setattr(access, key, value)
        access.updated_at = datetime.utcnow()
    else:
        access = AIDashboardAccess(
            user_id=user_record.id,
            **{k: v for k, v in req.permissions.items() if hasattr(AIDashboardAccess, k)},
        )
        db.add(access)
    await db.commit()
    return {"success": True, "message": "Access granted"}

@app.get("/api/usage")
async def get_usage(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    rdx_user_id = user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, rdx_user_id)
    stats = await memory_manager.get_usage_stats(db, user_record.id)
    return {"success": True, **stats}


@app.post("/api/connect/discord")
async def connect_discord(
    req: RQ.ConnectDiscordRequest,
    user: dict = Depends(get_current_user),
):
    from platforms.discord_bot import register_bot
    success, msg = await register_bot(user.get("sub"), req.token)
    return {"success": success, "message": msg}


@app.post("/api/connect/telegram")
async def connect_telegram(
    req: RQ.ConnectTelegramRequest,
    user: dict = Depends(get_current_user),
):
    from platforms.telegram_bot import register_bot
    success, msg = await register_bot(user.get("sub"), req.token)
    return {"success": success, "message": msg}


# ─── ADMIN ENDPOINTS ─────────────────────────────────────────────


@app.get("/api/admin/users")
async def admin_get_users(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(select(AIUser).order_by(AIUser.created_at.desc()))
    all_users = result.scalars().all()

    users_data = []
    for u in all_users:
        last_session = await db.execute(
            select(AISession)
            .where(AISession.user_id == u.id, AISession.is_active == True)
            .order_by(AISession.last_active.desc())
            .limit(1)
        )
        last_sesh = last_session.scalar_one_or_none()

        msg_count = await db.execute(
            select(func.count())
            .select_from(AIMessage)
            .join(AISession)
            .where(
                AISession.user_id == u.id,
                AIMessage.role == 'user',
                AIMessage.created_at >= today_start,
            )
        )
        messages_today = msg_count.scalar() or 0

        access_row = await db.execute(
            select(AIDashboardAccess).where(AIDashboardAccess.user_id == u.id)
        )
        access = access_row.scalar_one_or_none()

        users_data.append({
            "id": u.rdx_user_id,
            "username": u.username or u.rdx_user_id,
            "platform": last_sesh.platform if last_sesh else "None",
            "messages_today": messages_today,
            "api_key_status": "Custom" if u.api_key_encrypted else "Default",
            "premium_status": "Premium" if u.is_premium else "Free",
            "access_level": {
                "can_manage_licenses": access.can_manage_licenses if access else False,
                "can_view_analytics": access.can_view_analytics if access else False,
                "can_manage_billing": access.can_manage_billing if access else False,
                "can_manage_hwid": access.can_manage_hwid if access else False,
                "can_manage_security": access.can_manage_security if access else False,
            } if access else {
                "can_manage_licenses": False,
                "can_view_analytics": False,
                "can_manage_billing": False,
                "can_manage_hwid": False,
                "can_manage_security": False,
            },
        })

    return {"success": True, "users": users_data}


@app.get("/api/admin/stats")
async def admin_get_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    active_users = await db.execute(
        select(func.count(func.distinct(AISession.user_id)))
        .where(AISession.last_active >= today_start, AISession.is_active == True)
    )
    active_users_count = active_users.scalar() or 0

    messages_today = await db.execute(
        select(func.count())
        .select_from(AIMessage)
        .where(AIMessage.created_at >= today_start)
    )
    messages_today_count = messages_today.scalar() or 0

    api_health = "OK"
    try:
        await chat_engine.list_models(db)
    except Exception:
        api_health = "FAIL"

    return {
        "success": True,
        "status": "online",
        "active_users": active_users_count,
        "messages_today": messages_today_count,
        "api_health": api_health,
        "uptime": "99.9%",
    }


@app.get("/api/access")
async def get_access(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    rdx_user_id: Optional[str] = Query(None),
):
    target_user_id = rdx_user_id or user.get("sub") or user.get("id")
    user_record = await get_or_create_ai_user(db, target_user_id)
    result = await db.execute(
        select(AIDashboardAccess).where(
            AIDashboardAccess.user_id == user_record.id
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        return {
            "success": True,
            "access": {
                "can_manage_licenses": False,
                "can_view_analytics": False,
                "can_manage_billing": False,
                "can_manage_hwid": False,
                "can_manage_security": False,
            },
        }
    return {
        "success": True,
        "access": {
            "can_manage_licenses": access.can_manage_licenses,
            "can_view_analytics": access.can_view_analytics,
            "can_manage_billing": access.can_manage_billing,
            "can_manage_hwid": access.can_manage_hwid,
            "can_manage_security": access.can_manage_security,
        },
    }
