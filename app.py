# app.py (V83 - PARTIE 1/2 : Cerveau & Logique)
# ==============================================================================
import os
import re
import requests
import json
import asyncio
import logging
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- IMPORT MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    print("✅ [INIT] Module RAG chargé.")
except Exception as e:
    print(f"⚠️ [INIT] RAG non trouvé: {e}")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v83")
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b") # Modèle Stable
MAX_RETRIES = 2

IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

DIAGNOSTIC_QUESTIONS = {
    "q1_etat": "Ok, scan rapide. Batterie mentale : 0 (Zombie) à 10 (Guerrier). T'es où ? Et qu'est-ce qui te vide le plus ?",
    "q2_liens": "Noté. Niveau entourage : tu as une main à attraper si ça tangue, ou tu gères en mode loup solitaire ?",
    "q3_pivot": "Dernière chose : si tu avais une baguette magique pour changer UN seul truc ce soir, ce serait quoi ?",
}

# --- SMART ROUTER ---
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    
    # Filtre les messages courts SAUF urgence émotionnelle
    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide"]): return True
        return False

    deep_triggers = [
        "triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", 
        "honte", "fatigue", "bout", "marre", "pleur", "mal", "douleur", "panique", 
        "joie", "espoir", "perdu", "doute", "famille", "père", "mère", "parent", 
        "ami", "pote", "copain", "copine", "couple", "ex", "relation", "solitude", 
        "rejet", "abandon", "trahison", "confiance", "travail", "boulot", "étude", 
        "école", "argent", "avenir", "sens", "rien", "dormir", "nuit", "journée", 
        "problème", "solution", "conseil", "avis", "choix", "décision"
    ]
    
    if any(trigger in msg for trigger in deep_triggers): return True
    if len(msg.split()) >= 6: return True
    return False

def call_model_api_sync(messages, temperature=0.8, max_tokens=450):
    payload = {
        "model": MODEL_NAME, "messages": messages, "temperature": temperature,
        "max_tokens": max_tokens, "top_p": 0.9, "repetition_penalty": 1.15
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code in (401, 403): return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == MAX_RETRIES: return None
            time.sleep(1)
    return None

# --- SYSTEM PROMPT ---
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    role = "Tu es Sophia. Une confidente impliquée, pas une assistante. Fais parler l'utilisateur."
    instructions = (
        "### RÈGLES D'OR ###\n"
        f"1. ADRESSE-TOI à {user_name}. Directe, chaleureuse.\n"
        "2. INTERDICTION : Ne finis JAMAIS par 'Je suis là', 'N'hésite pas'.\n"
        "3. OBLIGATION : Finis TOUJOURS par une QUESTION de relance.\n"
        "4. SÉCURITÉ : Urgence vitale = renvoie 15 ou 3114.\n"
    )
    rag_section = f"\n### SCÉNARIOS (INSPIRATION) ###\n{rag_context}\n" if rag_context else ""
    context_section = (
        f"\n### PROFIL ###\n- Énergie: {user_profile.get('etat_esprit')}\n"
        f"- Entourage: {user_profile.get('entourage')}\n- Besoin: {user_profile.get('besoin_pivot')}\n"
    )
    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# --- ORCHESTRATION ---
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    if is_dangerous(user_msg):
        return "Je t'écoute et c'est lourd. Je suis une IA. Ne reste pas seul(e). Appelle le **3114** ou le **15**."

    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
    # RAG PRIORITAIRE V83 : Recherche LIVE si émotion forte
    if should_use_rag(user_msg):
        try:
            print(f"🔍 [RAG] Recherche LIVE : {user_msg[:30]}...")
            result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = result.get("context", "")
            context.user_data["rag_prefetch"] = None 
        except Exception: pass
    elif prefetch:
        rag_context = prefetch
        context.user_data["rag_prefetch"] = None 

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:]
    messages = [{"role": "system", "content": system_prompt}] + recent_history

    raw = await asyncio.to_thread(call_model_api_sync, messages)
    if not raw or raw == "FATAL_KEY": return "J'ai bugué... tu disais ?"

    clean = raw
    for pat in IDENTITY_PATTERNS: clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    clean = clean.replace("Je suis là pour toi", "").replace("N'hésite pas", "")
    return clean
# ... (Coller à la suite de la Partie 1) ...

# -----------------------
# HANDLERS (UX ORGANIQUE)
# -----------------------
def detect_name(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut"]:
        return text.capitalize()
    m = re.search(r"(?:je m'appelle|moi c'est|prenom est)\s*([A-Za-zÀ-ÖØ-öø-ÿ]+)", text, re.IGNORECASE)
    return m.group(1).capitalize() if m else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    
    await update.message.reply_text(
        "Bonjour. Je suis Sophia.\n\n"
        "Ici, c'est ta bulle. Pas de jugement.\n"
        "On commence par les présentations ? C'est quoi ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    if state == "awaiting_name":
        name = detect_name(user_msg)
        if name:
            profile["name"] = name
            context.user_data["state"] = "awaiting_choice"
            # [CHANGEMENT V83] Choix Direct 1/2
            await update.message.reply_text(
                f"Enchantée {name}. On fait comment ?\n\n"
                "1. Je te pose quelques questions ?\n"
                "2. C'est urgent, tu parles direct ?"
            )
            return
        else:
            profile["name"] = "l'ami"
            context.user_data["state"] = "awaiting_choice"
            await update.message.reply_text("Ok. On fait comment ?\n1. Questions guidées ?\n2. Tu parles direct ?")
            return

    if state == "awaiting_choice":
        msg_lower = user_msg.lower()
        if any(w in msg_lower for w in ["1", "un", "question", "guide", "oui"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"C'est parti. {DIAGNOSTIC_QUESTIONS['q1_etat']}")
            return
        
        # Par défaut ou "2" -> Chat direct
        context.user_data["state"] = "chatting"
        if len(user_msg.split()) < 5:
            await update.message.reply_text("Je t'écoute. Raconte-moi, qu'est-ce qui se passe ?")
            return

    if state.startswith("diag_"):
        if state == "diag_1":
            profile["etat_esprit"] = user_msg
            context.user_data["state"] = "diag_2"
            await update.message.reply_text(f"{DIAGNOSTIC_QUESTIONS['q2_liens']}")
            return
        if state == "diag_2":
            profile["entourage"] = user_msg
            context.user_data["state"] = "diag_3"
            await update.message.reply_text(f"{DIAGNOSTIC_QUESTIONS['q3_pivot']}")
            return
        if state == "diag_3":
            profile["besoin_pivot"] = user_msg
            context.user_data["state"] = "chatting"
            
            # Prefetch RAG
            prefetch_query = f"Besoin: {profile.get('besoin_pivot')} Psychologie"
            if RAG_ENABLED:
                try:
                    res = await asyncio.to_thread(rag_query, prefetch_query, 2)
                    if res.get("context"): context.user_data["rag_prefetch"] = res.get("context")
                except Exception: pass
            
            await update.message.reply_text(f"Merci {profile['name']}. C'est noté. \n\nJe t'écoute. Dis-moi ce qui t'amène vraiment ?")
            return

    history.append({"role": "user", "content": user_msg})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await chat_with_ai(profile, history, context)
    history.append({"role": "assistant", "content": response})
    if len(history) > 20:
        context.user_data["history"] = history[-20:]
    await update.message.reply_text(response)

async def error_handler(update, context):
    logger.error(f"Erreur Update: {context.error}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERREUR : TELEGRAM_BOT_TOKEN manquant")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("Soph_IA V83 (Anti-Boucle & UX Directe) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()