"""SharePoint list implementation of Poster."""

from __future__ import annotations

from .base import Poster, fingerprint
from ..graph_client import GraphClient


class SharePointPoster(Poster):
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_id: str,
        list_id: str,
    ):
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
            # Rebuild fingerprint from stored fields using the same keys sync writes
            stored = {k: fields.get(k, "") for k in _TRACKED_COLUMNS}
            result[notice_id] = (fingerprint(stored), item["id"])
        return result

    def _create(self, fields: dict) -> None:
        self._client.create_item(self._site_id, self._list_id, fields)

    def _update(self, backend_id: str, fields: dict) -> None:
        self._client.update_item(self._site_id, self._list_id, backend_id, fields)


# Columns that are compared for change detection — must match sync._FIELD_MAP keys
_TRACKED_COLUMNS = [
    "Title",
    "NoticeId",
    "SolicitationNumber",
    "Department",
    "OfficeAddress",
    "PostedDate",
    "ResponseDeadline",
    "SetAside",
    "NaicsCode",
    "OpportunityType",
    "Active",
    "UiLink",
    "Description",
]
