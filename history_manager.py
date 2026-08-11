"""Plex history operations with allowlisted, user-scoped deletion."""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

from .plex_client import PlexClient


class HistoryManager:
    def __init__(self, plugin):
        self.P = plugin
        self.logger = plugin.logger

    def _plex_mate_settings(self) -> tuple[str, str]:
        db_path = os.environ.get("PLEX_HISTORY_PLEX_MATE_DB", "/data/db/plex_mate.db")
        try:
            with sqlite3.connect(db_path, timeout=3) as con:
                values = dict(con.execute(
                    "select key, value from plex_mate_setting where key in (?, ?)",
                    ("base_url", "base_token"),
                ).fetchall())
            return str(values.get("base_url", "")).strip(), str(values.get("base_token", "")).strip()
        except (OSError, sqlite3.Error):
            return "", ""

    def client(self) -> PlexClient:
        settings = self.P.ModelSetting.to_dict()
        url = (settings.get("plex_history_plex_url") or "").strip()
        token = (settings.get("plex_history_plex_token") or "").strip()
        if not url or not token:
            url, token = self._plex_mate_settings()
        if not url or not token:
            raise RuntimeError("Plex 주소와 토큰을 먼저 설정하세요. plex_mate 설정도 자동으로 확인합니다.")
        return PlexClient(url, token)

    @staticmethod
    def account_id(value: Any) -> int:
        if not re.fullmatch(r"[0-9]+", str(value or "")):
            raise ValueError("잘못된 사용자 ID입니다.")
        return int(value)

    @staticmethod
    def history_id(value: Any) -> int:
        value = str(value or "").rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[0-9]+", value):
            raise ValueError("잘못된 기록 ID입니다.")
        return int(value)

    @classmethod
    def row_history_id(cls, row: dict) -> int | None:
        value = row.get("historyKey") or row.get("@historyKey") or row.get("id") or row.get("@id")
        if not value:
            return None
        try:
            return cls.history_id(value)
        except ValueError:
            return None

    def users(self):
        return self.client().users()

    def history(self, account_id, start=0, size=100):
        return self.client().history(self.account_id(account_id), int(start), min(int(size), 500))

    def delete_one(self, account_id, history_id):
        account_id = self.account_id(account_id)
        history_id = self.history_id(history_id)
        rows = self.history(account_id, 0, 500)
        if not any(self.row_history_id(row) == history_id for row in rows):
            raise ValueError("선택한 사용자의 기록이 아니거나 이미 삭제되었습니다.")
        self.client().delete_history(history_id)

    def delete_all(self, account_id):
        account_id = self.account_id(account_id)
        client = self.client()
        deleted = 0
        while True:
            rows = client.history(account_id, 0, 500)
            if not rows:
                break
            ids = [self.row_history_id(row) for row in rows]
            ids = [value for value in ids if value is not None]
            for value in ids:
                client.delete_history(value)
                deleted += 1
            if len(ids) == 0:
                break
            if len(rows) < 500:
                break
        return deleted
