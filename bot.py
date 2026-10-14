"""Bot Telegram : tu envoies un lien Insta, il prépare et pousse le post sur le compte US.

Variables d'environnement :
    TELEGRAM_TOKEN    token donné par @BotFather
    ALLOWED_USER_ID   ton ID Telegram (seul toi peux utiliser le bot)
"""

import asyncio
import logging
import os
import re
import shutil

from telegram import InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import geelark
import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("insta-bot")

TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED = int(os.getenv("ALLOWED_USER_ID", "0"))
LIEN_RE = re.compile(r"https?://(?:www\.)?instagram\.com/\S+")
LIMITE_TELEGRAM = 50 * 1024 * 1024  # 50 Mo : taille max d'envoi d'un bot


def autorise(update: Update) -> bool:
    return ALLOWED and update.effective_user and update.effective_user.id == ALLOWED


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ALLOWED:
        await update.message.reply_text(f"Ton ID Telegram est {uid}. Mets-le dans ALLOWED_USER_ID sur Render puis redéploie.")
        return
    if not autorise(update):
        return
    await update.message.reply_text("Prêt. Envoie-moi un lien Instagram : réel, post vidéo ou carrousel de photos.")


async def lien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorise(update):
        return
    m = LIEN_RE.search(update.message.text or "")
    if not m:
        await update.message.reply_text("Envoie-moi juste un lien instagram.com/reel/… ou /p/…")
        return
    url = m.group(0)
    statut = await update.message.reply_text("⏳ Téléchargement et traduction…")

    try:
        post = await asyncio.to_thread(pipeline.preparer, url)
    except Exception as e:
        log.exception("échec préparation")
        await statut.edit_text(f"❌ Échec de la préparation : {e}")
        return

    try:
        nb = len(post.medias)
        quoi = "réel" if post.type == "reel" else f"carrousel ({nb} photo{'s' if nb > 1 else ''})"
        avert = "\n⚠️ Plus de 10 médias : seuls les 10 premiers sont publiés." if post.tronque else ""
        if geelark.est_configure():
            await statut.edit_text(f"📤 Envoi à GeeLark ({quoi})…")
            if post.type == "reel":
                tache = await asyncio.to_thread(geelark.publier, post.video, post.caption_en)
            else:
                tache = await asyncio.to_thread(geelark.publier_carrousel, post.medias, post.caption_en)
            await statut.edit_text(
                f"✅ Publication programmée sur le compte US dans {geelark.DELAI_PUBLICATION // 60} min : {quoi} (tâche {tache}).{avert}\n\nCaption :\n{post.caption_en}"
            )
        else:
            # Mode manuel : on te renvoie tout, prêt à coller dans GeeLark
            await statut.edit_text(f"✅ Matériaux prêts : {quoi} (publication GeeLark pas encore branchée).{avert}")
            await envoyer_medias(update, post)
            await update.message.reply_text(post.caption_en or "(pas de caption)")
    except Exception as e:
        log.exception("échec publication")
        await update.message.reply_text(f"❌ Erreur à la publication : {e}")
    finally:
        shutil.rmtree(post.dossier, ignore_errors=True)


async def envoyer_medias(update: Update, post) -> None:
    if post.type == "reel":
        if post.video.stat().st_size <= LIMITE_TELEGRAM:
            with post.video.open("rb") as f:
                await update.message.reply_video(f, filename=post.video.name, supports_streaming=True)
        else:
            await update.message.reply_text("Vidéo trop lourde pour Telegram (> 50 Mo).")
        return
    fichiers = [m.open("rb") for m in post.medias]
    try:
        await update.message.reply_media_group([InputMediaPhoto(f, filename=m.name) for f, m in zip(fichiers, post.medias)])
    finally:
        for f in fichiers:
            f.close()


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lien))
    log.info("Bot démarré")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
