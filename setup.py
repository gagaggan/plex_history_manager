"""FlaskFarm plugin entrypoint for Plex per-user watch history management."""

from .history_manager import HistoryManager

__menu = {
    'uri': __package__, 'name': 'Plex 시청기록',
    'list': [
        {'uri': 'history', 'name': '시청기록', 'list': [
            {'uri': 'home', 'name': '사용자별 기록'},
            {'uri': 'setting', 'name': '설정'},
        ]},
    ],
}

setting = {
    'filepath': __file__, 'use_db': True, 'use_default_setting': True,
    'home_module': 'history', 'menu': __menu, 'setting_menu': None,
    'default_route': 'normal',
}

from plugin import *  # noqa: E402,F401,F403

P = create_plugin_instance(setting)
P.history_manager = HistoryManager(P)

from .mod_history import ModuleHistory  # noqa: E402
P.set_module_list([ModuleHistory])
