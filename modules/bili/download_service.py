import os
import asyncio
import threading
import subprocess
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from config import Config

try:
    from bilibili_api import select_client
    select_client("curl_cffi")
except Exception as e:
    print(f'[Bili] 无法选择 curl_cffi: {e}')

BILI_DIR = os.path.join(Config.TEMP_DIR, 'bili') if Config.TEMP_DIR else os.path.join(os.path.dirname(__file__), '..', 'temp', 'bili')

# Cache cleanup settings
CACHE_MAX_SIZE_MB = 10240   # 10 GB max cache size
CACHE_MAX_AGE_DAYS = 30     # Remove files older than 30 days
CACHE_CHECK_INTERVAL = 3600 # Check every hour

# Auto cleanup for unused videos (configurable, default 7 days)
UNUSED_VIDEO_AUTO_CLEANUP_DAYS = 7  # 可配置的变量，以后可以通过设置界面调整

_cleanup_thread = None
_cleanup_running = False

# Active FFmpeg process tracking
active_ffmpeg_processes = {}  # {bvid: subprocess.Popen}

FFMPEG_PATH = None
HAS_NVENC = False  # 是否支持 NVIDIA NVENC 硬件加速
HAS_QSV = False    # 是否支持 Intel QSV 硬件加速

QUALITY_MAP = {
    16: '360P',
    32: '480P',
    64: '720P',
    74: '720P60',
    80: '1080P',
    112: '1080P+',
    116: '1080P60',
    120: '4K',
}

DEFAULT_QUALITY = 32
MAX_CONCURRENT_DOWNLOADS = 2

download_tasks = {}
download_lock = threading.Lock()
active_downloads = 0
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)
download_queue = Queue()
executor = ThreadPoolExecutor(max_workers=5)


def check_ffmpeg():
    global FFMPEG_PATH
    from utils.ffmpeg import ensure_ffmpeg

    ffmpeg_path = ensure_ffmpeg()
    if ffmpeg_path:
        FFMPEG_PATH = ffmpeg_path
        return True

    FFMPEG_PATH = None
    return False


def check_qsv_support():
    """检测 FFmpeg 是否支持 Intel QSV 硬件编码器（实际可用）"""
    if not FFMPEG_PATH:
        return False
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        
        # 第一步：检查 FFmpeg 是否编译了 QSV 支持
        result = subprocess.run(
            [FFMPEG_PATH, '-encoders'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            timeout=10
        )
        if 'h264_qsv' not in result.stdout:
            print(f'[Bili] FFmpeg 未编译 QSV 支持')
            return False
        
        # 第二步：尝试实际初始化 QSV 编码器（检测是否真正可用）
        test_result = subprocess.run(
            [FFMPEG_PATH, '-f', 'lavfi', '-i', 'nullsrc=s=256x256:d=0.1', 
             '-c:v', 'h264_qsv', '-f', 'null', '-'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            timeout=10
        )
        
        if test_result.returncode == 0:
            print(f'[Bili] Intel QSV 硬件加速支持: True (实际可用)')
            return True
        else:
            stderr_lower = test_result.stderr.lower()
            if 'mfx' in stderr_lower or 'qsv' in stderr_lower:
                print(f'[Bili] Intel QSV 硬件加速支持: False (MFX/驱动不可用)')
            elif 'cannot allocate memory' in stderr_lower or 'out of memory' in stderr_lower:
                print(f'[Bili] Intel QSV 硬件加速支持: False (内存不足)')
            else:
                print(f'[Bili] Intel QSV 硬件加速支持: False (初始化失败)')
            return False
            
    except subprocess.TimeoutExpired:
        print(f'[Bili] 检测 Intel QSV 支持超时')
        return False
    except Exception as e:
        print(f'[Bili] 检测 Intel QSV 支持失败: {e}')
        return False


def check_nvenc_support():
    """检测 FFmpeg 是否支持 NVIDIA NVENC 硬件编码器（实际可用）"""
    if not FFMPEG_PATH:
        return False
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        
        # 第一步：检查 FFmpeg 是否编译了 NVENC 支持
        result = subprocess.run(
            [FFMPEG_PATH, '-encoders'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            timeout=10
        )
        if 'h264_nvenc' not in result.stdout:
            print(f'[Bili] FFmpeg 未编译 NVENC 支持')
            return False
        
        # 第二步：尝试实际初始化 NVENC 编码器（检测是否真正可用）
        test_result = subprocess.run(
            [FFMPEG_PATH, '-f', 'lavfi', '-i', 'nullsrc=s=256x256:d=0.1', 
             '-c:v', 'h264_nvenc', '-f', 'null', '-'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
            timeout=10
        )
        
        if test_result.returncode == 0:
            print(f'[Bili] NVIDIA NVENC 硬件加速支持: True (实际可用)')
            return True
        else:
            stderr_lower = test_result.stderr.lower()
            if 'cuda' in stderr_lower or 'nvenc' in stderr_lower or 'gpu' in stderr_lower:
                print(f'[Bili] NVIDIA NVENC 硬件加速支持: False (GPU/驱动不可用)')
            elif 'cannot allocate memory' in stderr_lower or 'out of memory' in stderr_lower:
                print(f'[Bili] NVIDIA NVENC 硬件加速支持: False (显存不足)')
            else:
                print(f'[Bili] NVIDIA NVENC 硬件加速支持: False (初始化失败)')
            return False
            
    except subprocess.TimeoutExpired:
        print(f'[Bili] 检测 NVIDIA NVENC 支持超时')
        return False
    except Exception as e:
        print(f'[Bili] 检测 NVIDIA NVENC 支持失败: {e}')
        return False


check_ffmpeg()
HAS_NVENC = check_nvenc_support()
HAS_QSV = check_qsv_support()


def get_video_encoder_params(encoder='x264'):
    """
    返回指定编码器的参数
    encoder: 'nvenc' (NVIDIA), 'qsv' (Intel), 'x264' (软件)
    """
    if encoder == 'nvenc':
        # NVIDIA NVENC 硬件编码，-cq 恒定质量，默认 preset=p4(medium)
        return ['-c:v', 'h264_nvenc', '-cq', '23']
    elif encoder == 'qsv':
        # Intel QSV 硬件编码，-global_quality 范围 0-51
        return ['-c:v', 'h264_qsv', '-global_quality', '23', '-preset', 'veryfast']
    else:
        # 软件编码，-threads 0 让 x264 自动决定线程数
        return ['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-threads', '0']


def _get_encoder_priority():
    """返回按优先级排列的可用编码器列表 [(name, keyword), ...]"""
    encoders = []
    if HAS_NVENC:
        encoders.append(('nvenc', 'nvenc'))
    if HAS_QSV:
        encoders.append(('qsv', 'qsv'))
    encoders.append(('x264', 'libx264'))
    return encoders


def _is_encoder_error(error_lines, keyword):
    """检查FFmpeg错误输出是否由指定编码器失败引起"""
    kw = keyword.lower()
    error_text = '\n'.join(line.lower() for line in error_lines)
    
    for line in error_lines:
        if kw in line.lower():
            return True
    
    if keyword == 'qsv':
        qsv_error_patterns = [
            'mfx', 'qsv', 'vaapi', 
            'failed to initialize',
            'not supported',
            'cannot allocate memory',
            'out of memory',
            'device creation failed',
        ]
        for pattern in qsv_error_patterns:
            if pattern in error_text:
                return True
    
    if keyword == 'nvenc':
        nvenc_error_patterns = [
            'cuda', 'nvenc', 'gpu', 'nvidia',
            'failed to initialize',
            'not supported',
            'cannot allocate memory',
            'out of memory',
            'device creation failed',
            'driver',
            'no capable devices',
            'failed to load nvenc',
            'cuda_error',
        ]
        for pattern in nvenc_error_patterns:
            if pattern in error_text:
                return True
    
    return False


def safe_rename(src, dst):
    """跨平台安全重命名，Windows下目标存在时先删除"""
    if os.path.exists(dst):
        try:
            os.remove(dst)
        except OSError:
            pass
    os.rename(src, dst)


def ensure_bili_dir():
    if not os.path.exists(BILI_DIR):
        os.makedirs(BILI_DIR)


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def get_video_info_sync(bvid):
    from bilibili_api import video

    async def _get_info():
        v = video.Video(bvid=bvid)
        info = await v.get_info()
        cid = info.get('cid', 0)
        if not cid and info.get('pages'):
            cid = info['pages'][0].get('cid', 0)
        return info, cid

    return run_async(_get_info())


def get_download_streams_sync(bvid, cid):
    from bilibili_api import video
    from bilibili_api.video import VideoDownloadURLDataDetecter, VideoQuality

    async def _get_streams():
        v = video.Video(bvid=bvid)
        url_data = await v.get_download_url(cid=cid)

        detecter = VideoDownloadURLDataDetecter(url_data)
        streams = detecter.detect_best_streams(
            video_max_quality=VideoQuality._480P,
            video_min_quality=VideoQuality._360P
        )
        return streams

    return run_async(_get_streams())


def get_video_cache_path(bvid):
    ensure_bili_dir()
    return os.path.join(BILI_DIR, f'{bvid}.mp4')


def is_video_cached(bvid):
    path = get_video_cache_path(bvid)
    return os.path.exists(path)


def get_cached_videos():
    """获取所有视频的缓存状态（包括已完成、下载中、转换中）"""
    ensure_bili_dir()
    videos = {}
    
    # 首先扫描已缓存的文件
    try:
        for filename in os.listdir(BILI_DIR):
            if filename.endswith('.mp4'):
                bvid = filename[:-4]
                filepath = os.path.join(BILI_DIR, filename)
                size = os.path.getsize(filepath)
                videos[bvid] = {
                    'bvid': bvid,
                    'status': 'completed',
                    'progress': 100,
                    'size': size,
                    'size_display': format_size(size),
                    'converting_progress': 100
                }
    except Exception as e:
        print(f'[Bili] 扫描缓存目录失败: {e}')
    
    # 然后合并正在下载/转换中的任务
    with download_lock:
        for bvid, task in download_tasks.items():
            if task.status != 'completed':
                task_dict = task.to_dict()
                # 如果文件已经存在但任务还在转换中，更新状态
                if bvid in videos:
                    videos[bvid].update({
                        'status': task.status,
                        'progress': task_dict.get('progress', 0),
                        'converting_progress': task_dict.get('converting_progress', 0),
                        'speed_display': task_dict.get('speed_display', ''),
                        'downloaded_display': task_dict.get('downloaded_display', ''),
                        'total_display': task_dict.get('total_display', ''),
                        'queue_position': task_dict.get('queue_position', 0),
                        'error': task_dict.get('error')
                    })
                else:
                    # 文件还不存在，添加到列表
                    videos[bvid] = {
                        'bvid': bvid,
                        'status': task.status,
                        'progress': task_dict.get('progress', 0),
                        'converting_progress': task_dict.get('converting_progress', 0),
                        'size': 0,
                        'size_display': '计算中...',
                        'speed_display': task_dict.get('speed_display', ''),
                        'downloaded_display': task_dict.get('downloaded_display', ''),
                        'total_display': task_dict.get('total_display', ''),
                        'queue_position': task_dict.get('queue_position', 0),
                        'error': task_dict.get('error'),
                        'title': getattr(task, 'title', bvid)
                    }
    
    return list(videos.values())


def format_size(size):
    if size < 1024:
        return f'{size} B'
    elif size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    elif size < 1024 * 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    else:
        return f'{size / (1024 * 1024 * 1024):.2f} GB'


class DownloadTask:
    def __init__(self, bvid, title, cid):
        self.bvid = bvid
        self.title = title
        self.cid = cid
        self.status = 'pending'
        self.progress = 0
        self.downloaded = 0
        self.total = 0
        self.speed = 0
        self.error = None
        self.start_time = None
        self.last_update = None
        self.last_downloaded = 0
        self.converting_progress = 0
        self.queue_position = 0

    def to_dict(self):
        return {
            'bvid': self.bvid,
            'title': self.title,
            'status': self.status,
            'progress': self.progress,
            'downloaded': self.downloaded,
            'total': self.total,
            'downloaded_display': format_size(self.downloaded),
            'total_display': format_size(self.total),
            'speed': self.speed,
            'speed_display': format_size(self.speed) + '/s' if self.speed > 0 else '0 B/s',
            'error': self.error,
            'converting_progress': self.converting_progress,
            'queue_position': self.queue_position
        }


def download_file(url, filepath, task, headers=None):
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
    }
    if headers:
        req_headers.update(headers)

    print(f'[Bili] 开始下载: {url[:100]}...')

    resp = requests.get(url, headers=req_headers, stream=True, timeout=30, allow_redirects=True)
    total_size = int(resp.headers.get('content-length', 0))
    task.total = total_size
    print(f'[Bili] 文件总大小: {format_size(total_size) if total_size > 0 else "未知"}')

    downloaded = 0
    last_check = time.time()
    last_downloaded = 0

    with open(filepath, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                task.downloaded = downloaded

                now = time.time()
                if now - last_check >= 0.3:
                    elapsed = now - last_check
                    task.speed = int((downloaded - last_downloaded) / elapsed) if elapsed > 0 else 0
                    if task.total > 0:
                        task.progress = int(task.downloaded / task.total * 100)
                    else:
                        task.progress = min(99, int(downloaded / (1024 * 1024) * 10))
                    last_check = now
                    last_downloaded = downloaded

                    print(f'[Bili] 下载进度: {task.progress}% ({format_size(downloaded)}) 速度: {format_size(task.speed)}/s')

    actual_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    task.downloaded = actual_size
    task.total = actual_size if actual_size > total_size else total_size
    task.progress = 100
    print(f'[Bili] 下载完成: {filepath}, 实际大小: {format_size(actual_size)}')
    return actual_size


def _run_ffmpeg_process(cmd, task, action_name='转换'):
    """运行 FFmpeg 子进程，解析时长和进度。返回 (success, error_output)"""
    global active_ffmpeg_processes
    
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        creationflags=creationflags
    )
    
    # 追踪活跃的 FFmpeg 进程
    if hasattr(task, 'bvid') and task.bvid:
        active_ffmpeg_processes[task.bvid] = process
        print(f'[Bili] 开始追踪 FFmpeg 进程: {task.bvid} (PID: {process.pid})')

    duration = None
    error_output = []
    import re
    while True:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break

        if line:
            error_output.append(line.strip())

            if 'Duration:' in line:
                match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if match:
                    h, m, s, ms = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
                    duration = h * 3600 + m * 60 + s + ms / 100
                    print(f'[Bili] 视频时长: {duration}秒')

            if 'time=' in line and duration:
                match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                if match:
                    h, m, s, ms = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
                    current_time = h * 3600 + m * 60 + s + ms / 100
                    if duration > 0:
                        task.converting_progress = int((current_time / duration) * 100)

            if 'Error' in line or 'error' in line:
                print(f'[Bili] FFmpeg输出: {line.strip()}')

    process.wait()
    
    # 从追踪列表中移除
    if hasattr(task, 'bvid') and task.bvid and task.bvid in active_ffmpeg_processes:
        del active_ffmpeg_processes[task.bvid]
        print(f'[Bili] FFmpeg 进程已完成: {task.bvid}')
    
    success = process.returncode == 0
    if not success:
        print(f'[Bili] FFmpeg{action_name}失败，返回码: {process.returncode}')
        print(f'[Bili] 错误输出:')
        for line in error_output[-20:]:
            print(f'    {line}')
    return success, error_output


def _try_encoders(input_path, output_path, task, build_cmd, action_name='转换'):
    """按优先级尝试编码器：NVENC → QSV → x264"""
    encoders = _get_encoder_priority()
    for i, (encoder_name, keyword) in enumerate(encoders):
        is_last = (i == len(encoders) - 1)
        encoder_label = {'nvenc': 'NVENC', 'qsv': 'QSV', 'x264': 'libx264'}[encoder_name]
        print(f'[Bili] 尝试 {encoder_label} 编码器{action_name}...')

        cmd = build_cmd(encoder_name)
        print(f'[Bili] FFmpeg命令: {" ".join(cmd)}')

        success, error_output = _run_ffmpeg_process(cmd, task, action_name)

        if success:
            output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            print(f'[Bili] 视频{action_name}完成: {output_path} ({format_size(output_size)})')
            return True

        if not is_last and _is_encoder_error(error_output, keyword):
            next_label = {'nvenc': 'QSV', 'qsv': 'libx264'}[encoder_name]
            print(f'[Bili] {encoder_label} 编码失败，回退到 {next_label} 重试')
            continue

        return False

    return False


def convert_to_h264(input_path, output_path, task):
    if not FFMPEG_PATH or not os.path.exists(input_path):
        print(f'[Bili] FFmpeg未找到或输入文件不存在，跳过转换')
        if os.path.exists(input_path):
            safe_rename(input_path, output_path)
            return True
        return False

    input_size = os.path.getsize(input_path)
    print(f'[Bili] 开始转换视频为H264格式: {input_path} -> {output_path} ({format_size(input_size)})')

    def build_cmd(encoder_name):
        encoder_params = get_video_encoder_params(encoder_name)
        return [
            FFMPEG_PATH, '-y',
            '-i', input_path,
        ] + encoder_params + [
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            output_path
        ]

    try:
        return _try_encoders(input_path, output_path, task, build_cmd, '转换')
    except FileNotFoundError:
        print('[Bili] FFmpeg未找到，跳过转换')
        if os.path.exists(input_path):
            safe_rename(input_path, output_path)
            return True
        return False
    except Exception as e:
        print(f'[Bili] 转换异常: {e}')
        import traceback
        traceback.print_exc()
        return False


def merge_and_convert_video_audio(video_path, audio_path, output_path, task):
    if not FFMPEG_PATH:
        print('[Bili] FFmpeg未找到，跳过合并转换')
        return False

    video_exists = os.path.exists(video_path)
    audio_exists = os.path.exists(audio_path)
    video_size = os.path.getsize(video_path) if video_exists else 0
    audio_size = os.path.getsize(audio_path) if audio_exists else 0

    print(f'[Bili] 开始合并并转换视频: video={video_path}({format_size(video_size)}), audio={audio_path}({format_size(audio_size)}), output={output_path}')

    if not video_exists:
        print(f'[Bili] 视频文件不存在: {video_path}')
        return False

    def build_cmd(encoder_name):
        encoder_params = get_video_encoder_params(encoder_name)
        cmd = [FFMPEG_PATH, '-y', '-i', video_path]
        if audio_exists:
            cmd.extend(['-i', audio_path])
        cmd.extend(encoder_params)
        if audio_exists:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        else:
            cmd.extend(['-an'])
        cmd.extend(['-movflags', '+faststart', output_path])
        return cmd

    try:
        return _try_encoders(video_path, output_path, task, build_cmd, '合并')
    except FileNotFoundError:
        print('[Bili] FFmpeg未找到，尝试直接复制')
        return False
    except Exception as e:
        print(f'[Bili] 合并转换异常: {e}')
        import traceback
        traceback.print_exc()
        return False


def download_video_task(task):
    from bilibili_api.video import VideoStreamDownloadURL, AudioStreamDownloadURL, FLVStreamDownloadURL, MP4StreamDownloadURL

    global active_downloads

    with download_semaphore:
        with download_lock:
            active_downloads += 1
            task.status = 'fetching'
            task.progress = 0
            task.queue_position = 0

        try:
            task.start_time = time.time()
            task.last_update = time.time()

            print(f'[Bili] 开始获取视频信息: {task.bvid}')
            info, cid = get_video_info_sync(task.bvid)
            task.title = info.get('title', task.bvid)
            print(f'[Bili] 视频标题: {task.title}')

            print(f'[Bili] 开始获取下载流')
            streams = get_download_streams_sync(task.bvid, cid)

            if not streams:
                raise Exception('未找到可用的下载流')

            video_path = get_video_cache_path(task.bvid)
            temp_video_path = video_path + '.video'
            temp_audio_path = video_path + '.audio'
            temp_merged_path = video_path + '.merged.mp4'

            headers = {'Referer': 'https://www.bilibili.com/'}

            if len(streams) == 1 and isinstance(streams[0], (FLVStreamDownloadURL, MP4StreamDownloadURL)):
                print(f'[Bili] 单流模式下载')
                stream = streams[0]
                url = stream.url
                task.status = 'downloading'
                task.progress = 0
                print(f'[Bili] 状态已更新为: downloading')
                download_file(url, temp_merged_path, task, headers)

                merged_size = os.path.getsize(temp_merged_path) if os.path.exists(temp_merged_path) else 0

                if merged_size < 1024:
                    raise Exception(f'下载的文件太小({merged_size}B)，可能是无效文件')

                task.status = 'converting'
                task.converting_progress = 0
                task.progress = 100
                print(f'[Bili] 状态已更新为: converting, 下载进度: 100%')
                print(f'[Bili] 开始转换为H264格式')
                success = convert_to_h264(temp_merged_path, video_path, task)

                if success:
                    try:
                        os.remove(temp_merged_path)
                    except:
                        pass
                    task.status = 'completed'
                    task.progress = 100
                    task.converting_progress = 100
                    print(f'[Bili] 视频处理成功: {video_path}, 状态: completed')
                else:
                    print(f'[Bili] 转换失败，保留原始文件')
                    if os.path.exists(temp_merged_path):
                        safe_rename(temp_merged_path, video_path)
                    task.status = 'completed'
                    task.progress = 100
                    task.error = '视频转换失败，保留原始格式'
                    print(f'[Bili] 状态: completed (转换失败但保留文件)')

            elif len(streams) >= 2:
                print(f'[Bili] 双流模式下载（音视频分离）')
                video_stream = None
                audio_stream = None

                for s in streams:
                    if isinstance(s, VideoStreamDownloadURL) and video_stream is None:
                        video_stream = s
                    elif isinstance(s, AudioStreamDownloadURL) and audio_stream is None:
                        audio_stream = s

                if not video_stream:
                    raise Exception('未找到视频流')

                video_url = video_stream.url
                audio_url = audio_stream.url if audio_stream else None

                print(f'[Bili] 视频流URL: {video_url[:100]}...')
                if audio_url:
                    print(f'[Bili] 音频流URL: {audio_url[:100]}...')

                task.status = 'downloading'
                task.progress = 0
                print(f'[Bili] 状态已更新为: downloading')

                print(f'[Bili] 开始下载视频流')
                download_file(video_url, temp_video_path, task, headers)

                video_size = os.path.getsize(temp_video_path) if os.path.exists(temp_video_path) else 0
                if video_size < 1024:
                    raise Exception(f'下载的视频文件太小({video_size}B)')

                if audio_url:
                    print(f'[Bili] 开始下载音频流')
                    download_file(audio_url, temp_audio_path, task, headers)

                    audio_size = os.path.getsize(temp_audio_path) if os.path.exists(temp_audio_path) else 0
                    if audio_size < 1024:
                        print(f'[Bili] 警告: 音频文件较小({audio_size}B)')

                task.status = 'converting'
                task.converting_progress = 0
                task.progress = 100
                print(f'[Bili] 状态已更新为: converting, 下载进度: 100%')
                print(f'[Bili] 开始合并并转换为H264格式')

                if audio_url and os.path.exists(temp_audio_path) and os.path.exists(temp_video_path):
                    success = merge_and_convert_video_audio(temp_video_path, temp_audio_path, video_path, task)
                    if success:
                        try:
                            os.remove(temp_video_path)
                            os.remove(temp_audio_path)
                        except:
                            pass
                        print(f'[Bili] 视频合并转换成功: {video_path}')
                    else:
                        print(f'[Bili] 合并转换失败，尝试仅转换视频')
                        if os.path.exists(temp_video_path):
                            success2 = convert_to_h264(temp_video_path, video_path, task)
                            if success2:
                                try:
                                    os.remove(temp_video_path)
                                    if os.path.exists(temp_audio_path):
                                        os.remove(temp_audio_path)
                                except:
                                    pass
                                print(f'[Bili] 视频转换成功: {video_path}')
                            else:
                                print(f'[Bili] 转换失败，保留原始文件')
                                if os.path.exists(temp_video_path):
                                    safe_rename(temp_video_path, video_path)
                                task.error = '视频转换失败，保留原始格式'
                else:
                    if os.path.exists(temp_video_path):
                        success = convert_to_h264(temp_video_path, video_path, task)
                        if success:
                            try:
                                os.remove(temp_video_path)
                            except:
                                pass
                            print(f'[Bili] 视频转换成功: {video_path}')
                        else:
                            print(f'[Bili] 转换失败，保留原始文件')
                            safe_rename(temp_video_path, video_path)
                            task.error = '视频转换失败，保留原始格式'

                task.status = 'completed'
                task.progress = 100
                task.converting_progress = 100
                print(f'[Bili] 下载完成: {video_path}, 状态: completed')
            else:
                raise Exception('未找到可用的下载地址')

        except Exception as e:
            task.status = 'error'
            task.error = str(e)
            print(f'[Bili] 下载失败 {task.bvid}: {e}, 状态: error')
            import traceback
            traceback.print_exc()
        finally:
            with download_lock:
                active_downloads -= 1


def update_queue_positions():
    with download_lock:
        pending_tasks = [t for t in download_tasks.values() if t.status == 'pending']
        for i, task in enumerate(pending_tasks):
            task.queue_position = i + 1


def start_download(bvid):
    with download_lock:
        if bvid in download_tasks:
            task = download_tasks[bvid]
            if task.status in ['pending', 'downloading', 'fetching', 'merging', 'converting']:
                return task

        if is_video_cached(bvid):
            return None

        try:
            info, cid = get_video_info_sync(bvid)
            title = info.get('title', bvid)

            task = DownloadTask(bvid, title, cid)
            download_tasks[bvid] = task

            pending_count = len([t for t in download_tasks.values() if t.status == 'pending'])
            active_count = len([t for t in download_tasks.values() if t.status in ['downloading', 'fetching', 'converting']])

            if active_count >= MAX_CONCURRENT_DOWNLOADS:
                task.status = 'pending'
                task.queue_position = pending_count + 1
                print(f'[Bili] 下载任务排队中: {bvid}, 队列位置: {task.queue_position}')
            else:
                task.queue_position = 0
                task.status = 'fetching'
                task.progress = 0
                print(f'[Bili] 开始下载任务: {bvid}, 状态已设置为 fetching')
                executor.submit(download_video_task, task)

            return task
        except Exception as e:
            raise Exception(f'启动下载失败: {e}')


def get_download_progress(bvid):
    with download_lock:
        if bvid in download_tasks:
            return download_tasks[bvid].to_dict()
    return None


def get_all_downloads():
    with download_lock:
        return [task.to_dict() for task in download_tasks.values()]


def delete_cached_video(bvid):
    path = get_video_cache_path(bvid)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def get_video_info(bvid):
    info, cid = get_video_info_sync(bvid)
    return info


def cleanup_cache(max_size_mb=None, max_age_days=None):
    """Auto-cleanup cache: remove old/over-limit files."""
    if max_size_mb is None:
        max_size_mb = CACHE_MAX_SIZE_MB
    if max_age_days is None:
        max_age_days = CACHE_MAX_AGE_DAYS

    ensure_bili_dir()
    files = []
    now = time.time()
    max_age_seconds = max_age_days * 86400

    try:
        for fname in os.listdir(BILI_DIR):
            if fname.endswith('.mp4'):
                fpath = os.path.join(BILI_DIR, fname)
                stat = os.stat(fpath)
                files.append({
                    'path': fpath,
                    'name': fname,
                    'size': stat.st_size,
                    'mtime': stat.st_mtime
                })
    except Exception as e:
        print(f'[Bili] 扫描缓存目录失败: {e}')
        return {'deleted': 0, 'freed_bytes': 0}

    deleted = 0
    freed = 0

    # Remove files older than max_age_days
    for f in files[:]:
        if now - f['mtime'] > max_age_seconds:
            try:
                os.remove(f['path'])
                freed += f['size']
                deleted += 1
                files.remove(f)
                print(f'[Bili] 清理过期缓存: {f["name"]}')
            except Exception as e:
                print(f'[Bili] 删除过期文件失败 {f["name"]}: {e}')

    # If total size still exceeds limit, remove oldest first
    total_size = sum(f['size'] for f in files)
    max_bytes = max_size_mb * 1024 * 1024
    if total_size > max_bytes:
        files.sort(key=lambda x: x['mtime'])
        for f in files:
            if total_size <= max_bytes:
                break
            try:
                os.remove(f['path'])
                total_size -= f['size']
                freed += f['size']
                deleted += 1
                print(f'[Bili] 清理超限缓存: {f["name"]} ({format_size(f["size"])})')
            except Exception as e:
                print(f'[Bili] 删除超限文件失败 {f["name"]}: {e}')

    if deleted > 0:
        print(f'[Bili] 缓存清理完成: 删除 {deleted} 个文件, 释放 {format_size(freed)}')
    return {'deleted': deleted, 'freed_bytes': freed, 'freed_display': format_size(freed)}


def cleanup_unused_videos(days=None):
    """清理指定天数内无人观看的视频（可配置，默认7天）"""
    from datetime import datetime, timezone, timedelta
    try:
        from models.bili_video import BiliVideoUser
        from extensions import db
    except ImportError:
        print('[Bili] 无法导入数据库模型，跳过未使用视频清理')
        return {'deleted_count': 0, 'deleted_files': [], 'error': '数据库模块不可用'}
    
    if days is None:
        days = UNUSED_VIDEO_AUTO_CLEANUP_DAYS
    
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    
    print(f'[Bili] 开始清理 {days} 天未观看的视频...')
    
    # 找出所有超过阈值未观看的记录
    unused_records = []
    try:
        unused_records = BiliVideoUser.query.filter(
            BiliVideoUser.last_watched_at < threshold,
            BiliVideoUser.last_watched_at.isnot(None)  # 排除从未观看过的记录
        ).all()
        
        # 也包括 last_watched_at 为 None 且 added_at 超过阈值的记录（添加后从未观看）
        old_new_records = BiliVideoUser.query.filter(
            BiliVideoUser.last_watched_at.is_(None),
            BiliVideoUser.added_at < threshold
        ).all()
        
        unused_records.extend(old_new_records)
    except Exception as e:
        print(f'[Bili] 查询未使用视频失败: {e}')
        return {'deleted_count': 0, 'deleted_files': [], 'error': str(e)}
    
    deleted_files = []
    deleted_count = 0
    
    for record in unused_records:
        bvid = record.bvid
        
        try:
            # 检查是否还有其他用户引用该视频
            other_users_count = BiliVideoUser.query.filter(
                BiliVideoUser.bvid == bvid,
                BiliVideoUser.user_id != record.user_id
            ).count()
            
            if other_users_count == 0:
                # 没有其他用户使用，可以删除文件和记录
                filepath = os.path.join(BILI_DIR, f'{bvid}.mp4')
                
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        deleted_files.append(bvid)
                        print(f'[Bili] 已删除未使用视频文件: {bvid}.mp4')
                    except Exception as e:
                        print(f'[Bili] 删除文件失败 {bvid}: {e}')
            
            # 删除用户的记录（无论文件是否被删除）
            db.session.delete(record)
            deleted_count += 1
            
        except Exception as e:
            print(f'[Bili] 处理未使用视频记录失败 {record.id}: {e}')
    
    # 提交所有更改
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'[Bili] 清理未使用视频提交失败: {e}')
        return {'deleted_count': 0, 'deleted_files': [], 'error': f'提交失败: {str(e)}'}
    
    result = {
        'deleted_count': deleted_count,
        'deleted_files': deleted_files,
        'deleted_files_count': len(deleted_files)
    }
    
    if deleted_count > 0 or len(deleted_files) > 0:
        print(f'[Bili] 未使用视频清理完成: 删除 {deleted_count} 条记录, 删除 {len(deleted_files)} 个文件')
    
    return result


def start_cache_cleanup_scheduler():
    """Start a background thread that periodically cleans cache."""
    global _cleanup_thread, _cleanup_running
    if _cleanup_running:
        return
    _cleanup_running = True

    def _run():
        print('[Bili] 缓存自动清理已启动')
        while _cleanup_running:
            time.sleep(CACHE_CHECK_INTERVAL)
            try:
                # 执行常规缓存清理（基于文件大小和年龄）
                result = cleanup_cache()
                if result['deleted'] > 0:
                    print(f'[Bili] 定期清理: {result}')
                
                # 执行未使用视频清理（基于观看时间）
                unused_result = cleanup_unused_videos()
                if unused_result.get('deleted_count', 0) > 0 or len(unused_result.get('deleted_files', [])) > 0:
                    print(f'[Bili] 未使用视频定期清理: {unused_result}')
                    
            except Exception as e:
                print(f'[Bili] 定期清理异常: {e}')

    _cleanup_thread = threading.Thread(target=_run, daemon=True)
    _cleanup_thread.start()


def stop_cache_cleanup_scheduler():
    global _cleanup_running
    _cleanup_running = False


def terminate_all_ffmpeg_processes():
    """终止所有活跃的 FFmpeg 转换进程（程序退出时调用）"""
    global active_ffmpeg_processes
    
    if not active_ffmpeg_processes:
        print('[Bili] 没有活跃的 FFmpeg 进程需要终止')
        return {'terminated_count': 0, 'errors': []}
    
    print(f'[Bili] 正在终止 {len(active_ffmpeg_processes)} 个 FFmpeg 进程...')
    
    terminated_count = 0
    errors = []
    
    for bvid, process in list(active_ffmpeg_processes.items()):
        try:
            if process.poll() is None:  # 进程仍在运行
                print(f'[Bili] 终止 FFmpeg 进程: {bvid} (PID: {process.pid})')
                
                # 先尝试优雅终止 (terminate)
                process.terminate()
                
                try:
                    # 等待最多5秒让进程正常退出
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 超时，强制杀死进程 (kill)
                    print(f'[Bili] 优雅终止超时，强制杀死进程: {bvid}')
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except:
                        pass
                
                terminated_count += 1
            else:
                print(f'[Bili] 进程已结束: {bvid}')
                terminated_count += 1
            
            del active_ffmpeg_processes[bvid]
            
        except Exception as e:
            error_msg = f'终止 FFmpeg 进程失败 {bvid}: {e}'
            errors.append(error_msg)
            print(f'[Bili] {error_msg}')
    
    result = {
        'terminated_count': terminated_count,
        'total_tracked': len(active_ffmpeg_processes) + terminated_count,
        'errors': errors
    }
    
    if terminated_count > 0:
        print(f'[Bili] FFmpeg 进程终止完成: 成功终止 {terminated_count} 个进程')
        if errors:
            print(f'[Bili] 错误数量: {len(errors)}')
    
    return result


# Auto-start cache cleanup on import (runs once on first load)
start_cache_cleanup_scheduler()
