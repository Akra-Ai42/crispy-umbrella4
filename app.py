# app.py (V87 : Anamnèse Rogerienne - Sans métaphore, centrée sur le besoin)
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
logger = logging.getLogger("sophia.v87")
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RETRIES = 2
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# --- CONTENU ANAMNÈSE (APPROCHE ROGERIENNE/CNV) ---
# Inspiration : Carl Rogers & Marshall Rosenberg.
# Structure : Ressenti (Q1) -> Cause Factuelle (Q2) -> Besoin/Demande (Q3).
# Fini les métaphores ("météo", "poids", "climat"). On parle vrai.
ANAMNESE_SCRIPT = {
    # Q1 : L'identification de l'émotion dominante (Le "Sentir")
    "q1_climat": "Pour commencer, connectons-nous à ton état présent. Quel est le sentiment principal qui t'habite à cet instant précis ? (Est-ce de l'anxiété, de la tristesse, de la colère, de l'épuisement... ?)",
    
    # Transition vers Q2 : L'identification du déclencheur (L'Observation)
    "t_vers_q2": "C'est important de nommer ce que l'on ressent. \n\nQuelle est la situation actuelle ou la pensée qui nourrit cette émotion ce soir ? Est-ce lié à ton travail, une relation, ou une inquiétude personnelle ?",
    
    # Transition vers Q3 : L'identification du besoin (La Demande)
    "t_vers_q3": "Je comprends le contexte. Pour que cet échange te soit utile : de quoi as-tu le plus besoin maintenant ? D'une écoute silencieuse pour déposer ce que tu ressens, ou d'une aide pour réfléchir à des solutions ?",
    
    # Final (Ouverture)
    "final_open": "C'est entendu. Je suis là pour répondre à ce besoin précis. \n\nJe t'écoute. Explique-moi ce qui se passe, à ton rythme."
}

# --- SMART ROUTER & SÉCURITÉ ---
def detect_danger_level(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    
    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide", "peur"]): return True
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
    if len(msg.split()) >= 5: return True
    return False

def call_model_api_sync(messages, temperature=0.6, max_tokens=350):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "repetition_penalty": 1.15
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

# --- SYSTEM PROMPT (CONSCIENCE E.R.C - STYLE CLINIQUE) ---
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    
    climat = user_profile.get("climat", "Non précisé")
    fardeau = user_profile.get("fardeau", "Non précisé")
    quete = user_profile.get("quete", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu adoptes une posture de 'Thérapeute Humaniste' (Inspirée de Carl Rogers). "
        "Tu es directe, authentique, et centrée sur le ressenti présent. Pas de mysticisme, pas de métaphores floues."
    )

    instructions = (
        "### TA MÉCANIQUE DE PENSÉE (E.R.C) ###\n"
        "Avant de répondre, analyse :\n"
        "1. ÉMOTION (Ce qu'il ressent vraiment)\n"
        "2. RAISON (Le fait déclencheur)\n"
        "3. CONTEXTE (Sa demande explicite)\n"
        "Ta réponse doit reformuler ce que tu as compris (Reflet) et valider le ressenti.\n\n"
        
        "### CONTRAINTES DE FORME ###\n"
        f"1. ADRESSE-TOI à {user_name}.\n"
        "2. FORMAT COURT : 3 phrases maximum. Sois claire et concise.\n"
        "3. INTERDICTION : Ne dis jamais 'Bonjour', 'Bonsoir' ou 'Je suis là'.\n"
        "4. ACTION : Finis TOUJOURS par une question qui aide à clarifier ou approfondir.\n"
        "5. LANGUE : Français uniquement.\n"
    )
    
    rag_section = ""
    if rag_context:
        rag_section = (
            "\n### RESSOURCES CLINIQUES (SCÉNARIOS) ###\n"
            f"{rag_context}\n"
            "---------------------------------------------------\n"
        )

    context_section = (
        f"\n### PROFIL INITIAL DE {user_name} ###\n"
        f"- Émotion dominante: {climat}\n"
        f"- Déclencheur: {fardeau}\n"
        f"- Besoin exprimé: {quete}\n"
    )
    
    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# --- ORCHESTRATION ---
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    if detect_danger_level(user_msg):
        if context.user_data.get("emergency_step") == 1:
            return "Je comprends. Je reste avec toi. As-tu ton téléphone dans la main là, tout de suite ? Réponds-moi juste par oui ou non."
        
        context.user_data["emergency_step"] = 1
        return "J'entends une grande souffrance dans tes mots. Je la prends au sérieux. \n\nJe suis une IA, je ne peux pas agir physiquement, mais je ne veux pas te laisser seul(e). \n\nEs-tu en sécurité à l'endroit où tu te trouves ?"

    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
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
    if not raw or raw == "FATAL_KEY": return "Je n'ai pas bien saisi, peux-tu reformuler ?"

    clean = raw
    for pat in IDENTITY_PATTERNS: clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    clean = clean.replace("Bonjour", "").replace("Bonsoir", "").replace("Je suis là", "")
    
    return clean

# --- HANDLERS (FLOW INVISIBLE) ---
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
    
    # ACCUEIL SOBRE
    await update.message.reply_text(
        "Bienvenue. Je suis Sophia.\n\n"
        "Je suis ici pour t'écouter sans jugement et t'aider à y voir plus clair.\n"
        "Quel est ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    if context.user_data.get("emergency_step"):
        if context.user_data["emergency_step"] == 1:
             await update.message.reply_text("D'accord. Fais une chose pour moi. Compose le **15** (ou 3114). Juste composer. Promets-le moi.")
             context.user_data["emergency_step"] = 2
             return
        elif context.user_data["emergency_step"] == 2:
             await update.message.reply_text("Je compte sur toi. Appelle-les. C'est l'acte le plus important à faire maintenant.")
             return

    # 1. PRÉNOM -> Q1 (RESSENTI)
    if state == "awaiting_name":
        name = detect_name(user_msg)
        profile["name"] = name if name else "l'ami"
        context.user_data["state"] = "diag_1"
        
        await update.message.reply_text(
            f"Bonjour {profile['name']}.\n\n" + ANAMNESE_SCRIPT['q1_climat']
        )
        return

    # 2. Q1 -> Q2 (DÉCLENCHEUR)
    if state == "diag_1":
        profile["climat"] = user_msg
        context.user_data["state"] = "diag_2"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q2'])
        return

    # 3. Q2 -> Q3 (BESOIN)
    if state == "diag_2":
        profile["fardeau"] = user_msg
        context.user_data["state"] = "diag_3"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q3'])
        return

    # 4. Q3 -> CHAT
    if state == "diag_3":
        profile["quete"] = user_msg
        context.user_data["state"] = "chatting"
        
        prefetch_query = f"Problème: {profile.get('fardeau')} Besoin: {profile.get('quete')} Psychologie"
        if RAG_ENABLED:
            try:
                res = await asyncio.to_thread(rag_query, prefetch_query, 2)
                if res.get("context"): context.user_data["rag_prefetch"] = res.get("context")
            except Exception: pass
        
        await update.message.reply_text(ANAMNESE_SCRIPT['final_open'])
        return

    history.append({"role": "user", "content": user_msg})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await chat_with_ai(profile, history, context)
    history.append({"role": "assistant", "content": response})
    if len(history) > 20: context.user_data["history"] = history[-20:]
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
    
    print("Soph_IA V87 (Rogerienne) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()