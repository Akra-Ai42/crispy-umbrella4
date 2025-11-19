import os
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# CONFIGURATION CHROMA (Doit matcher ton script d'ingestion)
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "sophia-arbre") # Nom de ta database
CHROMA_COLLECTION_NAME = "sophia" # Nom de ta collection
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'

# Singleton pour éviter de recharger le modèle à chaque message
_CLIENT = None
_COLLECTION = None
_EMBEDDING_FUNC = None

class LocalEmbeddingFunction(chromadb.EmbeddingFunction):
    """Wrapper pour utiliser le modèle localement (gratuit et rapide)."""
    def __init__(self, model_name):
        self.model = SentenceTransformer(model_name)
    
    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.model.encode(input, convert_to_tensor=False).tolist()

def get_collection():
    """Initialise la connexion à Chroma Cloud une seule fois."""
    global _CLIENT, _COLLECTION, _EMBEDDING_FUNC
    
    if _COLLECTION:
        return _COLLECTION

    try:
        print("🔌 Connexion RAG ChromaDB en cours...")
        if _EMBEDDING_FUNC is None:
            _EMBEDDING_FUNC = LocalEmbeddingFunction(EMBEDDING_MODEL_NAME)

        _CLIENT = chromadb.CloudClient(
            api_key=CHROMA_API_KEY,
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )
        
        _COLLECTION = _CLIENT.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=_EMBEDDING_FUNC
        )
        print("✅ RAG Connecté avec succès.")
        return _COLLECTION
    except Exception as e:
        print(f"❌ Erreur critique connexion RAG: {e}")
        return None

def rag_query(user_message: str, n_results: int = 3):
    """
    Interroge la base et retourne un contexte formaté pour le Prompt.
    """
    collection = get_collection()
    if not collection:
        return {"context": "", "chunks": []}

    try:
        # Recherche vectorielle
        results = collection.query(
            query_texts=[user_message],
            n_results=n_results,
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        # Construction du contexte pour Sophia
        context_blocks = []
        
        for meta in metadatas:
            meta = meta or {}
            
            # Récupération des champs spécifiques de ta base
            question_ref = meta.get('question', 'N/A')
            reponse_ref = meta.get('reponse', 'N/A')
            theme = meta.get('theme', 'Général')
            redflag = meta.get('redflag', 'non')
            
            # On formate un bloc digeste pour le LLM
            block = (
                f"--- CAS SIMILAIRE (Thème: {theme} | Danger: {redflag}) ---\n"
                f"Si l'utilisateur dit : \"{question_ref}\"\n"
                f"Une réponse sage et bienveillante serait : \"{reponse_ref}\""
            )
            context_blocks.append(block)

        full_context = "\n\n".join(context_blocks)

        return {
            "context": full_context,
            "chunks": documents
        }

    except Exception as e:
        print(f"⚠️ Erreur requête RAG: {e}")
        return {"context": "", "chunks": []}