"""Téléchargement + traduction : lien Insta -> (médias aux noms courts, caption EN).

Reel / vidéo -> yt-dlp. Post /p/ (carrousel de photos) -> gallery-dl.
"""

import logging
import os
import re
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yt_dlp
from deep_translator import GoogleTranslator

log = logging.getLogger("insta-bot")

WORKDIR = Path(os.getenv("WORKDIR", "/tmp/insta-bot"))
COOKIES = os.getenv("IG_COOKIES_FILE", "/etc/secrets/cookies.txt")  # chemin d'un cookies.txt (Secret File Render), optionnel


EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXT_VIDEOS = {".mp4", ".webm", ".mov"}
MAX_CARROUSEL = 10  # limite GeeLark


@dataclass
class Post:
    code: str
    dossier: Path
    medias: list  # list[Path], dans l'ordre du post
    type: str     # "reel" (une vidéo) ou "carrousel" (photos)
    caption_original: str
    tronque: bool = False
    legendes: dict = field(default_factory=dict)  # {"en": "...", "fr": "..."}

    def legende(self, langue: str) -> str:
        """Légende dans la langue voulue (traduite une seule fois, puis gardée en cache)."""
        if langue not in self.legendes:
            self.legendes[langue] = traduire(self.caption_original, langue)
        return self.legendes[langue]

    @property
    def video(self) -> Path:
        return self.medias[0]


def extraire_code(url: str) -> str:
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError("Lien Instagram non reconnu.")
    return m.group(1)


def _cookies() -> str:
    """Copie modifiable du cookies.txt (Render monte les Secret Files en lecture seule)."""
    if COOKIES and Path(COOKIES).exists():
        WORKDIR.mkdir(parents=True, exist_ok=True)
        copie = WORKDIR / "cookies.txt"
        shutil.copyfile(COOKIES, copie)
        return str(copie)
    return ""


def telecharger_galerie(url: str, code: str) -> tuple[list, str]:
    """Télécharge toutes les photos/vidéos d'un post (carrousel) avec gallery-dl, renommées 01.jpg, 02.jpg…"""
    dossier = WORKDIR / code
    shutil.rmtree(dossier, ignore_errors=True)
    dossier.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "gallery_dl", "-D", str(dossier),
           "-f", "{num}_{media_id}.{extension}", "--write-metadata", "--no-mtime"]
    cookies = _cookies()
    if cookies:
        cmd += ["--cookies", cookies]
    res = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=600)
    fichiers = sorted(
        (f for f in dossier.iterdir() if f.suffix.lower() in EXT_IMAGES | EXT_VIDEOS),
        key=lambda f: (int(f.stem.split("_")[0]) if f.stem.split("_")[0].isdigit() else 0, f.name),
    )
    if not fichiers:
        erreur = (res.stderr or res.stdout or "aucun média trouvé").strip().splitlines()[-1:]
        raise RuntimeError(f"Téléchargement du post impossible : {' '.join(erreur)[:200]}")
    caption = ""
    for meta in sorted(dossier.glob("*.json")):
        try:
            caption = json.loads(meta.read_text(encoding="utf-8")).get("description") or ""
        except Exception:
            continue
        if caption:
            break
    log.info("Post %s : %d média(s) téléchargé(s)", code, len(fichiers))
    medias = []
    for i, f in enumerate(fichiers, 1):  # noms courts : 01.jpg, 02.mp4…
        court = dossier / f"{i:02d}{f.suffix.lower()}"
        f.rename(court)
        medias.append(court)
    for meta in dossier.glob("*.json"):
        meta.unlink(missing_ok=True)
    return medias, caption


def telecharger(url: str, code: str) -> tuple[Path, str]:
    dossier = WORKDIR / code
    dossier.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dossier / f"post_{code}.%(ext)s"),  # nom court
        "format": "mp4/best",
        "quiet": True,
        "noplaylist": True,
    }
    cookies = _cookies()
    if cookies:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        chemin = Path(ydl.prepare_filename(info))
    caption = info.get("description") or ""
    return chemin, caption


DEEPL_KEY = os.getenv("DEEPL_API_KEY", "")  # optionnel : clé DeepL gratuite, plus fiable


def _deepl(texte: str, cible: str) -> str:
    hote = "api-free.deepl.com" if DEEPL_KEY.endswith(":fx") else "api.deepl.com"
    r = requests.post(
        f"https://{hote}/v2/translate",
        headers={"Authorization": f"DeepL-Auth-Key {DEEPL_KEY}"},
        data={"text": texte, "target_lang": "EN-US" if cible == "en" else cible.upper()},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["translations"][0]["text"]


def _google_gtx(texte: str, cible: str) -> str:
    """Autre point d'accès Google, souvent moins limité que celui de deep_translator."""
    r = requests.post(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": cible, "dt": "t"},
        data={"q": texte},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def _google(texte: str, cible: str) -> str:
    derniere = None
    for essai in range(3):
        try:
            return GoogleTranslator(source="auto", target=cible).translate(texte) or texte
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


def _mymemory(texte: str, source: str, cible: str) -> str:
    if not source or source == cible:  # langue inconnue : on suppose l'autre langue du couple fr/en
        source = "fr" if cible == "en" else "en"
    sorties = []
    for morceau in _decouper(texte):
        if not morceau.strip():
            sorties.append(morceau)
            continue
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": morceau, "langpair": f"{source}|{cible}"},
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
    """Devine la langue (en, fr, es, pt, it, de) avec les mots courants ; '' si incertain ou ex aequo."""
    propre = re.sub(r"zxq\d+qxz|https?://\S+", " ", texte.lower())
    mots = re.findall(r"[a-zà-ÿ]+", propre)
    if not mots:
        return ""
    scores = {lang: sum(m in set(liste.split()) for m in mots) for lang, liste in MOTS_COURANTS.items()}
    classes = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (meilleur, s1), (_, s2) = classes[0], classes[1]
    if s1 == 0 or s1 == s2:
        return ""
    return meilleur


def _normaliser(t: str) -> str:
    return re.sub(r"\W+", "", t.lower())


def _traduire_texte(texte: str, cible: str) -> str:
    if not re.search(r"[^\W\d_]", re.sub(r"ZXQ\d+QXZ", "", texte)):
        return texte  # que des emojis / hashtags : rien à traduire
    source = detecter_langue(texte)
    if source == cible:
        return texte  # déjà dans la bonne langue
    services = ([("DeepL", lambda t: _deepl(t, cible))] if DEEPL_KEY else []) + [
        ("Google", lambda t: _google_gtx(t, cible)),
        ("Google bis", lambda t: _google(t, cible)),
        ("MyMemory", lambda t: _mymemory(t, source, cible)),
    ]
    erreurs = []
    for nom, fn in services:
        try:
            resultat = fn(texte)
        except Exception as e:
            erreurs.append(f"{nom}: {str(e)[:80]}")
            continue
        if _normaliser(resultat) == _normaliser(texte):
            erreurs.append(f"{nom}: texte renvoyé non traduit")
            continue
        log.info("Caption traduite en %s via %s", cible, nom)
        return resultat
    raise RuntimeError("Traduction indisponible pour le moment (" + " | ".join(erreurs) + "). Réessaie dans quelques minutes.")


def traduire(caption: str, cible: str = "en") -> str:
    """Traduit la légende (cible : "en" ou "fr") en laissant hashtags et @mentions intacts."""
    if not caption.strip():
        return ""
    proteges: dict[str, str] = {}

    def proteger(m):
        cle = f"ZXQ{len(proteges)}QXZ"
        proteges[cle] = m.group(0)
        return cle

    texte = re.sub(r"[#@][\w.]+", proteger, caption)
    traduit = _traduire_texte(texte, cible)
    for cle, val in proteges.items():
        traduit = traduit.replace(cle, val)
    return traduit


def _construire_post(code: str, medias: list, caption: str) -> Post:
    videos = [m for m in medias if m.suffix.lower() in EXT_VIDEOS]
    if len(medias) == 1 and videos:
        type_post = "reel"
    elif not videos:
        type_post = "carrousel"
    else:
        raise RuntimeError(
            f"Ce carrousel mélange photos et vidéos ({len(medias) - len(videos)} photo(s), {len(videos)} vidéo(s)). "
            "GeeLark ne sait publier que des carrousels de photos ou un réel vidéo."
        )
    tronque = len(medias) > MAX_CARROUSEL
    return Post(code=code, dossier=WORKDIR / code, medias=medias[:MAX_CARROUSEL], type=type_post,
                caption_original=caption or "", tronque=tronque)


def preparer(url: str) -> Post:
    """Lien Instagram -> médias téléchargés (noms courts) + légende d'origine."""
    # On retire « ?img_index=1 », « ?igsh=… » etc. : img_index ferait télécharger une seule photo du carrousel
    url = url.split("#")[0].split("?")[0]
    code = extraire_code(url)
    if re.search(r"instagram\.com/(?:[\w.]+/)?p/", url):
        medias, caption = telecharger_galerie(url, code)
    else:
        video, caption = telecharger(url, code)
        medias = [video]
    return _construire_post(code, medias, caption)


def preparer_video(fichier: Path, code: str, caption: str) -> Post:
    """Vidéo envoyée directement dans Telegram -> même traitement qu'un réel."""
    return _construire_post(code, [fichier], caption)
