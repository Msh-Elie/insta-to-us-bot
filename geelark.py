"""Envoi à GeeLark pour publication sur le compte Instagram US (API ouverte GeeLark).

Variables d'environnement (à définir dans Render) :
    GEELARK_TOKEN     token API (client GeeLark > menu GeeHub)
    GEELARK_PHONE_ID  ID du cloud phone où est connecté le compte Instagram US

Étapes :
  1. POST /open/v1/upload/getUrl        -> uploadUrl (valable 30 min) + resourceUrl
  2. PUT  <uploadUrl> avec le fichier   -> la vidéo est hébergée chez GeeLark (3 jours)
  3. POST /open/v1/rpa/task/instagramPubReels -> tâche de publication sur le cloud phone
"""

import os
import time
import uuid
from pathlib import Path

import requests

BASE = "https://openapi.geelark.com/open/v1"
TOKEN = os.getenv("GEELARK_TOKEN", "")
PHONE_ID = os.getenv("GEELARK_PHONE_ID", "")
DELAI_PUBLICATION = int(os.getenv("GEELARK_DELAY_SECONDS", "60"))  # publication ~1 min après l'envoi


class GeeLarkError(RuntimeError):
    pass


def est_configure() -> bool:
    return bool(TOKEN and PHONE_ID)


def _post(chemin: str, payload: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "traceId": str(uuid.uuid4()),
        "Authorization": f"Bearer {TOKEN}",
    }
    r = requests.post(f"{BASE}{chemin}", json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise GeeLarkError(f"GeeLark {chemin} -> code {body.get('code')} : {body.get('msg')}")
    return body.get("data") or {}


def envoyer_video(video: Path) -> str:
    """Héberge la vidéo chez GeeLark et renvoie son resourceUrl."""
    ext = video.suffix.lstrip(".").lower() or "mp4"
    data = _post("/upload/getUrl", {"fileType": ext})
    with video.open("rb") as f:
        r = requests.put(data["uploadUrl"], data=f, timeout=600)
    if r.status_code != 200:
        raise GeeLarkError(f"Échec de l'envoi de la vidéo (HTTP {r.status_code})")
    return data["resourceUrl"]


def publier(video: Path, caption: str) -> str:
    """Envoie la vidéo puis crée la tâche « Instagram publish Reels video ». Renvoie l'ID de tâche."""
    url_video = envoyer_video(video)
    data = _post("/rpa/task/instagramPubReels", {
        "name": f"Repost {video.stem}"[:128],
        "scheduleAt": int(time.time()) + DELAI_PUBLICATION,  # timestamp en secondes
        "id": PHONE_ID,
        "description": caption[:2200],
        "video": [url_video],
    })
    return str(data.get("taskId", "?"))
