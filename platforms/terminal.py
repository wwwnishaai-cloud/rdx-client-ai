import asyncio
import uuid
import httpx
from typing import Optional

AI_SERVER_URL = "http://localhost:8001"


class TerminalClient:
    def __init__(self, server_url: str = AI_SERVER_URL):
        self.server_url = server_url
        self.session_token = None
        self.auth_token = None
        self.api_key = None
        self.model = None

    def set_auth(self, token: str):
        self.auth_token = token

    def set_api_key(self, key: str):
        self.api_key = key

    def set_model(self, model: str):
        self.model = model

    async def send_message(self, message: str) -> str:
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        payload = {
            "message": message,
            "platform": "terminal",
            "session_token": self.session_token or uuid.uuid4().hex,
        }
        if self.api_key:
            payload["user_api_key"] = self.api_key
        if self.model:
            payload["model"] = self.model

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{self.server_url}/api/chat",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    return f"Error: {error.decode()}"

                full = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        import json as j
                        try:
                            parsed = j.loads(data)
                            if parsed.get("done"):
                                self.session_token = parsed.get("session_token")
                                continue
                            content = parsed.get("content", "")
                            full += content
                            print(content, end="", flush=True)
                        except j.JSONDecodeError:
                            pass
                print()
                return full

    async def get_history(self, platform: Optional[str] = None) -> list:
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        url = f"{self.server_url}/api/history"
        if platform:
            url += f"/{platform}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("messages", [])
            return []

    async def switch_model(self, model: str) -> dict:
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/api/model/switch",
                headers=headers,
                json={"model": model},
            )
            if response.status_code == 200:
                self.model = model
            return response.json()

    async def clear_session(self) -> bool:
        if not self.session_token:
            return False
        headers = {"Authorization": f"Bearer {self.auth_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.server_url}/api/session/{self.session_token}",
                headers=headers,
            )
            if response.status_code == 200:
                self.session_token = None
                return True
            return False


terminal_client = TerminalClient()
