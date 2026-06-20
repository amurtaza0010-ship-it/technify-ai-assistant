"""ERP Client — low-level async HTTP client for the external ERP system (API-key authenticated, with retries)."""
import asyncio
from typing import Any, Optional

import httpx

from config.erp_config import get_erp_config


class ERPClientError(Exception):
    """Raised when a call to the ERP system fails after all retry attempts."""


class ERPClient:
    def __init__(self):
        settings = get_erp_config()
        self.base_url = settings.ERP_API_URL.rstrip("/")
        self.api_key = settings.ERP_API_KEY
        self.timeout = settings.ERP_TIMEOUT
        self.max_retries = settings.ERP_MAX_RETRIES

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, headers=self._headers(), **kwargs)
                    response.raise_for_status()
                    return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise ERPClientError(f"ERP request failed after {self.max_retries} attempts: {method} {url} ({last_error})")

    async def get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: Optional[dict] = None) -> Any:
        return await self._request("POST", path, json=json)

    async def put(self, path: str, json: Optional[dict] = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)


# Singleton instance (reused across the app)
_erp_client: Optional[ERPClient] = None


def get_erp_client() -> ERPClient:
    global _erp_client
    if _erp_client is None:
        _erp_client = ERPClient()
    return _erp_client
