"""Modèles et cloud phones GeeLark associés.

La config vient de la variable d'environnement MODELES_JSON (si elle existe, pratique pour
changer sans toucher au code), sinon du fichier modeles.json du dépôt.

Format :
{
  "Julie": {
    "US": [{"nom": "Julie US 1", "id": "6382..."}, ...],
    "FR": [{"nom": "Julie FR 1", "id": "6382..."}, ...]
  },
  ...
}
Un compte peut aussi être écrit simplement comme "6382..." (juste l'ID).
"""

import json
import os
from pathlib import Path

LANGUE_PAR_PAYS = {"US": "en", "FR": "fr"}
DRAPEAU = {"US": "🇺🇸", "FR": "🇫🇷"}


def charger() -> dict:
    brut = os.getenv("MODELES_JSON", "").strip()
    if not brut:
        brut = (Path(__file__).parent / "modeles.json").read_text(encoding="utf-8")
    data = json.loads(brut)
    modeles = {}
    for modele, pays in data.items():
        comptes = []
        for code_pays, liste in (pays or {}).items():
            code_pays = code_pays.upper()
            for i, c in enumerate(liste or [], 1):
                if isinstance(c, str):
                    c = {"id": c}
                if not str(c.get("id", "")).strip():
                    continue
                comptes.append({
                    "id": str(c["id"]).strip(),
                    "nom": c.get("nom") or f"{modele} {code_pays} {i}",
                    "pays": code_pays,
                    "langue": LANGUE_PAR_PAYS.get(code_pays, "en"),
                })
        modeles[modele] = comptes
    return modeles
