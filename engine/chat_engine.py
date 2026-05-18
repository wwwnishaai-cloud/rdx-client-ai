import json
import time
import httpx
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from server.config import settings
from engine.persona import SYSTEM_PROMPT
from database.models import AISetting


class UserAPIKeyRequiredError(Exception):
    pass


class ChatEngine:
    def __init__(self):
        self._cache = None
        self._cache_time = 0
        self._cache_ttl = 300

    async def _get_settings_from_db(self, db: Optional[AsyncSession] = None) -> dict:
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        db_settings = {}
        if db:
            try:
                result = await db.execute(
                    select(AISetting).where(
                        AISetting.setting_key.in_([
                            'api_base_url', 'default_api_key', 'default_model',
                            'max_tokens', 'temperature', 'allow_user_keys',
                            'rate_limit_free', 'rate_limit_premium',
                            'force_user_key',
                        ])
                    )
                )
                db_settings = {row.setting_key: row.setting_value for row in result.scalars().all()}
            except Exception:
                pass

        resolved = {
            'api_base_url': db_settings.get('api_base_url', settings.api_base_url),
            'default_api_key': db_settings.get('default_api_key', settings.default_api_key),
            'default_model': db_settings.get('default_model', settings.default_model),
            'max_tokens': int(db_settings.get('max_tokens', settings.max_tokens)),
            'temperature': float(db_settings.get('temperature', settings.temperature)),
            'allow_user_keys': db_settings.get('allow_user_keys', 'true').lower() == 'true',
            'force_user_key': db_settings.get('force_user_key', 'false').lower() == 'true',
        }

        self._cache = resolved
        self._cache_time = now
        return resolved

    def invalidate_cache(self):
        self._cache = None
        self._cache_time = 0

    def _get_api_key(self, db_settings: dict, user_api_key: Optional[str] = None) -> str:
        if user_api_key and db_settings.get('allow_user_keys', True):
            return user_api_key
        if db_settings.get('force_user_key', False):
            raise UserAPIKeyRequiredError(
                "API key required. Set your API key first: /api sk-your-key-here\n"
                "Get your free API key at: https://opencode.ai"
            )
        return db_settings.get('default_api_key', '')

    async def chat_stream(
        self,
        messages: list,
        db: Optional[AsyncSession] = None,
        user_api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        db_settings = await self._get_settings_from_db(db)
        api_key = self._get_api_key(db_settings, user_api_key)
        model_name = model or db_settings['default_model']
        temp = temperature if temperature is not None else db_settings['temperature']
        max_tok = max_tokens if max_tokens is not None else db_settings['max_tokens']
        base_url = db_settings['api_base_url']

        system_message = {"role": "system", "content": SYSTEM_PROMPT}
        full_messages = [system_message] + messages

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_name,
                    "messages": full_messages,
                    "temperature": temp,
                    "max_tokens": max_tok,
                    "stream": True,
                },
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield f"ERROR: API returned {response.status_code}: {error_text.decode()}"
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def chat(
        self,
        messages: list,
        db: Optional[AsyncSession] = None,
        user_api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        full_response = []
        async for chunk in self.chat_stream(
            messages=messages,
            db=db,
            user_api_key=user_api_key,
            model=model,
        ):
            full_response.append(chunk)
        return "".join(full_response)

    async def list_models(self, db: Optional[AsyncSession] = None, api_base_url: Optional[str] = None, api_key: Optional[str] = None) -> list:
        try:
            db_settings = await self._get_settings_from_db(db)
            resolved_key = api_key if api_key else self._get_api_key(db_settings)
            resolved_url = api_base_url if api_base_url else db_settings['api_base_url']

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{resolved_url}/models",
                    headers={"Authorization": f"Bearer {resolved_key}"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    return [m["id"] for m in data.get("data", [])]
                else:
                    print(f"[RDX CLIENT AI] Models API returned status {response.status_code}: {response.text}")
        except UserAPIKeyRequiredError:
            # Expected warning when database or API key is not yet configured, silence it
            pass
        except Exception as e:
            print(f"[RDX CLIENT AI] Unexpected error listing models: {e}")
            pass
        return self._get_default_models()

    def _get_default_models(self) -> list:
        return [
            "llama-3.3-70b-versatile",
            "gpt-4o-mini",
            "deepseek-reasoner",
            "gemini-2.0-flash",
        ]
