"""Microsoft Graph API client for SharePoint list operations."""

from __future__ import annotations

from typing import Any, Iterator, Optional

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self._app = msal.ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )

    def token(self) -> str:
        result = self._app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise RuntimeError(
                f"Microsoft auth failed: {result.get('error_description', result)}"
            )
        return result["access_token"]

    def _headers(self) -> dict[str, Any]:
        return {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------

    def get_site_id(self, hostname: str, site_path: str) -> str:
        """
        Resolve a human-readable site to its Graph site ID.

        hostname  = "contoso.sharepoint.com"
        site_path = "/sites/MySite"
        """
        url = f"{GRAPH_BASE}/sites/{hostname}:{site_path}"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()["id"]

    def list_lists(self, site_id: str) -> list[dict[str, Any]]:
        """Return all lists on a site (id + displayName)."""
        url = f"{GRAPH_BASE}/sites/{site_id}/lists?$select=id,displayName"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("value", [])

    # ------------------------------------------------------------------
    # List item operations
    # ------------------------------------------------------------------

    def iter_list_items(self, site_id: str, list_id: str) -> Iterator[dict[str, Any]]:
        """Yield every item in a SharePoint list (handles paging)."""
        url = (
            f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
            "?expand=fields&$top=999"
        )
        while url:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            data = resp.json()
            yield from data.get("value", [])
            url = data.get("@odata.nextLink")

    def create_item(self, site_id: str, list_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items"
        resp = requests.post(
            url, headers=self._headers(), json={"fields": fields}, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def update_item(
        self, site_id: str, list_id: str, item_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
        resp = requests.patch(url, headers=self._headers(), json=fields, timeout=30)
        resp.raise_for_status()
        return resp.json()
