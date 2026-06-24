import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "documents")
DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vector_store")

REQUIRED_POLICIES = [
    "attendance_policy.md",
    "grading_policy.md",
    "examination_rules.md",
    "fee_policy.md",
    "late_submission.md",
    "academic_integrity.md",
    "leave_policy.md",
]


def _get_embeddings():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


def main():
    missing = [name for name in REQUIRED_POLICIES if not os.path.exists(os.path.join(DATA_DIR, name))]
    if missing:
        raise FileNotFoundError(f"Missing required policy documents: {', '.join(missing)}")

    print("Loading documents...")
    loader = DirectoryLoader(
        DATA_DIR,
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    documents = loader.load()

    policy_docs = [d for d in documents if any(p in d.metadata.get("source", "") for p in REQUIRED_POLICIES)]
    print(f"Loaded {len(documents)} documents ({len(policy_docs)} required policy files).")

    print("Splitting text into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_documents(documents)

    print(f"Split into {len(chunks)} chunks.")

    print("Initializing Embeddings and ChromaDB...")
    embeddings = _get_embeddings()

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=DB_DIR,
    )

    print("Ingestion complete! Database saved to data/vector_store/")


if __name__ == "__main__":
    main()
