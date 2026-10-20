import os
import asyncio
import uuid
import json
import zipfile
import tempfile
import mimetypes
import shutil
import yt_dlp
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from pydantic import BaseModel

APP_VERSION = "1.0.4"
app = FastAPI(title="Nimbus Web Downloader", version=APP_VERSION)

# Configuration
DEFAULT_DOWNLOAD_DIR = "/app/downloads" if os.path.exists("/app") and os.access("/app", os.W_OK) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
DOWNLOAD_DIR = os.getenv("NIMBUS_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
NIMBUS_PASSWORD = os.getenv("NIMBUS_PASSWORD", "nimbus123")  # Default password for testing
COOKIES_PATH_ENV = os.getenv("NIMBUS_COOKIES_FILE")

EXCLUDED_FILENAMES = {"cookies.txt"}
EXCLUDED_EXTENSIONS = {".part", ".ytdl", ".temp", ".tmp"}

def is_managed_media_file(filename: str) -> bool:
    if filename in EXCLUDED_FILENAMES or filename.startswith("."):
        return False
    _, ext = os.path.splitext(filename.lower())
    if ext in EXCLUDED_EXTENSIONS:
        return False
    return True

def get_safe_filepath(filename: str) -> str:
    # Reject empty filename, path separators, null bytes, or hidden files
    if not filename or "/" in filename or "\\" in filename or "\0" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename or safe_name in EXCLUDED_FILENAMES or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    real_dir = os.path.realpath(DOWNLOAD_DIR)
    filepath = os.path.realpath(os.path.join(DOWNLOAD_DIR, safe_name))
    if os.path.commonpath([real_dir, filepath]) != real_dir or filepath == real_dir or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return filepath

def get_cookies_path() -> Optional[str]:
    candidates = []
    if COOKIES_PATH_ENV:
        candidates.append(COOKIES_PATH_ENV)
    candidates.extend([
        os.path.join(DOWNLOAD_DIR, "cookies.txt"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt"),
        "/app/cookies.txt"
    ])
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    return None

def get_writable_cookies_path() -> str:
    if COOKIES_PATH_ENV:
        return COOKIES_PATH_ENV
    return os.path.join(DOWNLOAD_DIR, "cookies.txt")

# Static Assets
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# State
downloads_state = {}
connected_clients: List[WebSocket] = []

# --- Authentication ---
def check_auth(request: Request):
    token = request.cookies.get("nimbus_session")
    if token != NIMBUS_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    return True

def get_auth_optional(request: Request):
    return request.cookies.get("nimbus_session") == NIMBUS_PASSWORD

# --- WebSocket Manager ---
async def broadcast_state():
    if not connected_clients:
        return
    state_json = json.dumps(downloads_state)
    for client in connected_clients:
        try:
            await client.send_text(state_json)
        except Exception:
            pass

class YTDLPLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        print(f"yt-dlp Warning: {msg}")
    def error(self, msg):
        print(f"yt-dlp Error: {msg}")

def download_hook(d, task_id):
    if d['status'] == 'downloading':
        percent_str = d.get('_percent_str', '0%').strip()
        speed_str = d.get('_speed_str', 'N/A').strip()
        eta_str = d.get('_eta_str', 'N/A').strip()
        
        # Clean up ANSI escape codes that yt-dlp sometimes outputs
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        percent_str = ansi_escape.sub('', percent_str)
        speed_str = ansi_escape.sub('', speed_str)
        eta_str = ansi_escape.sub('', eta_str)
        
        downloads_state[task_id].update({
            "status": "downloading",
            "progress_percent": percent_str,
            "speed": speed_str,
            "eta": eta_str
        })
        
        if 'info_dict' in d and d['info_dict'].get('title'):
            downloads_state[task_id]['title'] = d['info_dict']['title']
        elif 'filename' in d and ('title' not in downloads_state[task_id] or downloads_state[task_id]['title'] == 'Fetching metadata...'):
            downloads_state[task_id]['title'] = os.path.splitext(os.path.basename(d['filename']))[0]
            
    elif d['status'] == 'finished':
        downloads_state[task_id].update({
            "status": "finished",
            "progress_percent": "100%",
            "speed": "0MiB/s",
            "eta": "00:00"
        })

def build_ytdlp_format(format_type: str, quality: str = "best"):
    """
    Build yt-dlp format specification and format_sort order.
    Returns: (format_string, format_sort_list)
    """
    if format_type == "audio":
        return "bestaudio/best", []
    
    # Format selection:
    # 1. bestvideo: strictly DASH video stream (not pre-merged 360p format 18).
    # 2. bestaudio: strictly DASH audio stream.
    # 3. Merged together by FFmpeg into MP4 container.
    # 4. Supports both landscape and portrait (Shorts) orientation cleanly.
    quality_map = {
        "best": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/bestvideo[width<=1080]+bestaudio/best[height<=1080]/best[width<=1080]/best",
        "720p": "bestvideo[height<=720]+bestaudio/bestvideo[width<=720]+bestaudio/best[height<=720]/best[width<=720]/best",
        "480p": "bestvideo[height<=480]+bestaudio/bestvideo[width<=480]+bestaudio/best[height<=480]/best[width<=480]/best",
        "360p": "bestvideo[height<=360]+bestaudio/bestvideo[width<=360]+bestaudio/best[height<=360]/best[width<=360]/best",
    }
    
    sort_map = {
        "best": ["res", "fps", "codec:avc:m4a"],
        "1080p": ["res:1080", "fps", "codec:avc:m4a"],
        "720p": ["res:720", "fps", "codec:avc:m4a"],
        "480p": ["res:480", "fps", "codec:avc:m4a"],
        "360p": ["res:360", "fps", "codec:avc:m4a"],
    }
    
    fmt = quality_map.get(quality, quality_map["best"])
    format_sort = sort_map.get(quality, sort_map["best"])
    return fmt, format_sort

def run_download(url: str, format_type: str, quality: str, task_id: str):
    cookies_path = get_cookies_path()

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'logger': YTDLPLogger(),
        'progress_hooks': [lambda d: download_hook(d, task_id)],
        'quiet': False,
        'no_warnings': False,
        'http_headers': {
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    
    if cookies_path:
        ydl_opts['cookiefile'] = cookies_path
        # When cookies are supplied, prioritize web client for full 4K/8K resolution
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['web', 'tv_simply', 'default']
            }
        }
    else:
        # Without cookies, prioritize tv_simply (YouTube TV Cobalt client) which reliably
        # serves 1080p/4K DASH streams without PO token challenges or bot blocks,
        # with web and default fallbacks.
        # DO NOT include 'ios' because iOS client only serves 360p progressive streams.
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['tv_simply', 'web', 'default']
            }
        }
    
    fmt, format_sort = build_ytdlp_format(format_type, quality)
    ydl_opts['format'] = fmt
    if format_sort:
        ydl_opts['format_sort'] = format_sort
    
    if format_type == 'audio':
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Single-pass extraction and download for faster execution and less rate-limiting
            info_dict = ydl.extract_info(url, download=True)
            if info_dict and 'title' in info_dict:
                downloads_state[task_id]['title'] = info_dict['title']
            
        downloads_state[task_id]['status'] = 'completed'
    except Exception as e:
        err_msg = str(e)
        if "Sign in to confirm you're not a bot" in err_msg or "confirm you're not a bot" in err_msg:
            err_msg = "YouTube memerlukan verifikasi bot/login. Silakan tambahkan 'cookies.txt' melalui menu Cookies di atas untuk mengunduh video ini."
        downloads_state[task_id]['status'] = 'error'
        downloads_state[task_id]['error'] = err_msg

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    is_auth = get_auth_optional(request)
    prefix = request.headers.get("x-forwarded-prefix", "")
    return templates.TemplateResponse(request=request, name="index.html", context={"is_auth": is_auth, "app_version": APP_VERSION, "base_path": prefix})

# --- Cookie Management Endpoints ---

@app.get("/api/cookies", dependencies=[Depends(check_auth)])
async def get_cookies_status():
    cookie_file = get_cookies_path()
    if cookie_file and os.path.exists(cookie_file):
        stat = os.stat(cookie_file)
        return {
            "has_cookies": True,
            "path": cookie_file,
            "filename": os.path.basename(cookie_file),
            "size": stat.st_size,
            "updated_at": stat.st_mtime
        }
    return {
        "has_cookies": False,
        "path": None,
        "filename": None,
        "size": 0,
        "updated_at": None
    }

@app.post("/api/cookies/upload", dependencies=[Depends(check_auth)])
async def upload_cookies(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None)
):
    target_path = get_writable_cookies_path()
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    
    saved_bytes = 0
    if file and file.filename:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="File cookies kosong")
        with open(target_path, "wb") as f:
            f.write(file_bytes)
        saved_bytes = len(file_bytes)
    elif content and content.strip():
        text_bytes = content.strip().encode("utf-8")
        with open(target_path, "wb") as f:
            f.write(text_bytes)
        saved_bytes = len(text_bytes)
    else:
        raise HTTPException(status_code=400, detail="Harap pilih file cookies.txt atau tempel teks cookies")
        
    return {
        "status": "ok",
        "message": f"Cookies berhasil disimpan ({saved_bytes} bytes)",
        "path": target_path
    }

@app.delete("/api/cookies", dependencies=[Depends(check_auth)])
async def delete_cookies():
    cookie_file = get_cookies_path()
    if cookie_file and os.path.exists(cookie_file):
        try:
            os.remove(cookie_file)
            return {"status": "ok", "message": "File cookies berhasil dihapus"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gagal menghapus file cookies: {str(e)}")
    return {"status": "ok", "message": "Tidak ada file cookies yang aktif"}

@app.post("/api/login")
async def login(request: Request, password: str = Form(...)):
    prefix = request.headers.get("x-forwarded-prefix", "")
    target = f"{prefix}/" if prefix else "/"
    if password == NIMBUS_PASSWORD:
        response = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
        response.set_cookie(key="nimbus_session", value=password, httponly=True, max_age=86400 * 30, path=prefix or "/")
        return response
    err_target = f"{prefix}/?error=1" if prefix else "/?error=1"
    return RedirectResponse(url=err_target, status_code=status.HTTP_302_FOUND)

@app.post("/api/logout")
async def logout(request: Request):
    prefix = request.headers.get("x-forwarded-prefix", "")
    target = f"{prefix}/" if prefix else "/"
    response = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
    response.delete_cookie("nimbus_session", path=prefix or "/")
    return response

class DownloadRequest(BaseModel):
    url: str
    format: str = "video" # 'video' or 'audio'
    quality: Optional[str] = "best" # 'best', '1080p', '720p', '480p', '360p'

async def download_worker(url: str, format_type: str, quality: str, task_id: str):
    await asyncio.to_thread(run_download, url, format_type, quality, task_id)
    # Retain task status for a grace period so connected WebSocket clients receive final status
    await asyncio.sleep(10)
    downloads_state.pop(task_id, None)

@app.post("/api/download", dependencies=[Depends(check_auth)])
async def start_download(req: DownloadRequest):
    task_id = str(uuid.uuid4())
    downloads_state[task_id] = {
        "id": task_id,
        "url": req.url,
        "title": "Fetching metadata...",
        "status": "starting",
        "progress_percent": "0%",
        "speed": "0MiB/s",
        "eta": "--:--",
        "format": req.format,
        "quality": req.quality or "best"
    }
    
    # Run download worker in a background task
    asyncio.create_task(download_worker(req.url, req.format, req.quality or "best", task_id))
    
    return {"status": "ok", "task_id": task_id}

@app.get("/api/files", dependencies=[Depends(check_auth)])
async def list_files():
    files = []
    if os.path.exists(DOWNLOAD_DIR):
        for filename in os.listdir(DOWNLOAD_DIR):
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(filepath) and is_managed_media_file(filename):
                files.append({
                    "name": filename,
                    "size": os.path.getsize(filepath),
                    "created_at": os.path.getctime(filepath)
                })
    # Sort by newest first
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return {"files": files}

@app.get("/api/system/storage", dependencies=[Depends(check_auth)])
async def get_storage_info():
    total, used, free = shutil.disk_usage(DOWNLOAD_DIR)
    files_count = 0
    files_total_size = 0
    if os.path.exists(DOWNLOAD_DIR):
        for filename in os.listdir(DOWNLOAD_DIR):
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(filepath) and is_managed_media_file(filename):
                files_count += 1
                files_total_size += os.path.getsize(filepath)
    percent = round((used / total) * 100, 1) if total > 0 else 0
    return {
        "disk_total": total,
        "disk_used": used,
        "disk_free": free,
        "disk_used_percent": percent,
        "files_count": files_count,
        "files_total_size": files_total_size
    }

def cleanup_file(filepath: str):
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass

@app.get("/api/files/download/zip", dependencies=[Depends(check_auth)])
async def download_all_zip():
    if not os.path.exists(DOWNLOAD_DIR):
        raise HTTPException(status_code=404, detail="No files available")
    
    files = [f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f)) and is_managed_media_file(f)]
    if not files:
        raise HTTPException(status_code=404, detail="No files available to zip")
        
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip.close()
    
    with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in files:
            filepath = os.path.join(DOWNLOAD_DIR, f)
            zipf.write(filepath, arcname=f)
            
    return FileResponse(
        path=temp_zip.name,
        filename="nimbus_downloads.zip",
        media_type="application/zip",
        background=BackgroundTask(cleanup_file, temp_zip.name)
    )

@app.get("/api/files/{filename:path}", dependencies=[Depends(check_auth)])
async def get_file(filename: str, download: bool = False):
    filepath = get_safe_filepath(filename)
        
    if download:
        return FileResponse(path=filepath, filename=filename, media_type='application/octet-stream')
    else:
        # Guess media type for preview and mobile streaming
        guessed_type, _ = mimetypes.guess_type(filename)
        media_type = guessed_type or ('video/mp4' if filename.endswith('.mp4') else 'audio/mpeg' if filename.endswith('.mp3') else 'application/octet-stream')
        return FileResponse(path=filepath, media_type=media_type)

@app.delete("/api/files", dependencies=[Depends(check_auth)])
async def delete_all_files():
    deleted_count = 0
    if os.path.exists(DOWNLOAD_DIR):
        for filename in os.listdir(DOWNLOAD_DIR):
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(filepath) and is_managed_media_file(filename):
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception:
                    pass
    return {"status": "ok", "deleted_count": deleted_count}

@app.delete("/api/files/{filename:path}", dependencies=[Depends(check_auth)])
async def delete_file(filename: str):
    filepath = get_safe_filepath(filename)
    try:
        os.remove(filepath)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # Simple auth check for WS
    token = websocket.cookies.get("nimbus_session")
    if token != NIMBUS_PASSWORD:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    connected_clients.append(websocket)
    try:
        while True:
            # Send state every 1 second
            await websocket.send_text(json.dumps(downloads_state))
            await asyncio.sleep(1)
    except Exception:
        pass
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
