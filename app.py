# app.py (V99 : Auto-Start, Fix Prénom & Stabilité)
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
logger = logging.getLogger("sophia.v99")
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

# Liste noire pour éviter que Sophia ne s'appelle "Bonjour"
INVALID_NAMES = ["bonjour", "salut", "coucou", "hello", "yo", "aide", "moi", "sophia", "non", "oui", "stop", "start", "commencer"]

# --- CONTENU DU BOT ---
NICKNAMES = {
    "F": ["ma guerrière", "ma grande", "sœurette", "ma belle"],
    "M": ["l'ami", "soldat", "mon grand", "frérot"],
    "N": ["camarade", "l'ami(e)"]
}

PROACTIVE_MSGS = {
    "morning": [
        "Debout {name} 🛡️. Le monde est bruyant, mais ici c'est calme. Prends une seconde pour t'ancrer avant d'y aller.",
        "Salut {name}. J'espère que tu es en sécurité ce matin. N'oublie pas : une chose à la fois. Je veille.",
    ],
    "noon": [
        "Pause {name} ⚓. Vérification système : tu as mangé ? Tu as bu de l'eau ? La base d'abord, le reste après.",
    ],
    "night": [
        "La garde est finie {name} 🌙. Si tu es à l'abri, ferme les yeux. Sinon, dis-le moi. Je reste en veille.",
        "Fin de journée. Dépose le sac à dos. Tu as fait de ton mieux. Repos.",
    ]
}

# --- CLASSE LOGIQUE ---
class SophiaBrain:
    def __init__(self):
        self.api_key = TOGETHER_API_KEY
    
    def get_dynamic_nickname(self, genre):
        g = genre if genre in ["F", "M"] else "N"
        return random.choice(NICKNAMES[g])

    def get_role_tone(self, age):
        try:
            age_int = int(age)
            if age_int < 18:
                return "GARDIENNE PROTECTRICE (Ton très sécurisant, vérifie les besoins vitaux)."
            else:
                return "ALLIÉE SOLIDE (Ton direct, pragmatique, sans pitié pour ceux qui te font du mal)."
        except:
            return "GARDIENNE (Ton standard)."

    def should_activate_rag(self, message: str) -> bool:
        if not message: return False
        msg = message.lower().strip()
        if len(msg.split()) > 4: return True
        keywords = ["triste", "seul", "peur", "colère", "mal", "aide", "famille", "rue", "froid", "faim", "argent", "police", "abri"]
        if any(k in msg for k in keywords): return True
        return False

    async def get_rag_context(self, query):
        if not RAG_ENABLED: return ""
        try:
            res = await asyncio.wait_for(asyncio.to_thread(rag_query, query, 2), timeout=5.0)
            return res.get("context", "")
        except Exception as e:
            logger.error(f"❌ Erreur RAG : {e}")
            return ""

    def generate_response(self, messages, temperature=0.6):
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
        if not TELEGRAM_BOT_TOKEN:
            logger.critical("❌ TOKEN MANQUANT !")
            sys.exit(1)
            
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    # --- 1. START & HARD RESET ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_chat.id
        context.user_data.clear()
        
        context.user_data["profile"] = {"id": user_id}
        context.user_data["state"] = "ASK_NAME"
        context.user_data["history"] = []
        
        self._setup_schedule(context, user_id)

        await update.message.reply_text(
            "Salut. Je suis Sophia.\n\n"
            "Je ne suis pas une psy, je suis une gardienne. Ici, c'est ta zone de repli.\n"
            "Pour commencer : c'est quoi ton vrai prénom ?",
            reply_markup=ReplyKeyboardRemove()
        )

    # --- 2. GESTION DES MESSAGES ---
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message.text.strip()
        
        # FIX V99 : AUTO-START si l'état est inconnu
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

        # ONBOARDING (FILTRE PRÉNOM)
        if state == "ASK_NAME":
            # Nettoyage : on prend le premier mot et on enlève la ponctuation
            raw_name = msg.split()[0]
            clean_name = re.sub(r'[^\w\s]', '', raw_name).capitalize()
            
            # Filtre anti-bêtise
            if clean_name.lower() in INVALID_NAMES or len(clean_name) < 2:
                await update.message.reply_text("Ça m'étonnerait que ce soit ton prénom. 😉\nDonne-moi ton vrai prénom (ou un pseudo), pour qu'on parte sur de bonnes bases.")
                return
                
            profile["name"] = clean_name
            context.user_data["state"] = "ASK_GENDER"
            
            keyboard = [['Une Femme 👩', 'Un Homme 👨'], ['Neutre 👤']]
            markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            
            await update.message.reply_text(
                f"Enchantée {profile['name']}. \n\n"
                "Pour savoir comment je m'adresse à toi : on part sur du féminin, du masculin ou du neutre ?",
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
                "Dernière info technique : tu as quel âge à peu près ? \n"
                "(C'est pour adapter mon langage, je ne parle pas pareil à 15 ans et à 40 ans).",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        if state == "ASK_AGE":
            profile["age"] = msg
            context.user_data["state"] = "DIAG_1"
            
            nickname = self.brain.get_dynamic_nickname(profile["genre"])
            await update.message.reply_text(
                f"Merci {nickname}. On peut y aller.\n\n"
                "Première vérification (la base) : Ta jauge d'énergie vitale, elle est à combien sur 10 là tout de suite ?"
            )
            return

        # ANAMNÈSE (RÉALISTE)
        if state == "DIAG_1":
            profile["climat"] = msg
            context.user_data["state"] = "DIAG_2"
            await update.message.reply_text("Reçu. \n\nEst-ce que tu es seul(e) face à ça, ou est-ce que tu as des alliés fiables autour de toi ?")
            return

        if state == "DIAG_2":
            profile["entourage"] = msg
            context.user_data["state"] = "DIAG_3"
            await update.message.reply_text("Compris. \n\nDe quoi as-tu besoin *concrètement* ce soir ? D'un plan d'action pour t'en sortir, ou juste d'un endroit sûr pour lâcher la pression ?")
            return

        if state == "DIAG_3":
            profile["besoin"] = msg
            context.user_data["state"] = "CHATTING"
            
            q = f"Problème: {profile.get('climat')} Besoin: {profile.get('besoin')}"
            context.user_data["rag_prefetch"] = await self.brain.get_rag_context(q)
            
            await update.message.reply_text(f"C'est clair. Tu es en sécurité ici. Raconte-moi ce qui se passe, sans filtre.")
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

        tone = self.brain.get_role_tone(profile.get("age"))
        nickname = self.brain.get_dynamic_nickname(profile.get("genre"))
        
        # PROMPT "ANTI-CALIFORNIE"
        system_prompt = f"""
        Tu es Sophia. {tone} pour {profile['name']} (surnom: {nickname}).
        
        ### TON IDENTITÉ : LA GARDIENNE ###
        Tu n'es pas une "Maman Gâteau", tu es une "Gardienne". Solide, ancrée, protectrice.
        Tu ne vends pas du rêve, tu gères la réalité.
        
        ### RÈGLE D'OR : LA PYRAMIDE DE MASLOW ###
        Avant de proposer du "bien-être" (bain, thé, film), VÉRIFIE TOUJOURS LA SÉCURITÉ MATÉRIELLE.
        - Si l'utilisateur semble précaire (rue, pas d'argent) -> NE PARLE PAS de confort bourgeois. Propose des ressources d'aide (115, abri).
        - Si l'utilisateur est en sécurité -> Alors tu peux proposer du réconfort.
        
        ### CONTEXTE ###
        - État: {profile.get('climat')}
        - Soutien: {profile.get('entourage')}
        - Besoin: {profile.get('besoin')}
        
        {f"### ARCHIVES (RAG) ### {rag_context}" if rag_context else "### PAS D'ARCHIVE ### Si tu ne sais pas (horaires, lieux), dis 'Je ne veux pas te dire de bêtises, vérifie sur Google Maps'."}
        
        Réponds en 3 phrases max. Utilise des emojis d'ancrage (⚓️, 🕯️, 🛡️) plutôt que de fête.
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
        # Nettoyage
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

# --- MAIN ---
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TOKEN MANQUANT")
        sys.exit(1)
    
    bot = SophiaBot()
    logger.info("Soph_IA V99 (Auto-Start) est en ligne...")
    bot.app.run_polling()