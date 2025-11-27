# ==============================================================================
# Soph_IA - V79 "RAG Sensible & Concision"
# - RAG : Déclenchement facilité (seuil baissé).
# - Style : Concision forcée (Max 2 paragraphes).
# - Debug : Logs "print" visibles pour confirmer le RAG.
# ==============================================================================

import os
import re
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
    print("✅ [INIT] Module RAG chargé.")
except ImportError:
    print("⚠️ [INIT] Module RAG non trouvé.")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v79")

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
    "q1_fam": "Question 1 (Celle qui pique) : Ton enfance, c'était plutôt 'La Fête à la Maison' ou 'Hunger Games' ? Tu te sentais écouté ?",
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
    
    # Filtre Anti-Small Talk (seulement les très courts)
    if len(msg.split()) < 3 and len(msg) < 15: 
        print(f"🚫 [RAG SKIP] Message trop court : '{msg}'")
        return False
        
    # Mots-clés élargis
    keywords = ["seul", "triste", "angoisse", "stress", "famille", "travail", "couple", "conseil", "vide", "dépression", "peur", "perdu", "sens", "vie", "mal", "dormir", "fatigue", "boss", "patron"]
    
    if any(k in msg for k in keywords): 
        print(f"✅ [RAG TRIGGER] Mot-clé trouvé dans : '{msg}'")
        return True
        
    # Seuil de longueur baissé (25 chars)
    if len(msg) > 25: 
        print(f"✅ [RAG TRIGGER] Message long (>25 chars).")
        return True
        
    return False

def call_model_api_sync(messages, temperature=0.85, max_tokens=500): # Max tokens réduit pour forcer la concision
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
# SYSTEM PROMPT (CONCISION FORCÉE)
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")
    
    role = (
        "Tu es Sophia. Une confidente intime avec du caractère. "
        "Ton ton est **direct, chaleureux, cynique-bienveillant**. "
        "Tu es là pour secouer {user_name} avec affection."
    )

    instructions = (
        "### TES RÈGLES ABSOLUES ###\n"
        f"1. **Prénom** : Utilise {user_name} par moments.\n"
        "2. **CONCISION EXTRÊME** : Fais court. Max 2 paragraphes. Pas de romans. Va droit au but.\n"
        "3. **Style** : Parle comme une vraie personne. Métaphores décalées bienvenues, mais pas de poésie lourde.\n"
        "4. **RAG (Fond)** : Si tu as du contexte ci-dessous, utilise le conseil sage qu'il contient, mais reformule-le en mode 'Sophia Relou'.\n"
        "5. **Structure** : Une validation (drôle/directe) + Un conseil/avis + Une ouverture.\n"
    )

    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### SOURCE D'INSPIRATION (RAG) ###\n"
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
        return "Écoute, là tu me fais peur. Si tu es en danger, appelle le 15 ou le 112. Je ne peux pas t'aider physiquement. Ne reste pas seul."

    rag_context = ""
    if RAG_ENABLED and should_use_rag(user_msg):
        try:
            print(f"🔍 [RAG] Interrogation en cours pour : {user_msg[:30]}...")
            rag_result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = rag_result.get("context", "")
            if rag_context: 
                print(f"✅ [RAG] Contexte trouvé ({len(rag_context)} chars).")
            else:
                print("⚠️ [RAG] Aucune correspondance trouvée.")
        except Exception as e: 
            print(f"❌ [RAG] Erreur : {e}")

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:] 
    messages = [{"role": "system", "content": system_prompt}] + recent_history
    
    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Mon cerveau a un petit hoquet... tu peux répéter ?"
        
    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    clean = clean.replace("**Validation**", "").replace("###", "")
    
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
        "Salut l'humain. 👋 Moi c'est Sophia.\n\n"
        "Zone franche ici. Pas de jugement, pas de fuites.\n"
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
                "Menu du jour : Vider ton sac (Mode Libre) ou répondre à mes questions indiscrètes (Mode Guidé) ?"
            )
            return
        else:
             await update.message.reply_text("Allez, juste un prénom.")
             return

    # --- CHOICE ---
    if state == "awaiting_choice":
        if any(w in user_msg.lower() for w in ["guidé", "question", "toi", "vas-y"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"Ok, c'est parti. {DIAGNOSTIC_QUESTIONS['q1_fam']}")
            return
        else:
            context.user_data["state"] = "chatting"

    # --- DIAGNOSTIC ---
    if state.startswith("diag_"):
        if state == "diag_1":
            profile["socle_info"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"Noté. {DIAGNOSTIC_QUESTIONS['q2_geo']}")
            return
        if state == "diag_2":
            profile["geo_info"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"Je vois. {DIAGNOSTIC_QUESTIONS['q3_pro']}")
            return
        if state == "diag_3":
            profile["pro_info"] = user_msg
            context.user_data["state"] = "chatting"
            await update.message.reply_text(f"Merci {profile['name']}. J'ai le dossier. \n\nMaintenant, dis-moi ce qui t'amène vraiment.")
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
    print("Soph_IA V79 (RAG Sensible) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()