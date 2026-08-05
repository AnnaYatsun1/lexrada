"""RAG-сервис: загрузка legal documents в ChromaDB с метаданными."""
from pathlib import Path
from dataclasses import dataclass

import chromadb
import frontmatter
from langchain_text_splitters import RecursiveCharacterTextSplitter

from paths import RAG_DOCS_DIR, CHROMA_DB_PATH


COLLECTION_NAME = "legal_docs"


@dataclass
class Document:
    """Загруженный markdown-документ с метаданными."""
    content: str
    metadata: dict
    file_path: Path


@dataclass
class Chunk:
    """Часть документа готовая к индексации."""
    id: str
    content: str
    metadata: dict


# ─── Layer 1: Load ────────────────────────────────────────────

def load_documents(base_dir: Path = None) -> list[Document]:
    """
    Читает все markdown-файлы рекурсивно из RAG_DOCS_DIR.
    Парсит YAML front matter → метаданные.
    
    Не разбивает на chunks и не индексирует — только загрузка.
    """
    base_dir = base_dir or RAG_DOCS_DIR
    documents = []

    for file_path in sorted(base_dir.rglob("*.md")):
        try:
            post = frontmatter.load(file_path)
            metadata = _normalize_metadata(dict(post.metadata), file_path, base_dir)
            documents.append(Document(
                content=post.content,
                metadata=metadata,
                file_path=file_path,
            ))
        except Exception as e:
            print(f"⚠️  Пропускаю {file_path}: {e}")
            continue

    return documents


def _normalize_metadata(raw: dict, file_path: Path, base_dir: Path) -> dict:
    """
    Нормализует метаданные под требования ChromaDB (только str/int/float/bool).
    Добавляет defaults для обязательных полей.
    """
    metadata = dict(raw)

    # Обязательные поля с дефолтами
    metadata.setdefault("country", "UNKNOWN")
    metadata.setdefault("doc_type", "unknown")
    metadata.setdefault("document_type", "law")  # law | code | court_practice | template | regulation
    metadata.setdefault("source", "unknown")

    # article приводим к строке
    if "article" in metadata:
        metadata["article"] = str(metadata["article"])

    # relative path для debug
    metadata["file"] = str(file_path.relative_to(base_dir))

    return metadata


# ─── Layer 2: Chunk ───────────────────────────────────────────

def chunk_documents(
    documents: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> list[Chunk]:
    """
    Разбивает документы на chunks для векторной индексации.
    Метаданные родительского документа наследуются каждым chunk + добавляется chunk index.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    chunks = []
    for doc in documents:
        pieces = splitter.split_text(doc.content)
        for idx, piece in enumerate(pieces):
            chunks.append(Chunk(
                id=f"{doc.file_path.stem}_chunk_{idx}",
                content=piece,
                metadata={**doc.metadata, "chunk": idx},
            ))

    return chunks


# ─── Layer 3: Index ───────────────────────────────────────────

def index_documents(chunks: list[Chunk], collection) -> None:
    """
    Записывает chunks в ChromaDB collection.
    """
    if not chunks:
        print("⚠️  Нет chunks для индексации")
        return

    collection.add(
        ids=[c.id for c in chunks],
        documents=[c.content for c in chunks],
        metadatas=[c.metadata for c in chunks],
    )


# ─── Orchestrator ─────────────────────────────────────────────

def init_rag_db():
    """
    Инициализирует ChromaDB и загружает документы (если их ещё нет).
    Оркестрирует load → chunk → index.
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

    # Уже есть?
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
        doc_count = collection.count()
        if doc_count > 0:
            print(f"✅ ChromaDB уже инициализирован ({doc_count} чанков)")
            return client, collection
    except Exception:
        pass

    # Пересоздание
    try:
        client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    print("⏳ Индексирую документы в ChromaDB...")

    documents = load_documents()
    chunks = chunk_documents(documents)
    index_documents(chunks, collection)

    print(f"✅ Загружено {len(chunks)} чанков из {len(documents)} документов")
    return client, collection


# ─── Retrieval (пока здесь — потом переедет в Retriever) ─────

def retrieve_documents(
    query: str,
    top_k: int = 3,
    filter: dict | None = None,
) -> list[str]:
    """
    Ищет документы по запросу с опциональной фильтрацией по метаданным.
    
    Пример:
        retrieve_documents(
            "испытательный срок",
            filter={"country": "UA", "doc_type": "labor"}
        )
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    collection = client.get_collection(name=COLLECTION_NAME)

    kwargs = {"query_texts": [query], "n_results": top_k}
   
    where = build_where(filter)
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    return results["documents"][0] if results["documents"] else []

def build_where(filter: dict | None):
    if not filter:
        return None

    if len(filter) == 1:
        key, value = next(iter(filter.items()))
        return {key: value}

    return {
        "$and": [
            {k: v}
            for k, v in filter.items()
        ]
    }