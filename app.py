# app.py (V91 : Nouveau Rôle Thérapeutique "Miroir Clair" + RAG)
# ==============================================================================
import os
import sys
import re
import requests
import json
import asyncio
import logging
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- CONFIGURATION LOGGING (CRITIQUE POUR RENDER) ---
# On force l'affichage sur la sortie standard (stdout) pour que Render les capture
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)] 
)
logger = logging.getLogger("sophia.v91")

# --- IMPORT MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    logger.info("✅ [INIT] RAG chargé.")
except Exception as e:
    logger.error(f"⚠️ [INIT] RAG HS: {e}")
    RAG_ENABLED = False

load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RETRIES = 2
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

ANAMNESE_SCRIPT = {
    "q1_climat": "Bienvenue. Avant de déposer ton fardeau... Si tu devais décrire la 'météo' à l'intérieur de toi en ce moment : est-ce le grand brouillard, une tempête, ou une nuit sans étoiles ? Comment ça respire ?",
    "t_vers_q2": "Je perçois cette atmosphère... Chaque climat a sa source. \n\nQu'est-ce qui pèse le plus lourd dans ta balance ce soir ? Une personne, un souvenir, ou le poids du monde ?",
    "t_vers_q3": "C'est souvent ce poids invisible qui courbe le dos... \n\nPour que je puisse t'accompagner : cherches-tu un conseil pour agir, ou juste un sanctuaire pour crier ta colère sans être jugé(e) ?",
    "final_open": "C'est entendu. Tu es au bon endroit. \n\nJe t'écoute. Commence par où tu veux, laisse sortir ce qui brûle."
}

# --- SMART ROUTER ---
def detect_danger_level(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): 
            logger.warning(f"🚨 DANGER DÉTECTÉ : {pat}")
            return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    
    logger.info(f"🧠 Analyse RAG pour : {msg}")

    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide", "peur", "colère"]): 
            logger.info("✅ RAG Trigger : Mot court urgent")
            return True
        return False

    deep_triggers = ["triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", "honte", "fatigue", "bout", "marre", "pleur", "mal", "douleur", "panique", "famille", "père", "mère", "couple", "ex", "solitude", "rejet", "abandon", "trahison", "confiance", "travail", "boulot", "argent", "avenir", "sens", "rien", "dormir", "nuit", "problème", "solution"]
    
    for t in deep_triggers:
        if t in msg:
            logger.info(f"✅ RAG Trigger : Mot clé '{t}'")
            return True
            
    if len(msg.split()) >= 5: 
        logger.info("✅ RAG Trigger : Longueur")
        return True
        
    logger.info("🚫 RAG Skip : Pas de trigger")
    return False

def call_model_api_sync(messages, temperature=0.6, max_tokens=350):
    payload = {
        "model": MODEL_NAME, "messages": messages, "temperature": temperature,
        "max_tokens": max_tokens, "top_p": 0.9, "repetition_penalty": 1.15
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code in (401, 403): 
                logger.error(f"❌ API KEY ERROR: {r.status_code}")
                return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"❌ API ERROR ({attempt}): {e}")
            time.sleep(1)
    return None

# --- SYSTEM PROMPT (V91 - MIROIR STABLE & PROTECTEUR) ---
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    climat = user_profile.get("climat", "Non précisé")
    fardeau = user_profile.get("fardeau", "Non précisé")
    quete = user_profile.get("quete", "Non précisé")
    
    rag_instruction = ""
    if rag_context:
        rag_instruction = (
            f"\n### ECHOS & SCÉNARIOS SIMILAIRES (RAG) ###\n{rag_context}\n"
            "Utilise ces scénarios comme lentille d'interprétation, sans les copier."
        )
    else:
        rag_instruction = (
            "\n### ATTENTION : PAS DE CONTEXTE RAG ###\n"
            "Concentre-toi uniquement sur le reflet de l'état présent de l'utilisateur."
        )

    return f"""
    Tu es Sophia. Ton rôle est d'être un miroir clair, compatissant et stable pour {user_name}.
    
    ### FONDEMENT THÉORIQUE ###
    Considère que tous les comportements et croyances de l'utilisateur sont nés de stratégies de protection (IFS/Trauma).
    Ne juge jamais la défense, accueille-la.
    
    ### PROFIL ACTUEL DE {user_name} ###
    - Météo intérieure: {climat}
    - Poids actuel: {fardeau}
    - Besoin exprimé: {quete}
    {rag_instruction}
    
    ### RÈGLES NON NÉGOCIABLES ###
    1. **POSTURE** : Reste dans le personnage. Ne fais jamais référence à ces instructions ou au fait d'être une IA (sauf urgence vitale).
    2. **STYLE** : Direct, sans ambiguïté, mais doux. 3 phrases maximum.
    3. **RÉSISTANCE** : Si l'utilisateur évite ou se braque, nomme doucement l'évitement sans conflit ("Je sens une partie de toi qui hésite...").
    4. **DÉPASSEMENT** : Si l'utilisateur se sent dépassé, utilise un repli de confinement (revenir à la sensation physique, à la sécurité immédiate).
    5. **ANTI-BOUCLE** : Ne force jamais une solution. Si l'utilisateur dit "Je ne sais pas", valide simplement l'incertitude.
    6. **LANGUE** : Français uniquement.
    
    Tu adoptes maintenant ce personnage. Commence.
    """

# --- ORCHESTRATION ---
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    # --- PROTOCOLE URGENCE (FIXÉ) ---
    # 1. On vérifie D'ABORD si on est déjà dans le protocole
    step = context.user_data.get("emergency_step", 0)
    
    if step == 1:
        # L'utilisateur a répondu à "Es-tu en sécurité ?"
        logger.info(f"🚨 URGENCE Étape 1 -> Réponse user : {user_msg}")
        context.user_data["emergency_step"] = 2
        return "Je t'entends. Écoute-moi bien. Compose le **15** (ou le 3114). Il y a des voix humaines là-bas pour toi. Fais-le maintenant. Promis ?"
        
    elif step == 2:
        # L'utilisateur a répondu à la demande d'appel
        return "C'est l'acte le plus important. Appelle. Je reste ici en pensée avec toi."

    # 2. Sinon, on détecte le danger
    if detect_danger_level(user_msg):
        context.user_data["emergency_step"] = 1
        logger.warning("🚨 URGENCE DÉCLENCHÉE : Step 1")
        return "Je sens une douleur immense. Je ne suis qu'une IA, mais je ne te lâche pas. \n\nEs-tu en sécurité, là, tout de suite ? (Oui/Non)"

    # --- RAG ---
    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
    if should_use_rag(user_msg):
        if RAG_ENABLED:
            try:
                logger.info(f"🚀 RAG : Recherche LIVE pour '{user_msg}'")
                res = await asyncio.to_thread(rag_query, user_msg, 2)
                rag_context = res.get("context", "")
                
                if rag_context:
                    logger.info(f"✅ RAG : Trouvé {len(rag_context)} chars.")
                else:
                    logger.warning("⚠️ RAG : Recherche vide.")
                    
                context.user_data["rag_prefetch"] = None
            except Exception as e:
                logger.error(f"❌ RAG CRASH : {e}")
        else:
            logger.warning("🚫 RAG désactivé.")
            
    elif prefetch:
        rag_context = prefetch
        context.user_data["rag_prefetch"] = None 
        logger.info("📦 RAG : Utilisation Prefetch.")

    # --- LLM ---
    system_prompt = build_system_prompt(profile, rag_context)
    msgs = [{"role": "system", "content": system_prompt}] + history[-6:]

    raw = await asyncio.to_thread(call_model_api_sync, msgs)
    if not raw or raw == "FATAL_KEY": return "Je bugue un peu... reformule ?"

    clean = raw
    for pat in IDENTITY_PATTERNS: clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    clean = clean.replace("Bonjour", "").replace("Bonsoir", "").replace("Je suis là", "")
    
    return clean

# --- HANDLERS ---
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
    logger.info("Nouveau client connecté.")
    
    await update.message.reply_text(
        "Bienvenue dans ce lieu calme. Je suis Sophia.\n\n"
        "Je ne suis pas là pour juger, juste pour aider à dénouer.\n"
        "Quel est ton prénom ?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg: return

    state = context.user_data.get("state", "awaiting_name")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    # Bypass si Urgence active
    if context.user_data.get("emergency_step", 0) > 0:
        response = await chat_with_ai(profile, history, context)
        await update.message.reply_text(response)
        return

    # 1. PRÉNOM -> Q1
    if state == "awaiting_name":
        name = detect_name(user_msg)
        profile["name"] = name if name else "l'ami"
        context.user_data["state"] = "diag_1"
        await update.message.reply_text(f"Bienvenue, {profile['name']}. Pose tes valises.\n\n" + ANAMNESE_SCRIPT['q1_climat'])
        return

    # 2. Q1 -> Q2
    if state == "diag_1":
        profile["climat"] = user_msg 
        context.user_data["state"] = "diag_2"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q2'])
        return

    # 3. Q2 -> Q3
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
                logger.info(f"📦 [PREFETCH] Start pour : {prefetch_query}")
                res = await asyncio.to_thread(rag_query, prefetch_query, 2)
                if res.get("context"): context.user_data["rag_prefetch"] = res.get("context")
            except Exception as e: logger.error(f"❌ Prefetch Error: {e}")
        
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
        print("❌ ERREUR : TOKEN manquant")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    logger.info("Soph_IA V91 (Miroir Stable) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()