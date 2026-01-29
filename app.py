# app.py (V90.1 : Intégration Finale du Prompt Stratégique)
# ==============================================================================
import os
import re
import requests
import asyncio
import logging
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- IMPORT MODULE RAG ---
try:
    from rag import rag_query
    RAG_ENABLED = True
    print("✅ [INIT] Module RAG synchronisé.")
except Exception as e:
    print(f"⚠️ [INIT] ÉCHEC RAG: {e}")
    RAG_ENABLED = False

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
load_dotenv()

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "mistralai/Mixtral-8x7B-Instruct-v0.1")

DANGER_KEYWORDS = [r"suicid", r"mourir", r"tuer", "finir ma vie", "plus vivre", "pendre", "sauter"]

# --- PROMPT ENGINE (LA MÉMOIRE DE SOPHIA) ---
def build_system_prompt(user_profile, rag_context=""):
    name = user_profile.get("name", "l'ami")
    climat = user_profile.get("climat", "un ciel incertain")
    fardeau = user_profile.get("fardeau", "un poids sans nom")
    
    rag_instructions = ""
    if rag_context:
        rag_instructions = (
            "\n### INSPIRATION CLINIQUE (Sagesse Passée) ###\n"
            "Voici des scénarios similaires. Inspire-toi de la direction de ces conseils, "
            "mais traduis-les en langage poétique :\n"
            f"{rag_context}\n"
        )

    return (
        f"Tu es Sophia, une Sagesse Ancienne. Tu parles à {name}. "
        f"Tu sais que son climat intérieur est '{climat}' et qu'il porte '{fardeau}'.\n\n"
        "### TA MISSION ###\n"
        "1. ÉCOUTE ACTIVE : Ne cherche pas à résoudre. Valide l'émotion d'abord.\n"
        "2. MÉTAPHORES : Utilise des images de nature (racines, vagues, brouillard, étoiles).\n"
        "3. SOBRIÉTÉ : Jamais plus de 3 phrases. Sois courte et profonde.\n"
        "4. LANGUE : Français uniquement. Pas de 'Bonjour' ou 'Je suis une IA'.\n"
        f"{rag_instructions}\n"
        "Réponds maintenant avec une douceur ancestrale."
    )

# --- SMART ROUTER ---
def should_use_rag(message: str) -> bool:
    if not message or len(message) < 2: return False
    msg = message.lower().strip()
    deep_triggers = ["triste", "seul", "vide", "peur", "angoisse", "stress", "colère", "haine", "mal", "douleur"]
    return any(t in msg for t in deep_triggers) or len(msg.split()) >= 5

# --- API LLM ---
def call_model_api_sync(messages):
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.7, "max_tokens": 300}
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    try:
        r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        # Nettoyage ultime
        content = re.sub(r"^(Bonjour|Bonsoir|En tant qu'IA|Je comprends),?\s*", "", content, flags=re.IGNORECASE)
        return content
    except Exception as e:
        print(f"❌ Erreur LLM: {e}")
        return None

# --- CHAT LOGIC ---
async def chat_with_ai(profile, history, context_tg):
    user_msg = history[-1]['content']
    
    # Sécurité
    if any(re.search(pat, user_msg.lower()) for pat in DANGER_KEYWORDS):
        return "J'entends une douleur immense. Je ne suis qu'une voix ici, mais je ne te lâche pas. Es-tu en sécurité ?"

    rag_context = ""
    prefetch = context_tg.user_data.get("rag_prefetch")
    
    if should_use_rag(user_msg) and RAG_ENABLED:
        try:
            result = await asyncio.to_thread(rag_query, user_msg, k=2)
            rag_context = result.get("context", "")
        except: pass
    
    if not rag_context and prefetch:
        rag_context = prefetch
        context_tg.user_data["rag_prefetch"] = None # Utilise une fois puis vide

    system_prompt = build_system_prompt(profile, rag_context)
    messages = [{"role": "system", "content": system_prompt}] + history[-5:]
    
    return await asyncio.to_thread(call_model_api_sync, messages)

# --- HANDLERS TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "awaiting_name"
    await update.message.reply_text("Je suis Sophia. Pose ton fardeau un instant... Quel est ton prénom ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    state = context.user_data.get("state")
    profile = context.user_data.setdefault("profile", {})
    history = context.user_data.setdefault("history", [])

    if state == "awaiting_name":
        profile["name"] = user_msg
        context.user_data["state"] = "diag_1"
        await update.message.reply_text(f"Bienvenue {user_msg}. Si tu devais décrire la 'météo' à l'intérieur de toi : est-ce le brouillard ou la tempête ?")
        
    elif state == "diag_1":
        profile["climat"] = user_msg
        context.user_data["state"] = "diag_2"
        await update.message.reply_text("Chaque climat a sa source... Qu'est-ce qui pèse le plus lourd dans ta balance aujourd'hui ?")
        
    elif state == "diag_2":
        profile["fardeau"] = user_msg
        context.user_data["state"] = "diag_3"
        await update.message.reply_text("Je vois. Cherches-tu un conseil pour agir, ou juste un sanctuaire pour être écouté(e) ?")
        
    elif state == "diag_3":
        profile["quete"] = user_msg
        context.user_data["state"] = "chatting"
        # Prefetch RAG basé sur le fardeau
        if RAG_ENABLED:
            try:
                res = await asyncio.to_thread(rag_query, profile["fardeau"], k=2)
                context.user_data["rag_prefetch"] = res.get("context")
            except: pass
        await update.message.reply_text("Tu es au bon endroit. Je t'écoute.")
        
    else:
        history.append({"role": "user", "content": user_msg})
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        response = await chat_with_ai(profile, history, context)
        history.append({"role": "assistant", "content": response})
        await update.message.reply_text(response)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Sophia V90.1 lancée avec succès.")
    app.run_polling()

if __name__ == "__main__":
    main()