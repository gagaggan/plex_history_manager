from .setup import *  # noqa: F401,F403

name = 'history'


class ModuleHistory(PluginModuleBase):
    db_default = {
        'plex_history_plex_url': 'http://127.0.0.1:32400',
        'plex_history_plex_token': '',
        'plex_history_page_size': '100',
    }

    def __init__(self, P):
        super(ModuleHistory, self).__init__(P, name=name, first_menu='home')

    def process_menu(self, page, req):
        try:
            if page == 'setting':
                return render_template(f'{__package__}_{name}_setting.html', arg=self.P.ModelSetting.to_dict())
            account_id = req.args.get('account_id', '')
            users = self.P.history_manager.users()
            rows = self.P.history_manager.history(account_id, 0, self.P.ModelSetting.get_int('plex_history_page_size') or 100) if account_id else []
            return render_template(f'{__package__}_{name}_home.html', users=users, rows=rows, account_id=account_id)
        except Exception as e:
            self.P.logger.error(f'Exception:{str(e)}')
            self.P.logger.error(traceback.format_exc())
            return render_template('sample.html', title=f'{__package__}/{name}/{page}', text=str(e))

    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            if command == 'delete_one':
                if req.form.get('confirm') != 'DELETE':
                    return jsonify({'ok': False, 'error': '확인 문구가 올바르지 않습니다.'}), 400
                self.P.history_manager.delete_one(arg1, arg2)
                return jsonify({'ok': True, 'message': '시청기록을 삭제했습니다.'})
            if command == 'delete_all':
                if req.form.get('confirm') != 'DELETE_ALL':
                    return jsonify({'ok': False, 'error': '전체 삭제 확인 문구가 올바르지 않습니다.'}), 400
                count = self.P.history_manager.delete_all(arg1)
                return jsonify({'ok': True, 'message': f'{count}건을 삭제했습니다.'})
            return jsonify({'ok': False, 'error': 'unknown command'}), 400
        except Exception as e:
            self.P.logger.error(traceback.format_exc())
            return jsonify({'ok': False, 'error': str(e)}), 400
