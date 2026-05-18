import json
import httpx
from typing import AsyncGenerator, Optional

from server.config import settings
from engine.persona import SYSTEM_PROMPT


class ChatEngine:
    def __init__(self):
        self.base_url = settings.api_base_url
        self.default_model = settings.default_model
        self.default_api_key = settings.default_api_key

    def _get_api_key(self, user_api_key: Optional[str] = None) -> str:
        if user_api_key and settings.allow_user_keys:
            return user_api_key
        return self.default_api_key

    async def chat_stream(
        self,
        messages: list,
        user_api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        api_key = self._get_api_key(user_api_key)
        model_name = model or self.default_model
        temp = temperature if temperature is not None else settings.temperature
        max_tok = max_tokens if max_tokens is not None else settings.max_tokens

        system_message = {"role": "system", "content": SYSTEM_PROMPT}
        full_messages = [system_message] + messages

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
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
        user_api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        full_response = []
        async for chunk in self.chat_stream(
            messages=messages,
            user_api_key=user_api_key,
            model=model,
        ):
            full_response.append(chunk)
        return "".join(full_response)

    async def list_models(self) -> list:
        api_key = self._get_api_key()
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    return [m["id"] for m in data.get("data", [])]
            except Exception:
                pass
        return self._get_default_models()

    def _get_default_models(self) -> list:
        return [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]
