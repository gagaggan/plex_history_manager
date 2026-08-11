from .setup import *  # noqa: F401,F403

name = 'history'


class ModuleHistory(PluginModuleBase):
    db_default = {
        'plex_history_plex_url': 'http://127.0.0.1:32400',
        'plex_history_plex_token': '',
        'plex_history_page_size': '100',
        'plex_history_docker_container': 'plex',
    }

    def __init__(self, P):
        super(ModuleHistory, self).__init__(P, name=name, first_menu='home')

    def process_menu(self, page, req):
        try:
            if page == 'setting':
                return render_template(f'{__package__}_{name}_setting.html', arg=self.P.ModelSetting.to_dict())
            account_id = req.args.get('account_id', '')
            users = self.P.history_manager.users()
            if page == 'statistics':
                return render_template(f'{__package__}_{name}_statistics.html', rows=self.P.history_manager.statistics(), plex_status=self.P.history_manager.plex_container_status())
            settings = self.P.ModelSetting.to_dict()
            try:
                page_size = max(10, min(int(settings.get('plex_history_page_size') or 100), 500))
            except (TypeError, ValueError):
                page_size = 100
            rows = self.P.history_manager.history(account_id, 0, page_size) if account_id else []
            programs = self.P.history_manager.program_groups(account_id) if account_id else []
            return render_template(f'{__package__}_{name}_home.html', users=users, rows=rows, programs=programs, account_id=account_id)
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
            if command == 'plex_start':
                return jsonify({'ok': True, 'data': self.P.history_manager.plex_container_action('start')})
            if command == 'plex_stop':
                return jsonify({'ok': True, 'data': self.P.history_manager.plex_container_action('stop')})
            if command == 'delete_statistics':
                if req.form.get('confirm') != 'DELETE_STATISTICS':
                    return jsonify({'ok': False, 'error': '재생 통계 삭제 확인 문구가 올바르지 않습니다.'}), 400
                count, backup = self.P.history_manager.delete_statistics(arg1, arg2)
                return jsonify({'ok': True, 'message': f'{count}건의 통계를 삭제했습니다. 백업: {backup}'})
            if command == 'delete_program':
                if req.form.get('confirm') != 'DELETE_PROGRAM':
                    return jsonify({'ok': False, 'error': '프로그램 삭제 확인 문구가 올바르지 않습니다.'}), 400
                count = self.P.history_manager.delete_program(arg1, arg2)
                return jsonify({'ok': True, 'message': f'프로그램 시청기록 {count}건을 삭제했습니다.'})
            if command == 'delete_all':
                if req.form.get('confirm') != 'DELETE_ALL':
                    return jsonify({'ok': False, 'error': '전체 삭제 확인 문구가 올바르지 않습니다.'}), 400
                count = self.P.history_manager.delete_all(arg1)
                return jsonify({'ok': True, 'message': f'{count}건을 삭제했습니다.'})
            return jsonify({'ok': False, 'error': 'unknown command'}), 400
        except Exception as e:
            self.P.logger.error(traceback.format_exc())
            return jsonify({'ok': False, 'error': str(e)}), 400
