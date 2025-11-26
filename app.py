# ==============================================================================
# Soph_IA - V77 "Stabilité & Anti-Boucle Prénom"
# - Correction critique : Empêche le bot de redemander le prénom si déjà connu.
# - Optimisation : Meilleure gestion de la persistance de l'état.
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
logger = logging.getLogger("sophia.v77")

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
    "q1_fam": "Dis-moi : ton enfance, c'était plutôt ambiance 'soutien' ou 'chacun pour soi' ?",
    "q2_geo": "Et ton chez-toi actuel, c'est un refuge ou juste un endroit où tu dors ?",
    "q3_pro": "Dernière chose : au boulot ou en cours, tu te sens entouré ou c'est le désert ?",
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
    keywords = ["seul", "triste", "angoisse", "stress", "famille", "travail", "couple", "conseil", "vide", "dépression", "peur", "perdu"]
    if any(k in msg for k in keywords): return True
    return False

def call_model_api_sync(messages, temperature=0.7, max_tokens=500):
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
# SYSTEM PROMPT
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu es une amie proche, directe et chaleureuse. "
        "Ton style est **bref, percutant et conversationnel** (comme un SMS). "
        "Tu tutoies. Tu détestes les longs discours."
    )

    instructions = (
        "### TES RÈGLES D'OR ###\n"
        f"1. **Prénom** : Utilise {user_name} naturellement.\n"
        "2. **Concision** : Tes réponses ne doivent JAMAIS dépasser 3 ou 4 phrases. Sois direct.\n"
        "3. **Style Parlé** : Pas de poésie. Parle comme une vraie personne.\n"
        "4. **Réaction** : Valide l'émotion, et propose une idée simple.\n"
        "5. **RAG** : Utilise le contexte ci-dessous pour donner un conseil pertinent, mais reformule-le simplement.\n"
    )

    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### IDÉES UTILES ###\n"
            f"{rag_context}\n"
        )

    context_section = f"\nContexte: {env_info} / {socle_info}\n"

    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    if is_dangerous(user_msg):
        return "Si tu es en danger, appelle le 15 ou le 112. Je ne peux pas t'aider physiquement. Ne reste pas seul."

    rag_context = ""
    if RAG_ENABLED and should_use_rag(user_msg):
        try:
            rag_result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = rag_result.get("context", "")
        except Exception: pass

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:] 
    messages = [{"role": "system", "content": system_prompt}] + recent_history
    
    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Je bugue un peu... redis-moi ?"
        
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    return clean

# -----------------------
# HANDLERS
# -----------------------
def detect_name(text):
    text = text.strip()
    # Si c'est juste un mot, on suppose que c'est un nom
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut"]:
        return text.capitalize()
    # Si c'est une phrase, on cherche le pattern
    m = re.search(r"(?:je m'appelle|moi c'est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    
    await update.message.reply_text(
        "Salut. Moi c'est Sophia.\n"
        "Ici c'est privé.\n\n"
        "C'est quoi ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    # --- GESTION D'ÉTAT ROBUSTE ---
    # Si le profil a déjà un nom, on force l'état à ne JAMAIS être 'awaiting_name'
    # Sauf si l'utilisateur a explicitement fait /start (qui clear le profil)
    profile = context.user_data.setdefault("profile", {})
    if profile.get("name") and context.user_data.get("state") == "awaiting_name":
        # Correction automatique de l'état si bug
        context.user_data["state"] = "chatting"
    
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # --- AWAITING NAME ---
    if state == "awaiting_name":
        name = detect_name(user_msg)
        if name:
            profile["name"] = name
            context.user_data["state"] = "awaiting_choice"
            await update.message.reply_text(
                f"Enchantée {name}.\n\n"
                "Tu veux parler direct Mode Libre ou que je te pose des questions Mode Guidé ?"
            )
            return
        else:
             # Si on ne trouve pas de nom mais que la phrase est longue, on suppose que l'utilisateur veut parler
             # et on lui donne un nom par défaut pour débloquer la situation.
             if len(user_msg.split()) > 3:
                 profile["name"] = "l'ami"
                 context.user_data["state"] = "chatting"
                 # On traite le message comme du chat
                 history.append({"role": "user", "content": user_msg})
                 await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                 response = await chat_with_ai(profile, history, context)
                 history.append({"role": "assistant", "content": response})
                 await update.message.reply_text(response)
                 return
             else:
                 await update.message.reply_text("Juste ton prénom, stp.")
                 return

    # --- CHOICE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["guidé", "question", "toi", "vas-y"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ça marche. {DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"
            # Si l'utilisateur répond autre chose, on considère qu'il parle déjà
            if len(user_msg.split()) > 2:
                 history.append({"role": "user", "content": user_msg})
                 await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                 response = await chat_with_ai(profile, history, context)
                 history.append({"role": "assistant", "content": response})
                 await update.message.reply_text(response)
                 return
            else:
                 await update.message.reply_text("Ok, je t'écoute.")
                 return

    # --- DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"Ok. Et chez toi : {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Je vois. Dernière : {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci {profile['name']}. J'y vois plus clair.\n\nComment tu te sens là, tout de suite ?")
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
    print("Soph_IA V77 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()