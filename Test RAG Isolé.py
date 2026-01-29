# Test RAG Isolé.py
import os
import sys
from dotenv import load_dotenv

print("--- 🛠️ TEST DIAGNOSTIC RAG ---")

# 1. Vérification du .env
load_dotenv()
if not os.getenv("CHROMA_API_KEY"):
    print("❌ ERREUR : Fichier .env mal lu ou clés manquantes.")
    sys.exit()

# 2. Import du moteur
try:
    from rag import rag_query
    print("✅ Module 'rag.py' chargé.")
except Exception as e:
    print(f"❌ ERREUR IMPORT : {e}")
    sys.exit()

# 3. Test d'une question
query = "Je me sens seul et triste"
print(f"🚀 Test en cours pour : '{query}'")

try:
    # On appelle la fonction avec 'k=2' (le moteur accepte 'k' maintenant)
    result = rag_query(query, k=2)
    context = result.get("context", "")

    if context:
        print("\n✅ SUCCÈS TOTAL ! Voici ce que le RAG a trouvé :")
        print("-" * 30)
        print(context)
        print("-" * 30)
    else:
        print("\n⚠️ ÉCHEC : Le code tourne mais la base est vide ou injoignable.")

except Exception as e:
    print(f"\n💥 CRASH : {e}")

print("\n--- FIN DU TEST ---")