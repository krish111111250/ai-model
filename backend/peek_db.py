import os
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings

# 1. Point to your database folder
CHROMA_PATH = os.path.join("app", "chroma_db")

# 2. Load the embedding model
embeddings = OllamaEmbeddings(
    model="nomic-embed-text", 
    base_url="http://localhost:11434"
)

# 3. Connect to the database
vector_store = Chroma(
    collection_name="rag_collection",
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH
)

# 4. Fetch the data AND explicitly ask for the embeddings (vectors)
print("🔍 Searching database...\n")
db_data = vector_store.get(include=["documents", "metadatas", "embeddings"])

total_chunks = len(db_data['ids'])

if total_chunks > 0:
    print("--- HERE IS THE MATH BEHIND CHUNK 1 ---")
    
    # Get the text
    print(f"\n📝 THE TEXT:\n{db_data['documents'][0][:150]}...\n")
    
    # Get the vector array
    vector_array = db_data['embeddings'][0]
    total_numbers = len(vector_array)
    
    print(f"🧮 THE VECTOR (Total size: {total_numbers} numbers):")
    # Print just the first 10 numbers so we don't flood the screen
    print(vector_array[:10])
    print("... [and hundreds more numbers]")
else:
    print("Your database is empty!")