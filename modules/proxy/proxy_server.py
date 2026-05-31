import socket
import subprocess
import sys
import os
import time
import signal

PROXY_PORT = 5003
_proxy_host = '127.0.0.1'
_proxy_process = None


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _check_mitmproxy():
    """检查系统是否安装了 mitmproxy"""
    try:
        import mitmproxy
        return True
    except ImportError:
        print('[WebProxy] 未找到 mitmproxy，请运行: pip install mitmproxy')
        return False


def _update_addon_host():
    global _proxy_host
    addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'proxy_addon.py')
    try:
        with open(addon_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = content.replace(
            "PROXY_HOST = '127.0.0.1'",
            "PROXY_HOST = '" + _proxy_host + "'"
        )
        with open(addon_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print('[WebProxy] 更新 addon 脚本失败: ' + str(e))


def start_proxy_server(host='0.0.0.0', port=5003):
    global _proxy_host, _proxy_process

    _proxy_host = get_local_ip() or '127.0.0.1'

    if _proxy_process is not None and _proxy_process.poll() is None:
        return True

    # 先停止可能存在的旧进程
    try:
        print('[WebProxy] 正在关闭现有的 mitmproxy 进程...')
        if sys.platform == 'win32':
            result = subprocess.run(['taskkill', '/F', '/IM', 'mitmdump.exe'], capture_output=True, timeout=5, text=True)
            if result.returncode == 0:
                print('[WebProxy] 已关闭现有 mitmproxy 进程')
        else:
            try:
                subprocess.run(['pkill', '-f', 'mitmdump'], capture_output=True, timeout=5)
                print('[WebProxy] 已关闭现有 mitmproxy 进程')
            except Exception:
                pass
        time.sleep(1)
    except Exception as e:
        print(f'[WebProxy] 关闭现有进程时出错: {e}')

    try:
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        host_file = os.path.join(addon_dir, '.proxy_host')
        with open(host_file, 'w') as f:
            f.write(_proxy_host)
    except Exception:
        pass

    if not _check_mitmproxy():
        return False

    _update_addon_host()

    addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'proxy_addon.py')

    # 使用 mitmdump 命令运行 mitmproxy
    cmd = [
        'mitmdump',
        '--listen-host', host,
        '--listen-port', str(port),
        '--mode', 'regular',
        '--set', 'http2=false',
        '--set', 'ssl_insecure=true',
        '-s', addon_path,
    ]

    try:
        # 记录启动信息到日志文件
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'mitmdump_error.log')
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting mitmdump\n")
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Python: {sys.executable}\n")
            f.write(f"Working Dir: {os.getcwd()}\n")
            f.write(f"{'='*60}\n")
        
        # 在后台运行 mitmproxy（不显示窗口）
        if sys.platform == 'win32':
            creation_flags = subprocess.CREATE_NO_WINDOW
            _proxy_process = subprocess.Popen(
                cmd,
                creationflags=creation_flags,
            )
        else:
            _proxy_process = subprocess.Popen(cmd)

        time.sleep(2)

        if _proxy_process.poll() is not None:
            print('[WebProxy] mitmdump 进程启动后立即退出，退出码: ' + str(_proxy_process.returncode))
            print('[WebProxy] 请查看新窗口中的错误信息')
            print('[WebProxy] 日志文件: ' + log_file)
            _proxy_process = None
            return False
        
        print('[WebProxy] 代理服务器已启动: http://{host}:{port}'.format(
            host=_proxy_host,
            port=str(port)
        ))
        print('[WebProxy] mitmproxy 在后台运行')
        print('[WebProxy] 日志文件: ' + log_file)
        return True
    except Exception as e:
        print('[WebProxy] 代理服务器启动失败: ' + str(e))
        import traceback
        traceback.print_exc()
        _proxy_process = None
        return False


def stop_proxy_server():
    global _proxy_process
    # 直接杀掉所有 mitmdump.exe 进程，这是最可靠的方法
    try:
        print('[WebProxy] 正在停止 mitmproxy...')
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/IM', 'mitmdump.exe'], capture_output=True, timeout=5)
            print('[WebProxy] mitmproxy 已停止')
        else:
            try:
                subprocess.run(['pkill', '-f', 'mitmdump'], capture_output=True, timeout=5)
                print('[WebProxy] mitmproxy 已停止')
            except Exception:
                pass
    except Exception:
        pass
    if _proxy_process is not None:
        try:
            if sys.platform == 'win32':
                _proxy_process.terminate()
            else:
                _proxy_process.send_signal(signal.SIGTERM)
            try:
                _proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proxy_process.kill()
                _proxy_process.wait(timeout=3)
        except Exception:
            try:
                _proxy_process.kill()
            except Exception:
                pass
        _proxy_process = None


def is_proxy_running():
    global _proxy_process
    if _proxy_process is None:
        return False
    return _proxy_process.poll() is None


def get_proxy_url():
    if not is_proxy_running():
        return None
    return 'http://' + _proxy_host + ':' + str(PROXY_PORT)


def get_proxy_host():
    return _proxy_host
