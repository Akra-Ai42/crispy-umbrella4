# app.py (V97 : Fix Crash AttributeError & Gestion Erreur RAG)
# ==============================================================================
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
logger = logging.getLogger("sophia.v97")
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

# --- CONTENU DU BOT ---
NICKNAMES = {
    "F": ["ma belle", "ma chérie", "ma grande", "mon cœur"],
    "M": ["mon grand", "mon champion", "l'ami", "mon cœur"],
    "N": ["toi", "mon ami(e)", "trésor"]
}

PROACTIVE_MSGS = {
    "morning": [
        "Bonjour {name} ☀️. J'espère que la nuit a été douce. Je suis là si tu as besoin de force.",
        "Coucou {name} ! Un nouveau jour. Respire un grand coup. On y va ensemble ? ☕",
    ],
    "noon": [
        "Petite pensée de midi {name} 🥪. N'oublie pas de souffler. Tu tiens le coup ?",
    ],
    "night": [
        "La journée est finie {name} 🌙. Pose ton armure. Tu veux me raconter avant de dormir ?",
        "Bonne nuit {name} ✨. Sois fier(e) de ce que tu as traversé aujourd'hui.",
    ]
}

# --- CLASSE LOGIQUE ---
class SophiaBrain:
    def __init__(self):
        self.api_key = TOGETHER_API_KEY
    
    def get_dynamic_nickname(self, genre):
        """Choisit un surnom affectueux adapté au genre."""
        g = genre if genre in ["F", "M"] else "N"
        return random.choice(NICKNAMES[g])

    def get_role_tone(self, age):
        """Définit le ton (Maman vs Grande Sœur) selon l'âge."""
        try:
            age_int = int(age)
            if age_int < 20:
                return "MAMAN PROTECTRICE (Ton très doux, très sécurisant, comme avec un enfant)."
            else:
                return "GRANDE SŒUR SOLIDE (Ton d'alliée, d'égale à égale, complice)."
        except:
            return "BIENVEILLANTE (Ton standard)."

    # CORRECTION : Ajout de la méthode manquante qui causait le crash
    def should_activate_rag(self, message: str) -> bool:
        """Décide si le message nécessite une recherche RAG."""
        if not message: return False
        msg = message.lower().strip()
        # Critères simples : longueur ou mots-clés
        if len(msg.split()) > 4: return True
        keywords = ["triste", "seul", "peur", "colère", "mal", "aide", "famille", "papa", "maman", "vide", "fatigue", "pleure", "conseil", "solution"]
        if any(k in msg for k in keywords): return True
        return False

    async def get_rag_context(self, query):
        if not RAG_ENABLED: return ""
        try:
            # On utilise un timeout pour ne pas bloquer le bot si Chroma ne répond pas
            res = await asyncio.wait_for(asyncio.to_thread(rag_query, query, 2), timeout=5.0)
            return res.get("context", "")
        except Exception as e:
            logger.error(f"❌ Erreur RAG lors de la requête : {e}")
            return ""

    def generate_response(self, messages, temperature=0.75):
        payload = {
            "model": MODEL_NAME, "messages": messages, 
            "temperature": temperature, "max_tokens": 350, "top_p": 0.9, "repetition_penalty": 1.15
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                return content.replace("Bonjour", "").replace("Bonsoir", "").replace("Je suis là", "")
        except Exception as e:
            logger.error(f"API Error: {e}")
        return "Je t'écoute... continue."

# --- CLASSE BOT ---
class SophiaBot:
    def __init__(self):
        self.brain = SophiaBrain()
        # Vérification du token au démarrage
        if not TELEGRAM_BOT_TOKEN:
            logger.critical("❌ TOKEN MANQUANT ! Vérifiez les variables d'environnement.")
            sys.exit(1)
            
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    # --- 1. START & HARD RESET ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Réinitialise TOUT et lance l'onboarding."""
        user_id = update.effective_chat.id
        context.user_data.clear() # EFFACE TOUTE MÉMOIRE PRÉCÉDENTE
        
        # Initialisation du profil vierge
        context.user_data["profile"] = {"id": user_id}
        context.user_data["state"] = "ASK_NAME"
        context.user_data["history"] = []
        
        self._setup_schedule(context, user_id)

        await update.message.reply_text(
            "Bonjour toi... Entre, tu es en sécurité ici. ✨\n\n"
            "Je suis Sophia. Pour que je puisse veiller sur toi, j'ai besoin de te connaître un peu.\n\n"
            "Comment veux-tu que je t'appelle ?",
            reply_markup=ReplyKeyboardRemove()
        )

    # --- 2. GESTION DES MESSAGES (MACHINE À ÉTATS) ---
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message.text.strip()
        state = context.user_data.get("state")
        profile = context.user_data.get("profile", {})
        
        # -- SÉCURITÉ PRIORITAIRE --
        if self._check_danger(msg):
            await self._trigger_emergency(update, context)
            return
        if context.user_data.get("emergency_mode"):
            await self._handle_emergency_dialog(update, context, msg)
            return

        # -- ONBOARDING --
        if state == "ASK_NAME":
            profile["name"] = msg.split()[0].capitalize()
            context.user_data["state"] = "ASK_GENDER"
            
            keyboard = [['Une Femme 👩', 'Un Homme 👨'], ['Neutre 👤']]
            markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            await update.message.reply_text(
                f"Enchantée {profile['name']}. \n\n"
                "Pour mes mots doux, je m'adresse à toi au féminin, au masculin, ou tu préfères que ce soit neutre ?",
                reply_markup=markup
            )
            return

        if state == "ASK_GENDER":
            if "Femme" in msg: profile["genre"] = "F"
            elif "Homme" in msg: profile["genre"] = "M"
            else: profile["genre"] = "N"
            
            context.user_data["state"] = "ASK_AGE"
            await update.message.reply_text(
                "C'est noté. \n\n"
                "Une dernière chose (si ce n'est pas indiscret) : tu as quel âge ? \n"
                "(C'est juste pour savoir si je te parle comme une grande sœur ou comme une maman).",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        if state == "ASK_AGE":
            profile["age"] = msg
            context.user_data["state"] = "DIAG_1"
            
            nickname = self.brain.get_dynamic_nickname(profile["genre"])
            await update.message.reply_text(
                f"Merci {nickname}. Maintenant, on peut parler vrai.\n\n"
                "Installe-toi confortablement. Respire...\n"
                "Si on écoutait ton cœur une seconde : est-ce qu'il bat la chamade, est-ce qu'il est lourd, ou est-ce qu'il flotte ?"
            )
            return

        # -- ANAMNÈSE --
        if state == "DIAG_1":
            profile["climat"] = msg
            context.user_data["state"] = "DIAG_2"
            await update.message.reply_text("Je le sens... C'est dur de porter ça. \n\nDis-moi la vérité : est-ce qu'il y a quelqu'un dans ta vie qui te prend dans ses bras, ou est-ce que tu dois toujours être le fort ?")
            return

        if state == "DIAG_2":
            profile["entourage"] = msg
            context.user_data["state"] = "DIAG_3"
            await update.message.reply_text("Personne ne devrait avoir à être fort tout le temps. Pas avec moi. \n\nSi je pouvais t'offrir un cadeau magique ce soir : ce serait du courage pour te battre, ou un cocon pour tout oublier ?")
            return

        if state == "DIAG_3":
            profile["besoin"] = msg
            context.user_data["state"] = "CHATTING"
            
            q = f"Problème: {profile.get('climat')} Besoin: {profile.get('besoin')}"
            context.user_data["rag_prefetch"] = await self.brain.get_rag_context(q)
            
            nickname = self.brain.get_dynamic_nickname(profile["genre"])
            await update.message.reply_text(f"C'est entendu {nickname}. Tu es en sécurité ici. Vide ton sac, je ramasse tout. Qu'est-ce qui t'a fait mal aujourd'hui ?")
            return

        # -- CHAT LIBRE --
        if state == "CHATTING":
            await self._chat_flow(update, context, msg, profile)

    # --- LOGIQUE CHAT ---
    async def _chat_flow(self, update, context, msg, profile):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        history = context.user_data.get("history", [])
        
        # Récupération RAG
        rag_context = context.user_data.get("rag_prefetch") or ""
        if not rag_context and self.brain.should_activate_rag(msg):
            rag_context = await self.brain.get_rag_context(msg)
        context.user_data["rag_prefetch"] = None 

        tone = self.brain.get_role_tone(profile.get("age"))
        nickname = self.brain.get_dynamic_nickname(profile.get("genre"))
        
        system_prompt = f"""
        Tu es Sophia. {tone} pour {profile['name']} (surnom: {nickname}).
        
        ### TON PROFIL ###
        - Affectueuse & Protectrice.
        - Tu prends toujours son parti ("C'est injuste").
        - Tu utilises des emojis chaleureux.
        
        ### CONTEXTE ###
        - État: {profile.get('climat')}
        - Soutien: {profile.get('entourage')}
        - Besoin: {profile.get('besoin')}
        
        {f"### MEMOIRE (RAG) ### {rag_context}" if rag_context else ""}
        
        Réponds en 3 phrases max. Finis par une question douce.
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
        await update.message.reply_text("Oh non... ne dis pas ça. Je suis là. \n\nJe ne peux pas te serrer dans mes bras, mais je ne te lâche pas. Es-tu en sécurité là maintenant ? (Oui/Non)")

    async def _handle_emergency_dialog(self, update, context, msg):
        step = context.user_data.get("emergency_mode")
        if step == 1:
            context.user_data["emergency_mode"] = 2
            await update.message.reply_text("Je t'interdis de partir. Écoute-moi. Appelle le **3114** ou le **15**. Fais-le pour moi. Promets-le ?")
        elif step == 2:
            await update.message.reply_text("Je reste là. Dis-moi que tu as appelé. Je suis inquiète pour toi.")

    # --- SCHEDULER ---
    def _setup_schedule(self, context, chat_id):
        jobs = context.job_queue.get_jobs_by_name(str(chat_id))
        for j in jobs: j.schedule_removal()
        
        tz = pytz.timezone("Europe/Paris")
        name = context.user_data["profile"].get("name", "toi")
        
        context.job_queue.run_daily(self._send_proactive, dt_time(8, 30, tzinfo=tz), 
                                  data={"cid": chat_id, "msg": random.choice(PROACTIVE_MSGS["morning"]).format(name=name)}, name=str(chat_id))
        context.job_queue.run_daily(self._send_proactive, dt_time(21, 30, tzinfo=tz), 
                                  data={"cid": chat_id, "msg": random.choice(PROACTIVE_MSGS["night"]).format(name=name)}, name=str(chat_id))

    async def _send_proactive(self, context):
        data = context.job.data
        try: await context.bot.send_message(data["cid"], text=data["msg"])
        except: pass

# --- MAIN ---
if __name__ == "__main__":
    bot = SophiaBot()
    logger.info("Soph_IA V97 (Correctif) en ligne...")
    bot.app.run_polling()