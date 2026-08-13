from .setup import *  # noqa: F401,F403

name = 'history'


class ModuleHistory(PluginModuleBase):
    db_default = {
        'plex_history_page_size': '100',
        'plex_history_docker_container': 'plex',
        'plex_history_backup_dir': '/data/db/plex_history_manager_backups',
    }

    def __init__(self, P):
        super(ModuleHistory, self).__init__(P, name=name, first_menu='manage')

    def process_menu(self, page, req):
        try:
            if page == 'setting':
                return render_template(f'{__package__}_{name}_setting.html', arg=self.P.ModelSetting.to_dict())
            if page == 'manage':
                return render_template(
                    f'{__package__}_{name}_manage.html',
                    plex_status=self.P.history_manager.plex_container_status(),
                    arg=self.P.ModelSetting.to_dict(),
                )
            if page == 'backups':
                return render_template(
                    f'{__package__}_{name}_backups.html',
                    backups=self.P.history_manager.backup_list(),
                )
            account_id = req.args.get('account_id', '')
            if page == 'statistics':
                all_tree = self.P.history_manager.statistics_tree()
                tree = all_tree if not account_id else self.P.history_manager.statistics_tree(account_id)
                statistic_users = []
                seen_users = set()
                for row in all_tree['aggregates']:
                    if row['account_id'] not in seen_users:
                        statistic_users.append({'account_id': row['account_id'], 'title': row['account_name']})
                        seen_users.add(row['account_id'])
                for type_node in all_tree['types']:
                    for library in type_node['libraries']:
                        for item in library['items']:
                            if item['account_id'] not in seen_users:
                                statistic_users.append({'account_id': item['account_id'], 'title': item['account_name']})
                                seen_users.add(item['account_id'])
                return render_template(f'{__package__}_{name}_statistics.html', rows=tree['aggregates'], types=tree['types'], statistic_users=statistic_users, account_id=account_id)
            users = self.P.history_manager.users()
            settings = self.P.ModelSetting.to_dict()
            try:
                page_size = max(10, min(int(settings.get('plex_history_page_size') or 100), 500))
            except (TypeError, ValueError):
                page_size = 100
            history_types = self.P.history_manager.history_tree(account_id) if account_id else []
            return render_template(f'{__package__}_{name}_home.html', users=users, history_types=history_types, account_id=account_id)
        except Exception as e:
            self.P.logger.error(f'Exception:{str(e)}')
            self.P.logger.error(traceback.format_exc())
            return render_template('sample.html', title=f'{__package__}/{name}/{page}', text=str(e))

    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            if command == 'create_backup':
                backup = self.P.history_manager.create_backup()
                return jsonify({'ok': True, 'message': f'백업을 생성했습니다: {backup["name"]} ({backup["size_display"]})'})
            if command == 'delete_backup':
                if req.form.get('confirm') != 'DELETE_BACKUP':
                    return jsonify({'ok': False, 'error': '백업 삭제 확인 문구가 올바르지 않습니다.'}), 400
                name = self.P.history_manager.delete_backup(arg1)
                return jsonify({'ok': True, 'message': f'백업을 삭제했습니다: {name}'})
            if command == 'delete_guid':
                if req.form.get('confirm') != 'DELETE_GUID':
                    return jsonify({'ok': False, 'error': '항목 삭제 확인 문구가 올바르지 않습니다.'}), 400
                deleted = self.P.history_manager.delete_guid(arg1, arg2)
                return jsonify({'ok': True, 'message': f'시청기록 {deleted["views"]}건과 시청상태 {deleted["settings"]}건을 삭제했습니다.'})
            if command == 'delete_one':
                if req.form.get('confirm') != 'DELETE':
                    return jsonify({'ok': False, 'error': '확인 문구가 올바르지 않습니다.'}), 400
                deleted = self.P.history_manager.delete_one(arg1, arg2)
                return jsonify({'ok': True, 'message': f'시청기록 {deleted["views"]}건과 시청상태 {deleted["settings"]}건을 삭제했습니다.'})
            if command == 'plex_start':
                return jsonify({'ok': True, 'data': self.P.history_manager.plex_container_action('start')})
            if command == 'plex_stop':
                return jsonify({'ok': True, 'data': self.P.history_manager.plex_container_action('stop')})
            if command == 'delete_statistics':
                if req.form.get('confirm') != 'DELETE_STATISTICS':
                    return jsonify({'ok': False, 'error': '재생 통계 삭제 확인 문구가 올바르지 않습니다.'}), 400
                count, backup = self.P.history_manager.delete_statistics(arg1, arg2)
                return jsonify({'ok': True, 'message': f'{count}건의 통계를 삭제했습니다.'})
            if command == 'delete_program':
                if req.form.get('confirm') != 'DELETE_PROGRAM':
                    return jsonify({'ok': False, 'error': '프로그램 삭제 확인 문구가 올바르지 않습니다.'}), 400
                deleted = self.P.history_manager.delete_program(arg1, arg2)
                return jsonify({'ok': True, 'message': f'프로그램 시청기록 {deleted["views"]}건과 시청상태 {deleted["settings"]}건을 삭제했습니다.'})
            if command == 'delete_all_playback':
                if req.form.get('confirm') != 'DELETE_ALL_PLAYBACK':
                    return jsonify({'ok': False, 'error': '전체 시청데이터 삭제 확인 문구가 올바르지 않습니다.'}), 400
                deleted, backup = self.P.history_manager.delete_all_playback_data()
                total = sum(deleted.values())
                return jsonify({'ok': True, 'message': f'전체 시청 데이터 {total}건을 삭제했습니다.'})
            if command == 'delete_all':
                if req.form.get('confirm') != 'DELETE_ALL':
                    return jsonify({'ok': False, 'error': '전체 삭제 확인 문구가 올바르지 않습니다.'}), 400
                deleted, backup = self.P.history_manager.delete_all(arg1)
                total = sum(deleted.values())
                return jsonify({'ok': True, 'message': f'사용자 데이터 {total}건을 삭제했습니다. (시청기록 {deleted.get("metadata_item_views", 0)}건, 시청상태 {deleted.get("metadata_item_settings", 0)}건, 재생통계 {deleted.get("statistics_media", 0)}건)'})
            return jsonify({'ok': False, 'error': 'unknown command'}), 400
        except Exception as e:
            self.P.logger.error(traceback.format_exc())
            return jsonify({'ok': False, 'error': str(e)}), 400
