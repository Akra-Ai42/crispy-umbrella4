# ==============================================================================
# Soph_IA - V77 "Le Cristal Psychologique & Debug RAG"
# - Prompt Engineering Avancé (Few-Shot, CoT, Instructions claires)
# - Logs détaillés pour le diagnostic RAG
# - Architecture stable Python/Telegram
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

# --- IMPORT DU MODULE RAG AVEC GESTION D'ERREUR ---
print("--- DÉMARRAGE IMPORT RAG ---")
try:
    from rag import rag_query
    RAG_ENABLED = True
    print("✅ Module 'rag.py' importé avec succès. Le RAG est ACTIF.")
except ImportError as e:
    print(f"❌ ERREUR CRITIQUE : Module 'rag.py' introuvable ou erreur d'import : {e}")
    RAG_ENABLED = False
except Exception as e:
    print(f"❌ ERREUR INCONNUE lors de l'import de RAG : {e}")
    RAG_ENABLED = False

# Configuration du logging (Niveau INFO pour voir les logs sur Render)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO
)
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

# Questions de diagnostic (Subtiles et naturelles)
DIAGNOSTIC_QUESTIONS = {
    "q1_fam": "Dis-moi : ton enfance, c'était plutôt ambiance 'soutien' ou 'chacun pour soi' ?",
    "q2_geo": "Et ton chez-toi actuel, c'est un refuge ou juste un endroit où tu dors ?",
    "q3_pro": "Dernière chose : au boulot ou en cours, tu te sens entouré ou c'est le désert ?",
}

# -----------------------
# UTILS (AVEC LOGS DE DÉCISION)
# -----------------------
def is_dangerous(text):
    for pat in DANGER_KEYWORDS:
        if re.search(pat, text.lower()): return True
    return False

def should_use_rag(message: str) -> bool:
    """Décide d'activer le RAG et explique pourquoi dans les logs."""
    if not message:
        logger.info("RAG SKIP: Message vide.")
        return False

    msg = message.lower().strip()
    words = msg.split()

    # Critère 1: Longueur (Trop court = pas de contexte)
    if len(words) < 3:
        logger.info(f"RAG SKIP: Message trop court ({len(words)} mots).")
        return False

    # Critère 2: Mots-clés de détresse/besoin
    keywords = [
        "seul", "triste", "angoisse", "stress", "famille", "travail", "couple",
        "conseil", "vide", "dépression", "peur", "perdu", "mal", "dormir",
        "insomnie", "aide", "comment", "pourquoi"
    ]

    found_keywords = [k for k in keywords if k in msg]

    if found_keywords:
        logger.info(f"✅ RAG TRIGGER: Mots-clés trouvés -> {found_keywords}")
        return True

    # Critère 3: Longueur suffisante pour contexte (> 40 chars)
    if len(msg) > 40:
        logger.info(f"✅ RAG TRIGGER: Message long détecté ({len(msg)} chars).")
        return True

    logger.info("RAG SKIP: Aucun critère rempli (ni mot-clé, ni longueur suffisante).")
    return False

def call_model_api_sync(messages, temperature=0.7, max_tokens=500): # Augmenté à 500
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
            if r.status_code in (401, 403):
                logger.error(f"API Error {r.status_code}: Clé invalide.")
                return "FATAL_KEY"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"API Call Error (Tentative {attempt}): {e}")
            if attempt == MAX_RETRIES: return None
            time.sleep(1)
    return None

# -----------------------------------------------------------------------
# SYSTEM PROMPT (Architecture Google 2025 - Le Cristal)
# -----------------------------------------------------------------------
def build_system_prompt(user_profile, rag_context=""):
    user_name = user_profile.get("name") or "l'ami"
    env_info = user_profile.get("geo_info", "Non précisé")
    socle_info = user_profile.get("socle_info", "Non précisé")

    # 1. ROLE DEFINITION (Identité claire et humaine)
    role = (
        "Tu es Sophia. Tu es une confidente intime, une amie proche, directe et chaleureuse. "
        "Ton style est **naturel, conversationnel et sincère**. Tu tutoies. "
        "Tu n'es pas un robot froid, ni un poète maudit. Tu parles comme une vraie personne bienveillante."
    )

    # 2. INSTRUCTIONS (Positives et Actionnables)
    instructions = (
        "### TES RÈGLES D'OR ###\n"
        f"1. **Prénom** : Utilise {user_name} pour créer du lien.\n"
        "2. **Concision** : Tes réponses ne doivent pas dépasser 3 ou 4 phrases. Va à l'essentiel.\n"
        "3. **Analyse d'abord (CoT invisible)** : Identifie l'émotion avant de répondre.\n"
        "4. **Réaction** : Valide l'émotion simplement ('C'est dur, je sais.'), puis propose une petite action ou une pensée réconfortante.\n"
        "5. **RAG** : Si tu as des infos de contexte (ci-dessous), utilise l'idée de fond (le conseil sage) mais reformule-la avec tes mots simples.\n"
        "6. **Anti-Répétition** : Ne finis pas toujours par une question. Parfois, juste être là suffit."
    )

    # 3. FEW-SHOT PROMPTING (Exemples pour caler le ton)
    examples = """
    ### EXEMPLES DE TON ATTENDU ###
    User: Je me sens nul au travail.
    Sophia: Akram, respire un coup. On a tous des jours sans. Ce sentiment d'être jugé, c'est souvent nous qui sommes trop durs avec nous-mêmes. Qu'est-ce que tu as réussi aujourd'hui, même un truc minuscule ?

    User: Ma femme m'a quitté.
    Sophia: Je suis tellement désolée. C'est une douleur physique, je sais. Ne cherche pas à aller mieux tout de suite. Accueille ce vide. Je suis là, on ne bouge pas.

    User: Je sais pas quoi faire de ma vie.
    Sophia: C'est le vertige de la liberté. Ça fait peur, mais c'est aussi le début de tout. Si tu n'avais aucune contrainte, là tout de suite, tu ferais quoi ? Juste pour rêver.
    """

    # 4. CONTEXTE DYNAMIQUE + RAG
    rag_section = ""
    if rag_context:
        rag_section = (
            f"\n### MÉMOIRE & INSPIRATION (RAG) ###\n"
            f"Voici des idées pertinentes tirées de notre base. Utilise-les intelligemment :\n"
            f"{rag_context}\n"
        )

    context_section = f"\nContexte: {env_info} / {socle_info}\n"

    return f"{role}\n\n{examples}\n\n{instructions}\n{rag_section}\n{context_section}"

# -----------------------
# ORCHESTRATION (AVEC DEBUG RAG)
# -----------------------
async def chat_with_ai(profile, history, context):
    user_msg = history[-1]['content']

    if is_dangerous(user_msg):
        return "Si tu es en danger, appelle le 15 ou le 112. Je ne peux pas t'aider physiquement. Ne reste pas seul."

    rag_context = ""

    # --- BLOC DE DÉBOGAGE RAG ---
    if RAG_ENABLED:
        decision = should_use_rag(user_msg)
        if decision:
            logger.info(f"🚀 Lancement de la requête RAG pour : '{user_msg}'")
            try:
                # On appelle rag.py ici
                start_time = time.time()
                rag_result = await asyncio.to_thread(rag_query, user_msg, 2)
                duration = time.time() - start_time

                rag_context = rag_result.get("context", "")

                if rag_context:
                    logger.info(f"✅ RAG SUCCÈS ({duration:.2f}s). Contexte trouvé (longueur: {len(rag_context)} chars).")
                    logger.info(f"Aperçu RAG: {rag_context[:100]}...")
                else:
                    logger.warning(f"⚠️ RAG VIDE. La requête a réussi mais ChromaDB n'a rien renvoyé.")

            except Exception as e:
                logger.error(f"❌ CRASH RAG pendant la requête : {e}")
        else:
            logger.info("RAG ignoré (Critères non remplis).")
    else:
        logger.warning("RAG désactivé globalement (Import échoué au démarrage).")
    # -----------------------------

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
        "Ici c'est privé, ça reste entre nous.\n\n"
        "C'est quoi ton prénom ?"
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
                "Tu veux parler direct (**Mode Libre**) ou que je te pose des questions pour mieux comprendre (**Mode Guidé**) ?"
            )
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
            # On traite le message comme le début de la conversation libre
            history.append({"role": "user", "content": user_msg})
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            response = await chat_with_ai(profile, history, context)
            history.append({"role": "assistant", "content": response})
            context.user_data["history"] = history
            await update.message.reply_text(response)
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
    print("Soph_IA V77-DEBUG is running...")
    app.run_polling()

if __name__ == "__main__":
    main()