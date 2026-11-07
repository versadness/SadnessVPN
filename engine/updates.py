"""One startup check per process; explicit checks/downloads run in daemon workers."""
import copy
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from engine import update_policy as policy
from engine.app_meta import APP_VERSION
from engine.json_store import atomic_write_json
from engine.update_manifest import MAX_MANIFEST,parse,verify,safe_url,select_package,verify_file,version


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Перенаправление — только по HTTPS на CDN GitHub (подписанные ссылки с query)."""
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.hostname not in tuple(getattr(policy, 'REDIRECT_HOSTS', ())) + tuple(policy.ALLOWED_HOSTS)):
            raise ValueError('Перенаправление обновлений запрещено')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    safe_url(url,policy.ALLOWED_HOSTS)
    opener=urllib.request.build_opener(NoRedirect())
    return opener.open(urllib.request.Request(url,headers={'User-Agent':'SadnessVPN-Updater/'+APP_VERSION}),timeout=15)


class UpdateManager:
    def __init__(self, directory):
        self.directory=Path(directory)/'updates'
        self.lock=threading.RLock();self.cancel=threading.Event();self.startup_checked=False
        self.manifest=None;self.package=None;self.path=None
        self.state=dict(status='idle',version=APP_VERSION,channel='beta',progress=0,notes=[],message='Проверка ещё не выполнялась',checked_at=None)
        try:
            channel=json.loads((self.directory/'preferences.json').read_text())['channel']
            if channel in {'stable','beta'}:self.state['channel']=channel
        except (OSError,ValueError,KeyError,TypeError):pass
        self.previous_result=None
        self._read_result()

    def _read_result(self):
        try:
            result=Path(os.environ.get('ProgramData','C:/ProgramData'))/'SadnessVPN-Update'/'result.json'
            data=json.loads(result.read_text(encoding='utf-8'))
            if isinstance(data,dict):self.previous_result=data
        except (OSError,ValueError):pass

    def snapshot(self):
        with self.lock:
            self._read_result()
            result=self.previous_result or {}
            count=result.get('failure_count',0)
            suppressed=(result.get('version')==self.state.get('available_version')
                        and result.get('ok') is False and type(count) is int and count>=3)
            return copy.deepcopy({**self.state,'last_update':self.previous_result,'suppress_notice':suppressed,
                                  'can_download':bool(self.package) and self.state['status'] in {'available','error','cancelled'}})

    def change(self, **values):
        with self.lock:self.state.update(values)

    def check(self, automatic=False, channel=None):
        with self.lock:
            if automatic and self.startup_checked:return self.snapshot()
            if self.state['status'] in {'checking','downloading','installing'}:return self.snapshot()
            if automatic:self.startup_checked=True
            if channel is not None:
                if not isinstance(channel,str) or channel not in {'beta','stable'}:raise ValueError('Неизвестный канал обновлений')
                self.state['channel']=channel
                self.directory.mkdir(parents=True,exist_ok=True)
                atomic_write_json(str(self.directory/'preferences.json'),{'channel':channel})
            self.path=None;self.manifest=None;self.package=None
            self.state.update(status='checking',message='Проверка обновлений…',progress=0,
                              available_version=None,notes=[],size=0,published_at='')
            threading.Thread(target=self._check,daemon=True).start()
            return self.snapshot()

    def _check(self):
        try:
            if not policy.MANIFEST_BASE or not policy.PUBLIC_KEY_BASE64:
                self.change(status='unconfigured',message='Сервер обновлений ещё не настроен');return
            channel=self.state['channel']
            with fetch(policy.MANIFEST_BASE.rstrip('/')+'/'+channel+'.json') as response:
                data=verify(parse(response.read(MAX_MANIFEST+1)),policy.PUBLIC_KEY_BASE64,policy.ALLOWED_HOSTS,channel)
            package=select_package(data,APP_VERSION)
            with self.lock:self.manifest=data;self.package=package
            incompatible=not package and version(data['version'])>version(APP_VERSION)
            full=data.get('full')
            self.change(status='available' if package else ('incompatible' if incompatible else 'current'),available_version=data['version'],notes=data.get('notes',[]),
                        size=package['size'] if package else 0,published_at=data.get('published_at',''),
                        recovery_size=full['size'] if full and package and package!=full else 0,
                        message='Доступна новая версия' if package else ('Для вашей версии нет совместимого патча. Получите новый установщик у владельца.' if incompatible else 'Установлена актуальная версия'))
        except urllib.error.HTTPError as exc:
            self.change(status='unpublished' if exc.code==404 else 'error',message='Сервер подключён. В этом канале пока нет опубликованного релиза.' if exc.code==404 else 'Сервер обновлений временно недоступен.')
        except Exception:
            self.change(status='error',message='Не удалось проверить обновления. Проверьте соединение и доверие к серверу.')
        finally:self.change(checked_at=int(time.time()))

    def download(self):
        with self.lock:
            if not self.package or self.state['status'] not in {'available','error','cancelled'}:raise ValueError('Сначала проверьте обновления')
            self.cancel.clear();self.state.update(status='downloading',progress=0,message='Скачивание обновления…')
            threading.Thread(target=self._download,daemon=True).start()
            return self.snapshot()

    def _download(self):
        temporary=None
        try:
            package=self.package;self.directory.mkdir(parents=True,exist_ok=True)
            extension=Path(urlsplit(package['url']).path).suffix.lower()
            final=self.directory/(package['sha256']+extension)
            temporary=final.with_suffix(extension+'.download')
            # Exclusive creation; no following a pre-existing partial file.
            if temporary.exists():temporary.unlink()
            count=0
            with fetch(package['url']) as response, temporary.open('xb') as stream:
                while True:
                    if self.cancel.is_set():raise InterruptedError()
                    chunk=response.read(128*1024)
                    if not chunk:break
                    count+=len(chunk)
                    if count>package['size']:raise ValueError('Размер превышен')
                    stream.write(chunk);self.change(progress=min(99,int(count*100/package['size'])))
                stream.flush();os.fsync(stream.fileno())
            if self.cancel.is_set():raise InterruptedError()
            verify_file(temporary,package);os.replace(temporary,final)
            full=self.manifest.get('full')
            recovery_ready=True
            if full and full!=package:
                # Полный пакет нужен только для будущего восстановления. Его
                # сбой не отменяет уже проверенный патч.
                self.change(message='Скачивание полного пакета для будущего восстановления…',progress=0)
                recovery=self.directory/(full['sha256']+'.msi')
                temporary=recovery.with_suffix('.msi.download')
                try:
                    if temporary.exists():temporary.unlink()
                    count=0
                    with fetch(full['url']) as response,temporary.open('xb') as stream:
                        while True:
                            if self.cancel.is_set():raise InterruptedError()
                            chunk=response.read(128*1024)
                            if not chunk:break
                            count+=len(chunk)
                            if count>full['size']:raise ValueError('Размер превышен')
                            stream.write(chunk);self.change(progress=min(99,int(count*100/full['size'])))
                        stream.flush();os.fsync(stream.fileno())
                    if self.cancel.is_set():raise InterruptedError()
                    verify_file(temporary,full);os.replace(temporary,recovery)
                except (InterruptedError,ValueError):
                    # Отмена — решение пользователя; несовпадение хеша или
                    # размера — признак подмены на сервере: оба случая
                    # останавливают обновление целиком.
                    raise
                except OSError:
                    # Сетевой сбой (включая таймауты и ошибки HTTP) не отменяет
                    # уже проверенный патч.
                    recovery_ready=False
            atomic_write_json(str(self.directory/'manifest.json'),self.manifest)
            self.path=final
            self.change(status='ready',progress=100,
                        message='Готово к установке' if recovery_ready else
                        'Готово к установке. Полный пакет для восстановления скачать не удалось — '
                        'обновление установится, но автоматический откат полной версией будет недоступен.')
        except InterruptedError:self.change(status='cancelled',message='Загрузка отменена')
        except Exception:self.change(status='error',message='Не удалось скачать или проверить пакет. Установка отменена.')
        finally:
            if temporary and temporary.is_file():temporary.unlink()
