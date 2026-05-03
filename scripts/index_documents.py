from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from dotenv import load_dotenv
from openai import OpenAI
import hashlib
import json
import os
import re

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = BASE_DIR / "knowledge_documents"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = "".join(
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").split()
)

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_BASE_URL = os.getenv("AZURE_OPENAI_BASE_URL", "")
AZURE_OPENAI_EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "")


def supabase_request(method: str, path: str, payload=None):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase is not configured.")

    url = f"{SUPABASE_URL}/rest/v1/{path.lstrip('/')}"

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"

    request = Request(
        url=url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")

            if not response_body:
                return None

            return json.loads(response_body)

    except HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Supabase HTTP error {e.code}: {error_body}") from e

    except URLError as e:
        raise RuntimeError(f"Supabase URL error: {e}") from e


def create_embedding(client: OpenAI, text: str) -> list[float]:
    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def extract_title_and_tags(text: str, filename: str) -> tuple[str, list[str], str]:
    title = filename
    tags = []

    lines = text.splitlines()
    remaining_lines = []

    for line in lines:
        clean_line = line.strip()

        if clean_line.lower().startswith("naslov:"):
            title = clean_line.split(":", 1)[1].strip()
            continue

        if clean_line.lower().startswith("tagovi:"):
            raw_tags = clean_line.split(":", 1)[1].strip()
            tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
            continue

        remaining_lines.append(line)

    clean_text = "\n".join(remaining_lines).strip()

    return title, tags, clean_text


def split_text_into_chunks(
    text: str,
    max_words: int = 180,
    overlap_words: int = 40,
) -> list[str]:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]

    chunks = []
    current_words = []

    for paragraph in paragraphs:
        paragraph_words = paragraph.split()

        if len(current_words) + len(paragraph_words) <= max_words:
            current_words.extend(paragraph_words)
        else:
            if current_words:
                chunks.append(" ".join(current_words))

            overlap = current_words[-overlap_words:] if overlap_words > 0 else []
            current_words = overlap + paragraph_words

            while len(current_words) > max_words:
                chunks.append(" ".join(current_words[:max_words]))
                overlap = current_words[max_words - overlap_words : max_words]
                current_words = overlap + current_words[max_words:]

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def make_chunk_id(document_name: str, chunk_index: int, content: str) -> str:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

    safe_document_name = (
        document_name.replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "_")
    )

    return f"{safe_document_name}_{chunk_index}_{content_hash}"


def index_document(client: OpenAI, file_path: Path):
    raw_text = file_path.read_text(encoding="utf-8").strip()

    if not raw_text:
        print(f"Skipping empty file: {file_path.name}")
        return

    title, tags, body_text = extract_title_and_tags(raw_text, file_path.name)

    chunks = split_text_into_chunks(
        text=body_text,
        max_words=180,
        overlap_words=40,
    )

    print(f"\nDocument: {file_path.name}")
    print(f"Title: {title}")
    print(f"Tags: {tags}")
    print(f"Chunks: {len(chunks)}")

    for index, chunk in enumerate(chunks):
        embedding_input = f"""
Title: {title}
Document: {file_path.name}
Tags: {", ".join(tags)}

Content:
{chunk}
""".strip()

        print(f"Embedding chunk {index + 1}/{len(chunks)}")

        embedding = create_embedding(client, embedding_input)

        chunk_id = make_chunk_id(
            document_name=file_path.name,
            chunk_index=index,
            content=chunk,
        )

        payload = {
            "id": chunk_id,
            "document_name": file_path.name,
            "chunk_index": index,
            "title": title,
            "tags": tags,
            "content": chunk,
            "embedding": embedding,
        }

        supabase_request(
            method="POST",
            path="rag_chunks?on_conflict=id",
            payload=payload,
        )

        print(f"Saved chunk: {chunk_id}")


def main():
    if not DOCUMENTS_DIR.exists():
        raise RuntimeError(f"Missing folder: {DOCUMENTS_DIR}")

    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL missing.")

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY missing.")

    if not AZURE_OPENAI_API_KEY:
        raise RuntimeError("AZURE_OPENAI_API_KEY missing.")

    if not AZURE_OPENAI_BASE_URL:
        raise RuntimeError("AZURE_OPENAI_BASE_URL missing.")

    if not AZURE_OPENAI_EMBEDDING_MODEL:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_MODEL missing.")

    client = OpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        base_url=AZURE_OPENAI_BASE_URL,
    )

    files = sorted(DOCUMENTS_DIR.glob("*.txt"))

    if not files:
        print("No .txt files found in knowledge_documents.")
        return

    print(f"Found {len(files)} document files.")

    for file_path in files:
        index_document(client, file_path)

    print("\nIndexing finished.")


if __name__ == "__main__":
    main()