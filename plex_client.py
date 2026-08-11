"""Small Plex HTTP API client used by the FlaskFarm plugin."""

from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
try:
    import xmltodict
except ImportError:  # XML fallback for minimal FlaskFarm environments
    xmltodict = None


@dataclass(frozen=True)
class PlexUser:
    account_id: int
    title: str
    username: str = ''


class PlexClient:
    def __init__(self, base_url: str, token: str, timeout: int = 15):
        self.base_url = base_url.rstrip('/') + '/'
        self.token = token.strip()
        self.timeout = timeout

    def _request(self, method: str, path: str, **params):
        params['X-Plex-Token'] = self.token
        params.setdefault('includeGuids', '1')
        response = requests.request(
            method, urljoin(self.base_url, path.lstrip('/')),
            params=params, headers={'Accept': 'application/json, application/xml'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _objects(response, key):
        try:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get('MediaContainer'), dict):
                data = data['MediaContainer']
            value = data.get(key, []) if isinstance(data, dict) else []
            # Some Plex endpoints return a generic Metadata array. Only use
            # it as the Video fallback; otherwise Video and Track parsing can
            # append the same Metadata rows twice.
            if not value and key == 'Video' and isinstance(data, dict):
                value = data.get('Metadata', [])
            return value if isinstance(value, list) else [value]
        except ValueError:
            if xmltodict is None:
                return []
            data = xmltodict.parse(response.text).get('MediaContainer', {})
            value = data.get(key, [])
            return value if isinstance(value, list) else ([value] if value else [])

    def users(self) -> list[PlexUser]:
        response = self._request('GET', '/accounts')
        accounts = self._objects(response, 'Directory') or self._objects(response, 'Account')
        # /accounts can contain thousands of historical account records. Keep
        # the UI focused on accounts that actually have watch history.
        try:
            history_response = self._request(
                'GET', '/status/sessions/history/all', sort='viewedAt:desc',
                **{'X-Plex-Container-Size': 5000},
            )
            history_rows = self._objects(history_response, 'Video') + self._objects(history_response, 'Track')
            active_ids = {str(row.get('accountID') or row.get('@accountID')) for row in history_rows}
            filtered = [item for item in accounts if str(item.get('id') or item.get('@id')) in active_ids]
            if filtered:
                accounts = filtered
        except requests.RequestException:
            pass
        result = []
        for item in accounts:
            account_id = item.get('id') or item.get('@id')
            if not account_id:
                continue
            title = item.get('title') or item.get('@title') or item.get('name') or item.get('@name') or item.get('username') or item.get('@username')
            username = item.get('username') or item.get('@username') or item.get('name') or item.get('@name') or ''
            result.append(PlexUser(int(account_id), html.escape(str(title or account_id)), str(username)))
        return sorted(result, key=lambda user: user.title.lower())

    def libraries(self) -> dict[str, str]:
        response = self._request('GET', '/library/sections')
        result = {}
        for item in self._objects(response, 'Directory'):
            section_id = item.get('key') or item.get('@key') or item.get('id') or item.get('@id')
            title = item.get('title') or item.get('@title') or section_id
            if section_id:
                result[str(section_id)] = str(title)
        return result

    def history(self, account_id: int, start: int = 0, size: int = 100) -> list[dict]:
        response = self._request(
            'GET', '/status/sessions/history/all', accountID=int(account_id),
            sort='viewedAt:desc', **{'X-Plex-Container-Start': start, 'X-Plex-Container-Size': size},
        )
        rows = self._objects(response, 'Video') + self._objects(response, 'Track')
        unique = []
        seen = set()
        for row in rows:
            identity = (
                row.get('historyKey') or row.get('@historyKey') or
                row.get('id') or row.get('@id') or
                row.get('key') or row.get('@key') or
                (row.get('guid') or row.get('@guid'), row.get('viewedAt') or row.get('@viewedAt'))
            )
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(row)
        return unique

    def delete_history(self, history_id: int) -> None:
        self._request('DELETE', f'/status/sessions/history/{int(history_id)}')
