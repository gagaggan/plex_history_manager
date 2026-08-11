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
            if not value and key in ('Video', 'Track') and isinstance(data, dict):
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
        result = []
        for item in (self._objects(response, 'Directory') or self._objects(response, 'Account')):
            account_id = item.get('id') or item.get('@id')
            if not account_id:
                continue
            title = item.get('title') or item.get('@title') or item.get('username') or item.get('@username')
            username = item.get('username') or item.get('@username') or ''
            result.append(PlexUser(int(account_id), html.escape(str(title or account_id)), str(username)))
        return sorted(result, key=lambda user: user.title.lower())

    def history(self, account_id: int, start: int = 0, size: int = 100) -> list[dict]:
        response = self._request(
            'GET', '/status/sessions/history/all', accountID=int(account_id),
            sort='viewedAt:desc', **{'X-Plex-Container-Start': start, 'X-Plex-Container-Size': size},
        )
        return self._objects(response, 'Video') + self._objects(response, 'Track')

    def delete_history(self, history_id: int) -> None:
        self._request('DELETE', f'/status/sessions/history/{int(history_id)}')
