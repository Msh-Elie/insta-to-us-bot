# Insta → compte US (bot Telegram + GeeLark)

Tu envoies un lien Instagram (ou une vidéo) au bot, puis tu choisis la modèle. Il télécharge la vidéo (nom court `post_<code>.mp4`), traduit la caption en anglais (hashtags et @mentions intacts), puis lance la publication sur le cloud phone GeeLark du compte US.

## 1. Créer le bot Telegram
1. Sur Telegram, ouvre **@BotFather** → `/newbot` → donne un nom.
2. Copie le **token** qu'il te donne.

## 2. Déployer sur Render
1. Mets ce dossier dans un dépôt GitHub (privé).
2. Render → **New → Blueprint** → choisis le dépôt (le fichier `render.yaml` crée un *Background Worker*).
3. Renseigne `TELEGRAM_TOKEN`. Laisse `ALLOWED_USER_ID` vide pour l'instant.
4. Déploie, puis envoie `/start` au bot : il te répond avec ton ID Telegram.
5. Mets cet ID dans `ALLOWED_USER_ID`, redéploie. Le bot n'obéit plus qu'à toi.

## 3. Brancher GeeLark
1. Dans le client GeeLark, menu **GeeHub** : copie ton **token API**.
2. Sur Render, renseigne `GEELARK_TOKEN`, puis redéploie.
3. Renseigne les cloud phones de chaque modèle dans `modeles.json` (ou dans la variable `MODELES_JSON` sur Render, qui a priorité). Format : pour chaque modèle, une liste `US` et une liste `FR` avec `{"nom": "...", "id": "..."}`. Un compte peut aussi s'écrire juste comme son ID.

Quand tu envoies un lien Instagram ou une vidéo, le bot te demande la modèle. Il programme ensuite la publication uniquement sur les cloud phones de cette modèle : légende en anglais pour les comptes US, en français pour les comptes FR. La 1re publication part 5 minutes après (`GEELARK_DELAY_SECONDS`), puis chaque compte suivant avec 10 minutes d'écart (`GEELARK_STAGGER_SECONDS`). Tu peux suivre les tâches dans GeeLark > Automation.

Tant que `GEELARK_TOKEN` est vide, le bot te renvoie le média + les légendes sur Telegram à la place.

## Si un post refuse de se télécharger
Instagram bloque parfois les serveurs. Exporte tes cookies Instagram (extension « Get cookies.txt » sur ton navigateur connecté) et ajoute-les sur Render comme **Secret File** `cookies.txt`, puis ajoute la variable `IG_COOKIES_FILE=/etc/secrets/cookies.txt`.
