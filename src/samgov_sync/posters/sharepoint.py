"""SharePoint list writer."""

from __future__ import annotations

from typing import Any

from .base import Writer, fingerprint, is_closed
from ..graph_client import GraphClient


class SharePointWriter(Writer):
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_id: str,
        list_id: str,
    ):
        super().__init__()
        missing = [k for k, v in {
            "SP_TENANT_ID": tenant_id,
            "SP_CLIENT_ID": client_id,
            "SP_CLIENT_SECRET": client_secret,
            "SP_SITE_ID": site_id,
        }.items() if not v]
        if missing:
            raise ValueError(f"SharePoint requires: {', '.join(missing)}")
        self._client = GraphClient(tenant_id, client_id, client_secret)
        self._site_id = site_id
        self._list_id = list_id

    @property
    def name(self) -> str:
        return "SharePoint"

    def _load_existing(self) -> dict[str, tuple[str, str]]:
        result: dict[str, tuple[str, str]] = {}
        for item in self._client.iter_list_items(self._site_id, self._list_id):
            fields = item.get("fields", {})
            notice_id = fields.get("NoticeId")
            if not notice_id:
                continue
            stored = {k: fields.get(k, "") for k in _TRACKED_COLUMNS}
            result[notice_id] = (fingerprint(stored), item["id"])
        return result

    def _create(self, fields: dict[str, Any]) -> None:
        if not self._list_id:
            return
        self._client.create_item(self._site_id, self._list_id, fields)
        if is_closed(fields):
            self.set_closed(fields.get("NoticeId", ""), fields)

    def _update(self, backend_id: str, fields: dict[str, Any]) -> None:
        if not self._list_id:
            return
        self._client.update_item(self._site_id, self._list_id, backend_id, fields)
        if is_closed(fields):
            self.set_closed(backend_id, fields)

    def set_closed(self, notice_id: str, fields: dict[str, Any]) -> None:
        if not self._list_id or not notice_id:
            return
        try:
            self._client.update_item(
                self._site_id, self._list_id, notice_id, {"Active": "No"},
            )
        except Exception as exc:
            print(f"  [!] {notice_id}: SharePoint set_closed failed — {exc}")


_TRACKED_COLUMNS = [
    "Title", "NoticeId", "SolicitationNumber", "Department", "OfficeAddress",
    "PostedDate", "ResponseDeadline", "SetAside", "NaicsCode", "OpportunityType",
    "Active", "UiLink", "Description",
]
