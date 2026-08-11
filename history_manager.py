"""Plex history operations with allowlisted, user-scoped deletion."""

from __future__ import annotations

import os
import re
import sqlite3
import shutil
from datetime import datetime

import requests
import json
import socket
from urllib.parse import quote
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

    def libraries(self):
        return self.client().libraries()

    @staticmethod
    def program_key(row: dict) -> str:
        return str(row.get('grandparentKey') or row.get('@grandparentKey') or row.get('grandparentTitle') or row.get('@grandparentTitle') or row.get('key') or row.get('@key') or row.get('title') or row.get('@title') or '')

    def program_groups(self, account_id, limit=5000):
        groups = {}
        for row in self.client().history(self.account_id(account_id), 0, min(int(limit), 5000)):
            key = self.program_key(row)
            if not key:
                continue
            library_id = str(row.get('librarySectionID') or row.get('@librarySectionID') or '')
            group = groups.setdefault(key, {
                'key': key,
                'title': row.get('grandparentTitle') or row.get('@grandparentTitle') or row.get('title') or row.get('@title') or key,
                'library_id': library_id,
                'library_title': '',
                'count': 0,
                'episodes': [],
            })
            group['count'] += 1
            group['episodes'].append(row)
        libraries = self.libraries()
        for group in groups.values():
            group['library_title'] = libraries.get(group['library_id'], '알 수 없는 라이브러리')
        return sorted(groups.values(), key=lambda item: str(item['title']).lower())

    def delete_program(self, account_id, program_key):
        account_id = self.account_id(account_id)
        if not program_key:
            raise ValueError('프로그램 키가 없습니다.')
        rows = self.client().history(account_id, 0, 5000)
        targets = [row for row in rows if self.program_key(row) == str(program_key)]
        for row in targets:
            value = self.row_history_id(row)
            if value is not None:
                self.client().delete_history(value)
        return len(targets)

    def _database_path(self):
        settings = self.P.ModelSetting.to_dict()
        db_path = settings.get('plex_history_plex_db_path') or ''
        if not db_path:
            try:
                with sqlite3.connect('/data/db/plex_mate.db', timeout=3) as con:
                    row = con.execute("select value from plex_mate_setting where key='base_path_db'").fetchone()
                    db_path = row[0] if row else ''
            except (OSError, sqlite3.Error):
                db_path = ''
        if db_path.startswith('/host/') and not os.path.exists(db_path):
            db_path = db_path[5:]
        if not db_path or not os.path.isfile(db_path):
            raise RuntimeError('Plex DB 경로를 찾을 수 없습니다.')
        return db_path

    @staticmethod
    def media_type_name(value):
        return {1: '영화', 2: '음악', 4: '사진', 8: 'TV', 9: '에피소드'}.get(int(value or 0), f'유형 {value}')

    def statistics(self):
        db_path = self._database_path()
        query = """SELECT s.account_id, coalesce(a.name, cast(s.account_id as text)),
                   s.metadata_type, sum(s.count), sum(s.duration), min(s.at), max(s.at), count(*)
                   FROM statistics_media s LEFT JOIN accounts a ON a.id=s.account_id
                   GROUP BY s.account_id, s.metadata_type ORDER BY max(s.at) DESC"""
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as con:
            return [{'account_id': row[0], 'account_name': row[1], 'metadata_type': row[2], 'type_name': self.media_type_name(row[2]), 'play_count': row[3] or 0, 'duration': row[4] or 0, 'first_at': row[5], 'last_at': row[6], 'row_count': row[7]} for row in con.execute(query)]

    def _docker_request(self, method, path):
        socket_path = os.environ.get('PLEX_HISTORY_DOCKER_SOCKET', '/var/run/docker.sock')
        container = self.P.ModelSetting.to_dict().get('plex_history_docker_container') or 'plex'
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(10)
            client.connect(socket_path)
            client.sendall((f'{method} /containers/{quote(str(container), safe="")}{path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n').encode())
            data = b''
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                data += chunk
        finally:
            client.close()
        header, _, body = data.partition(b'\r\n\r\n')
        status_line = header.splitlines()[0].decode('latin1') if header else ''
        status = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0
        if status >= 400:
            raise RuntimeError(body.decode('utf-8', 'replace')[:300] or f'Docker API HTTP {status}')
        return json.loads(body.decode() or '{}') if body.strip() else {}

    def plex_container_status(self):
        try:
            data = self._docker_request('GET', '/json')
            state = data.get('State', {})
            return {'available': True, 'status': state.get('Status', 'unknown'), 'running': bool(state.get('Running')), 'error': ''}
        except Exception as exc:
            return {'available': False, 'status': 'unavailable', 'running': False, 'error': str(exc)}

    def plex_container_action(self, action):
        if action not in ('start', 'stop'):
            raise ValueError('지원하지 않는 Plex 작업입니다.')
        self._docker_request('POST', f'/{action}?t=15')
        return self.plex_container_status()

    def _ensure_plex_stopped(self):
        try:
            self.client()._request('GET', '/identity')
        except requests.exceptions.ConnectionError:
            return
        except requests.exceptions.RequestException as exc:
            raise RuntimeError('Plex 상태를 확인할 수 없어 DB 삭제를 중단했습니다.') from exc
        raise RuntimeError('Plex가 실행 중입니다. Plex를 중지한 뒤 다시 시도하세요.')

    def delete_statistics(self, account_id, metadata_type=''):
        account_id = self.account_id(account_id)
        if metadata_type and not str(metadata_type).isdigit():
            raise ValueError('잘못된 미디어 유형입니다.')
        self._ensure_plex_stopped()
        db_path = self._database_path()
        backup_dir = '/data/db/plex_history_manager_backups'
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"library-{datetime.now().strftime('%Y%m%d%H%M%S')}.db")
        shutil.copy2(db_path, backup_path)
        with sqlite3.connect(db_path, timeout=10) as con:
            if metadata_type:
                cur = con.execute('DELETE FROM statistics_media WHERE account_id=? AND metadata_type=?', (account_id, int(metadata_type)))
            else:
                cur = con.execute('DELETE FROM statistics_media WHERE account_id=?', (account_id,))
            con.commit()
            return cur.rowcount, backup_path

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
