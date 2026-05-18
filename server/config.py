import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self.database_url = os.getenv(
            'DATABASE_URL',
            'postgresql+asyncpg://postgres:postgres@localhost:5432/rdx_client_ai'
        )
        self.sync_database_url = os.getenv(
            'SYNC_DATABASE_URL',
            'postgresql://postgres:postgres@localhost:5432/rdx_client_ai'
        )
        self.rdx_auth_secret = os.getenv('RDX_AUTH_SECRET', '')
        self.rdx_main_server = os.getenv(
            'RDX_MAIN_SERVER', 'https://rdx-auth-recreate.onrender.com'
        )
        self.default_api_key = os.getenv('DEFAULT_API_KEY', '')
        self.default_model = os.getenv('DEFAULT_MODEL', 'llama-3.3-70b-versatile')
        self.api_base_url = os.getenv('API_BASE_URL', 'https://api.opencode.ai/v1')
        self.max_tokens = int(os.getenv('MAX_TOKENS', '2048'))
        self.temperature = float(os.getenv('TEMPERATURE', '0.7'))
        self.allow_user_keys = os.getenv('ALLOW_USER_KEYS', 'true').lower() == 'true'
        self.rate_limit_free = int(os.getenv('RATE_LIMIT_FREE', '50'))
        self.rate_limit_premium = int(os.getenv('RATE_LIMIT_PREMIUM', '999999'))
        self.encryption_key = os.getenv('ENCRYPTION_KEY', '')

    @property
    def is_encryption_configured(self) -> bool:
        return bool(self.encryption_key) and len(self.encryption_key) >= 32


settings = Settings()

DEFAULT_SETTINGS = {
    'api_provider': 'opencode',
    'api_base_url': 'https://api.opencode.ai/v1',
    'default_api_key': settings.default_api_key,
    'default_model': 'llama-3.3-70b-versatile',
    'max_tokens': '2048',
    'temperature': '0.7',
    'allow_user_keys': 'true',
    'rate_limit_free': '50',
    'rate_limit_premium': '999999',
}
