#!/usr/bin/env python3
"""
YouTube Professional Suite v2.0 - ENHANCED
═════════════════════════════════════════════════════════════════════════════
Download Profissional com todas as funcionalidades avançadas do yt-dlp original
  • Múltiplas resoluções e formatos profissionais
  • ProRes 422, DNxHR, H.264 CFR para edição
  • Segment control e trim avançado
  • Suporte a cookies
  • Metadados completos
"""

from __future__ import annotations

import contextlib, io, os, re, shutil, subprocess, sys, threading, unicodedata, csv, json, tempfile, zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import requests, tkinter as tk
from tkinter import filedialog, messagebox

import yt_dlp
from PIL import Image

try:
    from googleapiclient.discovery import build
except ImportError:
    build = None

try:
    import whisper
except ImportError:
    whisper = None

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

LANG: str = "pt"

# ══════════════════════════════════════════════════════════════════════════════
#  YOUTUBE COMMENTS EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

class YouTubeCommentsExtractor:
    """Extrai comentários de vídeos do YouTube"""
    def __init__(self):
        self.api_key = None
        self.youtube = None
        
    def set_api_key(self, api_key):
        if not build:
            raise Exception("Google API não instalada. Instale: pip install google-api-python-client")
        self.api_key = api_key
        self.youtube = build('youtube', 'v3', developerKey=api_key)
        
    def extract_video_id(self, url):
        patterns = [r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', r'(?:embed\/)([0-9A-Za-z_-]{11})', r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})']
        for pattern in patterns:
            if match := re.search(pattern, url):
                return match.group(1)
        return None
    
    def get_video_info(self, video_id):
        try:
            request = self.youtube.videos().list(part='snippet,statistics', id=video_id)
            response = request.execute()
            if response['items']:
                item = response['items'][0]
                return {'title': item['snippet']['title'], 'channel': item['snippet']['channelTitle'],
                        'views': item['statistics'].get('viewCount', 'N/A'),
                        'comments_count': item['statistics'].get('commentCount', 'N/A')}
        except Exception as e:
            raise Exception(f"Erro ao obter info do vídeo: {str(e)}")
        return None
    
    def get_comments(self, video_id, progress_callback=None, max_comments=None):
        comments = []
        next_page_token = None
        
        while True:
            try:
                request = self.youtube.commentThreads().list(part='snippet,replies', videoId=video_id,
                    maxResults=100, pageToken=next_page_token, textFormat='plainText')
                response = request.execute()
                
                for item in response['items']:
                    top_comment = item['snippet']['topLevelComment']['snippet']
                    comments.append({'autor': top_comment['authorDisplayName'], 'texto': top_comment['textDisplay'],
                        'likes': top_comment['likeCount'], 'data': top_comment['publishedAt'][:10], 'tipo': 'principal',
                        'respostas_count': item['snippet']['totalReplyCount']})
                    
                    if 'replies' in item:
                        for reply in item['replies']['comments']:
                            reply_snippet = reply['snippet']
                            comments.append({'autor': reply_snippet['authorDisplayName'], 'texto': reply_snippet['textDisplay'],
                                'likes': reply_snippet['likeCount'], 'data': reply_snippet['publishedAt'][:10],
                                'tipo': 'resposta', 'respostas_count': 0})
                    
                    if max_comments and len(comments) >= max_comments:
                        return comments[:max_comments]
                
                if progress_callback:
                    progress_callback(len(comments))
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
            except Exception as e:
                if 'commentsDisabled' in str(e):
                    raise Exception("Comentários desativados neste vídeo")
                raise e
        return comments

# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO TRANSCRIBER
# ══════════════════════════════════════════════════════════════════════════════

class AudioTranscriber:
    """Transcreve áudio usando Whisper"""
    def __init__(self):
        self.model = None
        self.model_name = "base"
        
    def load_model(self, model_name="base", progress_callback=None):
        if not whisper:
            raise Exception("Whisper não instalado. Instale: pip install openai-whisper")
        if progress_callback:
            progress_callback("Carregando modelo Whisper...")
        self.model_name = model_name
        self.model = whisper.load_model(model_name)
        
    def download_audio_from_youtube(self, url, progress_callback=None):
        if progress_callback:
            progress_callback("Baixando áudio do YouTube...")
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, 'yt_audio_%(id)s.%(ext)s')
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }
        if ff_path := _find_ffmpeg():
            ydl_opts['ffmpeg_location'] = os.path.dirname(ff_path)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info['id']
            video_title = info.get('title', 'Unknown')
            audio_file = os.path.join(temp_dir, f'yt_audio_{video_id}.mp3')
        return audio_file, video_title
    
    def transcribe(self, audio_path, progress_callback=None, language="pt"):
        if not self.model:
            self.load_model(progress_callback=progress_callback)
        _find_ffmpeg()
        if progress_callback:
            progress_callback("Transcrevendo áudio (pode demorar alguns minutos)...")
        result = self.model.transcribe(audio_path, language=language, verbose=False)
        return result
    
    def get_youtube_captions(self, url, progress_callback=None):
        if progress_callback:
            progress_callback("Buscando legendas...")
        try:
            ydl_opts = {
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['pt', 'pt-BR', 'en'],
                'skip_download': True,
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get('subtitles') or info.get('automatic_captions'):
                    return "✅ Legendas encontradas!", info.get('title', 'Unknown')
        except:
            pass
        return None, None
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C, FONTS = {
    "bg": "#0b0b0b", "card": "#141414", "card2": "#1a1a1a", "border": "#262626",
    "accent": "#3b82f6", "ahvr": "#2563eb", "text": "#efefef", "sub": "#666666",
    "success": "#22c55e", "error": "#ef4444", "warn": "#f59e0b", "info": "#38bdf8",
    "purple": "#a78bfa", "gold": "#fbbf24",
}, {
    "mono_lg": ("Courier New", 13, "bold"), "mono_sm": ("Courier New", 11),
    "label": (None, 11, "bold"), "title": (None, 14, "bold"),
}

OUTPUT_PROFILES = {
    "Original (MP4/MKV)": {"ext": None, "description": "H.264/HEVC - compatibilidade máxima",
        "ffmpeg_args": None, "needs_ffmpeg": False, "color": C["info"]},
    "ProRes 422 HQ (DaVinci/Premiere)": {"ext": "mov", "description": "Apple ProRes 422 HQ - edição offline",
        "ffmpeg_args": ["-vcodec", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le", "-acodec", "pcm_s24le"],
        "needs_ffmpeg": True, "color": C["purple"]},
    "DNxHR HQ (DaVinci/Avid)": {"ext": "mov", "description": "Avid DNxHR HQ - edição Windows",
        "ffmpeg_args": ["-vcodec", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p", "-acodec", "pcm_s24le"],
        "needs_ffmpeg": True, "color": C["gold"]},
    "H.264 CFR (DaVinci Free)": {"ext": "mp4", "description": "H.264 + AAC CFR - compatibilidade",
        "ffmpeg_args": ["-vcodec", "libx264", "-preset", "slow", "-crf", "18", "-acodec", "aac", "-b:a", "320k"],
        "needs_ffmpeg": True, "color": C["success"]},
}

FPS_OPTIONS = ["Manter original", "23.976", "24", "25", "29.97", "30", "50", "60"]
AUDIO_FORMATS = ["mp3", "flac", "wav", "aac", "opus", "m4a"]
MAX_HISTORY = 5
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"]
NAME_TEMPLATES = {"Title.ext": "%(title)s.%(ext)s", "[Date] - Title.ext": "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s", "Channel - Title.ext": "%(channel)s - %(title)s.%(ext)s"}

FFMPEG_DIR = Path(__file__).parent / "_ffmpeg"
FFMPEG_EXE = FFMPEG_DIR / "ffmpeg.exe"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_FFMPEG_DOWNLOADING = False

def _try_add_path(dir_path: str):
    if dir_path and dir_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = dir_path + os.pathsep + os.environ.get("PATH", "")

def _auto_download_ffmpeg(status_callback=None) -> Optional[str]:
    global _FFMPEG_DOWNLOADING
    if _FFMPEG_DOWNLOADING:
        return None
    if FFMPEG_EXE.is_file():
        _try_add_path(str(FFMPEG_DIR))
        return str(FFMPEG_EXE)
    try:
        _FFMPEG_DOWNLOADING = True
        if status_callback:
            status_callback("Baixando FFmpeg (82MB)...")
        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = FFMPEG_DIR / "ffmpeg.zip"
        r = requests.get(FFMPEG_URL, stream=True, timeout=60)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if status_callback and total:
                    pct = min(downloaded / total, 1.0)
                    status_callback(f"Baixando FFmpeg... {pct * 100:.0f}%")
        if status_callback:
            status_callback("Extraindo FFmpeg...")
        with zipfile.ZipFile(zip_path, "r") as z:
            for entry in z.namelist():
                if entry.endswith("bin/ffmpeg.exe") or entry.endswith("bin\\ffmpeg.exe"):
                    with z.open(entry) as src, open(FFMPEG_EXE, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                elif entry.endswith("bin/ffprobe.exe") or entry.endswith("bin\\ffprobe.exe"):
                    with z.open(entry) as src, open(FFMPEG_DIR / "ffprobe.exe", "wb") as dst:
                        shutil.copyfileobj(src, dst)
        os.remove(zip_path)
        if FFMPEG_EXE.is_file():
            _try_add_path(str(FFMPEG_DIR))
            if status_callback:
                status_callback("FFmpeg instalado com sucesso!")
            return str(FFMPEG_EXE)
    except Exception as e:
        if status_callback:
            status_callback(f"Falha ao baixar FFmpeg: {str(e)[:60]}")
    finally:
        _FFMPEG_DOWNLOADING = False
    return None

def _find_ffmpeg() -> Optional[str]:
    if FFMPEG_EXE.is_file():
        _try_add_path(str(FFMPEG_DIR))
        return str(FFMPEG_EXE)
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        if found := shutil.which("ffmpeg"):
            return found
    except: pass
    try:
        import imageio_ffmpeg
        if (path := imageio_ffmpeg.get_ffmpeg_exe()) and os.path.isfile(path):
            _try_add_path(os.path.dirname(path))
            return path
    except: pass
    return shutil.which("ffmpeg")

_FFMPEG_PATH, _FFMPEG_CHECKED = None, False

def ffmpeg_ok() -> bool:
    global _FFMPEG_PATH, _FFMPEG_CHECKED
    if not _FFMPEG_CHECKED:
        _FFMPEG_PATH = _find_ffmpeg()
        _FFMPEG_CHECKED = True
    return _FFMPEG_PATH is not None

def open_folder(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

@dataclass
class HistoryEntry:
    title: str
    url: str
    fmt: str
    status: str = "ok"
    ts: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))

class HistoryPanel(ctk.CTkFrame):
    SC, SI = {"ok": C["success"], "error": C["error"], "downloading": C["accent"]}, {"ok": "✔", "error": "✘", "downloading": "⬇"}

    def __init__(self, parent, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"], **kw)
        self.grid_columnconfigure(0, weight=1)
        self._entries, self._rows = [], []
        h = ctk.CTkFrame(self, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(h, text="HISTÓRICO DA SESSÃO", font=ctk.CTkFont(*FONTS["label"]), text_color=C["sub"]).pack(side="left")

    def add_or_update(self, entry: HistoryEntry):
        for i, e in enumerate(self._entries):
            if e.url == entry.url:
                self._entries[i] = entry
                self._redraw()
                return
        self._entries.insert(0, entry)
        if len(self._entries) > MAX_HISTORY:
            self._entries.pop()
        self._redraw()

    def _redraw(self):
        [row.destroy() for row in self._rows]
        self._rows.clear()
        for idx, e in enumerate(self._entries):
            row = ctk.CTkFrame(self, fg_color=C["card2"] if idx % 2 == 0 else C["card"], corner_radius=0)
            row.grid(row=idx + 1, column=0, sticky="ew")
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=self.SI.get(e.status, "?"), font=ctk.CTkFont(size=13, weight="bold"),
                text_color=self.SC.get(e.status, C["sub"]), width=24).grid(row=0, column=0, padx=(10, 4), pady=5)
            ctk.CTkLabel(row, text=(e.title[:50] + "…") if len(e.title) > 50 else e.title, anchor="w",
                font=ctk.CTkFont(size=11), text_color=C["text"]).grid(row=0, column=1, sticky="ew")
            ctk.CTkLabel(row, text=f"{e.fmt}  {e.ts}", font=ctk.CTkFont(size=10), text_color=C["sub"]).grid(row=0, column=2, padx=(4, 12))
            self._rows.append(row)

class YouTubeSuite(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("yt-dlp - Post-Production Edition v4")
        self.geometry("1100x900")
        self.minsize(1000, 750)
        self.configure(fg_color=C["bg"])
        
        self.dest_folder = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.format_choice = tk.StringVar(value="video")
        self.resolution = tk.StringVar(value="1080p")
        self.audio_format = tk.StringVar(value="mp3")
        self.container = tk.StringVar(value="mp4")
        self.output_profile = tk.StringVar(value="Original (MP4/MKV)")
        self.target_fps = tk.StringVar(value="Manter original")
        self.name_template = tk.StringVar(value="Title.ext")
        
        self.embed_subs = tk.BooleanVar(value=False)
        self.embed_meta = tk.BooleanVar(value=True)
        self.embed_thumb = tk.BooleanVar(value=True)
        self.dl_playlist = tk.BooleanVar(value=False)
        self.remove_silence = tk.BooleanVar(value=False)
        self.video_only = tk.BooleanVar(value=False)
        self.audio_wav_pcm = tk.BooleanVar(value=False)
        self.login_browser = tk.StringVar(value="")
        self.browser_profile = tk.StringVar(value="")
        
        self.pl_start = tk.StringVar(value="")
        self.pl_end = tk.StringVar(value="")
        self.trim_start = tk.StringVar(value="")
        self.trim_end = tk.StringVar(value="")
        
        self._is_downloading = False
        self._is_analyzing = False
        self._transcribe_running = False
        
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0, height=50)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr, text="▼  YouTube Professional Suite", font=ctk.CTkFont("Courier New", 18, "bold"),
            text_color=C["accent"]).grid(row=0, column=0, padx=20, pady=10)
        ctk.CTkLabel(hdr, text="v2.0 - Download | Comments | Transcription", font=ctk.CTkFont(size=11),
            text_color=C["sub"]).grid(row=0, column=1, sticky="w")
        self.ffmpeg_badge = ctk.CTkButton(hdr, text="  FFmpeg OK  " if ffmpeg_ok() else "  DOWNLOAD FFMPEG  ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#192619" if ffmpeg_ok() else "#2a1616",
            text_color=C["success"] if ffmpeg_ok() else C["error"],
            hover_color="#2a3a2a" if ffmpeg_ok() else "#3a1a1a",
            corner_radius=6, height=24,
            state="disabled" if ffmpeg_ok() else "normal",
            command=self._download_ffmpeg_action)
        self.ffmpeg_badge.grid(row=0, column=2, padx=(0, 16))
        
        # Status bar
        self.global_status = ctk.CTkLabel(self, text="  Pronto.",
            font=ctk.CTkFont(size=11), text_color=C["sub"],
            fg_color=C["card2"], anchor="w", height=22)
        self.global_status.grid(row=1, column=0, sticky="ew")
        
        # Tab View
        self.tabview = ctk.CTkTabview(self, fg_color=C["bg"], text_color=C["text"],
            text_color_disabled=C["sub"], segmented_button_fg_color=C["card"],
            segmented_button_selected_color=C["accent"], segmented_button_selected_hover_color=C["ahvr"])
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        self.tabview.add("Download")
        self.tabview.add("Comments")
        self.tabview.add("Transcription")
        
        # Setup each tab
        body = ctk.CTkScrollableFrame(self.tabview.tab("Download"), fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)

        def card(title, hint=""):
            f = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
            f.grid_columnconfigure(0, weight=1)
            f.pack(fill="x", padx=16, pady=(0, 10))
            h = ctk.CTkFrame(f, fg_color="transparent")
            h.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
            ctk.CTkLabel(h, text=title, font=ctk.CTkFont(*FONTS["label"]), text_color=C["sub"]).pack(side="left")
            if hint:
                ctk.CTkLabel(h, text=f"  {hint}", font=ctk.CTkFont(size=10), text_color="#363636").pack(side="left")
            return f

        # URL
        f = card("VIDEO / PLAYLIST URL")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(r, placeholder_text="Paste URL here...",
            fg_color="#0d0d0d", border_color=C["border"], text_color=C["text"],
            height=42, font=ctk.CTkFont(size=13), corner_radius=8)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.url_entry.bind("<Return>", lambda _: self._analyze_thread())
        self.analyze_btn = ctk.CTkButton(r, text="Analyze", width=110, height=42,
            fg_color=C["accent"], hover_color=C["ahvr"],
            font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8,
            command=self._analyze_thread)
        self.analyze_btn.grid(row=0, column=1)

        # Info
        f = card("VIDEO INFORMATION")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(1, weight=1)
        self.thumb_label = ctk.CTkLabel(r, text="no\npreview", width=160, height=90,
            fg_color="#0d0d0d", corner_radius=8, font=ctk.CTkFont(size=10), text_color="#2a2a2a")
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=(0, 14))
        self.lbl_title = ctk.CTkLabel(r, text="—", anchor="w", wraplength=650,
            font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"])
        self.lbl_title.grid(row=0, column=1, sticky="ew", pady=(0, 3))
        self.lbl_channel = ctk.CTkLabel(r, text="Channel: —", anchor="w",
            font=ctk.CTkFont(size=12), text_color=C["sub"])
        self.lbl_channel.grid(row=1, column=1, sticky="ew")
        self.lbl_duration = ctk.CTkLabel(r, text="Duration: —", anchor="w",
            font=ctk.CTkFont(size=12), text_color=C["sub"])
        self.lbl_duration.grid(row=2, column=1, sticky="ew", pady=(3, 0))

        # Segments
        f = card("SEGMENT CONTROL", "— select parts of the playlist or video")
        r1 = ctk.CTkFrame(f, fg_color="transparent")
        r1.grid(row=1, column=0, sticky="ew", padx=14, pady=(5, 5))
        ctk.CTkLabel(r1, text="Playlist (Index):", font=ctk.CTkFont(size=12),
            text_color=C["sub"], width=110, anchor="w").pack(side="left")
        ctk.CTkLabel(r1, text="From:", font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.pl_start, placeholder_text="1", width=60, height=28).pack(side="left", padx=5)
        ctk.CTkLabel(r1, text="To:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 0))
        ctk.CTkEntry(r1, textvariable=self.pl_end, placeholder_text="5", width=60, height=28).pack(side="left", padx=5)
        ctk.CTkLabel(r1, text=" (empty = all)", font=ctk.CTkFont(size=10), text_color="#3a3a3a").pack(side="left", padx=10)
        
        r2 = ctk.CTkFrame(f, fg_color="transparent")
        r2.grid(row=2, column=0, sticky="ew", padx=14, pady=(5, 12))
        ctk.CTkLabel(r2, text="Trim (Time):", font=ctk.CTkFont(size=12),
            text_color=C["sub"], width=110, anchor="w").pack(side="left")
        ctk.CTkLabel(r2, text="Start:", font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkEntry(r2, textvariable=self.trim_start, placeholder_text="00:00:00", width=90, height=28).pack(side="left", padx=5)
        ctk.CTkLabel(r2, text="End:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 0))
        ctk.CTkEntry(r2, textvariable=self.trim_end, placeholder_text="00:05:00", width=90, height=28).pack(side="left", padx=5)
        ctk.CTkLabel(r2, text=" Format: HH:MM:SS or seconds (e.g. 01:30)",
            font=ctk.CTkFont(size=10), text_color=C["warn"]).pack(side="left", padx=10)

        # Format
        f = card("BASE FORMAT")
        tr = ctk.CTkFrame(f, fg_color="transparent")
        tr.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for lbl, val in [("Video", "video"), ("Audio Only", "audio")]:
            ctk.CTkRadioButton(tr, text=lbl, variable=self.format_choice, value=val,
                font=ctk.CTkFont(size=13), fg_color=C["accent"],
                command=self._toggle_format).pack(side="left", padx=(0, 20))
        
        self._video_opts_row = ctk.CTkFrame(f, fg_color="transparent")
        self._video_opts_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        ctk.CTkLabel(self._video_opts_row, text="Resolution:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        ctk.CTkOptionMenu(self._video_opts_row,
            values=["2160p (4K)", "1440p", "1080p", "720p", "480p", "360p", "Best available"],
            variable=self.resolution, fg_color="#1c1c1c", button_color=C["accent"],
            font=ctk.CTkFont(size=12), width=165).pack(side="left", padx=(0, 14))
        ctk.CTkLabel(self._video_opts_row, text="Container:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        ctk.CTkOptionMenu(self._video_opts_row, values=["mp4", "mkv"], variable=self.container,
            fg_color="#1c1c1c", button_color=C["accent"], font=ctk.CTkFont(size=12), width=90).pack(side="left")

        self._audio_opts_row = ctk.CTkFrame(f, fg_color="transparent")
        ctk.CTkLabel(self._audio_opts_row, text="Format:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        ctk.CTkOptionMenu(self._audio_opts_row, values=AUDIO_FORMATS, variable=self.audio_format,
            fg_color="#1c1c1c", button_color=C["accent"], font=ctk.CTkFont(size=12), width=110).pack(side="left")

        nr = ctk.CTkFrame(f, fg_color="transparent")
        nr.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 12))
        ctk.CTkLabel(nr, text="Name template:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(nr, values=list(NAME_TEMPLATES.keys()), variable=self.name_template,
            fg_color="#1c1c1c", button_color=C["accent"], font=ctk.CTkFont(size=12), width=200).pack(side="left")

        # Professional
        f = card("PROFESSIONAL OUTPUT PROFILE", "— codec / container optimized for editing")
        pr = ctk.CTkFrame(f, fg_color="transparent")
        pr.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 0))
        ctk.CTkLabel(pr, text="Profile:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._profile_menu = ctk.CTkOptionMenu(pr, values=list(OUTPUT_PROFILES.keys()),
            variable=self.output_profile, fg_color="#1c1c1c", button_color=C["accent"],
            font=ctk.CTkFont(size=12), width=280, command=self._on_profile_change)
        self._profile_menu.pack(side="left")
        self._profile_badge = ctk.CTkLabel(pr, text="", font=ctk.CTkFont(size=10, weight="bold"),
            corner_radius=5, padx=8, pady=2)
        self._profile_badge.pack(side="left", padx=(10, 0))
        
        self._profile_desc = ctk.CTkLabel(f, text="", anchor="w",
            font=ctk.CTkFont(size=11), text_color="#4a4a4a")
        self._profile_desc.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 0))
        
        fr = ctk.CTkFrame(f, fg_color="transparent")
        fr.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 0))
        ctk.CTkLabel(fr, text="FPS / CFR:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(fr, values=FPS_OPTIONS, variable=self.target_fps,
            fg_color="#1c1c1c", button_color=C["accent"], font=ctk.CTkFont(size=12), width=160).pack(side="left")
        self._fps_hint = ctk.CTkLabel(fr, text="", font=ctk.CTkFont(size=10), text_color="#3a3a3a")
        self._fps_hint.pack(side="left")
        self.target_fps.trace_add("write", self._update_fps_hint)

        cr = ctk.CTkFrame(f, fg_color="transparent")
        cr.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 14))
        pro_checks = [
            (self.video_only, "Video Only (no audio)", "B-Roll — max resolution"),
            (self.remove_silence, "Remove Start/End Silence", "silenceremove via FFmpeg"),
            (self.audio_wav_pcm, "Audio WAV PCM 24-bit", "DaVinci Resolve fix"),
        ]
        for var, txt, hint in pro_checks:
            col = ctk.CTkFrame(cr, fg_color="transparent")
            col.pack(side="left", padx=(0, 24))
            ctk.CTkCheckBox(col, text=txt, variable=var, fg_color=C["accent"],
                hover_color=C["ahvr"], font=ctk.CTkFont(size=12)).pack(anchor="w")
            ctk.CTkLabel(col, text=hint, font=ctk.CTkFont(size=9), text_color="#3a3a3a").pack(anchor="w")

        self._on_profile_change(self.output_profile.get())

        # Options
        f = card("EXTRA OPTIONS")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        for txt, var in [("Embed Thumbnail", self.embed_thumb), ("Embed Metadata", self.embed_meta),
                         ("Embed Subtitles", self.embed_subs), ("Full Playlist", self.dl_playlist)]:
            col = ctk.CTkFrame(r, fg_color="transparent")
            col.pack(side="left", padx=(0, 20))
            ctk.CTkCheckBox(col, text=txt, variable=var, fg_color=C["accent"],
                hover_color=C["ahvr"], font=ctk.CTkFont(size=13)).pack(anchor="w")

        r2 = ctk.CTkFrame(f, fg_color="transparent")
        r2.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 12))
        ctk.CTkLabel(r2, text="Navegador para 4K:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(r2, values=["", "Chrome", "Firefox", "Edge", "Brave", "Opera", "Vivaldi", "Chromium"],
            variable=self.login_browser, fg_color="#1c1c1c", button_color=C["accent"],
            font=ctk.CTkFont(size=12), width=130).pack(side="left")
        ctk.CTkLabel(r2, text="vazio = desativado", font=ctk.CTkFont(size=10), text_color="#3a3a3a").pack(side="left", padx=10)

        r3 = ctk.CTkFrame(f, fg_color="transparent")
        r3.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        ctk.CTkLabel(r3, text="Pasta do Perfil:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        ctk.CTkEntry(r3, textvariable=self.browser_profile, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], height=30, font=ctk.CTkFont(size=11),
            corner_radius=6).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(r3, text="...", width=32, height=30, fg_color="#1c1c1c",
            hover_color=C["border"], font=ctk.CTkFont(size=12), corner_radius=6,
            command=lambda: self.browser_profile.set(
                filedialog.askdirectory(initialdir=self.browser_profile.get() or os.path.expanduser("~")) or self.browser_profile.get())
        ).pack(side="right")

        # Destination
        f = card("DESTINATION FOLDER")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(r, textvariable=self.dest_folder, fg_color="#0d0d0d",
            border_color=C["border"], text_color=C["text"], height=34,
            font=ctk.CTkFont(size=12), corner_radius=7).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(r, text="Browse...", width=90, height=34, fg_color="#1c1c1c",
            hover_color=C["border"], font=ctk.CTkFont(size=12), corner_radius=7,
            command=lambda: self.dest_folder.set(
                filedialog.askdirectory(initialdir=self.dest_folder.get()) or self.dest_folder.get())
        ).grid(row=0, column=1)

        # Download
        outer = ctk.CTkFrame(body, fg_color="transparent")
        outer.pack(fill="x", padx=16, pady=(0, 10))
        outer.grid_columnconfigure(0, weight=1)
        self.progress_bar = ctk.CTkProgressBar(outer, fg_color="#1c1c1c",
            progress_color=C["accent"], height=6, corner_radius=3)
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)
        
        st = ctk.CTkFrame(outer, fg_color="transparent")
        st.pack(fill="x")
        st.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(st, text="Waiting...",
            font=ctk.CTkFont("Courier New", 11), text_color=C["sub"], anchor="w")
        self.status_label.pack(side="left")
        self.speed_label = ctk.CTkLabel(st, text="", font=ctk.CTkFont("Courier New", 11),
            text_color=C["sub"], anchor="e")
        self.speed_label.pack(side="right")

        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))
        btn_row.grid_columnconfigure(0, weight=1)
        self.dl_btn = ctk.CTkButton(btn_row, text="DOWNLOAD", height=52, fg_color=C["accent"],
            hover_color=C["ahvr"], font=ctk.CTkFont(size=16, weight="bold"),
            corner_radius=10, command=self._download_thread)
        self.dl_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.open_folder_btn = ctk.CTkButton(btn_row, text="Open Folder", width=130, height=52,
            fg_color="#1c1c1c", hover_color=C["border"], font=ctk.CTkFont(size=13),
            corner_radius=10, state="disabled", command=lambda: open_folder(self.dest_folder.get()))
        self.open_folder_btn.pack(side="right")

        # History
        self.history_panel = HistoryPanel(body)
        self.history_panel.pack(fill="x", padx=16, pady=(0, 16))

        # Log
        lf = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=0, height=140)
        lf.pack(fill="x", padx=16, pady=(0, 16))
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(1, weight=1)
        hrow = ctk.CTkFrame(lf, fg_color="transparent")
        hrow.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(hrow, text="LOG / PIPELINE", font=ctk.CTkFont("Courier New", 11, "bold"),
            text_color=C["sub"]).pack(side="left")
        ctk.CTkButton(hrow, text="Clear", width=60, height=22, fg_color="transparent",
            hover_color=C["border"], font=ctk.CTkFont(size=10), text_color=C["sub"],
            command=self._clear_log).pack(side="right")
        self.log_box = ctk.CTkTextbox(lf, fg_color="#080808", text_color="#999999",
            font=ctk.CTkFont("Courier New", 11), corner_radius=0, border_width=0)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")
        
        # Setup other tabs
        self._setup_comments_tab()
        self._setup_transcription_tab()

    def _build_ydl_opts(self) -> dict:
        """Build yt-dlp options with professional quality settings"""
        dest = self.dest_folder.get()
        fmt = self.format_choice.get()
        res = self.resolution.get()
        cont = self.container.get()
        aud = self.audio_format.get()
        profile = self.output_profile.get()
        fps_val = self.target_fps.get()
        prof_cfg = OUTPUT_PROFILES.get(profile, OUTPUT_PROFILES["Original (MP4/MKV)"])
        
        tmpl = NAME_TEMPLATES.get(self.name_template.get(), "%(title)s.%(ext)s")
        outtmpl = os.path.join(dest, tmpl)
        
        # Professional container adjustment
        final_ext = prof_cfg.get("ext") or cont
        if self.audio_wav_pcm.get() and final_ext == "mp4":
            final_ext = "mov"
        
        # Download format
        video_only = self.video_only.get() and fmt == "video"
        res_map = {"2160p (4K)": "2160", "1440p": "1440", "1080p": "1080", "720p": "720", "480p": "480", "360p": "360", "Best available": "0"}
        h = res_map.get(res, "1080")
        
        if fmt == "audio":
            format_str = "ba/b"
        elif video_only:
            format_str = "bv*"
        else:
            format_str = "bv*+ba/b"
        
        # Post-processors for quality
        postprocs = []
        if self.embed_meta.get():
            postprocs.append({"key": "FFmpegMetadata", "add_metadata": True})
        
        if fmt == "audio":
            target_codec = "wav" if self.audio_wav_pcm.get() else aud
            target_quality = "320" if target_codec == "mp3" else "0"
            postprocs.append({"key": "FFmpegExtractAudio", "preferredcodec": target_codec, "preferredquality": target_quality})
        
        is_pro_codec = "ProRes" in profile or "DNxHR" in profile
        if self.embed_thumb.get() and ffmpeg_ok() and not video_only and not is_pro_codec:
            postprocs.append({"key": "EmbedThumbnail"})
        
        if self.embed_subs.get() and not video_only:
            postprocs.append({"key": "FFmpegEmbedSubtitle"})
        
        # FFmpeg arguments for quality
        pp_ffmpeg_args = []
        
        video_filters = []
        if is_pro_codec or fps_val != "Manter original":
            video_filters.append("scale='trunc(iw/2)*2:trunc(ih/2)*2'")
            if fps_val != "Manter original":
                video_filters.append(f"fps={fps_val}")
        
        if video_filters:
            pp_ffmpeg_args += ["-vf", ",".join(video_filters)]
        
        if self.audio_wav_pcm.get() and not video_only:
            pp_ffmpeg_args += ["-acodec", "pcm_s24le"]
        
        prof_args = prof_cfg.get("ffmpeg_args") or []
        for arg_idx, arg in enumerate(prof_args):
            if arg in ["-acodec", "-c:a"] and self.audio_wav_pcm.get():
                continue
            if arg_idx > 0 and prof_args[arg_idx - 1] in ["-acodec", "-c:a"] and self.audio_wav_pcm.get():
                continue
            if arg not in pp_ffmpeg_args:
                pp_ffmpeg_args.append(arg)
        
        if self.remove_silence.get():
            pp_ffmpeg_args += ["-af", "silenceremove=start_periods=1:start_threshold=-60dB:stop_periods=-1:stop_threshold=-60dB"]
        
        if fmt == "video" and ffmpeg_ok():
            postprocs.append({"key": "FFmpegVideoConvertor", "preferedformat": final_ext})
        
        # Build final options
        ff_path = _find_ffmpeg()
        opts = {
            "format": format_str,
            "outtmpl": outtmpl,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "noplaylist": not self.dl_playlist.get(),
            "writesubtitles": self.embed_subs.get() and not video_only,
            "embedsubtitles": self.embed_subs.get() and not video_only,
            "writethumbnail": self.embed_thumb.get() and not video_only,
            "postprocessors": postprocs,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "http_headers": {"User-Agent": USER_AGENTS[0]},
            "add_metadata": True,
            "merge_output_format": final_ext,
            "extractor_args": {"youtube": {"player_client": ["ios", "android_vr"]}},
        }
        
        if ff_path:
            opts["ffmpeg_location"] = os.path.dirname(ff_path)

        if self.login_browser.get():
            browser = self.login_browser.get().lower()
            profile = self.browser_profile.get().strip()
            if profile:
                opts["cookiesfrombrowser"] = (browser, profile)
            else:
                opts["cookiesfrombrowser"] = (browser,)

        if h != "0" and fmt != "audio":
            opts["format_sort"] = [f"res:{h}"]

        opts["postprocessor_args"] = {}
        
        if fmt == "audio":
            opts["postprocessor_args"]["ExtractAudio"] = ["-ar", "48000", "-id3v2_version", "3"]
        
        if pp_ffmpeg_args:
            opts["postprocessor_args"]["VideoConvertor"] = pp_ffmpeg_args
            if not video_only:
                opts["postprocessor_args"]["ExtractAudio"] = opts["postprocessor_args"].get("ExtractAudio", []) + pp_ffmpeg_args
        
        # Playlist items (segment control)
        pl_s = self.pl_start.get().strip()
        pl_e = self.pl_end.get().strip()
        if pl_s or pl_e:
            try:
                start_idx = int(pl_s) if pl_s else None
                end_idx = int(pl_e) if pl_e else None
                if start_idx is not None and end_idx is not None:
                    opts["playlist_items"] = f"{start_idx}-{end_idx}"
                elif start_idx is not None:
                    opts["playlist_items"] = f"{start_idx}-"
                elif end_idx is not None:
                    opts["playlist_items"] = f"-{end_idx}"
            except ValueError:
                pass
        
        # Trim with FFmpeg (time-based)
        t_start = self.trim_start.get().strip()
        t_end = self.trim_end.get().strip()
        
        if t_start or t_end:
            opts["external_downloader"] = "ffmpeg"
            ffmpeg_i_args = []
            if t_start:
                ffmpeg_i_args.extend(["-ss", t_start])
            if t_end:
                ffmpeg_i_args.extend(["-to", t_end])
            opts["external_downloader_args"] = {"ffmpeg_i": ffmpeg_i_args}
            opts["fixup"] = "force"
            if "ffmpeg" not in opts["postprocessor_args"]:
                opts["postprocessor_args"]["ffmpeg"] = []
            opts["postprocessor_args"]["ffmpeg"].extend(["-avoid_negative_ts", "make_zero"])
        
        return opts

    def _toggle_format(self):
        if self.format_choice.get() == "video":
            self._audio_opts_row.grid_forget()
            self._video_opts_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        else:
            self._video_opts_row.grid_forget()
            self._audio_opts_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))

    def _on_profile_change(self, name: str):
        prof = OUTPUT_PROFILES.get(name, {})
        color, desc = prof.get("color", C["info"]), prof.get("description", "")
        badge_bg = {"#3b82f6": "#0f2233", "#a78bfa": "#1e1428", "#fbbf24": "#2a1f0a",
                    "#22c55e": "#0f2a14", "#f59e0b": "#2a1e08", "#ef4444": "#2a0f0f"}.get(color, "#1c1c1c")
        self._profile_badge.configure(text=f"  {name.split('(')[0].strip()}  ",
            text_color=color, fg_color=badge_bg)
        self._profile_desc.configure(text=desc)

    def _update_fps_hint(self, *_):
        fps = self.target_fps.get()
        if fps == "Manter original":
            self._fps_hint.configure(text="  Original FPS preserved (VFR)", text_color="#3a3a3a")
        else:
            self._fps_hint.configure(text=f"  CFR re-encode @ {fps} fps", text_color=C["warn"])

    def _log(self, msg: str, log_type: str = "info"):
        """Log with different prefixes based on type"""
        prefix_map = {"info": "ℹ", "success": "✔", "error": "✘", "warn": "⚠", "purple": "◆", "gold": "★"}
        prefix = prefix_map.get(log_type, "•")
        
        def _do():
            self.log_box.configure(state="normal")
            ts = datetime.now().strftime('%H:%M:%S')
            log_line = f"[{ts}] {prefix} {msg}\n"
            self.log_box._textbox.insert("end", log_line)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        with contextlib.suppress(Exception):
            self.after(0, _do)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _analyze_thread(self):
        if self._is_analyzing:
            return
        self._is_analyzing = True
        self.analyze_btn.configure(text="...", state="disabled")
        threading.Thread(target=self._analyze, daemon=True).start()

    def _analyze(self):
        url = self.url_entry.get().strip()
        if not url:
            self._log("Paste a URL first", "warn")
            self._is_analyzing = False
            self.after(0, lambda: self.analyze_btn.configure(text="Analyze", state="normal"))
            return

        self._log(f"Analyzing: {url[:60]}...", "purple")
        try:
            opts = {"quiet": False, "skip_download": True, "http_headers": {"User-Agent": USER_AGENTS[0]}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            is_pl = info.get("_type") == "playlist"
            data = info.get("entries", [{}])[0] if is_pl and info.get("entries") else info

            title = str(data.get("title") or info.get("title") or "—")
            channel = str(data.get("channel") or data.get("uploader") or "—")
            duration = int(data.get("duration") or 0)
            thumb = str(data.get("thumbnail") or "")
            
            m, s = divmod(duration, 60)
            h, m = divmod(m, 60)
            dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

            self.lbl_title.configure(text=title + (" [PLAYLIST]" if is_pl else ""))
            self.lbl_channel.configure(text=f"Channel: {channel}")
            self.lbl_duration.configure(text=f"Duration: {dur_str}")
            self._log(f"OK: {title} [{dur_str}]", "success")

            if thumb:
                threading.Thread(target=self._load_thumb, args=(thumb,), daemon=True).start()

        except Exception as e:
            self._log(f"Error: {str(e)}", "error")
        finally:
            self._is_analyzing = False
            self.after(0, lambda: self.analyze_btn.configure(text="Analyze", state="normal"))

    def _load_thumb(self, url: str):
        try:
            r = requests.get(url, timeout=10)
            img = Image.open(io.BytesIO(r.content)).resize((160, 90))
            ci = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 90))
            self.after(0, lambda: self.thumb_label.configure(image=ci, text=""))
        except:
            pass

    def _download_thread(self):
        if self._is_downloading:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Paste a URL first")
            return

        self._is_downloading = True
        self.dl_btn.configure(text="Downloading...", state="disabled", fg_color="#2a2a2a")
        threading.Thread(target=self._download, args=(url,), daemon=True).start()

    def _download(self, url: str):
        self._log(f"Starting download: {url}", "info")
        profile = self.output_profile.get()
        fps = self.target_fps.get()
        self._log(f"Profile: {profile} | FPS: {fps}", "info")
        if self.video_only.get():
            self._log("B-Roll mode (video only)", "warn")
        if self.audio_wav_pcm.get():
            self._log("WAV PCM fix enabled", "warn")
        
        try:
            opts = self._build_ydl_opts()
            title = "Unknown"
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = str(info.get('title', 'Unknown'))
            except:
                pass
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            entry = HistoryEntry(title=title[:40], url=url, fmt=self._get_format_label(), status="ok")
            self.after(0, lambda e=entry: self.history_panel.add_or_update(e))
            self._log("Download complete!", "success")
            self.after(0, lambda: self.open_folder_btn.configure(state="normal", fg_color="#1c3a1c"))
        except Exception as e:
            self._log(f"Error: {str(e)}", "error")
            entry = HistoryEntry(title="Failed", url=url, fmt=self._get_format_label(), status="error")
            self.after(0, lambda e=entry: self.history_panel.add_or_update(e))
        finally:
            self._is_downloading = False
            self.after(0, lambda: self.dl_btn.configure(text="DOWNLOAD", state="normal", fg_color=C["accent"]))
    
    def _get_format_label(self):
        if self.format_choice.get() == "audio":
            return f"Audio {self.audio_format.get().upper()}"
        else:
            return f"{self.resolution.get()} · {self.output_profile.get().split('(')[0].strip()}"

    def _download_ffmpeg_action(self):
        if _FFMPEG_DOWNLOADING:
            return
        def update_badge(text, color, bg, disabled):
            self.after(0, lambda: self.ffmpeg_badge.configure(text=text, text_color=color, fg_color=bg, state="disabled" if disabled else "normal"))
        def status(msg):
            self.after(0, lambda: self.global_status.configure(text=msg))
            self._log(msg, "info")
        update_badge("  BAIXANDO...  ", C["warn"], "#2a1e08", True)
        status("Iniciando download do FFmpeg...")
        def do_dl():
            result = _auto_download_ffmpeg(status_callback=status)
            if result:
                update_badge("  FFmpeg OK  ", C["success"], "#192619", True)
                status("FFmpeg instalado com sucesso!")
                self._log("FFmpeg instalado localmente!", "success")
            else:
                if FFMPEG_EXE.is_file():
                    update_badge("  FFmpeg OK  ", C["success"], "#192619", True)
                    status("FFmpeg já instalado!")
                else:
                    update_badge("  DOWNLOAD FFMPEG  ", C["error"], "#2a1616", False)
                    status("Clique em DOWNLOAD FFMPEG para baixar automaticamente")
                    self._log("FFmpeg não encontrado. Clique no botão para baixar.", "warn")
        threading.Thread(target=do_dl, daemon=True).start()

    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            total, downloaded = d.get('total_bytes') or d.get('total_bytes_estimate') or 0, d.get('downloaded_bytes', 0)
            pct = downloaded / total if total else 0
            self.after(0, lambda p=pct: self.progress_bar.set(p))
            status_text = f"  Downloading: {pct * 100:.1f}%" if total else "Downloading..."
            self.after(0, lambda t=status_text: self.status_label.configure(text=t))
        elif d['status'] == 'finished':
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self.status_label.configure(text="Processing..."))

    def _setup_comments_tab(self):
        """Setup YouTube Comments extraction tab"""
        body = ctk.CTkScrollableFrame(self.tabview.tab("Comments"), fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        
        def card(title, hint=""):
            f = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
            f.grid_columnconfigure(0, weight=1)
            f.pack(fill="x", padx=16, pady=(0, 10))
            h = ctk.CTkFrame(f, fg_color="transparent")
            h.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
            ctk.CTkLabel(h, text=title, font=ctk.CTkFont(*FONTS["label"]), text_color=C["sub"]).pack(side="left")
            if hint:
                ctk.CTkLabel(h, text=f"  {hint}", font=ctk.CTkFont(size=10), text_color="#363636").pack(side="left")
            return f
        
        # ⚠️ Instructions Banner
        instr = ctk.CTkFrame(body, fg_color="#1a2a1a", corner_radius=10, border_width=1, border_color=C["success"])
        instr.grid_columnconfigure(0, weight=1)
        instr.pack(fill="x", padx=16, pady=(0, 10))
        
        title_row = ctk.CTkFrame(instr, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 6))
        ctk.CTkLabel(title_row, text="🔑 Como Obter API Key do YouTube", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C["success"]).pack(side="left")
        
        instr_text = ctk.CTkFrame(instr, fg_color="transparent")
        instr_text.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        
        instructions = """1. Acesse https://console.cloud.google.com
2. Crie um novo projeto (ou selecione um existente)
3. Vá para "APIs e Serviços" → "Biblioteca"
4. Procure por "YouTube Data API v3" e ative
5. Vá para "Credenciais" → "Criar Credencial"
6. Selecione "API Key" e copie
7. Cole a chave no campo abaixo (será mostrada como •••)"""
        
        ctk.CTkLabel(instr_text, text=instructions, justify="left", anchor="nw",
            font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(fill="x", anchor="nw")
        
        # API Key
        f = card("Google API Key", "Sua chave privada (mostrada como •••)")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(0, weight=1)
        api_key = tk.StringVar()
        ctk.CTkEntry(r, textvariable=api_key, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], show="•", height=34, font=ctk.CTkFont(size=12),
            corner_radius=7).grid(row=0, column=0, sticky="ew")
        
        # Video URL
        f = card("Video URL", "YouTube link ou Video ID")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(0, weight=1)
        video_url = tk.StringVar()
        ctk.CTkEntry(r, textvariable=video_url, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], height=34, font=ctk.CTkFont(size=12),
            corner_radius=7).grid(row=0, column=0, sticky="ew")
        
        # Options
        f = card("Opções de Extração")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(1, weight=1)
        
        max_comments = tk.StringVar(value="1000")
        ctk.CTkLabel(r, text="Máx. Comentários:", font=ctk.CTkFont(size=12), text_color=C["text"]).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkEntry(r, textvariable=max_comments, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], width=100, height=32, font=ctk.CTkFont(size=11),
            corner_radius=6).grid(row=0, column=1, sticky="w")
        
        # Export Format
        f = card("Formato de Exportação")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        export_fmt = tk.StringVar(value="CSV")
        for fmt in ["CSV", "JSON", "TXT"]:
            ctk.CTkRadioButton(r, text=fmt, variable=export_fmt, value=fmt,
                font=ctk.CTkFont(size=12), border_color=C["accent"],
                border_width_checked=6).pack(side="left", padx=8)
        
        # Action Buttons
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=10)
        btn_row.grid_columnconfigure(0, weight=1)
        
        status_label = ctk.CTkLabel(btn_row, text="", font=ctk.CTkFont(size=11), text_color=C["sub"])
        status_label.pack(side="left", padx=8)
        
        ctk.CTkButton(btn_row, text="EXTRAIR COMENTÁRIOS", height=44, fg_color=C["accent"],
            hover_color=C["ahvr"], font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8, command=lambda: self._extract_comments(api_key.get(), video_url.get(),
                max_comments.get(), export_fmt.get(), status_label)).pack(side="right")
    
    def _extract_comments(self, api_key, video_url, max_comments, fmt, status_label):
        """Extract comments from YouTube video"""
        if not api_key or not video_url:
            status_label.configure(text="⚠ API Key e URL são obrigatórios", text_color=C["error"])
            return
        
        def do_extract():
            try:
                status_label.configure(text="⏳ Extraindo comentários...", text_color=C["warn"])
                extractor = YouTubeCommentsExtractor()
                extractor.set_api_key(api_key)
                video_id = extractor.extract_video_id(video_url)
                if not video_id:
                    raise Exception("ID do vídeo inválido")
                
                info = extractor.get_video_info(video_id)
                comments = extractor.get_comments(video_id, max_comments=int(max_comments) if max_comments.isdigit() else None)
                
                # Save comments
                dest = filedialog.asksaveasfilename(defaultextension=f".{fmt.lower()}",
                    filetypes=[(f"{fmt} files", f"*.{fmt.lower()}")])
                if dest:
                    if fmt == "CSV":
                        with open(dest, 'w', newline='', encoding='utf-8') as f:
                            writer = csv.DictWriter(f, fieldnames=['autor', 'texto', 'likes', 'data', 'tipo', 'respostas_count'], extrasaction='ignore')
                            writer.writeheader()
                            writer.writerows(comments)
                    elif fmt == "JSON":
                        with open(dest, 'w', encoding='utf-8') as f:
                            json.dump(comments, f, ensure_ascii=False, indent=2)
                    else:  # TXT
                        with open(dest, 'w', encoding='utf-8') as f:
                            f.write(f"Video: {info['title']}\n")
                            f.write(f"Canal: {info['channel']}\n")
                            f.write(f"Comentários: {len(comments)}\n\n")
                            for c in comments:
                                f.write(f"[{c['tipo'].upper()}] {c['autor']} ({c['data']})\n")
                                f.write(f"{c['texto']}\n")
                                f.write(f"Likes: {c['likes']}")
                                if c.get('respostas_count', 0) > 0:
                                    f.write(f" | Respostas: {c['respostas_count']}")
                                f.write("\n\n")
                    
                    status_label.configure(text=f"✅ {len(comments)} comentários salvos!", text_color=C["success"])
                    self._log(f"{len(comments)} comentários extraídos e salvos!", "success")
            except Exception as e:
                status_label.configure(text=f"❌ Erro: {str(e)}", text_color=C["error"])
                self._log(f"Erro na extração: {str(e)}", "error")
        
        threading.Thread(target=do_extract, daemon=True).start()
    
    def _setup_transcription_tab(self):
        """Setup Audio Transcription tab"""
        body = ctk.CTkScrollableFrame(self.tabview.tab("Transcription"), fg_color=C["bg"], corner_radius=0)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        
        def card(title, hint=""):
            f = ctk.CTkFrame(body, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"])
            f.grid_columnconfigure(0, weight=1)
            f.pack(fill="x", padx=16, pady=(0, 10))
            h = ctk.CTkFrame(f, fg_color="transparent")
            h.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
            ctk.CTkLabel(h, text=title, font=ctk.CTkFont(*FONTS["label"]), text_color=C["sub"]).pack(side="left")
            if hint:
                ctk.CTkLabel(h, text=f"  {hint}", font=ctk.CTkFont(size=10), text_color="#363636").pack(side="left")
            return f
        
        # Source
        f = card("Fonte de Áudio", "URL do YouTube ou arquivo local")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        r.grid_columnconfigure(0, weight=1)
        source_url = tk.StringVar()
        ctk.CTkEntry(r, textvariable=source_url, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], height=34, font=ctk.CTkFont(size=12),
            corner_radius=7).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(r, text="Procurar Arquivo...", width=140, height=34, fg_color="#1c1c1c",
            hover_color=C["border"], font=ctk.CTkFont(size=12), corner_radius=7,
            command=lambda: source_url.set(filedialog.askopenfilename(
                filetypes=[("Áudio/Vídeo", "*.mp3 *.wav *.m4a *.mp4 *.mkv"), ("Tudo", "*.*")]) or source_url.get())
        ).grid(row=0, column=1)
        
        # Model Info
        f = card("🤖 Modelo Whisper", "Performance vs Qualidade (carregar pode levar tempo)")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        
        model_info = {
            "tiny": "🚀 Muito rápido (~500MB RAM)",
            "base": "⭐ Recomendado (~1GB RAM)",
            "small": "📊 Mais preciso (~2GB RAM)",
            "medium": "🎯 Alta precisão (~5GB RAM)",
            "large": "🔬 Máxima qualidade (~10GB RAM)"
        }
        
        model = tk.StringVar(value="base")
        for m in ["tiny", "base", "small", "medium", "large"]:
            ctk.CTkRadioButton(r, text=f"{m.upper():6s} - {model_info[m]}", variable=model, value=m,
                font=ctk.CTkFont(size=11), border_color=C["accent"],
                border_width_checked=6).pack(side="left", padx=8, fill="x")
        
        # Language
        f = card("Idioma", "português, english, etc")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        lang = tk.StringVar(value="pt")
        lang_options = ["pt", "en", "es", "fr", "de", "it"]
        for l in lang_options:
            ctk.CTkRadioButton(r, text=l.upper(), variable=lang, value=l,
                font=ctk.CTkFont(size=11), border_color=C["accent"],
                border_width_checked=6).pack(side="left", padx=8)
        
        # Batch Folder
        f = card("LOTE - Transcrever Pasta", "transcreve todos os arquivos de áudio/vídeo com nome automático")
        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        r.grid_columnconfigure(0, weight=1)
        batch_folder = tk.StringVar()
        ctk.CTkEntry(r, textvariable=batch_folder, fg_color="#0d0d0d", border_color=C["border"],
            text_color=C["text"], height=34, font=ctk.CTkFont(size=12),
            corner_radius=7).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(r, text="Procurar Pasta...", width=130, height=34, fg_color="#1c1c1c",
            hover_color=C["border"], font=ctk.CTkFont(size=12), corner_radius=7,
            command=lambda: self._select_batch_folder(batch_folder)
        ).grid(row=0, column=1)

        r2 = ctk.CTkFrame(f, fg_color="transparent")
        r2.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 4))
        ctk.CTkLabel(r2, text="Formato:", text_color=C["sub"],
            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        batch_fmt = tk.StringVar(value="TXT")
        for fmt_lbl in ["TXT", "SRT", "JSON"]:
            ctk.CTkRadioButton(r2, text=fmt_lbl, variable=batch_fmt, value=fmt_lbl,
                font=ctk.CTkFont(size=11), fg_color=C["accent"],
                border_width_checked=6).pack(side="left", padx=8)

        self.batch_file_list = ctk.CTkTextbox(f, fg_color="#080808", text_color="#999999",
            font=ctk.CTkFont("Courier New", 10), corner_radius=6, height=100)
        self.batch_file_list.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 0))
        self.batch_file_list.configure(state="disabled")

        r3 = ctk.CTkFrame(f, fg_color="transparent")
        r3.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 12))
        ctk.CTkButton(r3, text="Escanear Pasta", height=34, fg_color="#1c1c1c",
            hover_color=C["border"], font=ctk.CTkFont(size=12), corner_radius=7,
            command=lambda: self._scan_batch_folder(batch_folder.get())
        ).pack(side="left", padx=(0, 10))
        self.batch_btn = ctk.CTkButton(r3, text="TRANSCREVER LOTE", height=34, fg_color=C["purple"],
            hover_color="#7c3aed", font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=7, state="disabled",
            command=lambda: self._transcribe_batch(model.get(), lang.get(), batch_fmt.get()))
        self.batch_btn.pack(side="left")

        self._batch_files = []

        # Progress section
        outer = ctk.CTkFrame(body, fg_color="transparent")
        outer.pack(fill="x", padx=16, pady=(0, 10))
        outer.grid_columnconfigure(0, weight=1)
        
        # Progress bar
        self.transcribe_progress = ctk.CTkProgressBar(outer, fg_color="#1c1c1c",
            progress_color=C["accent"], height=6, corner_radius=3)
        self.transcribe_progress.pack(fill="x", pady=(0, 8))
        self.transcribe_progress.set(0)
        
        # Status labels
        st = ctk.CTkFrame(outer, fg_color="transparent")
        st.pack(fill="x")
        st.grid_columnconfigure(0, weight=1)
        
        self.transcribe_status = ctk.CTkLabel(st, text="Aguardando...",
            font=ctk.CTkFont("Courier New", 11), text_color=C["sub"], anchor="w")
        self.transcribe_status.pack(side="left")
        
        self.transcribe_detail = ctk.CTkLabel(st, text="",
            font=ctk.CTkFont("Courier New", 10), text_color=C["sub"], anchor="e")
        self.transcribe_detail.pack(side="right")
        
        # Action Buttons
        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=10)
        btn_row.grid_columnconfigure(0, weight=1)
        
        self.transcribe_btn = ctk.CTkButton(btn_row, text="TRANSCREVER", height=44, fg_color=C["accent"],
            hover_color=C["ahvr"], font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=8, command=lambda: self._transcribe(source_url.get(),
                model.get(), lang.get()))
        self.transcribe_btn.pack(side="right")
    
    def _transcribe(self, source, model_name, language):
        """Transcribe audio using Whisper with real-time feedback"""
        if not source:
            self.transcribe_status.configure(text="⚠️  URL ou arquivo obrigatório", text_color=C["error"])
            return
        
        # Ask for save location BEFORE starting thread (prevents Tkinter issues)
        dest = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt"), ("Legendas SRT", "*.srt"), ("JSON", "*.json")])
        
        if not dest:
            return
        
        self.transcribe_btn.configure(state="disabled", fg_color="#2a2a2a")
        self._transcribe_running = True
        
        def update_progress(step, detail=""):
            """Update progress bar and status"""
            progress_map = {"init": 0.1, "load_model": 0.2, "download": 0.3, "transcribe": 0.6, "save": 0.9, "done": 1.0}
            pct = progress_map.get(step, 0.1)
            self.after(0, lambda: self.transcribe_progress.set(pct))
            
            status_map = {
                "init": "⏳ Inicializando...",
                "load_model": "🔄 Carregando modelo Whisper...",
                "download": "📥 Baixando áudio do YouTube...",
                "transcribe": "🎙️  Transcrevendo (isso pode levar)...",
                "save": "💾 Salvando resultado...",
                "done": "✅ Transcrição concluída!"
            }
            status = status_map.get(step, "Processando...")
            self.after(0, lambda: self.transcribe_status.configure(text=status))
            if detail:
                self.after(0, lambda: self.transcribe_detail.configure(text=detail))
        
        def do_transcribe():
            try:
                update_progress("init")
                transcriber = AudioTranscriber()
                
                # Step 1: Load model
                update_progress("load_model", f"Modelo: {model_name}")
                transcriber.load_model(model_name)
                
                # Step 2: Get audio
                if source.startswith("http"):
                    update_progress("download", "YouTube → Áudio")
                    audio_path, title = transcriber.download_audio_from_youtube(source)
                else:
                    update_progress("download", "Arquivo local")
                    audio_path, title = source, "Local Audio"
                
                # Step 3: Transcribe
                update_progress("transcribe", f"Idioma: {language}")
                result = transcriber.transcribe(audio_path, language=language or None)
                
                # Step 4: Save
                update_progress("save")
                
                if dest.endswith('.srt'):
                    with open(dest, 'w', encoding='utf-8') as f:
                        for i, seg in enumerate(result.get('segments', []), 1):
                            h_s = int(seg['start']//3600)
                            m_s = int((seg['start']%3600)//60)
                            s_s = int(seg['start']%60)
                            h_e = int(seg['end']//3600)
                            m_e = int((seg['end']%3600)//60)
                            s_e = int(seg['end']%60)
                            f.write(f"{i}\n{h_s:02d}:{m_s:02d}:{s_s:02d},000 --> {h_e:02d}:{m_e:02d}:{s_e:02d},000\n{seg['text']}\n\n")
                elif dest.endswith('.json'):
                    with open(dest, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                else:
                    with open(dest, 'w', encoding='utf-8') as f:
                        f.write(f"Título: {title}\n")
                        f.write(f"Modelo: {model_name}\n")
                        f.write(f"Idioma: {result.get('language', 'unknown')}\n")
                        f.write(f"Duração: {result.get('duration', 0):.1f}s\n\n")
                        f.write(result.get('text', ''))
                
                update_progress("done")
                self.after(0, lambda: self.transcribe_status.configure(text="✅ Transcrição salva com sucesso!", text_color=C["success"]))
                self._log("Transcrição concluída!", "success")
            except Exception as e:
                error_msg = str(e)[:80]
                self.after(0, lambda: self.transcribe_status.configure(text=f"❌ Erro: {error_msg}", text_color=C["error"]))
                self._log(f"Erro na transcrição: {error_msg}", "error")
            finally:
                self._transcribe_running = False
                self.after(0, lambda: self.transcribe_btn.configure(state="normal", fg_color=C["accent"]))
        
        threading.Thread(target=do_transcribe, daemon=True).start()

    def _select_batch_folder(self, batch_folder_var):
        folder = filedialog.askdirectory(initialdir=batch_folder_var.get() or os.path.expanduser("~"))
        if folder:
            batch_folder_var.set(folder)
            self._scan_batch_folder(folder)

    def _scan_batch_folder(self, folder):
        if not folder:
            return
        AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.flac', '.opus', '.ogg', '.wma', '.aac',
                     '.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv'}
        files = []
        for p in Path(folder).iterdir():
            if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                files.append(p)
        files.sort(key=lambda x: x.name.lower())
        self._batch_files = files

        self.batch_file_list.configure(state="normal")
        self.batch_file_list.delete("1.0", "end")
        if files:
            lines = [f"  {i+1:>3}. {f.name}" for i, f in enumerate(files)]
            self.batch_file_list.insert("end", "\n".join(lines))
            self.batch_file_list.insert("end", f"\n\n  Total: {len(files)} arquivo(s)")
            self.batch_btn.configure(state="normal", fg_color=C["purple"])
            self._log(f"Lote: {len(files)} arquivos encontrados em {folder}", "info")
        else:
            self.batch_file_list.insert("end", "  Nenhum arquivo de áudio/vídeo encontrado na pasta.")
            self.batch_btn.configure(state="disabled", fg_color="#2a2a2a")
            self._log("Nenhum arquivo compatível encontrado na pasta", "warn")
        self.batch_file_list.configure(state="disabled")

    def _transcribe_batch(self, model_name, language, output_fmt):
        files = list(self._batch_files)
        if not files:
            self.transcribe_status.configure(text="Nenhum arquivo no lote", text_color=C["error"])
            return

        self.batch_btn.configure(state="disabled", fg_color="#2a2a2a")
        self.transcribe_btn.configure(state="disabled", fg_color="#2a2a2a")
        self._transcribe_running = True
        total = len(files)

        ext_map = {"TXT": ".txt", "SRT": ".srt", "JSON": ".json"}

        def save_transcription(result, dest_path, fmt, source_name):
            if fmt == "SRT":
                with open(dest_path, 'w', encoding='utf-8') as f:
                    for i, seg in enumerate(result.get('segments', []), 1):
                        h_s = int(seg['start'] // 3600)
                        m_s = int((seg['start'] % 3600) // 60)
                        s_s = int(seg['start'] % 60)
                        h_e = int(seg['end'] // 3600)
                        m_e = int((seg['end'] % 3600) // 60)
                        s_e = int(seg['end'] % 60)
                        f.write(f"{i}\n{h_s:02d}:{m_s:02d}:{s_s:02d},000 --> {h_e:02d}:{m_e:02d}:{s_e:02d},000\n{seg['text']}\n\n")
            elif fmt == "JSON":
                with open(dest_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            else:
                with open(dest_path, 'w', encoding='utf-8') as f:
                    f.write(f"Arquivo: {source_name}\n")
                    f.write(f"Modelo: {model_name}\n")
                    f.write(f"Idioma: {result.get('language', 'unknown')}\n")
                    f.write(f"Duração: {result.get('duration', 0):.1f}s\n\n")
                    f.write(result.get('text', ''))

        def do_batch():
            transcriber = None
            try:
                self.after(0, lambda: self.transcribe_status.configure(text=f"Carregando modelo {model_name}...", text_color=C["warn"]))
                self._log(f"Lote: carregando modelo Whisper '{model_name}'...", "info")
                transcriber = AudioTranscriber()
                transcriber.load_model(model_name)
                self._log(f"Lote: modelo carregado. Iniciando {total} arquivo(s)...", "info")

                for idx, file_path in enumerate(files):
                    self.after(0, lambda i=idx: self.transcribe_progress.set((i) / total))
                    self.after(0, lambda i=idx: self.transcribe_status.configure(
                        text=f"[{i+1}/{total}] Transcrevendo: {file_path.name}"))
                    self.after(0, lambda i=idx: self.transcribe_detail.configure(
                        text=f"Arquivo {i+1} de {total}"))
                    self._log(f"[{idx+1}/{total}] {file_path.name}", "purple")

                    try:
                        result = transcriber.transcribe(str(file_path), language=language or None)
                        out_name = file_path.stem + "_transcricao" + ext_map.get(output_fmt, ".txt")
                        dest_path = file_path.parent / out_name
                        save_transcription(result, dest_path, output_fmt, file_path.name)
                        self._log(f"  Salvo: {dest_path.name}", "success")
                    except Exception as e:
                        self._log(f"  Erro em {file_path.name}: {str(e)[:100]}", "error")

                self.after(0, lambda: self.transcribe_progress.set(1.0))
                self.after(0, lambda: self.transcribe_status.configure(
                    text=f"Lote concluído: {total} arquivo(s) processado(s)!",
                    text_color=C["success"]))
                self.after(0, lambda: self.transcribe_detail.configure(text=""))
                self._log(f"Lote concluído: {total} arquivo(s)", "success")

            except Exception as e:
                error_msg = str(e)[:80]
                self.after(0, lambda: self.transcribe_status.configure(
                    text=f"Erro no lote: {error_msg}", text_color=C["error"]))
                self._log(f"Erro no lote: {error_msg}", "error")
            finally:
                self._transcribe_running = False
                self.after(0, lambda: self.batch_btn.configure(state="normal", fg_color=C["purple"]))
                self.after(0, lambda: self.transcribe_btn.configure(state="normal", fg_color=C["accent"]))

        threading.Thread(target=do_batch, daemon=True).start()

if __name__ == "__main__":
    app = YouTubeSuite()
    app.mainloop()
