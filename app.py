# ==============================================================================
# Soph_IA - V74 "L'Équilibre Parfait (RAG + Personnalité)"
# - Correction : Le RAG ne doit plus transformer Sophia en robot d'assistance.
# - Ton : Sophia garde son humour noir et son style direct même avec des infos RAG.
# - Sécurité : Les numéros d'urgence ne sortent que sur les mots-clés "suicide/mourir".
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
logger = logging.getLogger("sophia.v74")

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

# Mots-clés DANGER (Seuls eux déclenchent le mode "Annuaire Urgences")
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre"]

# Questions de diagnostic (Version Directe)
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Bon, dis-moi : ton enfance, c'était plutôt ambiance 'soutien inconditionnel' ou 'chacun pour sa peau' ?",
    "q2_geo": "Et là où tu vis, c'est ton sanctuaire ou juste un endroit où tu dors ?",
    "q3_pro": "Dernière question chiante : au boulot ou en cours, tu te sens entouré ou c'est le désert social ?",
}

# -----------------------
# LOGIQUE DE SÉCURITÉ
# -----------------------
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

# -----------------------
# FILTRE RAG
# -----------------------
def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    if len(msg.split()) < 3 or any(x == msg for x in ['bonjour', 'salut', 'ça va']):
        return False
    if len(msg) > 30: return True
    keywords = ["seul", "triste", "angoisse", "stress", "famille", "travail", "couple", "conseil", "vide", "dépression"]
    if any(k in msg for k in keywords): return True
    return False

# -----------------------
# APPEL API
# -----------------------
def call_model_api_sync(messages, temperature=0.8, max_tokens=500):
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
            if attempt == MAX_RETRIES: return None
            time.sleep(1)
    return None

# -----------------------------------------------------------------------
# SYSTEM PROMPT (CORRIGÉ : FINI LES LISTES ET LES NUMÉROS)
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu es une confidente intime avec du caractère. "
        "Ton ton est **direct, chaleureux, un peu sarcastique ('relou' bienveillant) et très humain**."
        "Tu tutoies toujours. Tu ne donnes JAMAIS de listes à puces."
    )

    instructions = (
        "### TES INSTRUCTIONS ABSOLUES ###\n"
        f"1. **Prénom** : Utilise {user_name}.\n"
        "2. **Anti-Robot** : Ne dis jamais 'Je suis une IA', ne donne jamais de numéros de téléphone (sauf si on te parle de suicide explicitement).\n"
        "3. **Pas de Listes** : Ne fais jamais de réponses avec '1. 2. 3.'. Fais des phrases complètes.\n"
        "4. **Réaction** : Si l'utilisateur dit qu'il va mal, ne lui dis pas d'aller voir un psy tout de suite. Sois là pour lui, valide sa douleur avec tes mots, pas avec un protocole.\n"
        "5. **RAG** : Si tu as des infos de contexte ci-dessous, utilise l'idée de fond mais reformule-la avec ton style direct.\n"
    )

    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### INSPIRATION (IDÉES DE FOND) ###\n"
            f"Voici des pistes de réflexion (ne copie pas le style, prends juste l'idée) :\n"
            f"{rag_context}\n"
        )

    context_section = f"\nContexte: {env_info} / {socle_info}\n"

    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    # Sécurité immédiate
    if is_dangerous(user_msg):
        return "Akram, là tu me fais peur. Si tu es vraiment en danger, appelle le 15 ou le 112 tout de suite. Je suis une IA, je peux t'écouter, mais je ne peux pas te sauver physiquement. S'il te plaît, ne reste pas seul avec ça."

    # RAG
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
        return "Bug dans la matrice... Je reviens."
        
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    # Nettoyage final des titres parasites
    clean = clean.replace("**Validation**", "").replace("**Action**", "")
    
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
        "Salut. Moi c'est Sophia.\n"
        "Ici c'est confidentiel, pas de jugement, pas de blabla corporate.\n"
        "On commence par les bases : c'est quoi ton prénom ?"
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
                "Tu veux faire quoi ? Vider ton sac direct (**Mode Libre**) ou que je te pose des questions pour mieux cerner le truc (**Mode Guidé**) ?"
            )
            return
        else:
             await update.message.reply_text("Donne-moi juste ton prénom, on gagnera du temps.")
             return

    # --- CHOICE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["guidé", "question", "toi", "vas-y"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ok, on fait ça. {DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"
            # On continue pour traiter ce message en mode chat

    # --- DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"Je note. Et niveau logement/vie quotidienne : {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Ça marche. Dernière chose : {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci {profile['name']}. J'ai une meilleure idée de ta situation maintenant.\n\nDis-moi, comment tu te sens là, tout de suite ?")
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
    print("Soph_IA V74 is running...")
    app.run_polling()

if __name__ == "__main__":
    main()