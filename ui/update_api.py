"""Local UI endpoints; callbacks retain ownership of VPN/window lifecycle."""
import ctypes
import os
from pathlib import Path
import sys
from flask import jsonify,request
from engine.updates import UpdateManager
from engine.paths import data_dir


def register(app, idle):
    manager=UpdateManager(data_dir())

    @app.get('/api/updates/state')
    def update_state():
        from ui import window_control
        return jsonify(**manager.snapshot(),ui_ready=window_control.ui_ready())

    @app.post('/api/updates/check')
    def update_check():
        data=request.get_json(silent=True) or {}
        return jsonify(ok=True,**manager.check(automatic=data.get('automatic') is True,channel=data.get('channel')))

    @app.post('/api/updates/download')
    def update_download():return jsonify(ok=True,**manager.download())

    @app.post('/api/updates/cancel')
    def update_cancel():manager.cancel.set();return jsonify(ok=True)

    @app.post('/api/updates/install')
    def update_install():
        if not idle():return jsonify(ok=False,error='Отключите VPN и Zapret перед установкой'),409
        if manager.snapshot()['status']!='ready':return jsonify(ok=False,error='Пакет не готов'),400
        if not getattr(sys,'frozen',False):return jsonify(ok=False,error='Установка доступна в установленной версии'),400
        updater=Path(sys.executable).parent.parent/'SadnessUpdater.exe'
        if not updater.is_file():return jsonify(ok=False,error='Компонент обновления не установлен'),400
        with manager.lock:
            # Run outside INSTALLDIR so MSI can replace the updater itself too.
            from installer.updater_main import protected_directory
            import hashlib
            import shutil
            protected=protected_directory()
            with updater.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            staged=protected/('SadnessUpdater-'+checksum+'.exe')
            if not staged.exists():
                with updater.open('rb') as src,staged.open('xb') as dst:shutil.copyfileobj(src,dst)
            with staged.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if staged.is_symlink() or actual!=checksum:return jsonify(ok=False,error='Не удалось подготовить updater'),400
            manager.state['status']='installing'
            code=ctypes.windll.shell32.ShellExecuteW(None,'runas',str(staged),None,str(protected),0)
            if code<=32:
                manager.state['status']='ready';return jsonify(ok=False,error='Запрос Windows отменён'),400
        # Окном владеет Electron: страница по shell_quit просит его выйти.
        return jsonify(ok=True, shell_quit=True)

    @app.post('/api/updates/close-for-recovery')
    def update_recovery_close():
        # Вызывает updater, а не страница: выход передаётся оболочке через
        # её длинный опрос /api/shell/show-wait.
        if not idle():return jsonify(ok=False,error='Соединение активно'),409
        from ui import window_control
        window_control.request_quit()
        return jsonify(ok=True,shell_quit=True)
    return manager
