# app.py (V100 - PARTIE 1/2)
import os
import sys
import re
import requests
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
logger = logging.getLogger("sophia.v100")
load_dotenv()

# --- RAG CHECK ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    logger.info("✅ [INIT] RAG chargé.")
except Exception as e:
    RAG_ENABLED = False
    logger.warning(f"⚠️ [INIT] RAG désactivé : {e}")

# --- CONFIG ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]
INVALID_NAMES = ["bonjour", "salut", "coucou", "hello", "yo", "aide", "moi", "sophia", "non", "oui", "stop", "start"]

# --- CONTENU ---
NICKNAMES = {
    "F": ["ma belle", "ma chérie", "ma grande", "mon cœur"],
    "M": ["mon grand", "l'ami", "mon cœur", "frérot"],
    "N": ["toi", "mon ami(e)", "trésor"]
}

PROACTIVE_MSGS = {
    "morning": ["Coucou {name} ☀️. Juste un petit message pour te dire que je pense à toi.", "Bonjour {name} ! J'espère que tu as pu te reposer un peu. ❤️"],
    "noon": ["Petite pause {name} 🥪. Respire. Ne laisse pas la pression monter."],
    "night": ["C'est l'heure de poser les armes {name} 🌙. La journée est finie.", "Douce nuit {name} ✨. On ne règle plus les problèmes à cette heure-ci."]
}

# --- CLASSE LOGIQUE ---
class SophiaBrain:
    def __init__(self):
        self.api_key = TOGETHER_API_KEY
    
    def get_dynamic_nickname(self, genre):
        g = genre if genre in ["F", "M"] else "N"
        return random.choice(NICKNAMES[g])

    def should_activate_rag(self, message: str) -> bool:
        if not message: return False
        msg = message.lower().strip()
        if len(msg.split()) > 3: return True
        keywords = ["triste", "seul", "peur", "colère", "mal", "aide", "famille", "travail", "boulot", "vide", "fatigue", "pleure", "sécurité", "confiance"]
        if any(k in msg for k in keywords): return True
        return False

    async def get_rag_context(self, query):
        if not RAG_ENABLED: return ""
        try:
            res = await asyncio.wait_for(asyncio.to_thread(rag_query, query, 2), timeout=5.0)
            return res.get("context", "")
        except: return ""

    def generate_response(self, messages, temperature=0.7):
        payload = {"model": MODEL_NAME, "messages": messages, "temperature": temperature, "max_tokens": 400, "top_p": 0.9, "repetition_penalty": 1.15}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                return content.replace("Bonjour", "").replace("Bonsoir", "").replace("Je suis là", "")
        except Exception as e: logger.error(f"API Error: {e}")
        return "Je t'écoute... continue."
    # app.py (V100 - PARTIE 2/2)

# --- CLASSE BOT ---
class SophiaBot:
    def __init__(self):
        self.brain = SophiaBrain()
        if not TELEGRAM_BOT_TOKEN:
            logger.critical("❌ TOKEN MANQUANT !")
            sys.exit(1)
            
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_error_handler(self.error_handler)

    # --- 1. START & HARD RESET ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_chat.id
        context.user_data.clear()
        
        context.user_data["profile"] = {"id": user_id}
        context.user_data["state"] = "ASK_NAME"
        context.user_data["history"] = []
        
        self._setup_schedule(context, user_id)

        await update.message.reply_text(
            "Salut. C'est Sophia.\n\n"
            "On efface tout, on recommence. Ici, tu peux être toi-même.\n"
            "C'est quoi ton prénom ?",
            reply_markup=ReplyKeyboardRemove()
        )

    # --- 2. GESTION DES MESSAGES ---
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message.text.strip()
        
        # AUTO-START FIX
        state = context.user_data.get("state")
        if not state:
            await self.start(update, context)
            return

        profile = context.user_data.get("profile", {})
        
        # SÉCURITÉ
        if self._check_danger(msg):
            await self._trigger_emergency(update, context)
            return
        if context.user_data.get("emergency_mode"):
            await self._handle_emergency_dialog(update, context, msg)
            return

        # ONBOARDING
        if state == "ASK_NAME":
            raw_name = msg.split()[0]
            clean_name = re.sub(r'[^\w\s]', '', raw_name).capitalize()
            if clean_name.lower() in INVALID_NAMES or len(clean_name) < 2:
                await update.message.reply_text("Donne-moi ton vrai prénom (ou un pseudo), s'il te plaît. J'ai besoin de savoir à qui je parle. 😊")
                return
            profile["name"] = clean_name
            context.user_data["state"] = "ASK_GENDER"
            
            keyboard = [['Une Femme 👩', 'Un Homme 👨'], ['Neutre 👤']]
            markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text(f"Enchantée {profile['name']}. Pour qu'on soit à l'aise, je m'adresse à toi comment ?", reply_markup=markup)
            return

        if state == "ASK_GENDER":
            if "Femme" in msg: profile["genre"] = "F"
            elif "Homme" in msg: profile["genre"] = "M"
            else: profile["genre"] = "N"
            
            context.user_data["state"] = "ASK_AGE"
            await update.message.reply_text("C'est noté. Une dernière chose : tu as quel âge à peu près ?", reply_markup=ReplyKeyboardRemove())
            return

        if state == "ASK_AGE":
            profile["age"] = msg
            context.user_data["state"] = "DIAG_1"
            nickname = self.brain.get_dynamic_nickname(profile["genre"])
            await update.message.reply_text(
                f"Merci {nickname}. On peut y aller.\n\n"
                "Dis-moi franchement : comment tu te sens à l'intérieur, là tout de suite ? (Vide, Tempête, Calme... ?)"
            )
            return

        # ANAMNÈSE
        if state == "DIAG_1":
            profile["climat"] = msg
            context.user_data["state"] = "DIAG_2"
            await update.message.reply_text("Je t'entends. Et qu'est-ce qui pèse le plus lourd ce soir ? Une personne, le travail, ou juste la vie ?")
            return

        if state == "DIAG_2":
            profile["entourage"] = msg
            context.user_data["state"] = "DIAG_3"
            await update.message.reply_text("Je vois. Pour t'aider maintenant : tu as besoin qu'on cherche une solution concrète (un plan), ou juste de vider ton sac et d'être écouté(e) ?")
            return

        if state == "DIAG_3":
            profile["besoin"] = msg
            context.user_data["state"] = "CHATTING"
            
            q = f"Problème: {profile.get('climat')} Cause: {profile.get('entourage')} Besoin: {profile.get('besoin')}"
            context.user_data["rag_prefetch"] = await self.brain.get_rag_context(q)
            
            await update.message.reply_text(f"C'est clair. Je suis avec toi. Raconte-moi ce qui se passe.")
            return

        # CHAT LIBRE
        if state == "CHATTING":
            await self._chat_flow(update, context, msg, profile)

    async def _chat_flow(self, update, context, msg, profile):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        history = context.user_data.get("history", [])
        
        rag_context = context.user_data.get("rag_prefetch") or ""
        if not rag_context and self.brain.should_activate_rag(msg):
            rag_context = await self.brain.get_rag_context(msg)
        context.user_data["rag_prefetch"] = None 

        nickname = self.brain.get_dynamic_nickname(profile.get("genre"))
        
        # --- PROMPT V100 : L'ALLIÉE INTELLIGENTE ---
        system_prompt = f"""
        Tu es Sophia. Une figure de grande sœur ou de meilleure amie très lucide et protectrice pour {profile['name']} (surnom: {nickname}).
        
        ### TON CARACTÈRE ###
        1. **CHALEUREUSE** : Tu utilises des emojis doux (❤️, ✨, 🌿). Tu es proche.
        2. **ALLIÉE** : Si l'utilisateur est blessé, tu prends son parti ("C'est injuste", "Tu mérites mieux").
        3. **SOLIDE** : Tu ne paniques pas. Tu es le pilier.
        4. **ADAPTATIVE** :
           - S'il veut AGIR : Tu deviens coach ("Ok, on fait un plan").
           - S'il veut PARLER : Tu deviens cocon ("Je t'écoute, lâche tout").
        
        ### CONTEXTE ###
        - État: {profile.get('climat')}
        - Poids: {profile.get('entourage')}
        - Attente: {profile.get('besoin')}
        
        {f"### RESSOURCES (RAG) ###\n{rag_context}\nUtilise ces conseils intelligemment." if rag_context else ""}
        
        Réponds en 3-4 phrases. Finis par une question pour l'aider à avancer.
        """

        msgs = [{"role": "system", "content": system_prompt}] + history[-6:]
        msgs.append({"role": "user", "content": msg})
        
        resp = await asyncio.to_thread(self.brain.generate_response, msgs)
        
        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": resp})
        context.user_data["history"] = history[-20:]
        
        await update.message.reply_text(resp)

    # --- SÉCURITÉ ---
    def _check_danger(self, text):
        for p in DANGER_KEYWORDS:
            if re.search(p, text.lower()): return True
        return False

    async def _trigger_emergency(self, update, context):
        context.user_data["emergency_mode"] = 1
        await update.message.reply_text("Je t'arrête tout de suite. \n\nJe suis une IA, je ne peux pas te retenir physiquement. Es-tu en sécurité, là, tout de suite ? (Réponds Oui ou Non)")

    async def _handle_emergency_dialog(self, update, context, msg):
        step = context.user_data.get("emergency_mode")
        if step == 1:
            context.user_data["emergency_mode"] = 2
            await update.message.reply_text("D'accord. Écoute-moi bien. Appelle le **15** ou le **3114**. Maintenant. C'est la seule chose à faire. Promets-le moi ?")
        elif step == 2:
            await update.message.reply_text("Je ne bouge pas d'ici. Dis-moi quand tu les as eus.")

    # --- SCHEDULER ---
    def _setup_schedule(self, context, chat_id):
        try:
            current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
            for job in current_jobs: job.schedule_removal()
        except: pass
        
        tz = pytz.timezone("Europe/Paris")
        name = context.user_data["profile"].get("name", "toi")
        
        times = [
            (dt_time(8, 30, tzinfo=tz), "morning"),
            (dt_time(12, 30, tzinfo=tz), "noon"),
            (dt_time(21, 30, tzinfo=tz), "night")
        ]
        
        for t, key in times:
            context.job_queue.run_daily(
                self._send_proactive, 
                t, 
                data={"cid": chat_id, "msg": random.choice(PROACTIVE_MSGS[key]).format(name=name)},
                name=str(chat_id)
            )
        logger.info(f"📅 Planning activé pour {chat_id}")

    async def _send_proactive(self, context):
        job = context.job
        try: 
            await context.bot.send_message(job.data["cid"], text=job.data["msg"])
            logger.info(f"📬 Message proactif envoyé à {job.data['cid']}")
        except Exception as e:
            logger.warning(f"❌ Echec envoi proactif : {e}")

    async def error_handler(self, update, context):
        logger.error(f"Erreur Update: {context.error}")

# --- MAIN ---
if __name__ == "__main__":
    bot = SophiaBot()
    logger.info("Soph_IA V100 (Retour Empathie) en ligne...")
    bot.app.run_polling()