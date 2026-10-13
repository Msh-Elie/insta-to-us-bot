"""Téléchargement + traduction : lien Insta -> (vidéo au nom court, caption EN)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from deep_translator import GoogleTranslator

WORKDIR = Path(os.getenv("WORKDIR", "/tmp/insta-bot"))
COOKIES = os.getenv("IG_COOKIES_FILE", "")  # chemin d'un cookies.txt (Secret File Render), optionnel


@dataclass
class Post:
    code: str
    video: Path
    caption_original: str
    caption_en: str


def extraire_code(url: str) -> str:
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError("Lien Instagram non reconnu.")
    return m.group(1)


def telecharger(url: str, code: str) -> tuple[Path, str]:
    dossier = WORKDIR / code
    dossier.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dossier / f"post_{code}.%(ext)s"),  # nom court
        "format": "mp4/best",
        "quiet": True,
        "noplaylist": True,
    }
    if COOKIES and Path(COOKIES).exists():
        opts["cookiefile"] = COOKIES
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        chemin = Path(ydl.prepare_filename(info))
    caption = info.get("description") or ""
    return chemin, caption


def traduire(caption: str) -> str:
    """Traduit en anglais en laissant hashtags et @mentions intacts."""
    if not caption.strip():
        return ""
    proteges: dict[str, str] = {}

    def proteger(m):
        cle = f"ZXQ{len(proteges)}QXZ"
        proteges[cle] = m.group(0)
        return cle

    texte = re.sub(r"[#@][\w.]+", proteger, caption)
    traduit = GoogleTranslator(source="auto", target="en").translate(texte) or texte
    for cle, val in proteges.items():
        traduit = traduit.replace(cle, val)
    return traduit


def preparer(url: str) -> Post:
    code = extraire_code(url)
    video, caption = telecharger(url, code)
    return Post(code=code, video=video, caption_original=caption, caption_en=traduire(caption))
