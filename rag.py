import chromadb
import os

# -------------------------
# 🔑 CHROMA CLOUD CONFIG
# -------------------------
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")
CHROMA_TENANT = os.getenv("CHROMA_TENANT")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "sophia")


# -------------------------
# 🔌 CONNECT TO CHROMA
# -------------------------
def get_chroma_collection():
    client = chromadb.CloudClient(
        api_key=CHROMA_API_KEY,
        tenant=CHROMA_TENANT,
        database=CHROMA_DATABASE,
    )
    return client.get_collection(CHROMA_COLLECTION)


# -------------------------
# 🔍 RAG QUERY
# -------------------------
def rag_query(user_message: str, n_results: int = 5):
    """
    Interroge Chroma Cloud (déjà chunkée / déjà encodée)
    et renvoie un contexte propre pour le LLM.
    """

    collection = get_chroma_collection()

    results = collection.query(
        query_texts=[user_message],
        n_results=n_results,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    # Construction d’un contexte lisible
    context_blocks = []
    for doc, meta in zip(documents, metadatas):
        block = f"""
[THEME: {meta.get("theme")} | TYPE: {meta.get("type")} | NIVEAU: {meta.get("niveau_souffrance")} | REDFLAG: {meta.get("redflag")}]

QUESTION:
{meta.get("question")}

RÉPONSE:
{meta.get("reponse")}
"""
        context_blocks.append(block)

    context = "\n\n---\n\n".join(context_blocks)

    return {
        "context": context,
        "chunks": documents,
        "metadata": metadatas
    }
