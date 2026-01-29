# rag.py (V82 : Aligné sur la structure sophia_structured.jsonL)
import os
import chromadb
import requests
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# CONFIGURATION
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "sophia-arbre")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "sophia")

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HF_MODEL_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"

_CLIENT = None
_COLLECTION = None

class HuggingFaceEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        if not HF_API_KEY:
            # Si pas de clé, on renvoie vide pour laisser Chroma gérer ou échouer proprement
            return []
        
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        try:
            # Option 'wait_for_model' pour éviter les erreurs 503 au démarrage
            resp = requests.post(
                HF_MODEL_URL, 
                headers=headers, 
                json={"inputs": input, "options": {"wait_for_model": True}}, 
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"⚠️ [RAG] Erreur Embeddings HF: {e}")
            return []

def get_collection():
    global _CLIENT, _COLLECTION
    if _COLLECTION:
        return _COLLECTION

    if not CHROMA_API_KEY or not CHROMA_TENANT:
        print("❌ [RAG] Erreur: Clés API manquantes.")
        return None

    try:
        print(f"🔌 [RAG] Connexion à la collection '{CHROMA_COLLECTION_NAME}'...")
        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        
        emb_fn = HuggingFaceEmbeddingFunction() if HF_API_KEY else None

        if emb_fn:
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=emb_fn)
        else:
            _COLLECTION = _CLIENT.get_collection(name=CHROMA_COLLECTION_NAME)
            
        print("✅ [RAG] Collection connectée.")
        return _COLLECTION
    except Exception as e:
        print(f"❌ [RAG] Erreur connexion: {e}")
        return None

def rag_query(user_message: str, n_results: int = 2):
    """
    Récupère les scénarios en utilisant les clés EXACTES de ton script d'ingestion.
    """
    collection = get_collection()
    if not collection:
        return {"context": "", "chunks": [], "metadatas": []}

    try:
        results = collection.query(
            query_texts=[user_message],
            n_results=n_results,
        )
        
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            return {"context": "", "chunks": [], "metadatas": []}

        context_blocks = []
        for idx, meta in enumerate(metadatas):
            meta = meta or {}
            
            # [CORRECTION] Extraction basée sur ton script d'ingestion
            # On utilise .get() avec les clés précises de ton JSONL
            question_source = meta.get("question") or "Situation inconnue"
            reponse_psy = meta.get("reponse") or "Conseil non disponible"
            theme = meta.get("theme") or "Général"
            souffrance = meta.get("niveau_souffrance") or "Inconnu"
            redflag = meta.get("redflag") # Peut être True/False ou "Oui"/"Non"

            # Construction du bloc lisible par app.py
            block = (
                f"--- SCÉNARIO SIMILAIRE (Thème: {theme} | Intensité: {souffrance}) ---\n"
                f"👤 Situation: \"{question_source}\"\n"
                f"💡 Réponse Psy: \"{reponse_psy}\"\n"
            )
            
            # Gestion explicite du Redflag pour alerter app.py
            is_redflag = str(redflag).lower() in ["oui", "true", "yes", "1"]
            if is_redflag:
                block += "⚠️ NOTE: Redflag DÉTECTÉ (Situation à risque)\n"
                
            context_blocks.append(block)

        full_context = "\n".join(context_blocks)
        return {"context": full_context, "chunks": documents, "metadatas": metadatas}
        
    except Exception as e:
        print(f"⚠️ [RAG] Erreur requête: {e}")
        return {"context": "", "chunks": [], "metadatas": []}