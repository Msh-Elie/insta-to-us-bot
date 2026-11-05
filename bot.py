"""Bot Telegram : tu envoies un lien Insta (ou une vidéo), tu choisis la modèle,
et le bot programme la publication sur tous ses cloud phones GeeLark :
légende en anglais pour les comptes US, en français pour les comptes FR.

Variables d'environnement :
    TELEGRAM_TOKEN    token donné par @BotFather
    ALLOWED_USER_ID   ton ID Telegram (seul toi peux utiliser le bot)
"""

import asyncio
import logging
import os
import re
import shutil
import time
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import geelark
import modeles
import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("insta-bot")

TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED = int(os.getenv("ALLOWED_USER_ID", "0"))
LIEN_RE = re.compile(r"https?://(?:www\.)?instagram\.com/\S+")
LIMITE_ENVOI_TELEGRAM = 50 * 1024 * 1024      # ce que le bot peut t'envoyer
LIMITE_RECEPTION_TELEGRAM = 20 * 1024 * 1024  # ce que le bot peut télécharger depuis Telegram


def autorise(update: Update) -> bool:
    return bool(ALLOWED) and update.effective_user is not None and update.effective_user.id == ALLOWED


def clavier_modeles(cle: str) -> InlineKeyboardMarkup:
    boutons = []
    for nom, comptes in modeles.charger().items():
        us = sum(c["pays"] == "US" for c in comptes)
        fr = sum(c["pays"] == "FR" for c in comptes)
        libelle = f"{nom} ({us} US · {fr} FR)" if comptes else f"{nom} (aucun compte)"
        boutons.append([InlineKeyboardButton(libelle, callback_data=f"m|{cle}|{nom}")])
    boutons.append([InlineKeyboardButton("❌ Annuler", callback_data=f"x|{cle}|")])
    return InlineKeyboardMarkup(boutons)


async def demander_modele(update: Update, context: ContextTypes.DEFAULT_TYPE, travail: dict):
    cle = uuid.uuid4().hex[:8]
    context.user_data.setdefault("attentes", {})[cle] = travail
    await update.message.reply_text("Pour quelle modèle ?", reply_markup=clavier_modeles(cle))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALLOWED:
        await update.message.reply_text(
            f"Ton ID Telegram est {update.effective_user.id}. Mets-le dans ALLOWED_USER_ID sur Render puis redéploie.")
        return
    if not autorise(update):
        return
    await update.message.reply_text(
        "Prêt. Envoie-moi un lien Instagram (réel ou carrousel) ou directement une vidéo, "
        "puis choisis la modèle.")


async def recevoir_lien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorise(update):
        return
    m = LIEN_RE.search(update.message.text or "")
    if not m:
        await update.message.reply_text("Envoie-moi un lien instagram.com/reel/… ou /p/…, ou une vidéo.")
        return
    await demander_modele(update, context, {"type": "lien", "url": m.group(0)})


async def recevoir_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorise(update):
        return
    msg = update.message
    fichier = msg.video or msg.document
    if fichier.file_size and fichier.file_size > LIMITE_RECEPTION_TELEGRAM:
        await msg.reply_text(
            "❌ Vidéo trop lourde : Telegram ne laisse pas un bot télécharger plus de 20 Mo. "
            "Compresse-la ou envoie plutôt le lien Instagram.")
        return
    await demander_modele(update, context, {
        "type": "video",
        "file_id": fichier.file_id,
        "caption": msg.caption or "",
    })


async def choix_modele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not autorise(update):
        await query.answer()
        return
    action, cle, nom = query.data.split("|", 2)
    attentes = context.user_data.get("attentes", {})

    if action == "x":
        attentes.pop(cle, None)
        await query.answer("Annulé")
        await query.edit_message_text("Annulé.")
        return

    travail = attentes.get(cle)
    if not travail:
        await query.answer("Demande expirée, renvoie le lien ou la vidéo.", show_alert=True)
        return
    comptes = modeles.charger().get(nom, [])
    if not comptes:
        await query.answer(f"{nom} n'a pas encore de compte configuré.", show_alert=True)
        return

    attentes.pop(cle, None)
    await query.answer()
    await query.edit_message_text(f"⏳ {nom} : téléchargement et traduction…")
    await traiter(query, context, travail, nom, comptes)


async def preparer_post(context: ContextTypes.DEFAULT_TYPE, travail: dict):
    if travail["type"] == "lien":
        return await asyncio.to_thread(pipeline.preparer, travail["url"])
    code = "video_" + uuid.uuid4().hex[:8]
    dossier = pipeline.WORKDIR / code
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "01.mp4"
    fichier = await context.bot.get_file(travail["file_id"])
    await fichier.download_to_drive(custom_path=str(chemin))
    return pipeline.preparer_video(chemin, code, travail["caption"])


async def traiter(query, context, travail: dict, nom: str, comptes: list):
    try:
        post = await preparer_post(context, travail)
        langues = sorted({c["langue"] for c in comptes})
        for langue in langues:  # on traduit avant de créer les tâches pour repérer un souci tout de suite
            await asyncio.to_thread(post.legende, langue)
    except Exception as e:
        log.exception("échec préparation")
        await query.edit_message_text(f"❌ {nom} : échec de la préparation : {e}")
        return

    nb = len(post.medias)
    quoi = "réel" if post.type == "reel" else f"carrousel ({nb} photo{'s' if nb > 1 else ''})"
    avert = "\n⚠️ Plus de 10 médias : seuls les 10 premiers sont publiés." if post.tronque else ""
    legendes_txt = "\n\n".join(
        f"{'🇺🇸 EN' if l == 'en' else '🇫🇷 FR'} :\n{post.legende(l) or '(pas de légende)'}" for l in langues)

    try:
        if not geelark.est_configure():
            await query.edit_message_text(f"✅ {nom} : matériaux prêts ({quoi}), GeeLark pas branché.{avert}")
            await envoyer_medias(query.message, post)
            await query.message.reply_text(legendes_txt)
            return

        await query.edit_message_text(f"📤 {nom} : envoi du {quoi} à GeeLark…")
        urls = await asyncio.to_thread(geelark.envoyer_medias, post.medias)

        debut = int(time.time()) + geelark.DELAI_PUBLICATION
        lignes, ok = [], 0
        for i, compte in enumerate(comptes):
            quand = debut + i * geelark.ECART_COMPTES
            drapeau = modeles.DRAPEAU.get(compte["pays"], "")
            try:
                await asyncio.to_thread(
                    geelark.creer_tache, post.type, urls, post.legende(compte["langue"]),
                    compte["id"], quand, f"{compte['nom']} - repost {post.code}")
                ok += 1
                lignes.append(f"{drapeau} {compte['nom']} : dans {max(1, (quand - int(time.time())) // 60)} min ✅")
            except Exception as e:
                log.exception("échec tâche %s", compte["nom"])
                lignes.append(f"{drapeau} {compte['nom']} : ❌ {e}")

        await query.edit_message_text(
            f"{'✅' if ok == len(comptes) else '⚠️'} {nom} : {quoi}, {ok}/{len(comptes)} publication(s) programmée(s).{avert}\n\n"
            + "\n".join(lignes) + f"\n\n{legendes_txt}")
    except Exception as e:
        log.exception("échec publication")
        await query.message.reply_text(f"❌ {nom} : erreur à la publication : {e}")
    finally:
        shutil.rmtree(post.dossier, ignore_errors=True)


async def envoyer_medias(message, post) -> None:
    if post.type == "reel":
        if post.video.stat().st_size <= LIMITE_ENVOI_TELEGRAM:
            with post.video.open("rb") as f:
                await message.reply_video(f, filename=post.video.name, supports_streaming=True)
        else:
            await message.reply_text("Vidéo trop lourde pour Telegram (> 50 Mo).")
        return
    fichiers = [m.open("rb") for m in post.medias]
    try:
        await message.reply_media_group([InputMediaPhoto(f, filename=m.name) for f, m in zip(fichiers, post.medias)])
    finally:
        for f in fichiers:
            f.close()


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, recevoir_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recevoir_lien))
    app.add_handler(CallbackQueryHandler(choix_modele))
    log.info("Bot démarré")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
