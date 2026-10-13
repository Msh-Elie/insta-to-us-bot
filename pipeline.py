"""Téléchargement + traduction : lien Insta -> (vidéo au nom court, caption EN)."""

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import yt_dlp
from deep_translator import GoogleTranslator

WORKDIR = Path(os.getenv("WORKDIR", "/tmp/insta-bot"))
COOKIES = os.getenv("IG_COOKIES_FILE", "/etc/secrets/cookies.txt")  # chemin d'un cookies.txt (Secret File Render), optionnel


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
        # Render monte les Secret Files en lecture seule : yt-dlp a besoin d'une copie modifiable
        copie = WORKDIR / "cookies.txt"
        shutil.copyfile(COOKIES, copie)
        opts["cookiefile"] = str(copie)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        chemin = Path(ydl.prepare_filename(info))
    caption = info.get("description") or ""
    return chemin, caption


DEEPL_KEY = os.getenv("DEEPL_API_KEY", "")  # optionnel : clé DeepL gratuite, plus fiable


def _deepl(texte: str) -> str:
    hote = "api-free.deepl.com" if DEEPL_KEY.endswith(":fx") else "api.deepl.com"
    r = requests.post(
        f"https://{hote}/v2/translate",
        headers={"Authorization": f"DeepL-Auth-Key {DEEPL_KEY}"},
        data={"text": texte, "target_lang": "EN-US"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["translations"][0]["text"]


def _google(texte: str) -> str:
    derniere = None
    for essai in range(3):
        try:
            return GoogleTranslator(source="auto", target="en").translate(texte) or texte
        except Exception as e:  # trop de requêtes, coupure réseau…
            derniere = e
            time.sleep(3 * (essai + 1))
    raise derniere


def _decouper(texte: str, taille: int = 450) -> list[str]:
    morceaux, courant = [], ""
    for ligne in texte.split("\n"):
        while len(ligne) > taille:  # ligne très longue : on coupe au dernier espace
            coupe = ligne.rfind(" ", 0, taille)
            coupe = coupe if coupe > 0 else taille
            if courant:
                morceaux.append(courant)
                courant = ""
            morceaux.append(ligne[:coupe])
            ligne = ligne[coupe:].lstrip()
        if courant and len(courant) + 1 + len(ligne) > taille:
            morceaux.append(courant)
            courant = ligne
        else:
            courant = f"{courant}\n{ligne}" if courant else ligne
    if courant:
        morceaux.append(courant)
    return morceaux


def _mymemory(texte: str) -> str:
    sorties = []
    for morceau in _decouper(texte):
        if not morceau.strip():
            sorties.append(morceau)
            continue
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": morceau, "langpair": "Autodetect|en"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if int(data.get("responseStatus", 0)) != 200:
            raise RuntimeError(data.get("responseDetails", "MyMemory indisponible"))
        sorties.append(data["responseData"]["translatedText"])
    return "\n".join(sorties)


def _traduire_texte(texte: str) -> str:
    services = ([("DeepL", _deepl)] if DEEPL_KEY else []) + [("Google", _google), ("MyMemory", _mymemory)]
    erreurs = []
    for nom, fn in services:
        try:
            return fn(texte)
        except Exception as e:
            erreurs.append(f"{nom}: {str(e)[:80]}")
    raise RuntimeError("Traduction indisponible pour le moment (" + " | ".join(erreurs) + "). Réessaie dans quelques minutes.")


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
    traduit = _traduire_texte(texte)
    for cle, val in proteges.items():
        traduit = traduit.replace(cle, val)
    return traduit


def preparer(url: str) -> Post:
    code = extraire_code(url)
    video, caption = telecharger(url, code)
    return Post(code=code, video=video, caption_original=caption, caption_en=traduire(caption))
