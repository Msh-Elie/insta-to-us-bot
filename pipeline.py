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


def _google_gtx(texte: str) -> str:
    """Autre point d'accès Google, souvent moins limité que celui de deep_translator."""
    r = requests.post(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t"},
        data={"q": texte},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


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


def _mymemory(texte: str, source: str) -> str:
    source = source if source and source != "en" else "fr"  # par défaut : français
    sorties = []
    for morceau in _decouper(texte):
        if not morceau.strip():
            sorties.append(morceau)
            continue
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": morceau, "langpair": f"{source}|en"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if int(data.get("responseStatus", 0)) != 200:
            raise RuntimeError(data.get("responseDetails", "MyMemory indisponible"))
        sorties.append(data["responseData"]["translatedText"])
    return "\n".join(sorties)


MOTS_COURANTS = {
    "en": "the and you for with this that are was have your from just not what all our new get love one out more",
    "fr": "le la les des une est et pour avec dans sur pas que qui vous nous mon ma mes ce cette tout bien très merci",
    "es": "el los las una es y para con por que del muy pero como más gracias esta este todo mi tu",
    "pt": "o os uma é e para com não que do da muito mas como mais obrigado esta este tudo meu você",
    "it": "il gli una è e per con non che del della molto ma come più grazie questa questo tutto mio",
    "de": "der die das und ist für mit nicht ein eine auf ich du wir sehr aber wie mehr danke",
}


def detecter_langue(texte: str) -> str:
    """Devine la langue (en, fr, es, pt, it, de) avec les mots les plus courants ; '' si incertain."""
    propre = re.sub(r"ZXQ\d+QXZ|https?://\S+", " ", texte.lower())
    mots = re.findall(r"[a-zà-ÿ]+", propre)
    if not mots:
        return ""
    scores = {lang: sum(m in set(liste.split()) for m in mots) for lang, liste in MOTS_COURANTS.items()}
    meilleur = max(scores, key=scores.get)
    return meilleur if scores[meilleur] > 0 else ""


def _traduire_texte(texte: str) -> str:
    source = detecter_langue(texte)
    if not re.search(r"[^\W\d_]", re.sub(r"ZXQ\d+QXZ", "", texte)):
        return texte  # que des emojis / hashtags : rien à traduire
    if source == "en":
        return texte  # déjà en anglais : rien à faire
    services = ([("DeepL", _deepl)] if DEEPL_KEY else []) + [
        ("Google", _google_gtx),
        ("Google bis", _google),
        ("MyMemory", lambda t: _mymemory(t, source)),
    ]
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
