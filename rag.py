# app.py (V82 : Optimisation pour Lecture des Redflags/Souffrance)
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
from typing import Dict, List

# --- IMPORT DU MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    # [CHANGEMENT V82] Confirmation que le module RAG est aligné
    print("✅ [INIT] Module RAG chargé (Support Redflags & Souffrance).")
except Exception as e:
    print(f"⚠️ [INIT] Module RAG non trouvé: {e}")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("sophia.v82")

load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
# [CORRECTION] Retour au modèle stable utilisé en production
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

MAX_RECENT_TURNS = 10
RESPONSE_TIMEOUT = 30
MAX_RETRIES = 2

IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une ia"]
DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# PROTOCOLE GUIDÉ (MODERNE : Théorie de l'Autodétermination & Thérapie Brève)
DIAGNOSTIC_QUESTIONS = {
    # But : Évaluer la charge mentale et la capacité de régulation immédiate
    "q1_etat": "Ok, on fait un scan rapide. Sur une échelle de batterie mentale, si 0 c'est 'Zombie complet' et 10 'Prêt à conquérir le monde', tu te situes où là tout de suite ? Et qu'est-ce qui consomme le plus ton énergie ?",
    
    # But : Évaluer le réseau de soutien (Facteur de protection vs Isolement)
    "q2_liens": "Je note le niveau d'énergie. Maintenant, regarde autour de toi : quand ça tangue, est-ce que tu as une 'main' à attraper (ami, famille, partenaire) ou est-ce que tu gères tout en mode loup solitaire ?",
    
    # But : "Question Miracle" - Identifier le besoin prioritaire pour orienter le RAG
    "q3_pivot": "Dernière chose pour que je puisse vraiment t'aider : si tu avais une baguette magique pour changer UN seul truc dans ta situation ce soir, ce serait quoi ?",
}

# -----------------------
# SMART ROUTER
# -----------------------
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    """
    Déclencheur RAG V82 : Toujours basé sur la profondeur émotionnelle
    pour aller chercher les scénarios correspondants.
    """
    if not message: return False
    msg = message.lower().strip()
    
    if len(msg.split()) < 3 and len(msg) < 12:
        print(f"🚫 [RAG SKIP] Message trop court/superficiel.")
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
    
    if any(trigger in msg for trigger in deep_triggers):
        print(f"✅ [RAG TRIGGER] Thème émotionnel détecté.")
        return True
    
    if len(msg.split()) >= 6:
        print(f"✅ [RAG TRIGGER] Narration détectée.")
        return True

    return False

def call_model_api_sync(messages, temperature=0.75, max_tokens=450):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "repetition_penalty": 1.1
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
# SYSTEM PROMPT (V82 : Lecture Intelligente des Métadonnées)
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    # Mise à jour des clés de profil pour correspondre aux nouvelles questions
    etat_esprit = user_profile.get("etat_esprit", "Non précisé")
    entourage = user_profile.get("entourage", "Non précisé")
    besoin_pivot = user_profile.get("besoin_pivot", "Non précisé")
    
    role = (
        "Tu es Sophia, la 'Confidente de Poche'. "
        "Ni psy clinique, ni robot froid. Tu es une présence lucide, apaisante et expérimentée. "
        "Tu ne juges jamais, mais tu sais repérer quand ça ne va pas."
    )

    instructions = (
        "### TES DIRECTIVES ###\n"
        f"1. Tonalité : Parle à {user_name} naturellement. Phrases fluides, chaleureuses.\n"
        "2. Écoute Active : Valide l'émotion avant de conseiller.\n"
        "3. UTILISATION DU RAG (IMPORTANT) : Les textes ci-dessous sont des CAS SIMILAIRES passés.\n"
        "   - Regarde l'INTENSITÉ (niveau de souffrance) indiquée dans l'exemple.\n"
        "   - Si un exemple contient '⚠️ NOTE: Redflag', sois extrêmement prudente et douce.\n"
        "   - Inspire-toi de la 'Réponse idéale' pour structurer ta propre réponse.\n"
        "4. SÉCURITÉ : En cas de risque vital immédiat, renvoie vers le 15 ou le 3114.\n"
    )

    rag_section = ""
    if rag_context:
        # [CHANGEMENT V82] En-tête explicite pour guider le modèle
        rag_section = (
            "\n### 🧠 MÉMOIRE EXPÉRIENTIELLE (Scénarios Comparables) ###\n"
            "Analyse ces précédents pour calibrer ta réponse :\n"
            f"{rag_context}\n"
            "---------------------------------------------------\n"
        )

    context_section = (
        f"\n### PROFIL IMMÉDIAT ###\n"
        f"- État/Énergie: {etat_esprit}\n"
        f"- Soutien Social: {entourage}\n"
        f"- Besoin Prioritaire (Pivot): {besoin_pivot}\n"
    )
    
    return f"{role}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']
    
    if is_dangerous(user_msg):
        return "Je t'écoute et je sens que c'est très lourd. Mais je suis une IA, je ne peux pas intervenir physiquement. \n\nS'il te plaît, ne reste pas seul(e). Appelle le **3114** (Écoute Suicide 24/7) ou le **15**. C'est important."

    rag_context = ""
    prefetch = context.user_data.get("rag_prefetch")
    
    if prefetch:
        rag_context = prefetch
        context.user_data["rag_prefetch"] = None 
        print(f"🔎 [RAG] Utilisation du profil préchargé.")
    elif RAG_ENABLED and should_use_rag(user_msg):
        try:
            print(f"🔍 [RAG] Recherche de scénarios pour : {user_msg[:30]}...")
            # On récupère 2 scénarios pour l'inspiration
            result = await asyncio.to_thread(rag_query, user_msg, 2)
            rag_context = result.get("context", "")
            if rag_context:
                print(f"✅ [RAG] Scénarios trouvés (avec métadonnées).")
            else:
                print("⚠️ [RAG] Pas de scénario proche.")
        except Exception as e:
            print(f"❌ [RAG] Erreur : {e}")

    system_prompt = build_system_prompt(profile, rag_context)
    recent_history = history[-6:]
    messages = [{"role": "system", "content": system_prompt}] + recent_history

    raw = await asyncio.to_thread(call_model_api_sync, messages)
    
    if not raw or raw == "FATAL_KEY":
        return "Je t'ai perdu une seconde... tu peux répéter ?"

    clean = raw
    for pat in IDENTITY_PATTERNS:
        clean = re.sub(pat, "", clean, flags=re.IGNORECASE)
    
    return clean

# -----------------------
# HANDLERS (UX ORGANIQUE)
# -----------------------
def detect_name(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in ["bonjour", "salut", "hello", "yo"]:
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
        "Ici, c'est ta bulle. Pas de jugement, juste de l'écoute.\n"
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
            await update.message.reply_text(
                f"Enchantée {name}. \n\n"
                "Je suis là pour t'écouter. Tu veux me raconter ce qui t'arrive directement, "
                "ou tu préfères que je te pose quelques questions pour t'aider à y voir plus clair ?"
            )
            return
        else:
            profile["name"] = "l'ami"
            context.user_data["state"] = "awaiting_choice"
            await update.message.reply_text(
                "Ça marche, restons discrets. \n\n"
                "Dis-moi : tu veux vider ton sac tout de suite, ou tu préfères que je te guide avec des questions ?"
            )
            return

    if state == "awaiting_choice":
        msg_lower = user_msg.lower()
        if any(w in msg_lower for w in ["question", "guide", "guider", "pose", "interroge", "vas-y", "aide-moi"]):
            context.user_data["state"] = "diag_1"
            await update.message.reply_text(f"C'est parti. {DIAGNOSTIC_QUESTIONS['q1_etat']}")
            return
        
        context.user_data["state"] = "chatting"
        if len(user_msg.split()) < 5:
            await update.message.reply_text("Je t'écoute. Prends ton temps, je suis là.")
            return

    if state.startswith("diag_"):
        if state == "diag_1":
            profile["etat_esprit"] = user_msg
            context.user_data["state"] = "diag_2"
            # Transition fluide basée sur la réponse précédente
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
            
            # Prefetch RAG ciblé sur le "Besoin Pivot" + "État d'esprit"
            # C'est ici que la finalité s'exprime : on cherche une réponse adaptée au BUT de l'utilisateur
            prefetch_query = f"État: {profile.get('etat_esprit')} Besoin: {profile.get('besoin_pivot')} psychologie"
            if RAG_ENABLED:
                try:
                    res = await asyncio.to_thread(rag_query, prefetch_query, 2)
                    pref = res.get("context", "")
                    if pref: context.user_data["rag_prefetch"] = pref
                except Exception: pass
            
            await update.message.reply_text(f"Merci {profile['name']}. C'est très clair. \n\nJe t'écoute, dis-moi ce qui t'amène aujourd'hui, on va regarder ça ensemble.")
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
        print("❌ ERREUR : TELEGRAM_BOT_TOKEN manquant dans .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    print("Soph_IA V82 (Organique & Redflags Aware) est en ligne...")
    app.run_polling()

if __name__ == "__main__":
    main()