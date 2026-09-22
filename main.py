import os
import asyncio
import uuid
import json
import yt_dlp
from typing import Dict, List
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Nimbus Web Downloader")

# Configuration
DOWNLOAD_DIR = os.getenv("NIMBUS_DOWNLOAD_DIR", "/app/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
NIMBUS_PASSWORD = os.getenv("NIMBUS_PASSWORD", "nimbus123")  # Default password for testing

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
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'logger': YTDLPLogger(),
        'progress_hooks': [lambda d: download_hook(d, task_id)],
        'quiet': True,
        'no_warnings': True,
    }
    
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
        downloads_state[task_id]['status'] = 'error'
        downloads_state[task_id]['error'] = str(e)

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    is_auth = get_auth_optional(request)
    return templates.TemplateResponse("index.html", {"request": request, "is_auth": is_auth})

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
    
    # Run download in a background thread to not block the event loop
    asyncio.create_task(asyncio.to_thread(run_download, req.url, req.format, task_id))
    
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

@app.get("/api/files/{filename}", dependencies=[Depends(check_auth)])
async def get_file(filename: str, download: bool = False):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
        
    if download:
        return FileResponse(path=filepath, filename=filename, media_type='application/octet-stream')
    else:
        # Guess media type for preview
        media_type = 'video/mp4' if filename.endswith('.mp4') else 'audio/mpeg' if filename.endswith('.mp3') else 'application/octet-stream'
        return FileResponse(path=filepath, media_type=media_type)

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
