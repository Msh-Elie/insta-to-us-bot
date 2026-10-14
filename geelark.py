"""Envoi à GeeLark pour publication sur le compte Instagram US (API ouverte GeeLark).

Variables d'environnement (à définir dans Render) :
    GEELARK_TOKEN     token API (client GeeLark > menu GeeHub)
    GEELARK_PHONE_ID  ID du cloud phone où est connecté le compte Instagram US

Étapes :
  1. POST /open/v1/upload/getUrl        -> uploadUrl (valable 30 min) + resourceUrl
  2. PUT  <uploadUrl> avec le fichier   -> la vidéo est hébergée chez GeeLark (3 jours)
  3. POST /open/v1/rpa/task/instagramPubReels       -> réel vidéo
     POST /open/v1/rpa/task/instagramPubReelsImages -> carrousel de photos (publishPost=true)
"""

import hashlib
import os
import time
import uuid
from pathlib import Path

import requests

BASE = "https://openapi.geelark.com/open/v1"
TOKEN = os.getenv("GEELARK_TOKEN", "")      # token OU API Key (GeeHub)
APP_ID = os.getenv("GEELARK_APP_ID", "")    # si renseigné : authentification par clé (API Key + AppId)
PHONE_ID = os.getenv("GEELARK_PHONE_ID", "")
DELAI_PUBLICATION = int(os.getenv("GEELARK_DELAY_SECONDS", "60"))  # publication ~1 min après l'envoi


class GeeLarkError(RuntimeError):
    pass


def est_configure() -> bool:
    return bool(TOKEN and PHONE_ID)


def entetes(trace_id: str | None = None, ts: int | None = None) -> dict:
    trace_id = trace_id or str(uuid.uuid4())
    if not APP_ID:  # authentification par token
        return {"Content-Type": "application/json", "traceId": trace_id, "Authorization": f"Bearer {TOKEN}"}
    # authentification par clé : sign = SHA256(AppId + traceId + ts + nonce + ApiKey) en hexa majuscules
    ts = str(ts if ts is not None else int(time.time() * 1000))
    nonce = trace_id[:6]
    sign = hashlib.sha256(f"{APP_ID}{trace_id}{ts}{nonce}{TOKEN}".encode()).hexdigest().upper()
    return {"Content-Type": "application/json", "appId": APP_ID, "traceId": trace_id,
            "ts": ts, "nonce": nonce, "sign": sign}


def _post(chemin: str, payload: dict) -> dict:
    headers = entetes()
    r = requests.post(f"{BASE}{chemin}", json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise GeeLarkError(f"GeeLark {chemin} -> code {body.get('code')} : {body.get('msg')}")
    return body.get("data") or {}


def envoyer_fichier(fichier: Path) -> str:
    """Héberge un fichier (photo ou vidéo) chez GeeLark et renvoie son resourceUrl."""
    ext = fichier.suffix.lstrip(".").lower() or "mp4"
    data = _post("/upload/getUrl", {"fileType": ext})
    with fichier.open("rb") as f:
        r = requests.put(data["uploadUrl"], data=f, timeout=600)
    if r.status_code != 200:
        raise GeeLarkError(f"Échec de l'envoi de {fichier.name} (HTTP {r.status_code})")
    return data["resourceUrl"]


envoyer_video = envoyer_fichier


def publier(video: Path, caption: str) -> str:
    """Réel vidéo : tâche « Instagram publish Reels video ». Renvoie l'ID de tâche."""
    url_video = envoyer_fichier(video)
    data = _post("/rpa/task/instagramPubReels", {
        "name": f"Repost {video.parent.name}"[:128],
        "scheduleAt": int(time.time()) + DELAI_PUBLICATION,  # timestamp en secondes
        "id": PHONE_ID,
        "description": caption[:2200],
        "video": [url_video],
    })
    return str(data.get("taskId", "?"))


def publier_carrousel(images: list, caption: str) -> str:
    """Carrousel de photos publié comme post classique (publishPost=true), jusqu'à 10 photos."""
    urls = [envoyer_fichier(img) for img in images[:10]]
    data = _post("/rpa/task/instagramPubReelsImages", {
        "name": f"Repost carrousel {images[0].parent.name}"[:128],
        "scheduleAt": int(time.time()) + DELAI_PUBLICATION,
        "id": PHONE_ID,
        "description": caption[:2200],
        "image": urls,
        "publishPost": True,
    })
    return str(data.get("taskId", "?"))
