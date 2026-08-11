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
        try:
            users = self.client().users()
            if users:
                return users
        except (requests.RequestException, RuntimeError):
            pass
        # The API may return no history after a bulk cleanup even though the
        # local imported database still contains views or watch settings.
        try:
            db_path = self._database_path()
            query = """SELECT a.id, coalesce(a.name, a.username, cast(a.id as text))
                       FROM accounts a
                       WHERE EXISTS (
                           SELECT 1 FROM metadata_item_views v
                           WHERE v.account_id=a.id
                       )
                       OR EXISTS (
                           SELECT 1 FROM metadata_item_settings s
                           WHERE s.account_id=a.id
                             AND (coalesce(s.view_count, 0)>0
                                  OR coalesce(s.view_offset, 0)>0
                                  OR s.last_viewed_at IS NOT NULL)
                       )
                       ORDER BY coalesce(a.name, a.username, cast(a.id as text)) COLLATE NOCASE"""
            with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as con:
                rows = con.execute(query).fetchall()
            return [
                type('PlexUserFallback', (), {
                    'account_id': row[0], 'title': str(row[1]), 'username': ''
                })
                for row in rows
            ]
        except (OSError, sqlite3.Error, RuntimeError):
            return []

    def history(self, account_id, start=0, size=100):
        rows = self.client().history(self.account_id(account_id), int(start), min(int(size), 500))
        for row in rows:
            row['_viewed_at_display'] = self.format_timestamp(row.get('viewedAt') or row.get('@viewedAt'))
        return rows

    @staticmethod
    def format_timestamp(value):
        try:
            timestamp = float(value)
            if timestamp > 100000000000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError, OverflowError, OSError):
            return str(value or '-')

    def libraries(self):
        return self.client().libraries()

    @staticmethod
    def program_key(row: dict) -> str:
        return str(row.get('grandparentKey') or row.get('@grandparentKey') or row.get('grandparentTitle') or row.get('@grandparentTitle') or row.get('key') or row.get('@key') or row.get('title') or row.get('@title') or '')

    @staticmethod
    def history_type(row):
        value = row.get('type') or row.get('@type') or row.get('metadataType') or row.get('@metadataType') or ''
        names = {'movie': 1, 'music': 2, 'track': 2, 'photo': 12, 'show': 2, 'episode': 4}
        if str(value).isdigit():
            return int(value)
        return names.get(str(value).lower(), 0)

    def history_tree(self, account_id, limit=5000):
        account_id = self.account_id(account_id)
        types = {}
        libraries = self.libraries()
        rows = self.client().history(account_id, 0, min(int(limit), 5000))
        seen_guids = {str(row.get('guid') or row.get('@guid') or '') for row in rows}
        # Imported or old Plex databases can retain watch state in
        # metadata_item_settings even when the history API no longer returns it.
        try:
            db_path = self._database_path()
            query = """SELECT s.guid, s.view_count, s.view_offset, s.last_viewed_at,
                              mi.metadata_type, mi.library_section_id, mi.title,
                              parent.title, grand.title
                       FROM metadata_item_settings s
                       LEFT JOIN metadata_items mi ON mi.guid=s.guid
                       LEFT JOIN metadata_items parent ON parent.id=mi.parent_id
                       LEFT JOIN metadata_items grand ON grand.id=parent.parent_id
                       WHERE s.account_id=?
                         AND (coalesce(s.view_count, 0)>0 OR coalesce(s.view_offset, 0)>0
                              OR s.last_viewed_at IS NOT NULL)"""
            with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as con:
                for guid, view_count, view_offset, last_viewed_at, metadata_type, library_id, title, parent_title, grand_title in con.execute(query, (account_id,)):
                    guid = str(guid or '')
                    if not guid or guid in seen_guids:
                        continue
                    seen_guids.add(guid)
                    rows.append({
                        'guid': guid, 'type': metadata_type or 0,
                        'librarySectionID': library_id or '',
                        'grandparentTitle': grand_title or parent_title or title or '',
                        'parentTitle': parent_title or '',
                        'title': title or '',
                        'viewedAt': last_viewed_at or '',
                        '_settings_only': True,
                        '_settings_view_count': view_count or 0,
                        '_settings_view_offset': view_offset or 0,
                    })
        except (OSError, sqlite3.Error, RuntimeError):
            pass
        for row in rows:
            type_id = self.history_type(row)
            type_node = types.setdefault(type_id, {
                'metadata_type': type_id,
                'type_name': self.media_type_name(type_id) if type_id else '기타',
                'libraries': [],
            })
            library_id = str(row.get('librarySectionID') or row.get('@librarySectionID') or '')
            library_name = libraries.get(library_id, '알 수 없는 라이브러리')
            library = next((item for item in type_node['libraries'] if item['name'] == library_name), None)
            if library is None:
                library = {'name': library_name, 'programs': []}
                type_node['libraries'].append(library)
            program_key = self.program_key(row)
            program_title = row.get('grandparentTitle') or row.get('@grandparentTitle') or row.get('title') or row.get('@title') or program_key
            program = next((item for item in library['programs'] if item['key'] == program_key), None)
            if program is None:
                program = {'key': program_key, 'title': program_title, 'episodes': []}
                library['programs'].append(program)
            row['_viewed_at_display'] = self.format_timestamp(row.get('viewedAt') or row.get('@viewedAt'))
            program['episodes'].append(row)
        for type_node in types.values():
            type_node['libraries'].sort(key=lambda item: item['name'].lower())
            for library in type_node['libraries']:
                library['programs'].sort(key=lambda item: item['title'].lower())
        return sorted(types.values(), key=lambda item: item['type_name'])

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
            row['_viewed_at_display'] = self.format_timestamp(row.get('viewedAt') or row.get('@viewedAt'))
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
        if not targets:
            return {'views': 0, 'settings': 0, 'backup': ''}
        return self._delete_history_rows(account_id, targets)

    def _delete_history_rows(self, account_id, targets):
        """Delete selected history rows and matching watch settings by GUID."""
        self._ensure_plex_stopped()
        db_path = self._database_path()
        backup_dir = '/data/db/plex_history_manager_backups'
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            f"library-partial-{account_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.db",
        )
        shutil.copy2(db_path, backup_path)
        guids = {
            str(row.get('guid') or row.get('@guid') or '')
            for row in targets
        }
        guids.discard('')
        history_ids = {
            self.row_history_id(row)
            for row in targets
        }
        history_ids.discard(None)
        with sqlite3.connect(db_path, timeout=10) as con:
            view_count = 0
            settings_count = 0
            if guids:
                placeholders = ','.join('?' for _ in guids)
                cur = con.execute(
                    f'DELETE FROM metadata_item_settings WHERE account_id=? AND guid IN ({placeholders})',
                    (account_id, *sorted(guids)),
                )
                settings_count = cur.rowcount
                cur = con.execute(
                    f'DELETE FROM metadata_item_views WHERE account_id=? AND guid IN ({placeholders})',
                    (account_id, *sorted(guids)),
                )
                view_count = cur.rowcount
            # Some Plex API rows expose only a history id. Remove those view
            # rows as a fallback when the id maps to the local row id.
            if history_ids and not guids:
                placeholders = ','.join('?' for _ in history_ids)
                cur = con.execute(
                    f'DELETE FROM metadata_item_views WHERE account_id=? AND id IN ({placeholders})',
                    (account_id, *sorted(history_ids)),
                )
                view_count = cur.rowcount
            con.commit()
        return {'views': view_count, 'settings': settings_count, 'backup': backup_path}

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
        return {1: '영화', 2: 'TV', 3: 'TV', 4: 'TV', 8: 'TV', 9: '에피소드', 12: '기타'}.get(int(value or 0), f'유형 {value}')

    def statistics(self):
        db_path = self._database_path()
        query = """SELECT s.account_id, coalesce(a.name, cast(s.account_id as text)),
                   s.metadata_type, sum(s.count), sum(s.duration), min(s.at), max(s.at), count(*)
                   FROM statistics_media s LEFT JOIN accounts a ON a.id=s.account_id
                   GROUP BY s.account_id, s.metadata_type ORDER BY max(s.at) DESC"""
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as con:
            return [{'account_id': row[0], 'account_name': row[1], 'metadata_type': row[2], 'type_name': self.media_type_name(row[2]), 'play_count': row[3] or 0, 'duration': row[4] or 0, 'first_at': self.format_timestamp(row[5]), 'last_at': self.format_timestamp(row[6]), 'row_count': row[7]} for row in con.execute(query)]

    def statistics_tree(self, account_id=''):
        """Build media type -> library -> program/episode details.
        statistics_media is aggregate-only and has no item or library key.
        """
        db_path = self._database_path()
        selected_account = self.account_id(account_id) if account_id else None
        aggregate_query = """SELECT s.account_id, coalesce(a.name, cast(s.account_id as text)),
                   s.metadata_type, sum(s.count), sum(s.duration), max(s.at)
                   FROM statistics_media s LEFT JOIN accounts a ON a.id=s.account_id
                   GROUP BY s.account_id, s.metadata_type ORDER BY max(s.at) DESC"""
        detail_query = """SELECT v.account_id, coalesce(a.name, cast(v.account_id as text)),
                   v.metadata_type, coalesce(ls.name, '알 수 없는 라이브러리'),
                   coalesce(v.grandparent_title, v.parent_title, v.title, '제목 없음'),
                   coalesce(v.parent_title, ''), coalesce(v.title, ''),
                   max(v.viewed_at), count(*)
                   FROM metadata_item_views v
                   LEFT JOIN accounts a ON a.id=v.account_id
                   LEFT JOIN library_sections ls ON ls.id=v.library_section_id
                   GROUP BY v.account_id, v.metadata_type, v.library_section_id,
                            v.grandparent_title, v.parent_title, v.title
                   ORDER BY max(v.viewed_at) DESC"""
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5) as con:
            aggregates = [
                {'account_id': row[0], 'account_name': row[1], 'metadata_type': row[2],
                 'type_name': self.media_type_name(row[2]), 'play_count': row[3] or 0,
                 'duration': row[4] or 0, 'last_at': self.format_timestamp(row[5])}
                for row in con.execute(aggregate_query)
            ]
            if selected_account is not None:
                aggregates = [row for row in aggregates if row['account_id'] == selected_account]
            types = {}
            for row in con.execute(detail_query):
                if selected_account is not None and row[0] != selected_account:
                    continue
                type_id = row[2]
                type_node = types.setdefault(type_id, {
                    'metadata_type': type_id, 'type_name': self.media_type_name(type_id),
                    'libraries': [],
                })
                library = next((item for item in type_node['libraries'] if item['name'] == row[3]), None)
                if library is None:
                    library = {'name': row[3], 'items': [], 'count': 0}
                    type_node['libraries'].append(library)
                library['count'] += row[8] or 0
                library['items'].append({
                    'account_id': row[0], 'account_name': row[1],
                    'program': row[4], 'parent_title': row[5], 'title': row[6],
                    'last_at': self.format_timestamp(row[7]), 'count': row[8] or 0,
                })
            return {'aggregates': aggregates, 'types': sorted(types.values(), key=lambda item: item['type_name'])}

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
        rows = self.client().history(account_id, 0, 5000)
        targets = [row for row in rows if self.row_history_id(row) == history_id]
        if not targets:
            raise ValueError("선택한 사용자의 기록이 아니거나 이미 삭제되었습니다.")
        return self._delete_history_rows(account_id, targets)

    def delete_guid(self, account_id, guid):
        account_id = self.account_id(account_id)
        guid = str(guid or '').strip()
        if not guid:
            raise ValueError('잘못된 항목 GUID입니다.')
        return self._delete_history_rows(account_id, [{'guid': guid}])

    def delete_user_data(self, account_id):
        """Delete all playback-related data for one user with a backup."""
        account_id = self.account_id(account_id)
        self._ensure_plex_stopped()
        db_path = self._database_path()
        backup_dir = '/data/db/plex_history_manager_backups'
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            f"library-user-{account_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.db",
        )
        shutil.copy2(db_path, backup_path)
        deleted = {}
        with sqlite3.connect(db_path, timeout=10) as con:
            for table in ('metadata_item_views', 'metadata_item_settings', 'statistics_media'):
                cur = con.execute(f'DELETE FROM {table} WHERE account_id=?', (account_id,))
                deleted[table] = cur.rowcount
            con.commit()
        return deleted, backup_path

    def delete_all(self, account_id):
        # Keep the existing command name used by the history page.
        deleted, backup_path = self.delete_user_data(account_id)
        return sum(deleted.values()), backup_path
