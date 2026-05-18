import json
import time
import httpx
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from server.config import settings
from engine.persona import SYSTEM_PROMPT
from database.models import AISetting


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_stats",
            "description": "Fetch overall stats including total users, active apps, and generated licenses."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_apps",
            "description": "Fetch a list of all applications owned by the user."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_licenses",
            "description": "Fetch the generated license keys for the user."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_users",
            "description": "Fetch the users/members registered in the user's apps."
        }
    }
]

async def execute_tool(tool_name: str, jwt_token: str) -> str:
    if not jwt_token:
        return json.dumps({"error": "Unauthorized. No token."})
    base_url = settings.rdx_main_server
    headers = {"Authorization": f"Bearer {jwt_token}"}
    endpoints = {
        "get_dashboard_stats": "/rdx/api/stats",
        "get_apps": "/rdx/api/apps",
        "get_licenses": "/rdx/api/licenses",
        "get_users": "/rdx/api/users"
    }
    if tool_name not in endpoints:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{base_url}{endpoints[tool_name]}", headers=headers)
            return resp.text
        except Exception as e:
            return json.dumps({"error": str(e)})


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
        jwt_token: Optional[str] = None,
        allow_tools: bool = True
    ) -> AsyncGenerator[str, None]:
        db_settings = await self._get_settings_from_db(db)
        api_key = self._get_api_key(db_settings, user_api_key)
        model_name = model or db_settings['default_model']
        temp = temperature if temperature is not None else db_settings['temperature']
        max_tok = max_tokens if max_tokens is not None else db_settings['max_tokens']
        base_url = db_settings['api_base_url']

        # Filter out system messages from the passed messages just in case, to avoid duplication
        filtered_messages = [m for m in messages if m.get("role") != "system"]
        system_message = {"role": "system", "content": SYSTEM_PROMPT}
        full_messages = [system_message] + filtered_messages

        json_payload = {
            "model": model_name,
            "messages": full_messages,
            "temperature": temp,
            "max_tokens": max_tok,
            "stream": True,
        }
        
        if allow_tools and jwt_token:
            json_payload["tools"] = TOOLS

        tool_calls_accumulator = {}

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=json_payload,
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
                        
                        # Handle text content
                        content = delta.get("content", "")
                        if content:
                            yield content
                            
                        # Handle tool calls delta
                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_accumulator:
                                    tool_calls_accumulator[idx] = {"id": tc.get("id"), "type": "function", "function": {"name": "", "arguments": ""}}
                                if "id" in tc and tc["id"]:
                                    tool_calls_accumulator[idx]["id"] = tc["id"]
                                if "function" in tc:
                                    if "name" in tc["function"] and tc["function"]["name"]:
                                        tool_calls_accumulator[idx]["function"]["name"] += tc["function"]["name"]
                                    if "arguments" in tc["function"] and tc["function"]["arguments"]:
                                        tool_calls_accumulator[idx]["function"]["arguments"] += tc["function"]["arguments"]

                    except json.JSONDecodeError:
                        continue
        
        # If tools were called, execute them and recurse
        if tool_calls_accumulator:
            tool_calls = list(tool_calls_accumulator.values())
            
            # Construct the assistant message containing the tool_calls to maintain conversation history
            assistant_message = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls
            }
            messages.append(assistant_message)
            
            for tc in tool_calls:
                t_name = tc["function"]["name"]
                t_id = tc["id"]
                yield f"\n[AI is autonomously fetching {t_name}...]\n"
                t_result = await execute_tool(t_name, jwt_token)
                
                # Truncate result if too long to prevent token overflow
                if len(t_result) > 3000:
                    t_result = t_result[:3000] + "... [TRUNCATED]"
                    
                messages.append({
                    "role": "tool",
                    "tool_call_id": t_id,
                    "name": t_name,
                    "content": t_result
                })
            
            # Call chat_stream again with the results, disable tools to prevent infinite loops on error
            async for chunk in self.chat_stream(
                messages=messages,
                db=db,
                user_api_key=user_api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                jwt_token=jwt_token,
                allow_tools=False
            ):
                yield chunk

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
