import os
import aiohttp
import httpx

# 1. Patch aiohttp to bypass SSL verification
original_aio_init = aiohttp.TCPConnector.__init__
def patched_aio_init(self, *args, **kwargs):
    if not any(k in kwargs for k in ['ssl', 'ssl_context', 'verify_ssl', 'fingerprint']):
        kwargs['ssl'] = False
    original_aio_init(self, *args, **kwargs)
aiohttp.TCPConnector.__init__ = patched_aio_init

# 2. Patch httpx to bypass SSL verification
original_client_init = httpx.Client.__init__
def patched_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    original_client_init(self, *args, **kwargs)
httpx.Client.__init__ = patched_client_init

original_async_init = httpx.AsyncClient.__init__
def patched_async_init(self, *args, **kwargs):
    kwargs['verify'] = False
    original_async_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = patched_async_init

from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")  # Gemini API key only

@dataclass
class AgentConfig:
    # Reads model from environment GEMINI_MODEL. Default gemini-2.5-flash.
    model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mcp_server_port: int = 8090
    max_iterations: int = 3
    pii_redaction_enabled: bool = True
    injection_detection_enabled: bool = True

config = AgentConfig()
