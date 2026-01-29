# rag.py
import os
import chromadb
import requests
from dotenv import load_dotenv

load_dotenv()

# CONFIGURATION
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "sophia-arbre")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "sophia")

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HF_MODEL_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

_CLIENT = None
_COLLECTION = None

def get_collection():
    global _CLIENT, _COLLECTION
    if _COLLECTION: return _COLLECTION

    try:
        print(f"🔌 [RAG] Connexion à la collection '{CHROMA_COLLECTION_NAME}'...")
        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        # On laisse Chroma gérer l'embedding function par défaut pour éviter les conflits
        _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME)
        print("✅ [RAG] Collection connectée.")
        return _COLLECTION
    except Exception as e:
        print(f"❌ [RAG] Erreur connexion: {e}")
        return None

def rag_query(user_message: str, k: int = 2):
    """Récupère les scénarios similaires dans la base de données."""
    collection = get_collection()
    if not collection: return {"context": "", "chunks": [], "metadatas": []}

    try:
        results = collection.query(query_texts=[user_message], n_results=k)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents: return {"context": "", "chunks": [], "metadatas": []}

        context_blocks = []
        for meta in metadatas:
            meta = meta or {}
            block = (
                f"--- SCÉNARIO (Thème: {meta.get('theme', 'Général')}) ---\n"
                f"👤 Situation: \"{meta.get('question', 'Inconnue')}\"\n"
                f"💡 Réponse Psy: \"{meta.get('reponse', 'Non disponible')}\"\n"
            )
            context_blocks.append(block)

        return {
            "context": "\n".join(context_blocks),
            "chunks": documents,
            "metadatas": metadatas
        }
    except Exception as e:
        print(f"⚠️ [RAG] Erreur requête: {e}")
        return {"context": "", "chunks": [], "metadatas": []}