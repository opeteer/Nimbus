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

APP_VERSION = "1.0.1"
app = FastAPI(title="Nimbus Web Downloader", version=APP_VERSION)

# Configuration
DOWNLOAD_DIR = os.getenv("NIMBUS_DOWNLOAD_DIR", "/app/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
NIMBUS_PASSWORD = os.getenv("NIMBUS_PASSWORD", "nimbus123")  # Default password for testing
COOKIES_PATH_ENV = os.getenv("NIMBUS_COOKIES_FILE")

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
        pass
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
        
        if 'filename' in d and 'title' not in downloads_state[task_id]:
            downloads_state[task_id]['title'] = os.path.basename(d['filename'])
            
    elif d['status'] == 'finished':
        downloads_state[task_id].update({
            "status": "finished",
            "progress_percent": "100%",
            "speed": "0MiB/s",
            "eta": "00:00"
        })

def run_download(url: str, format_type: str, task_id: str):
    cookies_path = get_cookies_path()

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'logger': YTDLPLogger(),
        'progress_hooks': [lambda d: download_hook(d, task_id)],
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    
    if cookies_path:
        ydl_opts['cookiefile'] = cookies_path
    
    if format_type == 'audio':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        # Default to best video (MP4)
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info first to get the title quickly
            info_dict = ydl.extract_info(url, download=False)
            downloads_state[task_id]['title'] = info_dict.get('title', 'Unknown Video')
            
            # Then download
            ydl.download([url])
            
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
    return templates.TemplateResponse(request=request, name="index.html", context={"is_auth": is_auth, "app_version": APP_VERSION})

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
async def login(password: str = Form(...)):
    if password == NIMBUS_PASSWORD:
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(key="nimbus_session", value=password, httponly=True, max_age=86400 * 30)
        return response
    return RedirectResponse(url="/?error=1", status_code=status.HTTP_302_FOUND)

@app.post("/api/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("nimbus_session")
    return response

class DownloadRequest(BaseModel):
    url: str
    format: str = "video" # 'video' or 'audio'

async def download_worker(url: str, format_type: str, task_id: str):
    await asyncio.to_thread(run_download, url, format_type, task_id)
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
        "format": req.format
    }
    
    # Run download worker in a background task
    asyncio.create_task(download_worker(req.url, req.format, task_id))
    
    return {"status": "ok", "task_id": task_id}

@app.get("/api/files", dependencies=[Depends(check_auth)])
async def list_files():
    files = []
    if os.path.exists(DOWNLOAD_DIR):
        for filename in os.listdir(DOWNLOAD_DIR):
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(filepath):
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
            if os.path.isfile(filepath):
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
    
    files = [f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))]
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

@app.get("/api/files/{filename}", dependencies=[Depends(check_auth)])
async def get_file(filename: str, download: bool = False):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
        
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
            if os.path.isfile(filepath):
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception:
                    pass
    return {"status": "ok", "deleted_count": deleted_count}

@app.delete("/api/files/{filename}", dependencies=[Depends(check_auth)])
async def delete_file(filename: str):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="File not found")

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
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
