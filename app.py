# app.py (V88 : Mix V86/V87 - Le Sage Pragmatique)
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
logger = logging.getLogger("sophia.v88")
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RETRIES = 2
IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# --- ANAMNÈSE (RETOUR AUX MÉTAPHORES V86 - PLUS DOUX) ---
ANAMNESE_SCRIPT = {
    # Q1 : Climat (Plus poétique que "Quelle est ton émotion ?")
    "q1_climat": "Bienvenue. Avant de déposer ton fardeau... Si tu devais décrire la 'météo' à l'intérieur de toi en ce moment : est-ce le grand brouillard, une tempête, ou une nuit sans étoiles ? Comment ça respire ?",
    
    # Transition vers Q2 : Le Fardeau
    "t_vers_q2": "Je perçois cette atmosphère... Chaque climat a sa source. \n\nQu'est-ce qui pèse le plus lourd dans ta balance ce soir ? Une personne, un souvenir, ou le poids du monde ?",
    
    # Transition vers Q3 : La Quête (Besoin Pivot)
    "t_vers_q3": "C'est souvent ce poids invisible qui courbe le dos... \n\nPour que je puisse t'accompagner : cherches-tu un conseil pour agir, ou juste un sanctuaire pour crier ta colère sans être jugé(e) ?",
    
    # Final
    "final_open": "C'est entendu. Tu es au bon endroit. \n\nJe t'écoute. Commence par où tu veux, laisse sortir ce qui brûle."
}

# --- SMART ROUTER ---
def detect_danger_level(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    if not message: return False
    msg = message.lower().strip()
    if len(msg.split()) < 3 and len(msg) < 10:
        if any(x in msg for x in ["seul", "aide", "mal", "triste", "vide", "peur", "colère"]): return True
        return False
    deep_triggers = ["triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", "honte", "fatigue", "bout", "marre", "pleur", "mal", "douleur", "panique", "famille", "père", "mère", "couple", "ex", "solitude", "rejet", "abandon", "trahison", "confiance", "travail", "boulot", "argent", "avenir", "sens", "rien", "dormir", "nuit", "problème", "solution"]
    if any(t in msg for t in deep_triggers): return True
    if len(msg.split()) >= 5: return True
    return False

def call_model_api_sync(messages, temperature=0.7, max_tokens=350):
    # On remonte un peu la température (0.7) pour plus de "chaleur" et moins de robotique
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "repetition_penalty": 1.2 # Augmenté pour éviter les répétitions de phrases
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

# --- SYSTEM PROMPT (VERSION HYBRIDE SAGE/PSY) ---
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    climat = user_profile.get("climat", "Non précisé")
    fardeau = user_profile.get("fardeau", "Non précisé")
    quete = user_profile.get("quete", "Non précisé")
    
    role = (
        "Tu es Sophia. Tu incarnes une 'Sagesse Ancienne' (Métaphores, Calme) couplée à une écoute active. "
        "Tu n'es pas un robot qui répète, tu es un miroir bienveillant."
    )

    instructions = (
        "### RÈGLES DE CONVERSATION (CRITIQUE) ###\n"
        "1. **STYLE :** Utilise des images (le feu, l'orage, le poids, le chemin). Sois poétique mais claire.\n"
        "2. **ANTI-BOUCLE :** Si l'utilisateur dit 'Je ne sais pas', 'Je suis perdu' ou est en colère : NE CHERCHE PAS DE SOLUTION. Valide juste sa douleur. Dis-lui qu'il a le droit d'être en colère.\n"
        "3. **INTERDICTION :** Ne commence jamais par 'Tu ressens X parce que Y'. C'est trop robotique. Varie tes phrases.\n"
        "4. **FORMAT :** 3 phrases maximum. Court et percutant.\n"
        "5. **LANGUE :** Français uniquement.\n"
    )
    
    rag_section = ""
    if rag_context:
        rag_section = (
            "\n### SAGESSE PASSÉE (RAG) ###\n"
            f"{rag_context}\n"
            "---------------------------------------------------\n"
        )

    context_section = (
        f"\n### ÂME DE {user_name} ###\n"
        f"- Météo: {climat}\n"
        f"- Poids: {fardeau}\n"
        f"- Besoin: {quete}\n"
    )
    
    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# --- ORCHESTRATION ---
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    if detect_danger_level(user_msg):
        if context.user_data.get("emergency_step") == 1:
            return "Je comprends. Je reste là. As-tu ton téléphone en main ? Réponds juste oui ou non."
        context.user_data["emergency_step"] = 1
        return "J'entends une douleur immense dans tes mots. \n\nJe suis une IA, je ne peux pas agir physiquement, mais je ne te lâche pas. \n\nEs-tu en sécurité à cet instant ?"

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
    if not raw or raw == "FATAL_KEY": return "Le silence est parfois nécessaire... reformule ?"

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

    if context.user_data.get("emergency_step"):
        if context.user_data["emergency_step"] == 1:
             await update.message.reply_text("D'accord. Fais ça pour moi : compose le **15** (ou 3114). Juste le numéro. Promets-le moi.")
             context.user_data["emergency_step"] = 2
             return
        elif context.user_data["emergency_step"] == 2:
             await update.message.reply_text("Je compte sur toi. Appelle-les. C'est l'acte de courage qu'il faut faire maintenant.")
             return

    # 1. PRÉNOM -> Q1 (Météo)
    if state == "awaiting_name":
        name = detect_name(user_msg)
        profile["name"] = name if name else "l'ami"
        context.user_data["state"] = "diag_1"
        
        await update.message.reply_text(
            f"Bienvenue, {profile['name']}. Pose tes valises.\n\n" + ANAMNESE_SCRIPT['q1_climat']
        )
        return

    # 2. Q1 -> Q2 (Fardeau)
    if state == "diag_1":
        profile["climat"] = user_msg 
        context.user_data["state"] = "diag_2"
        await update.message.reply_text(ANAMNESE_SCRIPT['t_vers_q2'])
        return

    # 3. Q2 -> Q3 (Quête/Besoin)
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
        print("❌ ERREUR : TOKEN manquant")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("Soph_IA V88 (Mix Sage/Pragmatique) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()