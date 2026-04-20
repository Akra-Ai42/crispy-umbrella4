# app.py (V102 : Correction API & Optimisation Background Worker)
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
logger = logging.getLogger("sophia.v102")
load_dotenv()

# --- RAG CHECK (Optionnel) ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    logger.info("✅ [INIT] RAG chargé.")
except Exception as e:
    RAG_ENABLED = False
    logger.warning(f"⚠️ [INIT] RAG désactivé ou absent : {e}")

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
# Utilisation du modèle stable Llama-3.3-70B
MODEL_NAME = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]
INVALID_NAMES = ["bonjour", "salut", "coucou", "hello", "yo", "aide", "moi", "sophia", "non", "oui", "stop", "start"]

NICKNAMES = {
    "F": ["ma belle", "ma chérie", "ma grande", "mon cœur"],
    "M": ["mon grand", "l'ami", "mon cœur", "frérot"],
    "N": ["toi", "mon ami(e)", "trésor"]
}

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

    async def generate_response(self, messages, temperature=0.7):
        payload = {
            "model": MODEL_NAME, 
            "messages": messages, 
            "temperature": temperature, 
            "max_tokens": 400, 
            "top_p": 0.9
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(MODEL_API_URL, json=payload, headers=headers, timeout=30.0)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"].strip()
                    # Nettoyage des tics de langage IA
                    return content.replace("Bonjour", "").replace("En tant qu'IA", "En tant que Sophia").strip()
                else:
                    logger.error(f"Erreur Together API : {r.status_code} - {r.text}")
            except Exception as e:
                logger.error(f"API Error: {e}")
        return "Je suis là, je t'écoute... Dis-m'en plus."

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
        context.user_data.clear()
        context.user_data["state"] = "ASK_NAME"
        context.user_data["history"] = []
        
        await update.message.reply_text(
            "Salut. C'est Sophia.\n\n"
            "Ici, tu peux être toi-même sans filtre.\n"
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
        if self._check_danger(msg):
            await self._trigger_emergency(update, context)
            return

        # LOGIQUE D'ONBOARDING
        if state == "ASK_NAME":
            clean_name = re.sub(r'[^\w\s]', '', msg.split()[0]).capitalize()
            if clean_name.lower() in INVALID_NAMES or len(clean_name) < 2:
                await update.message.reply_text("Donne-moi ton vrai prénom, s'il te plaît. 😊")
                return
            context.user_data["name"] = clean_name
            context.user_data["state"] = "ASK_GENDER"
            keyboard = [['Une Femme 👩', 'Un Homme 👨'], ['Neutre 👤']]
            await update.message.reply_text(f"Enchantée {clean_name}. Je m'adresse à toi comment ?", 
                                            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
            return

        if state == "ASK_GENDER":
            context.user_data["genre"] = "F" if "Femme" in msg else ("M" if "Homme" in msg else "N")
            context.user_data["state"] = "CHATTING"
            nickname = self.brain.get_dynamic_nickname(context.user_data["genre"])
            await update.message.reply_text(f"C'est noté {nickname}. Je suis là pour toi. Qu'est-ce qui se passe dans ta vie en ce moment ?", 
                                            reply_markup=ReplyKeyboardRemove())
            return

        # CHAT LIBRE
        if state == "CHATTING":
            await self._chat_flow(update, context, msg)

    async def _chat_flow(self, update, context, msg):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        history = context.user_data.get("history", [])
        name = context.user_data.get("name", "toi")
        genre = context.user_data.get("genre", "N")
        nickname = self.brain.get_dynamic_nickname(genre)

        system_prompt = f"""
        Tu es Sophia, la grande sœur protectrice et lucide de {name} (surnom: {nickname}).
        TON STYLE : Chaleureuse, emojis doux (❤️, ✨), ton de "meilleure amie".
        TA MISSION : Écouter, valider les émotions et rester solide. 
        RÈGLE : Réponds en 3 phrases maximum. Finis toujours par une question bienveillante.
        """

        messages = [{"role": "system", "content": system_prompt}] + history[-6:]
        messages.append({"role": "user", "content": msg})
        
        resp = await self.brain.generate_response(messages)
        
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": resp})
        context.user_data["history"] = history[-10:]
        
        await update.message.reply_text(resp)

    def _check_danger(self, text):
        return any(re.search(p, text.lower()) for p in DANGER_KEYWORDS)

    async def _trigger_emergency(self, update, context):
        await update.message.reply_text("Je t'arrête tout de suite. Ta sécurité est ma priorité. ❤️\n\n"
                                        "Es-tu en sécurité là ? Appelle le 3114 (Prévention Suicide) ou le 15. "
                                        "Je reste ici, mais s'il te plaît, contacte des pros.")

    async def error_handler(self, update, context):
        logger.error(f"Erreur Update: {context.error}")

# --- MAIN ---
if __name__ == "__main__":
    bot = SophiaBot()
    logger.info("🚀 Sophia V102 en ligne (Polling mode)...")
    # drop_pending_updates=True permet de supprimer les anciens webhooks qui bloqueraient le bot
    bot.app.run_polling(drop_pending_updates=True)