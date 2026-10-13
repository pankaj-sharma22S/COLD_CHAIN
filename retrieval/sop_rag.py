import os
from pathlib import Path

from dotenv import load_dotenv

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_chroma import Chroma

from langchain_openai import OpenAIEmbeddings


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

load_dotenv()
VECTOR_DB_PATH = os.getenv("SOP_VECTOR_DB_PATH", "sop/chroma_db")


# ---------------------------------------------------------
# LOAD DOCUMENT
# ---------------------------------------------------------

def load_document(file_path: str):
    """
    Load PDF, TXT or DOCX SOP document.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"SOP file not found: {file_path}"
        )

    extension = path.suffix.lower()

    if extension == ".pdf":
        loader = PyPDFLoader(str(path))

    elif extension == ".txt":
        loader = TextLoader(
            str(path),
            encoding="utf-8"
        )

    elif extension == ".docx":
        loader = Docx2txtLoader(str(path))

    else:
        raise ValueError(
            "Supported files: PDF, TXT, DOCX"
        )

    return loader.load()


# ---------------------------------------------------------
# SPLIT DOCUMENT
# ---------------------------------------------------------

def split_document(documents):
    """
    Split SOP document into smaller chunks.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100
    )

    return splitter.split_documents(documents)


# ---------------------------------------------------------
# VECTOR STORE
# ---------------------------------------------------------

def get_vector_store():
    """
    Create or load Chroma vector database.
    """

    embeddings = OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    )

    vector_store = Chroma(
        collection_name="cold_chain_sops",
        embedding_function=embeddings,
        persist_directory=VECTOR_DB_PATH,
    )

    return vector_store


# ---------------------------------------------------------
# INDEX SOP
# ---------------------------------------------------------

def index_sop(file_path: str):
    """
    Load and store an SOP document in Chroma.
    """

    documents = load_document(file_path)

    chunks = split_document(documents)

    vector_store = get_vector_store()

    vector_store.add_documents(chunks)

    return {
        "status": "success",
        "file": file_path,
        "chunks_added": len(chunks)
    }


# ---------------------------------------------------------
# RETRIEVE SOP
# ---------------------------------------------------------

def get_sop(query: str, top_k: int = 3):
    """
    Search SOP knowledge.

    This is the function that LangGraph
    can call later.
    """

    if not query.strip():
        raise ValueError(
            "SOP query cannot be empty."
        )

    vector_store = get_vector_store()

    documents = vector_store.similarity_search(
        query,
        k=top_k
    )

    results = []

    for document in documents:

        results.append({
            "content": document.page_content,
            "source": document.metadata.get(
                "source"
            ),
            "page": document.metadata.get(
                "page"
            )
        })

    return results


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":

    # Example:
    # Put an SOP file here before running.
    file_path = "backend/sop/example_sop.pdf"

    result = index_sop(file_path)

    print(result)

    print("\nSearching SOP...\n")

    results = get_sop(
        "What should we do when the truck is near the warehouse?"
    )

    for result in results:
        print("--------------------------------")
        print(result["content"])
        print("Source:", result["source"])
        print("Page:", result["page"])
