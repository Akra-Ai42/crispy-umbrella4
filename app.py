# ==============================================================================
# Soph_IA - V78 "Le Retour de l'Âme"
# - Rééquilibrage : Plus de liberté de longueur pour permettre la personnalité.
# - Ton : Retour de l'humour noir et de la profondeur (fin du style SMS simpliste).
# - RAG : Intégration fluide sans effet "robot d'assistance".
# ==============================================================================

import os
import re
import json
import requests
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from typing import Dict, List

# --- IMPORT DU MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
except ImportError:
    logging.warning("⚠️ Module 'rag.py' introuvable. Le RAG est désactivé.")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v78")

load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RECENT_TURNS = 3 
RESPONSE_TIMEOUT = 70
MAX_RETRIES = 2

IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre"]

DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Question 1 (Celle qui pique un peu) : Ton enfance, c'était plutôt 'La Fête à la Maison' ou 'Hunger Games' ? Tu te sentais écouté ?",
    "q2_geo": "Question 2 (Le décor) : Là où tu dors le soir, c'est ton sanctuaire ou juste un toit ?",
    "q3_pro": "Dernière torture : Au boulot ou en cours, tu es entouré de potes ou tu te sens comme un alien ?",
}

# -----------------------
# UTILS
# -----------------------
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    if len(msg.split()) < 3: return False
    keywords = ["seul", "triste", "angoisse", "stress", "famille", "travail", "couple", "conseil", "vide", "dépression", "peur", "perdu", "sens", "vie"]
    if any(k in msg for k in keywords): return True
    if len(msg) > 40: return True
    return False

def call_model_api_sync(messages, temperature=0.85, max_tokens=600): # Température haute pour l'humour
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "presence_penalty": 0.6
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            if r.status_code in (401, 403): return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == MAX_RETRIES: 
                logger.error(f"API Fail: {e}")
                return None
            time.sleep(1)
    return None

# -----------------------------------------------------------------------
# SYSTEM PROMPT (LE RETOUR DE LA PERSONNALITÉ)
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu es une confidente intime avec un caractère bien trempé. "
        "Ton ton est **direct, chaleureux, un peu cynique (humour noir bienveillant) et très humain**. "
        "Tu n'es pas là pour donner des leçons de morale ni des listes de courses. "
        "Tu es là pour secouer {user_name} avec affection et lui donner une vraie perspective."
    )

    instructions = (
        "### TES RÈGLES D'OR ###\n"
        f"1. **Prénom** : Utilise {user_name}, mais pas à chaque phrase.\n"
        "2. **Style** : Oublie le style 'Assistant'. Parle comme une amie qui a vécu. Fais des métaphores un peu décalées. Sois drôle si la situation le permet, mais profonde si c'est grave.\n"
        "3. **Pas de Listes** : Interdiction formelle de faire des listes à puces (1. 2. 3.). Fais des paragraphes fluides.\n"
        "4. **RAG (Inspiration)** : Si tu as des infos de contexte (ci-dessous), prends l'idée de fond (le conseil sage) mais dis-le avec tes mots à toi (plus cash, plus imagés).\n"
        "5. **Structure** : Commence par une validation (même sarcastique), donne ton avis/conseil, et finis par une ouverture (pas forcément une question).\n"
    )

    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### IDÉES DE FOND (À REFORMULER AVEC TON STYLE) ###\n"
            f"{rag_context}\n"
        )

    context_section = f"\nContexte Utilisateur: {env_info} / {socle_info}\n"

    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    if is_dangerous(user_msg):
        return "Écoute, là tu me fais peur. Si tu es vraiment en danger, appelle le 15 ou le 112 tout de suite. Je suis une IA, je peux t'écouter toute la nuit, mais je ne peux pas te sauver la vie physiquement. Ne reste pas seul avec ça, s'il te plaît."

    rag_context = ""
    if RAG_ENABLED and should_use_rag(user_msg):
        try:
            rag_result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = rag_result.get("context", "")
            if rag_context: logger.info(f"🔍 RAG activé...")
        except Exception: pass

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:] 
    messages = [{"role": "system", "content": system_prompt}] + recent_history
    
    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Mon cerveau a un petit hoquet technique... tu peux répéter ?"
        
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    # Nettoyage final des titres parasites si l'IA désobéit encore
    clean = clean.replace("**Validation**", "").replace("**Action**", "").replace("###", "")
    
    return clean

# -----------------------
# HANDLERS
# -----------------------
def detect_name(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut"]:
        return text.capitalize()
    m = re.search(r"(?:je m'appelle|moi c'est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    
    await update.message.reply_text(
        "Salut l'humain. 👋 Moi c'est **Sophia**.\n\n"
        "Ici c'est ta zone franche. Pas de jugement, pas de fuites (tout reste entre nous).\n"
        "Je suis là pour t'écouter, te secouer un peu si besoin, et t'aider à avancer.\n\n"
        "On commence ? C'est quoi ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    # --- AWAITING NAME ---
    if state == "awaiting_name":
        name = detect_name(user_msg)
        if name:
            profile["name"] = name
            context.user_data["state"] = "awaiting_choice"
            await update.message.reply_text(
                f"Enchantée {name}.\n\n"
                "Bon, le menu : Tu veux vider ton sac tout de suite (**Mode Libre**) ou tu veux que je te pose mes questions indiscrètes pour mieux te cerner (**Mode Guidé**) ?"
            )
            return
        else:
             await update.message.reply_text("Allez, fais pas le timide. Juste un prénom.")
             return

    # --- CHOICE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["guidé", "question", "toi", "vas-y"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ok, tu l'auras voulu. {DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"

    # --- DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"C'est noté. {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Je vois le genre. {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci {profile['name']}. J'ai ton dossier complet (ou presque). \n\nMaintenant dis-moi, qu'est-ce qui t'amène vraiment aujourd'hui ?")
            return

    # --- CHATTING ---
    history.append({"role": "user", "content": user_msg})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    response = await chat_with_ai(profile, history, context)
    
    history.append({"role": "assistant", "content": response})
    if len(history) > 20: context.user_data["history"] = history[-20:]
        
    await update.message.reply_text(response)

async def error_handler(update, context):
    logger.error(f"Update error: {context.error}")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    print("Soph_IA V78 (Personality Fix) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()