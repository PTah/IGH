#!/usr/bin/env python3
"""Локальный офлайн-просмотрщик карты IGH (Windows / macOS / Linux).

Frozen IGH.exe (--noconsole): один процесс, терминал и так свободен.
Рядом с exe обязателен каталог map/ (из zip). Лог — igh.log.
Остановка: кнопка «Остановить сервер и выйти» на карте или IGH.exe --quit

Не-frozen (python igh_launcher.py из консоли): detach через --serve,
чтобы отпустить терминал.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Валидный 1×1 JPEG (PIL); старая hex-заглушка не декодировалась в браузерах.
_EMPTY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000503040404"
    "030504040405050506070c08070707070f0b0b090c110f1212110f111113"
    "161c1713141a1511111821181a1d1d1f1f1f13172224221e241c1e1f1eff"
    "db0043010505050706070e08080e1e1411141e1e1e1e1e1e1e1e1e1e1e1e"
    "1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e"
    "1e1e1e1e1e1e1e1effc00011080001000103012200021101031101ffc400"
    "1f0000010501010101010100000000000000000102030405060708090a0b"
    "ffc400b5100002010303020403050504040000017d010203000411051221"
    "31410613516107227114328191a1082342b1c11552d1f02433627282090a"
    "161718191a25262728292a3435363738393a434445464748494a53545556"
    "5758595a636465666768696a737475767778797a838485868788898a9293"
    "9495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6"
    "c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7"
    "f8f9faffc4001f0100030101010101010101010000000000000102030405"
    "060708090a0bffc400b51100020102040403040705040400010277000102"
    "031104052131061241510761711322328108144291a1b1c109233352f015"
    "6272d10a162434e125f11718191a262728292a35363738393a4344454647"
    "48494a535455565758595a636465666768696a737475767778797a828384"
    "85868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7"
    "b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9ea"
    "f2f3f4f5f6f7f8f9faffda000c03010002110311003f00f73a28a2803fff"
    "d9"
)

_CLIENT_GONE = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
    TimeoutError,
)

_WORKER_FLAG = "--serve"
_QUIT_FLAG = "--quit"
_FOREGROUND_FLAG = "--foreground"

# Не больше одной вкладки на процесс и не чаще раза в N сек на каталог.
_BROWSER_OPENED_HERE = False
_BROWSER_DEBOUNCE_SEC = 8.0


def runtime_dir() -> Path:
    """Каталог рядом с exe / скриптом — igh.log, igh.state.json, map/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    if (here / "map" / "index.html").exists():
        return here
    if (here.parent / "map" / "index.html").exists():
        return here.parent
    return here


def map_dir() -> Path | None:
    """Корень HTTP: сначала map/ на диске рядом с exe (не _MEIPASS)."""
    disk = runtime_dir() / "map"
    if (disk / "index.html").is_file():
        return disk
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", "") or "")
        bundled = meipass / "map"
        if (bundled / "index.html").is_file():
            return bundled
    return None


def log_path() -> Path:
    return runtime_dir() / "igh.log"


def state_path() -> Path:
    return runtime_dir() / "igh.state.json"


def stop_path() -> Path:
    return runtime_dir() / "igh.stop"


def lock_path() -> Path:
    return runtime_dir() / "igh.lock"


def browser_stamp_path() -> Path:
    return runtime_dir() / "igh.browser"

def _is_client_gone(exc: BaseException) -> bool:
    if isinstance(exc, _CLIENT_GONE):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
        return True
    return False


def _log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def _alert(msg: str) -> None:
    _log("ERROR: " + msg)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "IGH", 0x10)
        except Exception:
            pass


def _port_alive(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _read_state() -> dict | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("port"):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_state(port: int, url: str) -> None:
    payload = {
        "pid": os.getpid(),
        "port": port,
        "url": url,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    state_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _clear_state() -> None:
    try:
        state_path().unlink(missing_ok=True)
    except OSError:
        pass


def _clear_stop() -> None:
    try:
        stop_path().unlink(missing_ok=True)
    except OSError:
        pass


def _release_lock() -> None:
    try:
        lock_path().unlink(missing_ok=True)
    except OSError:
        pass


def _try_acquire_lock() -> bool:
    """Один сервер: атомарный igh.lock (O_EXCL)."""
    path = lock_path()
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    finally:
        os.close(fd)
    return True


def _lock_owner_pid() -> int | None:
    try:
        text = lock_path().read_text(encoding="utf-8").strip().splitlines()[0]
        return int(text)
    except (OSError, IndexError, ValueError):
        return None


def _browser_recently_opened(url: str) -> bool:
    path = browser_stamp_path()
    if not path.exists():
        return False
    try:
        line = path.read_text(encoding="utf-8").strip()
        parts = line.split(None, 1)
        ts = float(parts[0])
        prev_url = parts[1] if len(parts) > 1 else ""
        if prev_url and prev_url != url:
            return False
        return (time.time() - ts) < _BROWSER_DEBOUNCE_SEC
    except (OSError, ValueError, IndexError):
        return False


def _mark_browser_opened(url: str) -> None:
    try:
        browser_stamp_path().write_text(
            f"{time.time():.3f} {url}\n", encoding="utf-8"
        )
    except OSError:
        pass


def _open_browser(url: str) -> None:
    """Строго один раз на процесс; плюс debounce между процессами (двойной клик)."""
    global _BROWSER_OPENED_HERE
    if _BROWSER_OPENED_HERE:
        _log("браузер: пропуск (уже открывали в этом процессе)")
        return
    if _browser_recently_opened(url):
        _log(f"браузер: пропуск дубля (уже открывали ≤{_BROWSER_DEBOUNCE_SEC:.0f}с)")
        return

    _log(f"браузер: открываю {url}")
    try:
        if sys.platform == "win32":
            # Один ShellExecute; webbrowser/os.startfile на части систем даёт 2 вкладки.
            import ctypes

            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "open", url, None, None, 1
            )
            if rc <= 32:
                raise OSError(f"ShellExecuteW failed code={rc}")
        else:
            webbrowser.open(url)
        _BROWSER_OPENED_HERE = True
        _mark_browser_opened(url)
        _log("браузер: открыт")
    except Exception as exc:
        _log(f"браузер: ошибка — {exc}")


def _request_stop() -> None:
    try:
        stop_path().write_text(
            time.strftime("%Y-%m-%d %H:%M:%S") + " quit\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _log(f"не удалось записать igh.stop: {exc}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _running_instance() -> dict | None:
    st = _read_state()
    if not st:
        return None
    pid = int(st.get("pid") or 0)
    port = int(st.get("port") or 0)
    url = st.get("url") or f"http://127.0.0.1:{port}/index.html"
    if pid and _pid_alive(pid) and _port_alive(port) and _http_ok(url):
        return st
    _log(f"устаревшее состояние сброшено (pid={pid}, port={port})")
    _clear_state()
    return None


def quit_running() -> int:
    st = _read_state()
    if not st:
        _log("остановка: сервер не запущен (нет igh.state.json)")
        _clear_stop()
        return 0
    pid = int(st.get("pid") or 0)
    port = int(st.get("port") or 0)
    url = st.get("url") or f"http://127.0.0.1:{port}/index.html"
    _log(f"остановка: запрошена (pid={pid}, port={port}, url={url})")

    if pid and _pid_alive(pid):
        _request_stop()
        # Дать serve() самому закрыться и записать «сервер остановлен»
        deadline = time.time() + 8.0
        stopped_clean = False
        while time.time() < deadline:
            alive = _pid_alive(pid)
            port_up = _port_alive(port)
            state_gone = not state_path().exists()
            if not alive:
                stopped_clean = True
                break
            # serve уже закрыл HTTP и сбросил state — считаем успехом
            if (not port_up) and state_gone:
                stopped_clean = True
                break
            time.sleep(0.2)
        if stopped_clean:
            if _pid_alive(pid):
                # редкий хвост процесса после закрытия порта
                _kill_pid(pid)
                time.sleep(0.2)
            _log(f"остановка: сервер остановлен (pid={pid}, port={port})")
        else:
            _log(f"остановка: процесс не вышел вовремя — принудительно (pid={pid})")
            _kill_pid(pid)
            time.sleep(0.4)
            _log(f"остановка: сервер остановлен принудительно (pid={pid}, port={port})")
    else:
        _log(f"остановка: процесс уже не жив (pid={pid}, port={port})")

    _clear_state()
    _clear_stop()
    _release_lock()
    return 0


def _worker_argv() -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), _WORKER_FLAG]


def spawn_detached_worker() -> None:
    """Только для не-frozen: отпустить интерактивную консоль."""
    args = _worker_argv()  # --serve: без браузера, вкладку откроет bootstrap
    kwargs: dict = {
        "cwd": str(runtime_dir()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
        except Exception:
            pass
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def wait_for_server(timeout: float = 15.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _read_state()
        if not st:
            time.sleep(0.15)
            continue
        url = st.get("url") or f"http://127.0.0.1:{st['port']}/index.html"
        if _port_alive(int(st["port"])) and _http_ok(url):
            return st
        time.sleep(0.15)
    return None


class QuietHandler(SimpleHTTPRequestHandler):
    server_version = "IGH/1"
    sys_version = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def log_error(self, format: str, *args) -> None:  # noqa: A003
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def list_directory(self, path):  # noqa: ANN001
        self.send_error(404, "Not found")
        return None

    def copyfile(self, source, outputfile):  # noqa: ANN001
        try:
            super().copyfile(source, outputfile)
        except Exception as exc:
            if _is_client_gone(exc):
                return
            raise

    def send_error(self, code, message=None, explain=None):  # noqa: ANN001
        try:
            super().send_error(code, message, explain)
        except Exception as exc:
            if _is_client_gone(exc):
                return
            raise

    def finish(self) -> None:
        try:
            super().finish()
        except Exception as exc:
            if _is_client_gone(exc):
                return
            raise

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except Exception as exc:
            if _is_client_gone(exc):
                return
            raise

    def _api_path(self) -> str:
        return urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not _is_client_gone(exc):
                raise

    def _handle_quit_api(self) -> bool:
        """True = ответ уже отправлен (POST/GET /api/quit)."""
        if self._api_path() != "/api/quit":
            return False
        _log("остановка: запрос из браузера (/api/quit)")
        _request_stop()
        self._send_json(200, {"ok": True, "message": "stopping"})
        return True

    def do_POST(self) -> None:
        if self._handle_quit_api():
            return
        self.send_error(404, "Not found")

    def do_GET(self) -> None:
        if self._handle_quit_api():
            return
        path = self.translate_path(self.path)
        rel = Path(path)
        try:
            under_tiles = "tiles" in rel.parts and rel.suffix.lower() in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }
        except Exception:
            under_tiles = False
        if under_tiles and not rel.is_file():
            try:
                body = _EMPTY_JPEG
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                if not _is_client_gone(exc):
                    raise
            return
        try:
            super().do_GET()
        except Exception as exc:
            if _is_client_gone(exc):
                return
            raise


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        exc = sys.exc_info()[1]
        if exc is not None and _is_client_gone(exc):
            return
        if isinstance(exc, FileNotFoundError):
            return
        super().handle_error(request, client_address)


def _stop_server(httpd: QuietServer) -> None:
    try:
        httpd.shutdown()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        pass
    try:
        httpd.server_close()
    except Exception:
        pass


def _reopen_existing(st: dict) -> None:
    url = st.get("url") or f"http://127.0.0.1:{st['port']}/index.html"
    # Деbounce внутри _open_browser; повторный клик через >8с снова откроет вкладку.
    _log(f"уже запущен — запрос открыть карту: {url}")
    _open_browser(url)


def _reopen_or_wait_existing() -> bool:
    """True = чужой сервер учтён, свой поднимать не нужно."""
    for _ in range(30):
        st = _running_instance()
        if st:
            _reopen_existing(st)
            return True
        time.sleep(0.15)
    owner = _lock_owner_pid()
    if owner is not None and not _pid_alive(owner):
        _log(f"устаревший igh.lock (pid={owner}) — снимаю")
        _release_lock()
        return False
    return False


def serve(*, open_browser: bool = True) -> int:
    root = map_dir()
    if root is None:
        _alert(
            "Не найден map/index.html рядом с программой.\n"
            f"Ожидается: {runtime_dir() / 'map' / 'index.html'}\n"
            "Распакуйте zip целиком (нужна папка map рядом с IGH.exe)."
        )
        _release_lock()
        return 1

    if not _try_acquire_lock():
        _log("lock занят — жду уже запущенный сервер")
        if _reopen_or_wait_existing():
            return 0
        if not _try_acquire_lock():
            _alert("Не удалось запустить: другой IGH уже держит igh.lock. См. igh.log")
            return 1

    _clear_stop()
    # Порт 0: ОС выдаёт свободный порт без TOCTOU free_port()→bind.
    handler = partial(QuietHandler, directory=str(root.resolve()))
    httpd = QuietServer(("127.0.0.1", 0), handler)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/index.html"
    _write_state(port, url)
    _log(
        f"сервер запущен: pid={os.getpid()}, port={port}, "
        f"map={root.resolve()}, url={url}"
    )

    if not _http_ok(url):
        _log(f"сервер не прошёл проверку: {url} не отвечает 200")
        _stop_server(httpd)
        _clear_state()
        _clear_stop()
        _release_lock()
        _alert(f"Сервер поднялся, но {url} не отвечает 200. См. igh.log")
        return 1

    _log("проверка URL: OK")
    if open_browser:
        _open_browser(url)
    else:
        _log("браузер: пропуск (откроет родительский процесс)")

    reason = "неизвестно"
    try:
        while True:
            if stop_path().exists():
                reason = "команда --quit (igh.stop)"
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        reason = "KeyboardInterrupt"
    finally:
        _log(f"сервер останавливается: причина={reason}")
        _stop_server(httpd)
        _clear_state()
        _clear_stop()
        _release_lock()
        _log(f"сервер остановлен: pid={os.getpid()}, port={port}")
    return 0


def bootstrap_script() -> int:
    """Не-frozen: spawn python --serve и сразу выйти из консоли."""
    st = _running_instance()
    if st:
        _reopen_existing(st)
        return 0

    _log("запуск фонового процесса --serve")
    # Worker без браузера: вкладку откроем один раз здесь после ready.
    spawn_detached_worker()
    ready = wait_for_server()
    if not ready:
        _alert("Server did not start. See igh.log")
        return 1
    url = ready.get("url") or ""
    _log(f"фоновый сервер готов: {url}")
    if url:
        _open_browser(url)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if _QUIT_FLAG in argv:
        return quit_running()

    frozen = bool(getattr(sys, "frozen", False))
    as_worker = _WORKER_FLAG in argv
    foreground = _FOREGROUND_FLAG in argv

    # Уже крутится — только открыть браузер (и для exe, и для скрипта).
    if not as_worker and not foreground:
        st = _running_instance()
        if st:
            _reopen_existing(st)
            return 0

    # Frozen onefile: НЕ спавнить второй IGH.exe (ломает _MEIPASS → 404 + Warning).
    if frozen or as_worker or foreground:
        # --serve (worker): браузер откроет bootstrap_script один раз
        return serve(open_browser=not as_worker)

    return bootstrap_script()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
