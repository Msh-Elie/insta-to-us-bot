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

from telegram import Update
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
    await update.message.reply_text("Prêt. Envoie-moi un lien Instagram (reel ou post vidéo).")


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
        await statut.edit_text(f"❌ Impossible de récupérer ce post : {e}")
        return

    try:
        if geelark.est_configure():
            await statut.edit_text("📤 Envoi à GeeLark…")
            tache = await asyncio.to_thread(geelark.publier, post.video, post.caption_en)
            await statut.edit_text(f"✅ Tâche de publication lancée sur le compte US (tâche {tache}).\n\nCaption :\n{post.caption_en}")
        else:
            # Mode manuel : on te renvoie tout, prêt à coller dans le modèle GeeLark
            await statut.edit_text("✅ Matériaux prêts (publication GeeLark pas encore branchée).")
            if post.video.stat().st_size <= LIMITE_TELEGRAM:
                with post.video.open("rb") as f:
                    await update.message.reply_video(f, filename=post.video.name, supports_streaming=True)
            else:
                await update.message.reply_text("Vidéo trop lourde pour Telegram (> 50 Mo).")
            await update.message.reply_text(post.caption_en or "(pas de caption)")
    except Exception as e:
        log.exception("échec publication")
        await update.message.reply_text(f"❌ Erreur à la publication : {e}")
    finally:
        shutil.rmtree(post.video.parent, ignore_errors=True)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lien))
    log.info("Bot démarré")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
