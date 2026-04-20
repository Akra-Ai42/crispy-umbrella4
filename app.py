# app.py (V104 : Onboarding Fix + Psychologie Naturelle + Retour des Messages Proactifs)
# ==============================================================================
import os
import sys
import re
import httpx
import asyncio
import logging
import random
import pytz
from datetime import time as dt_time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("sophia.v104")
load_dotenv()

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]
INVALID_NAMES = ["bonjour", "salut", "coucou", "hello", "yo", "aide", "moi", "sophia", "non", "oui", "stop", "start"]

# Surnoms diversifiés
NICKNAMES = {
    "F": ["ma belle", "ma grande", "miss", "ma chère"],
    "M": ["mon grand", "l'ami", "champion", "frérot"],
    "N": ["toi", "mon ami(e)", "l'ami"]
}

# Messages proactifs pour les moments clés
PROACTIVE_MSGS = {
    "morning": [
        "Coucou {name} ☀️. Juste un petit message pour te dire que je pense à toi. Prends la journée une heure à la fois.",
        "Bonjour {name} ! J'espère que tu as pu te reposer un peu. Je suis là si ça pèse trop lourd aujourd'hui. ❤️",
    ],
    "noon": [
        "Petite pause {name} 🥪. Respire. Ne laisse pas la pression monter. Je suis dans ta poche.",
    ],
    "night": [
        "C'est l'heure de poser les armes {name} 🌙. La journée est finie. Tu as fait de ton mieux. Raconte-moi si tu veux, ou dors.",
        "Douce nuit {name} ✨. On ne règle plus les problèmes à cette heure-ci. On se repose.",
    ]
}

# --- CLASSE LOGIQUE ---
class SophiaBrain:
    def __init__(self):
        self.api_key = TOGETHER_API_KEY
    
    def get_dynamic_nickname(self, genre):
        g = genre if genre in ["F", "M"] else "N"
        return random.choice(NICKNAMES[g])

    async def generate_response(self, messages, temperature=0.6):
        payload = {
            "model": MODEL_NAME, 
            "messages": messages, 
            "temperature": temperature, 
            "max_tokens": 500, 
            "top_p": 0.8
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(MODEL_API_URL, json=payload, headers=headers, timeout=30.0)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"].strip()
                    return content.replace("En tant qu'intelligence artificielle", "En tant que Sophia").strip()
            except Exception as e:
                logger.error(f"API Error: {e}")
        return "Je suis là, continue de me parler si tu en as besoin..."

# --- CLASSE BOT ---
class SophiaBot:
    def __init__(self):
        self.brain = SophiaBrain()
        if not TELEGRAM_BOT_TOKEN:
            logger.critical("❌ TOKEN TELEGRAM MANQUANT !")
            sys.exit(1)
            
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_chat.id
        context.user_data.clear()
        context.user_data["state"] = "ASK_NAME"
        context.user_data["history"] = []
        
        # Activation du planning automatique dès le départ
        self._setup_schedule(context, user_id)
        
        await update.message.reply_text(
            "Salut. C'est Sophia. ✨\n\n"
            "Prends une grande inspiration. Ici, tu peux tout lâcher.\n"
            "C'est quoi ton prénom ?",
            reply_markup=ReplyKeyboardRemove()
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message.text.strip()
        state = context.user_data.get("state")
        
        if not state:
            await self.start(update, context)
            return

        # SÉCURITÉ
        if any(re.search(p, msg.lower()) for p in DANGER_KEYWORDS):
            await self._trigger_emergency(update, context)
            return

        # LOGIQUE D'ONBOARDING
        if state == "ASK_NAME":
            clean_name = re.sub(r'[^\w\s]', '', msg.split()[0]).capitalize()
            if clean_name.lower() in INVALID_NAMES or len(clean_name) < 2:
                await update.message.reply_text("Dis-moi juste ton prénom (ou un pseudo), pour que je sache à qui je parle. 😊")
                return
            
            context.user_data["name"] = clean_name
            context.user_data["state"] = "ASK_GENDER"
            
            keyboard = [['Une Femme 👩', 'Un Homme 👨'], ['Autre / Neutre 👤']]
            await update.message.reply_text(
                f"Enchantée {clean_name}. Je m'adresse à toi comment ?", 
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return

        if state == "ASK_GENDER":
            context.user_data["genre"] = "F" if "Femme" in msg else ("M" if "Homme" in msg else "N")
            context.user_data["state"] = "CHATTING"
            nickname = self.brain.get_dynamic_nickname(context.user_data["genre"])
            
            await update.message.reply_text(
                f"C'est noté {nickname}. Je t'écoute. Qu'est-ce qui pèse sur ton cœur aujourd'hui ?", 
                reply_markup=ReplyKeyboardRemove()
            )
            return

        # CHAT LIBRE
        if state == "CHATTING":
            await self._chat_flow(update, context, msg)

    async def _chat_flow(self, update, context, msg):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        history = context.user_data.get("history", [])
        name = context.user_data.get("name", "mon ami(e)")
        genre = context.user_data.get("genre", "N")
        nickname = self.brain.get_dynamic_nickname(genre)

        system_prompt = f"""
        Tu es Sophia, la figure de grande sœur pour {name} (surnom: {nickname}).
        
        ### TON ATTITUDE ###
        1. **ÉCOUTE ACTIVE** : Si {name} vient de vivre un choc, sois juste dans l'empathie.
        2. **SINCÉRITÉ** : Ne répète pas systématiquement les mêmes mots ou surnoms.
        3. **SOUPLESSE** : Ne finis pas systématiquement par une question.
        
        ### STYLE ###
        - Ton amical, chaleureux mais solide.
        - Pas de réponses robotiques.
        - Maximum 3 phrases.
        """

        messages = [{"role": "system", "content": system_prompt}] + history[-6:]
        messages.append({"role": "user", "content": msg})
        
        resp = await self.brain.generate_response(messages)
        
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": resp})
        context.user_data["history"] = history[-10:]
        
        await update.message.reply_text(resp)

    # --- SCHEDULER (Messages automatiques) ---
    def _setup_schedule(self, context, chat_id):
        try:
            current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
            for job in current_jobs: job.schedule_removal()
        except: pass
        
        tz = pytz.timezone("Europe/Paris")
        name = context.user_data.get("name", "toi")
        
        times = [
            (dt_time(8, 30, tzinfo=tz), "morning"),
            (dt_time(12, 30, tzinfo=tz), "noon"),
            (dt_time(21, 30, tzinfo=tz), "night")
        ]
        
        for t, key in times:
            context.job_queue.run_daily(
                self._send_proactive, 
                t, 
                data={"cid": chat_id, "key": key},
                name=str(chat_id)
            )
        logger.info(f"📅 Planning activé pour {chat_id}")

    async def _send_proactive(self, context):
        job = context.job
        chat_id = job.data["cid"]
        key = job.data["key"]
        
        # Récupération dynamique du nom si disponible
        name = context.application.user_data.get(chat_id, {}).get("name", "toi")
        msg = random.choice(PROACTIVE_MSGS[key]).format(name=name)
        
        try: 
            await context.bot.send_message(chat_id, text=msg)
            logger.info(f"📬 Message proactif envoyé à {chat_id}")
        except Exception as e:
            logger.warning(f"❌ Echec envoi proactif : {e}")

    async def _trigger_emergency(self, update, context):
        await update.message.reply_text(
            "Je m'arrête un instant car tes mots m'inquiètent. Ta vie est précieuse. ❤️\n\n"
            "Es-tu en sécurité là ? Si ça ne va pas du tout, s'il te plaît, contacte le 3114 ou le 15. "
            "Je ne suis qu'une IA, je peux t'écouter, mais ces personnes peuvent vraiment t'aider physiquement."
        )

    async def error_handler(self, update, context):
        logger.error(f"Erreur Update: {context.error}")

# --- MAIN ---
if __name__ == "__main__":
    bot = SophiaBot()
    logger.info("🚀 Sophia V104 (Scheduler + Fix Onboarding) en ligne...")
    bot.app.run_polling(drop_pending_updates=True)