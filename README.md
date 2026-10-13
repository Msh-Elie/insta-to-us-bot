# Insta → compte US (bot Telegram + GeeLark)

Tu envoies un lien Instagram au bot. Il télécharge la vidéo (nom court `post_<code>.mp4`), traduit la caption en anglais (hashtags et @mentions intacts), puis lance la publication sur le cloud phone GeeLark du compte US.

## 1. Créer le bot Telegram
1. Sur Telegram, ouvre **@BotFather** → `/newbot` → donne un nom.
2. Copie le **token** qu'il te donne.

## 2. Déployer sur Render
1. Mets ce dossier dans un dépôt GitHub (privé).
2. Render → **New → Blueprint** → choisis le dépôt (le fichier `render.yaml` crée un *Background Worker*).
3. Renseigne `TELEGRAM_TOKEN`. Laisse `ALLOWED_USER_ID` vide pour l'instant.
4. Déploie, puis envoie `/start` au bot : il te répond avec ton ID Telegram.
5. Mets cet ID dans `ALLOWED_USER_ID`, redéploie. Le bot n'obéit plus qu'à toi.

## 3. Brancher GeeLark (publication 100 % auto)
1. Dans le client GeeLark, menu **GeeHub** : copie ton **token API**.
2. Récupère l'**ID du cloud phone** où le compte Instagram US est connecté (visible dans la liste des cloud phones).
3. Sur Render, renseigne `GEELARK_TOKEN` et `GEELARK_PHONE_ID`, puis redéploie.

Le bot envoie la vidéo chez GeeLark puis crée la tâche « Instagram publish Reels video », programmée ~1 minute plus tard (réglable avec `GEELARK_DELAY_SECONDS`). Tu peux suivre la tâche dans GeeLark > Automation.

Tant que ces deux variables sont vides, le bot te renvoie la vidéo + la caption anglaise sur Telegram à la place.

## Si un post refuse de se télécharger
Instagram bloque parfois les serveurs. Exporte tes cookies Instagram (extension « Get cookies.txt » sur ton navigateur connecté) et ajoute-les sur Render comme **Secret File** `cookies.txt`, puis ajoute la variable `IG_COOKIES_FILE=/etc/secrets/cookies.txt`.
