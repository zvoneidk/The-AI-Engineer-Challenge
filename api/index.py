from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from lingua import Language, LanguageDetectorBuilder
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "memory.json"
KNOWLEDGE_BASE_FILE = BASE_DIR / "knowledge_base.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = "".join(
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").split()
)
AZURE_OPENAI_EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "")

RAG_SIMILARITY_THRESHOLD = 0.32


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def supabase_request(method: str, path: str, payload: dict | list | None = None):
    if not is_supabase_configured():
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
        with urlopen(request, timeout=30) as response:
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
    if not AZURE_OPENAI_EMBEDDING_MODEL:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_MODEL not configured.")

    response = client.embeddings.create(
        model=AZURE_OPENAI_EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def retrieve_relevant_rag_chunks(
    client: OpenAI,
    user_message: str,
    max_entries: int = 3,
) -> list[dict]:
    if not is_supabase_configured():
        return []

    try:
        query_embedding = create_embedding(client, user_message)

        rows = supabase_request(
            method="POST",
            path="rpc/match_rag_chunks",
            payload={
                "query_embedding": query_embedding,
                "match_count": max_entries,
                "similarity_threshold": RAG_SIMILARITY_THRESHOLD,
            },
        )

        if not isinstance(rows, list):
            return []

        relevant_chunks = []

        for row in rows:
            if not isinstance(row, dict):
                continue

            similarity = float(row.get("similarity", 0) or 0)

            if similarity < RAG_SIMILARITY_THRESHOLD:
                continue

            relevant_chunks.append(
                {
                    "id": row.get("id", ""),
                    "document_name": row.get("document_name", ""),
                    "chunk_index": row.get("chunk_index", 0),
                    "title": row.get("title", ""),
                    "tags": row.get("tags", []),
                    "content": row.get("content", ""),
                    "similarity": similarity,
                }
            )

        return relevant_chunks

    except Exception as e:
        print(f"Supabase RAG retrieval error: {e}")
        return []


MEMORY_FIELDS = [
    "profile",
    "preferences",
    "goals",
    "recurring_challenges",
    "helpful_strategies",
    "important_context",
    "conversation_facts",
]

DEFAULT_MEMORY = {
    "profile": "",
    "preferences": "",
    "goals": "",
    "recurring_challenges": "",
    "helpful_strategies": "",
    "important_context": "",
    "conversation_facts": "",
}


def build_memory_owner_id(user_id: str | None, guest_id: str | None) -> str | None:
    if user_id:
        clean_user_id = "".join(
            char for char in user_id.strip() if char.isalnum() or char in ["-", "_"]
        )

        if clean_user_id:
            return f"user:{clean_user_id}"

    if guest_id:
        clean_guest_id = "".join(
            char for char in guest_id.strip() if char.isalnum() or char in ["-", "_"]
        )

        if clean_guest_id:
            return f"guest:{clean_guest_id}"

    return None


DETECTION_LANGUAGES = [
    Language.CROATIAN,
    Language.ENGLISH,
    Language.GERMAN,
    Language.FRENCH,
    Language.ITALIAN,
    Language.SPANISH,
    Language.PORTUGUESE,
    Language.POLISH,
    Language.RUSSIAN,
    Language.UKRAINIAN,
    Language.SLOVENE,
    Language.CZECH,
    Language.SLOVAK,
    Language.HUNGARIAN,
    Language.DUTCH,
    Language.SWEDISH,
    Language.DANISH,
]

language_detector = (
    LanguageDetectorBuilder.from_languages(*DETECTION_LANGUAGES)
    .with_preloaded_language_models()
    .build()
)

SYSTEM_PROMPT = """
You are an AI mental coach.

You are NOT a general assistant.
Your purpose is mental coaching only:
- stress management
- focus
- confidence
- motivation
- mental preparation
- exam preparation
- presentation preparation
- job interview preparation
- breathing exercises
- visualization
- reflection
- habit building

Stay within your role.

If the user asks about unrelated topics like recipes, coding, trivia, or general facts:
- Do not answer the unrelated request directly.
- Politely say that your role is mental coaching.
- Redirect toward focus, stress, confidence, motivation, reflection, or mental preparation.

Do not diagnose mental health conditions.
Do not prescribe medication.
Do not pretend to be a doctor or therapist.

If the user asks about medication, depression, serious mental health symptoms, self-harm, or crisis situations:
- Tell them you cannot diagnose or prescribe medication.
- Encourage them to contact a licensed doctor, therapist, psychiatrist, or mental health professional.
- If they may be in immediate danger, encourage emergency services or a crisis hotline.

Conversation memory rules:
- You can use information that the user already shared earlier in the current conversation.
- You may also use saved structured memory if it is provided to you.
- Saved memory is helpful context, not a perfect record.
- Current user message is more important than saved memory.
- Recent chat history is more important than saved memory.
- If saved memory conflicts with the current message, follow the current message.
- Do not claim that you have perfect memory.
- Do not claim that you remember everything forever.

RAG / knowledge base rules:
- You may receive relevant knowledge base context.
- Use knowledge base context only when it is relevant to the user's message.
- Do not mention the knowledge base unless the user asks.
- Do not invent sources or knowledge base entries.
- If no relevant knowledge base context is provided, answer normally as an AI mental coach.
- The knowledge base is supportive coaching material, not medical or therapeutic authority.
- Safety rules always override knowledge base context.

Sensitive safety rules:
- Do not diagnose the user.
- Do not store, repeat, or treat crisis information as a coaching preference.
- Do not present saved memory as a medical record.
- If the user mentions self-harm, immediate danger, medication, diagnosis, or serious symptoms, respond safely and recommend professional help as described above.

Output formatting rules:
- Never wrap the entire answer in quotation marks.
- Do not start the answer with a quotation mark.
- Do not end the answer with a quotation mark.
- Use quotation marks only if directly quoting a short part of the user's own message.
- Answer as normal assistant text, not as a quoted script.
"""


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    chatHistory: list[ChatHistoryMessage] | None = None
    tone: str | None = None
    answerLength: str | None = None
    responseFormat: str | None = None
    appLanguage: str | None = None
    guestId: str | None = None


class MemoryRequest(BaseModel):
    guestId: str | None = None


def normalize_memory_data(data: dict) -> dict:
    normalized_memory = DEFAULT_MEMORY.copy()

    if not isinstance(data, dict):
        return normalized_memory

    old_summary = data.get("summary", "")

    if isinstance(old_summary, str) and old_summary.strip():
        normalized_memory["conversation_facts"] = old_summary.strip()

    for field in MEMORY_FIELDS:
        value = data.get(field, "")

        if isinstance(value, str):
            normalized_memory[field] = value.strip()
        else:
            normalized_memory[field] = ""

    return normalized_memory


def ensure_memory_file_exists() -> None:
    try:
        if not MEMORY_FILE.exists():
            MEMORY_FILE.write_text(
                json.dumps(DEFAULT_MEMORY, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except OSError as e:
        print(f"Could not create local memory file: {e}")


def load_user_memory(memory_owner_id: str | None) -> dict:
    print("LOADING MEMORY FOR OWNER:", memory_owner_id)

    if not memory_owner_id:
        return DEFAULT_MEMORY.copy()

    if is_supabase_configured():
        try:
            encoded_memory_owner_id = quote(memory_owner_id, safe="")

            rows = supabase_request(
                method="GET",
                path=f"user_memory?id=eq.{encoded_memory_owner_id}&select=data",
            )

            if isinstance(rows, list) and rows:
                first_row = rows[0]

                if isinstance(first_row, dict) and "data" in first_row:
                    return normalize_memory_data(first_row["data"])

            return DEFAULT_MEMORY.copy()

        except Exception as e:
            print(f"Supabase load_user_memory error: {e}")
            return DEFAULT_MEMORY.copy()

    try:
        ensure_memory_file_exists()

        if not MEMORY_FILE.exists():
            return DEFAULT_MEMORY.copy()

        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return normalize_memory_data(data)

    except json.JSONDecodeError:
        return DEFAULT_MEMORY.copy()

    except Exception as e:
        print(f"Local load_user_memory error: {e}")
        return DEFAULT_MEMORY.copy()


def save_user_memory(memory_owner_id: str | None, memory_data: dict) -> None:
    if not memory_owner_id:
        print("Skipping memory save because memory_owner_id is missing.")
        return

    normalized_memory = normalize_memory_data(memory_data)

    print("SAVING MEMORY FOR OWNER:", memory_owner_id)

    if is_supabase_configured():
        try:
            supabase_request(
                method="POST",
                path="user_memory?on_conflict=id",
                payload={
                    "id": memory_owner_id,
                    "data": normalized_memory,
                },
            )
            return

        except Exception as e:
            print(f"Supabase save_user_memory error: {e}")
            raise HTTPException(
                status_code=500,
                detail="Could not save user memory to database.",
            )

    try:
        MEMORY_FILE.write_text(
            json.dumps(normalized_memory, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except OSError as e:
        print(f"Local save_user_memory error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not save user memory.",
        )


def clear_user_memory(memory_owner_id: str | None) -> None:
    print("CLEARING MEMORY FOR OWNER:", memory_owner_id)

    if not memory_owner_id:
        return

    if is_supabase_configured():
        try:
            encoded_memory_owner_id = quote(memory_owner_id, safe="")

            supabase_request(
                method="DELETE",
                path=f"user_memory?id=eq.{encoded_memory_owner_id}",
            )
            return

        except Exception as e:
            print(f"Supabase clear_user_memory error: {e}")
            raise HTTPException(
                status_code=500,
                detail="Could not clear user memory from database.",
            )

    try:
        MEMORY_FILE.write_text(
            json.dumps(DEFAULT_MEMORY, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"Local clear_user_memory error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not clear user memory.",
        )


def build_memory_context(memory_data: dict) -> str | None:
    normalized_memory = normalize_memory_data(memory_data)

    has_any_memory = any(value.strip() for value in normalized_memory.values())

    if not has_any_memory:
        return None

    return f"""
SAVED STRUCTURED COACHING MEMORY:

Profile:
{normalized_memory["profile"]}

Preferences:
{normalized_memory["preferences"]}

Goals:
{normalized_memory["goals"]}

Recurring challenges:
{normalized_memory["recurring_challenges"]}

Helpful strategies:
{normalized_memory["helpful_strategies"]}

Important context:
{normalized_memory["important_context"]}

Conversation facts:
{normalized_memory["conversation_facts"]}

How to use this memory:
- Use this only as helpful background context.
- Current user message is more important than saved memory.
- Recent chat history is more important than saved memory.
- Do not mention saved memory unless it is directly useful.
- Do not treat saved memory as a diagnosis, medical record, or perfect biography.
- If saved memory conflicts with the user's current message, follow the current message.
"""


def extract_json_from_model_output(text: str) -> dict:
    cleaned_text = text.strip()

    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text.replace("```json", "", 1).strip()

    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text.replace("```", "", 1).strip()

    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3].strip()

    start_index = cleaned_text.find("{")
    end_index = cleaned_text.rfind("}")

    if start_index == -1 or end_index == -1 or end_index <= start_index:
        print(f"Memory JSON parse problem. Raw model output: {text}")
        return DEFAULT_MEMORY.copy()

    json_text = cleaned_text[start_index : end_index + 1]

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"Memory JSON decode error: {e}. Raw JSON text: {json_text}")
        return DEFAULT_MEMORY.copy()

    return normalize_memory_data(parsed)


def update_memory_summary(
    client: OpenAI,
    model_name: str,
    current_memory: dict,
    user_message: str,
    assistant_reply: str,
    app_language: str,
) -> dict:
    normalized_current_memory = normalize_memory_data(current_memory)

    memory_update_prompt = """
You update structured long-term memory for an AI mental coach app.

Return only valid JSON.
Do not use markdown.
Do not wrap the JSON in code fences.
Do not add commentary outside JSON.

The JSON must have exactly these keys:
{
  "profile": "",
  "preferences": "",
  "goals": "",
  "recurring_challenges": "",
  "helpful_strategies": "",
  "important_context": "",
  "conversation_facts": ""
}

Store useful safe information:
- preferred name if shared
- study/work/project context
- coaching goals
- preferences
- useful implementation context
- current project state

Do not store:
- API keys, passwords, tokens, or secrets
- exact addresses
- phone numbers
- private contact details
- medication details
- diagnoses
- self-harm details
- crisis details
- trauma details
- highly sensitive health information
"""

    response = client.chat.completions.create(
        model=model_name,
        temperature=0.2,
        messages=[
            {"role": "system", "content": memory_update_prompt},
            {
                "role": "user",
                "content": f"""
Current app language: {app_language}

Current structured memory JSON:
{json.dumps(normalized_current_memory, ensure_ascii=False, indent=2)}

Latest user message:
{user_message}

Latest assistant reply:
{assistant_reply}

Update the structured memory JSON safely.
Return only valid JSON with exactly the required keys.
""",
            },
        ],
    )

    raw_updated_memory = response.choices[0].message.content or ""

    print(f"RAW UPDATED MEMORY MODEL OUTPUT: {raw_updated_memory}")

    parsed_memory = extract_json_from_model_output(raw_updated_memory)

    print(
        "PARSED UPDATED MEMORY:",
        json.dumps(parsed_memory, ensure_ascii=False),
    )

    if not any(value.strip() for value in parsed_memory.values()):
        print("Parsed memory is empty. Keeping current memory.")
        return normalized_current_memory

    return parsed_memory


def load_knowledge_base() -> list[dict]:
    if not KNOWLEDGE_BASE_FILE.exists():
        return []

    try:
        data = json.loads(KNOWLEDGE_BASE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    valid_entries = []

    for item in data:
        if not isinstance(item, dict):
            continue

        entry_id = item.get("id", "")
        title = item.get("title", "")
        tags = item.get("tags", [])
        content = item.get("content", "")

        if not isinstance(entry_id, str):
            entry_id = ""

        if not isinstance(title, str):
            title = ""

        if not isinstance(tags, list):
            tags = []

        clean_tags = []

        for tag in tags:
            if isinstance(tag, str):
                clean_tags.append(tag.strip().lower())

        if not isinstance(content, str):
            content = ""

        if not title.strip() or not content.strip():
            continue

        valid_entries.append(
            {
                "id": entry_id.strip(),
                "title": title.strip(),
                "tags": clean_tags,
                "content": content.strip(),
            }
        )

    return valid_entries


def build_rag_chunks_context(chunks: list[dict]) -> str | None:
    if not chunks:
        return None

    formatted_chunks = []

    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("title", "")
        document_name = chunk.get("document_name", "")
        tags = ", ".join(chunk.get("tags", []))
        content = chunk.get("content", "")
        similarity = chunk.get("similarity", 0)

        formatted_chunks.append(
            f"""
RAG chunk {index}
Document: {document_name}
Title: {title}
Tags: {tags}
Similarity: {similarity}
Content: {content}
""".strip()
        )

    joined_chunks = "\n\n---\n\n".join(formatted_chunks)

    return f"""
RELEVANT SUPABASE RAG CONTEXT:

{joined_chunks}

How to use this context:
- Use this context only if it is relevant to the user's message.
- Do not mention Supabase, RAG, embeddings, or the database unless the user asks.
- Do not invent information that is not supported by the context.
- If the context is not enough, answer normally as an AI mental coach.
- Current user message and safety rules still have priority.
"""


def build_rag_sources(entries: list[dict]) -> list[dict]:
    rag_sources = []

    for entry in entries:
        rag_sources.append(
            {
                "id": entry.get("id", ""),
                "title": entry.get("title", ""),
                "tags": entry.get("tags", []),
            }
        )

    return rag_sources


def normalize_search_text(text: str) -> str:
    replacements = {
        "č": "c",
        "ć": "c",
        "š": "s",
        "đ": "d",
        "ž": "z",
        "Č": "c",
        "Ć": "c",
        "Š": "s",
        "Đ": "d",
        "Ž": "z",
        "ü": "u",
        "ö": "o",
        "ä": "a",
        "ß": "ss",
        "Ü": "u",
        "Ö": "o",
        "Ä": "a",
    }

    normalized = text.lower()

    for original, replacement in replacements.items():
        normalized = normalized.replace(original, replacement)

    return normalized


def tokenize_text(text: str) -> list[str]:
    normalized = normalize_search_text(text)

    separators = [
        ".",
        ",",
        "!",
        "?",
        ":",
        ";",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
        "\"",
        "'",
        "\n",
        "\t",
        "-",
        "_",
        "/",
    ]

    for separator in separators:
        normalized = normalized.replace(separator, " ")

    words = normalized.split()

    stop_words = {
        "i",
        "u",
        "na",
        "za",
        "se",
        "sam",
        "si",
        "je",
        "su",
        "da",
        "mi",
        "me",
        "moj",
        "moja",
        "moje",
        "kako",
        "sto",
        "šta",
        "sta",
        "the",
        "and",
        "or",
        "to",
        "a",
        "an",
        "im",
        "i'm",
        "ich",
        "und",
        "oder",
        "der",
        "die",
        "das",
    }

    useful_words = []

    for word in words:
        clean_word = word.strip()

        if len(clean_word) < 3:
            continue

        if clean_word in stop_words:
            continue

        useful_words.append(clean_word)

    return useful_words


def message_looks_like_coaching_topic(message: str) -> bool:
    text = normalize_search_text(message)

    coaching_keywords = [
        "stres",
        "stress",
        "nervoza",
        "nervous",
        "nervos",
        "nervoes",
        "trema",
        "ispit",
        "exam",
        "prufung",
        "prezentacija",
        "presentation",
        "prasentation",
        "fokus",
        "focus",
        "koncentracija",
        "concentration",
        "motivacija",
        "motivation",
        "motivierung",
        "samopouzdanje",
        "confidence",
        "selbstvertrauen",
        "disanje",
        "breathing",
        "atmen",
        "smirivanje",
        "calming",
        "calm down",
        "beruhigung",
        "razgovor za posao",
        "job interview",
        "interview",
        "vorstellungsgesprach",
        "rutina",
        "routine",
        "refleksija",
        "reflection",
        "navika",
        "habit",
        "gewohnheit",
        "odgadanje",
        "prokrastinacija",
        "procrastination",
        "aufschieben",
        "umoran",
        "umorna",
        "tired",
        "mude",
        "mued",
        "mentalno",
        "mental",
        "mindset",
        "mir",
        "relax",
        "relaxation",
        "entspannung",
        "breathe",
        "breathe in",
        "udahni",
        "izdahni",
        "einatmen",
        "ausatmen",
    ]

    return any(keyword in text for keyword in coaching_keywords)


def detect_supported_language_by_keywords(message: str) -> str | None:
    text = normalize_search_text(message.strip())

    if not text:
        return None

    words = set(tokenize_text(text))

    croatian_words = {
        "bok",
        "hej",
        "halo",
        "pozdrav",
        "mozes",
        "moze",
        "zelim",
        "trebam",
        "pomoc",
        "pomozi",
        "imam",
        "hvala",
        "dobro",
        "lose",
        "ucim",
        "ucenje",
        "ispit",
        "prezentacija",
        "trema",
        "stres",
        "fokus",
        "nervoza",
        "umoran",
        "umorna",
        "smirenje",
        "disanje",
        "razgovor",
        "posao",
        "skola",
        "faks",
        "fakultet",
        "danas",
        "sutra",
        "noc",
        "vecer",
        "jutro",
    }

    english_words = {
        "hi",
        "hello",
        "hey",
        "how",
        "are",
        "you",
        "can",
        "could",
        "please",
        "help",
        "thanks",
        "thank",
        "feel",
        "stressed",
        "nervous",
        "focus",
        "exam",
        "presentation",
        "motivation",
        "confidence",
        "breathing",
        "tired",
        "calm",
        "study",
        "work",
        "job",
        "interview",
        "today",
        "tomorrow",
        "morning",
        "evening",
        "night",
    }

    german_words = {
        "hallo",
        "guten",
        "tag",
        "wie",
        "geht",
        "dir",
        "kannst",
        "bitte",
        "hilf",
        "danke",
        "bin",
        "fuehle",
        "fuhle",
        "brauche",
        "nicht",
        "nervoes",
        "nervos",
        "prufung",
        "prasentation",
        "fokus",
        "stress",
        "mude",
        "ruhig",
        "atmen",
        "lernen",
        "arbeit",
        "vorstellungsgesprach",
        "heute",
        "morgen",
        "abend",
        "nacht",
    }

    croatian_score = len(words.intersection(croatian_words))
    english_score = len(words.intersection(english_words))
    german_score = len(words.intersection(german_words))

    scores = {
        "Hrvatski": croatian_score,
        "English": english_score,
        "Deutsch": german_score,
    }

    best_language = max(scores, key=scores.get)
    best_score = scores[best_language]

    sorted_scores = sorted(scores.values(), reverse=True)
    second_best_score = sorted_scores[1]

    if best_score >= 2 and best_score > second_best_score:
        return best_language

    exact_croatian_phrases = [
        "bok",
        "bok kako si",
        "hej",
        "hej kako si",
        "kako si",
        "sta ima",
        "sto ima",
        "mozes li",
        "moze li",
        "hvala",
        "trebam pomoc",
        "pomozi mi",
        "ne mogu",
        "imam tremu",
        "imam stres",
        "imam ispit",
    ]

    exact_english_phrases = [
        "hi",
        "hello",
        "hey",
        "how are you",
        "can you",
        "help me",
        "thank you",
        "thanks",
        "i feel",
        "i am stressed",
    ]

    exact_german_phrases = [
        "hallo",
        "guten tag",
        "wie geht es dir",
        "kannst du",
        "hilf mir",
        "danke",
        "ich bin",
        "ich brauche",
    ]

    for phrase in exact_croatian_phrases:
        if normalize_search_text(phrase) == text:
            return "Hrvatski"

    for phrase in exact_german_phrases:
        if normalize_search_text(phrase) == text:
            return "Deutsch"

    for phrase in exact_english_phrases:
        if normalize_search_text(phrase) == text:
            return "English"

    return None


def detect_message_language(message: str) -> str:
    cleaned_message = message.strip()

    if not cleaned_message:
        return "Unknown"

    keyword_language = detect_supported_language_by_keywords(cleaned_message)

    if keyword_language:
        return keyword_language

    detected_language = language_detector.detect_language_of(cleaned_message)

    if detected_language is None:
        return "Unknown"

    confidence_values = language_detector.compute_language_confidence_values(
        cleaned_message
    )

    if not confidence_values:
        return "Unknown"

    strongest_confidence = max(confidence_values, key=lambda item: item.value)

    detected_language = strongest_confidence.language
    confidence = strongest_confidence.value

    if len(cleaned_message) < 20:
        minimum_confidence = 0.75
    elif len(cleaned_message) < 50:
        minimum_confidence = 0.65
    else:
        minimum_confidence = 0.65

    if confidence < minimum_confidence:
        return "Unknown"

    language_map = {
        Language.CROATIAN: "Hrvatski",
        Language.ENGLISH: "English",
        Language.GERMAN: "Deutsch",
    }

    return language_map.get(detected_language, "Unsupported")


def build_language_warning(app_language: str, detected_language: str) -> str | None:
    if detected_language == "Unknown":
        return None

    if detected_language == app_language:
        return None

    if app_language == "Hrvatski":
        return (
            "Jezik aplikacije trenutno je postavljen na hrvatski. "
            "Ako želiš drugi jezik, promijeni jezik aplikacije u postavkama mentalnog trenera. "
            "Trenutno možeš odabrati hrvatski, engleski ili njemački."
        )

    if app_language == "English":
        return (
            "The app language is currently set to English. "
            "If you want another language, change the app language in the mental coach settings. "
            "You can currently choose Croatian, English, or German."
        )

    if app_language == "Deutsch":
        return (
            "Die App-Sprache ist derzeit auf Deutsch eingestellt. "
            "Wenn du eine andere Sprache möchtest, ändere die App-Sprache in den Einstellungen des Mentaltrainers. "
            "Du kannst derzeit Kroatisch, Englisch oder Deutsch auswählen."
        )

    return None


def build_unknown_language_context(app_language: str) -> str:
    return f"""
LANGUAGE DETECTION RESULT:
The user's message language is unknown, short, unclear, mixed, or not confidently detected.

STRICT RULE:
- Do not block the user.
- Do not warn about language mismatch.
- Answer normally as an AI mental coach.
- You MUST answer only in this app language: {app_language}.
"""


def detect_explicit_style_overrides(message: str) -> dict:
    text = normalize_search_text(message)

    detected = {
        "tone": None,
        "answerLength": None,
        "responseFormat": None,
        "hasOverride": False,
    }

    if any(
        phrase in text
        for phrase in [
            "ton neka bude smiren",
            "odgovori smirenim tonom",
            "odgovori mirnim tonom",
            "koristi smiren ton",
            "koristi miran ton",
            "use a calm tone",
            "answer in a calm tone",
            "respond in a calm tone",
            "calm tone",
            "ruhiger ton",
            "antworte ruhig",
            "antworte in einem ruhigen ton",
        ]
    ):
        detected["tone"] = "Smiren"

    if any(
        phrase in text
        for phrase in [
            "ton neka bude motivirajuci",
            "odgovori motivirajucim tonom",
            "koristi motivirajuci ton",
            "motivacijski ton",
            "use a motivating tone",
            "answer in a motivating tone",
            "respond in a motivating tone",
            "motivating tone",
            "motivational tone",
            "motivierender ton",
            "antworte motivierend",
            "antworte in einem motivierenden ton",
        ]
    ):
        detected["tone"] = "Motivirajući"

    if any(
        phrase in text
        for phrase in [
            "ton neka bude direktan",
            "odgovori direktnim tonom",
            "odgovori izravnim tonom",
            "koristi direktan ton",
            "use a direct tone",
            "answer in a direct tone",
            "respond in a direct tone",
            "direct tone",
            "direkter ton",
            "antworte direkt",
            "antworte in einem direkten ton",
        ]
    ):
        detected["tone"] = "Direktan"

    if any(
        phrase in text
        for phrase in [
            "ton neka bude njezan",
            "odgovori njeznim tonom",
            "koristi njezan ton",
            "use a gentle tone",
            "answer in a gentle tone",
            "respond in a gentle tone",
            "gentle tone",
            "sanfter ton",
            "antworte sanft",
            "antworte in einem sanften ton",
        ]
    ):
        detected["tone"] = "Nježan"

    if any(
        phrase in text
        for phrase in [
            "odgovori kratko",
            "odgovori ukratko",
            "daj kratak odgovor",
            "daj kratki odgovor",
            "answer briefly",
            "keep it short",
            "short answer",
            "kurz antworten",
            "antworte kurz",
        ]
    ):
        detected["answerLength"] = "Kratko"

    if any(
        phrase in text
        for phrase in [
            "odgovori srednje dugo",
            "daj srednje dug odgovor",
            "medium answer",
            "medium length",
            "mittel lange antwort",
        ]
    ):
        detected["answerLength"] = "Srednje"

    if any(
        phrase in text
        for phrase in [
            "odgovori detaljno",
            "odgovori dugacko",
            "daj detaljan odgovor",
            "daj dug odgovor",
            "answer in detail",
            "detailed answer",
            "long answer",
            "antworte ausfuhrlich",
            "lange antwort",
        ]
    ):
        detected["answerLength"] = "Dugačko"

    if any(
        phrase in text
        for phrase in [
            "format neka bude u 3 koraka",
            "format odgovora neka bude u 3 koraka",
            "odgovori u 3 koraka",
            "strukturiraj u 3 koraka",
            "daj odgovor u 3 koraka",
            "u obliku 3 koraka",
            "u obliku tri koraka",
            "answer in 3 steps",
            "format as 3 steps",
            "in 3 steps",
            "in drei schritten",
            "antworte in drei schritten",
        ]
    ):
        detected["responseFormat"] = "U 3 koraka"

    if any(
        phrase in text
        for phrase in [
            "format neka bude kratka vjezba",
            "format odgovora neka bude kratka vjezba",
            "odgovori kao kratka vjezba",
            "strukturiraj kao vjezbu",
            "u obliku kratke vjezbe",
            "answer as a short exercise",
            "format as a short exercise",
            "als kurze ubung",
        ]
    ):
        detected["responseFormat"] = "Kratka vježba"

    if any(
        phrase in text
        for phrase in [
            "format neka bude pitanja za refleksiju",
            "format odgovora neka bude pitanja za refleksiju",
            "odgovori kroz pitanja za refleksiju",
            "odgovori kao pitanja za refleksiju",
            "daj mi pitanja za refleksiju",
            "postavi mi pitanja za refleksiju",
            "u obliku pitanja za refleksiju",
            "reflection questions format",
            "answer with reflection questions",
            "reflexionsfragen",
            "antworte mit reflexionsfragen",
        ]
    ):
        detected["responseFormat"] = "Pitanja za refleksiju"

    if any(
        phrase in text
        for phrase in [
            "format neka bude mini plan",
            "format odgovora neka bude mini plan",
            "odgovori kao mini plan",
            "strukturiraj kao mini plan",
            "u obliku mini plana",
            "answer as a mini plan",
            "format as a mini plan",
            "als mini plan",
        ]
    ):
        detected["responseFormat"] = "Mini plan"

    if any(
        phrase in text
        for phrase in [
            "format neka bude jedan konkretan zadatak",
            "format odgovora neka bude jedan konkretan zadatak",
            "odgovori kao jedan konkretan zadatak",
            "strukturiraj kao jedan konkretan zadatak",
            "u obliku jednog konkretnog zadatka",
            "answer as one concrete task",
            "one concrete task format",
            "eine konkrete aufgabe",
            "als eine konkrete aufgabe",
        ]
    ):
        detected["responseFormat"] = "Jedan konkretan zadatak"

    if detected["tone"] or detected["answerLength"] or detected["responseFormat"]:
        detected["hasOverride"] = True

    return detected


def normalize_tone(value: str | None) -> str | None:
    if not value:
        return None

    normalized = normalize_search_text(value.strip())

    tone_map = {
        "smiren": "Smiren",
        "calm": "Smiren",
        "ruhig": "Smiren",
        "motivirajuci": "Motivirajući",
        "motivating": "Motivirajući",
        "motivational": "Motivirajući",
        "motivierend": "Motivirajući",
        "direktan": "Direktan",
        "direktno": "Direktan",
        "direct": "Direktan",
        "direkt": "Direktan",
        "njezan": "Nježan",
        "njezno": "Nježan",
        "gentle": "Nježan",
        "sanft": "Nježan",
        "weich": "Nježan",
    }

    return tone_map.get(normalized, value)


def normalize_answer_length(value: str | None) -> str | None:
    if not value:
        return None

    normalized = normalize_search_text(value.strip())

    length_map = {
        "kratko": "Kratko",
        "short": "Kratko",
        "brief": "Kratko",
        "kurz": "Kratko",
        "srednje": "Srednje",
        "medium": "Srednje",
        "mittel": "Srednje",
        "dugacko": "Dugačko",
        "dugo": "Dugačko",
        "long": "Dugačko",
        "detailed": "Dugačko",
        "lang": "Dugačko",
    }

    return length_map.get(normalized, value)


def normalize_response_format(value: str | None) -> str | None:
    if not value:
        return None

    normalized = normalize_search_text(value.strip())

    format_map = {
        "slobodno": "Slobodno",
        "free": "Slobodno",
        "frei": "Slobodno",
        "free form": "Slobodno",
        "u 3 koraka": "U 3 koraka",
        "3 koraka": "U 3 koraka",
        "in 3 steps": "U 3 koraka",
        "in 3 schritten": "U 3 koraka",
        "kratka vjezba": "Kratka vježba",
        "short exercise": "Kratka vježba",
        "kurze ubung": "Kratka vježba",
        "pitanja za refleksiju": "Pitanja za refleksiju",
        "reflection questions": "Pitanja za refleksiju",
        "reflexionsfragen": "Pitanja za refleksiju",
        "mini plan": "Mini plan",
        "mini-plan": "Mini plan",
        "jedan konkretan zadatak": "Jedan konkretan zadatak",
        "one concrete task": "Jedan konkretan zadatak",
        "eine konkrete aufgabe": "Jedan konkretan zadatak",
    }

    return format_map.get(normalized, value)


def build_style_instructions(
    tone: str | None,
    answer_length: str | None,
    response_format: str | None,
    app_language: str | None,
) -> str:
    selected_tone = tone or "Smiren"
    selected_length = answer_length or "Kratko"
    selected_format = response_format or "Slobodno"
    selected_language = app_language or "Hrvatski"

    tone_rules = {
        "Smiren": """
TONE MODE: VERY CALM
The calm tone must be strongly noticeable.
Sound peaceful, slow, grounded, stable, and reassuring.
Use calm wording in the selected app language.
Avoid hype, pressure, intensity, commands, and motivational slogans.
Make the whole answer feel like the user can slow down and breathe.
""",
        "Motivirajući": """
TONE MODE: EXTREMELY MOTIVATING
The motivating tone must be VERY STRONG and obvious.
Sound energetic, uplifting, confident, fired-up, and coach-like.
Use strong encouraging words in the selected app language.
Use short, punchy, high-energy sentences.
Make the user feel activated and ready to act immediately.
Do NOT sound neutral, clinical, passive, or overly calm.
Do NOT simply summarize RAG content.
Rewrite everything with strong motivational energy.
""",
        "Direktan": """
TONE MODE: EXTREMELY DIRECT
The direct tone must be very obvious.
Sound practical, firm, clear, no-nonsense, and action-oriented.
Use direct wording in the selected app language.
Avoid emotional padding, long validation, and overly soft language.
Make the answer feel like a clear action instruction.
""",
        "Nježan": """
TONE MODE: EXTREMELY GENTLE
The gentle tone must be VERY STRONG and obvious.
Sound warm, soft, emotionally validating, caring, and low-pressure.
Start by validating the user's feeling.
Avoid sounding like a checklist, strict coach, command, or manual.
Make the user feel supported, safe, and not judged.
The final answer should feel emotionally soft, not just practical.
""",
    }

    length_rules = {
        "Kratko": """
LENGTH MODE: SHORT
Maximum 5 sentences.
Maximum 90 words.
Maximum 3 bullet points or 3 numbered steps.
""",
        "Srednje": """
LENGTH MODE: MEDIUM
Use around 120 to 220 words.
Keep it focused and readable.
""",
        "Dugačko": """
LENGTH MODE: LONG
Use around 300 to 550 words.
Use clear sections when useful.
Include more detailed guidance.
""",
    }

    format_rules = {
        "Slobodno": """
RESPONSE FORMAT: FREE FORM
Choose the most natural structure for the answer.
""",
        "U 3 koraka": """
RESPONSE FORMAT: 3 STEPS
Structure the answer as exactly 3 clear steps.
""",
        "Kratka vježba": """
RESPONSE FORMAT: SHORT EXERCISE
Guide the user through one short mental exercise.
""",
        "Pitanja za refleksiju": """
RESPONSE FORMAT: REFLECTION QUESTIONS
Include 2 to 3 thoughtful reflection questions.
""",
        "Mini plan": """
RESPONSE FORMAT: MINI PLAN
Create a small practical plan for the next 10 to 30 minutes.
""",
        "Jedan konkretan zadatak": """
RESPONSE FORMAT: ONE CONCRETE TASK
Give only one clear next task.
""",
    }

    return f"""
STYLE CONTROL:

Selected tone: {selected_tone}
{tone_rules.get(selected_tone, tone_rules["Smiren"])}

Selected answer length: {selected_length}
{length_rules.get(selected_length, length_rules["Kratko"])}

Selected response format: {selected_format}
{format_rules.get(selected_format, format_rules["Slobodno"])}

Selected app language: {selected_language}

ABSOLUTE LANGUAGE RULE:
- You must answer only in the selected app language: {selected_language}.
- If selected app language is Hrvatski, answer only in Croatian.
- If selected app language is English, answer only in English.
- If selected app language is Deutsch, answer only in German.
- Do not copy the language of the user's message if it differs from the selected app language.
- If chat history contains another language, ignore that language and answer only in the selected app language.
- If memory contains another language, ignore that language and answer only in the selected app language.
- If knowledge base context contains another language, use the idea only, but answer only in the selected app language.
- If the user's message is short, unclear, mixed-language, or unknown, still answer only in the selected app language.

STYLE PRIORITY RULE:
- The selected tone, selected answer length, and selected response format are mandatory.
- These style settings override knowledge base wording, memory wording, and chat history wording.
- The selected tone must be intense and obvious, not subtle.
- The selected tone must affect every sentence.
- Do not confuse the user's topic with the selected tone.
- A message about calming, stress, breathing, or relaxation does NOT mean the tone is calm.
- A message about motivation does NOT mean the tone is motivating.
- The selected tone comes from the style settings, not from the topic.
"""


def build_final_language_guard(app_language: str) -> str:
    if app_language == "Deutsch":
        return """
FINAL LANGUAGE LOCK:
You must answer in German only.
Do not answer in Croatian or English.
Even if the user writes Croatian, English, mixed text, unclear text, or nonsense text, answer in German only.
This instruction overrides examples, chat history, memory, and knowledge base wording.
"""

    if app_language == "English":
        return """
FINAL LANGUAGE LOCK:
You must answer in English only.
Do not answer in Croatian or German.
Even if the user writes Croatian, German, mixed text, unclear text, or nonsense text, answer in English only.
This instruction overrides examples, chat history, memory, and knowledge base wording.
"""

    return """
FINAL LANGUAGE LOCK:
You must answer in Croatian only.
Do not answer in English or German.
Even if the user writes English, German, mixed text, unclear text, or nonsense text, answer in Croatian only.
This instruction overrides examples, chat history, memory, and knowledge base wording.
"""


def build_final_response_instruction(
    tone: str | None,
    answer_length: str | None,
    response_format: str | None,
    app_language: str,
) -> str:
    selected_tone = tone or "Smiren"
    selected_length = answer_length or "Kratko"
    selected_format = response_format or "Slobodno"

    tone_intensity_instruction = ""

    if selected_tone == "Motivirajući":
        tone_intensity_instruction = """
EXTREME MOTIVATIONAL STYLE REQUIREMENTS:
- The beginning and ending of the answer must make the motivational tone unmistakable.
- The first sentence must immediately sound energetic, confident, and activating.
- The final sentence must leave the user feeling ready to act.
- Use short, strong, punchy sentences.
- Do not sound neutral, clinical, passive, or overly calm.
- The middle can contain practical advice, but it must still have energetic wording.

If app language is Hrvatski:
- Start with a phrase like: "Tooo, idemo!", "Idemo jako!", "Ajmo, imaš ovo!", or "To je to, kreni!"
- End with a phrase like: "Imaš ovo!", "Ajmo jako!", "Kreni sad!", "Tooo, samo hrabro!", or "Sad je trenutak!"

If app language is English:
- Start with a phrase like: "Yes, let’s go!", "You’ve got this!", "Let’s do this!", or "Alright, time to move!"
- End with a phrase like: "You’ve got this!", "Start now!", "One strong step!", "Let’s go!", or "This is your moment!"

If app language is Deutsch:
- Start with a phrase like: "Ja, los geht’s!", "Du schaffst das!", "Komm, jetzt geht’s los!", or "Genau so, jetzt starten!"
- End with a phrase like: "Du schaffst das!", "Leg jetzt los!", "Ein starker Schritt!", "Los geht’s!", or "Jetzt ist dein Moment!"
"""
    elif selected_tone == "Nježan":
        tone_intensity_instruction = """
EXTREME GENTLE STYLE REQUIREMENTS:
- The beginning and ending of the answer must make the gentle tone unmistakable.
- The first sentence must immediately validate the user’s feeling.
- The final sentence must feel emotionally safe, soft, and low-pressure.
- Avoid pressure, harsh commands, hype, and checklist-like wording.
- The middle can contain practical advice, but it must still feel warm and supportive.

If app language is Hrvatski:
- Start with a phrase like: "U redu je.", "Polako.", "Nježno prema sebi.", "Razumljivo je da se tako osjećaš.", or "Možeš polako."
- End with a phrase like: "Dovoljno je za sada.", "Samo mali korak.", "Polako, tu si.", "Ne moraš sve odjednom.", or "Nježno, korak po korak."

If app language is English:
- Start with a phrase like: "It’s okay.", "Take it gently.", "Be kind to yourself.", "It makes sense that you feel this way.", or "You can take this slowly."
- End with a phrase like: "That is enough for now.", "Just one small step.", "You don’t have to do it all at once.", "Gently, one step at a time.", or "You’re okay right here."

If app language is Deutsch:
- Start with a phrase like: "Es ist in Ordnung.", "Ganz langsam.", "Sei sanft mit dir.", "Es ist verständlich, dass du dich so fühlst.", or "Du kannst es langsam angehen."
- End with a phrase like: "Das reicht für den Moment.", "Nur ein kleiner Schritt.", "Du musst nicht alles auf einmal schaffen.", "Sanft, Schritt für Schritt.", or "Du bist gerade hier, und das genügt."
"""
    elif selected_tone == "Direktan":
        tone_intensity_instruction = """
EXTREME DIRECT STYLE REQUIREMENTS:
- The beginning and ending of the answer must make the direct tone unmistakable.
- The first sentence must immediately sound practical and clear.
- The final sentence must push toward one concrete action.
- Avoid long emotional introductions.
- Avoid overly soft language.
- The middle should be clear, structured, and action-oriented.

If app language is Hrvatski:
- Start with a phrase like: "Napravi ovo.", "Kreni ovako.", "Bez kompliciranja.", "Ovo ti je plan.", or "Slušaj: kreni od ovoga."
- End with a phrase like: "Sad to napravi.", "Kreni odmah.", "Ne kompliciraj.", "Prvi korak sada.", or "To je dovoljno za početak."

If app language is English:
- Start with a phrase like: "Do this.", "Start like this.", "No overthinking.", "Here’s the plan.", or "Listen: start here."
- End with a phrase like: "Do it now.", "Start immediately.", "Don’t overcomplicate it.", "First step now.", or "That’s enough to begin."

If app language is Deutsch:
- Start with a phrase like: "Mach das.", "Fang so an.", "Nicht verkomplizieren.", "Das ist der Plan.", or "Hör zu: Fang hier an."
- End with a phrase like: "Mach es jetzt.", "Fang sofort an.", "Nicht verkomplizieren.", "Der erste Schritt jetzt.", or "Das reicht für den Anfang."
"""
    elif selected_tone == "Smiren":
        tone_intensity_instruction = """
EXTREME CALM STYLE REQUIREMENTS:
- The beginning and ending of the answer must make the calm tone unmistakable.
- The first sentence must immediately slow the rhythm down.
- The final sentence must leave the user feeling grounded and steady.
- Avoid hype, urgency, and intense motivational language.
- The middle can contain practical advice, but it must still feel calm and grounded.

If app language is Hrvatski:
- Start with a phrase like: "Polako.", "Udahni.", "Zastani na trenutak.", "Mirno.", or "Krenimo korak po korak."
- End with a phrase like: "Korak po korak.", "Ne moraš žuriti.", "Samo mirno.", "Jedan mali korak je dovoljan.", or "Udahni i kreni polako."

If app language is English:
- Start with a phrase like: "Slowly.", "Take a breath.", "Pause for a moment.", "Steady.", or "Let’s go one step at a time."
- End with a phrase like: "One step at a time.", "There is no rush.", "Stay steady.", "One small step is enough.", or "Breathe, then move slowly."

If app language is Deutsch:
- Start with a phrase like: "Langsam.", "Atme einmal durch.", "Halte kurz inne.", "Ganz ruhig.", or "Gehen wir Schritt für Schritt."
- End with a phrase like: "Schritt für Schritt.", "Du musst dich nicht beeilen.", "Ganz ruhig.", "Ein kleiner Schritt reicht.", or "Atme durch und geh langsam weiter."
"""

    return f"""
FINAL RESPONSE INSTRUCTION:

You may use RAG context for facts, ideas, techniques, and examples.
However, do NOT copy the style, structure, or wording of the RAG context.

The RAG context gives you WHAT to say.
The selected tone tells you HOW to say it.
The HOW is mandatory and must be very noticeable.

Selected tone: {selected_tone}
Selected answer length: {selected_length}
Selected response format: {selected_format}
Selected app language: {app_language}

{tone_intensity_instruction}

Mandatory rules:
- Use ONLY the selected app language: {app_language}.
- The selected tone must be unmistakable in the FIRST sentence.
- The selected tone must be unmistakable in the LAST sentence.
- Do not use Croatian tone phrases when app language is English or Deutsch.
- Do not use English tone phrases when app language is Hrvatski or Deutsch.
- Do not use German tone phrases when app language is Hrvatski or English.
- The beginning and ending are the most important places for tone.
- Apply the selected tone strongly to the entire final answer.
- The tone must be obvious, not subtle.
- The tone must affect word choice, sentence length, rhythm, and emotional energy.
- Apply the selected answer length to the entire final answer.
- Apply the selected response format to the entire final answer.
- RAG content is source material, not the final writing style.
- Do not produce a neutral answer when a tone is selected.
- Do not simply list techniques from RAG.
- Rewrite the final answer so the selected tone is clearly felt.
- Do not confuse the topic with tone.
- If the user asks for a calming exercise while selected tone is motivating, give a calming exercise in a motivating tone.
- If the user asks for motivation while selected tone is gentle, give motivation in a gentle tone.
"""


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/api/memory")
def get_memory(guestId: str | None = Query(default=None)):
    memory_owner_id = build_memory_owner_id(
        user_id=None,
        guest_id=guestId,
    )

    memory_data = load_user_memory(memory_owner_id)

    return {
        "memoryOwnerId": memory_owner_id,
        "memory": memory_data,
    }


@app.delete("/api/memory")
def clear_memory(
    guestId: str | None = Query(default=None),
    memory_request: MemoryRequest | None = Body(default=None),
):
    body_guest_id = None

    if memory_request:
        body_guest_id = memory_request.guestId

    effective_guest_id = guestId or body_guest_id

    memory_owner_id = build_memory_owner_id(
        user_id=None,
        guest_id=effective_guest_id,
    )

    clear_user_memory(memory_owner_id)

    return {
        "memoryOwnerId": memory_owner_id,
        "memory": DEFAULT_MEMORY.copy(),
        "message": "Memory cleared.",
    }


@app.get("/api/knowledge")
def get_knowledge_base():
    entries = load_knowledge_base()
    return {"count": len(entries), "entries": entries}


@app.post("/api/chat")
def chat(request: ChatRequest):
    model_name = os.getenv("AZURE_OPENAI_MODEL")

    if not os.getenv("AZURE_OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_API_KEY not configured",
        )

    if not os.getenv("AZURE_OPENAI_BASE_URL"):
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_BASE_URL not configured",
        )

    if not model_name:
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_MODEL not configured",
        )

    client = OpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        base_url=os.getenv("AZURE_OPENAI_BASE_URL"),
    )

    app_language = request.appLanguage or "Hrvatski"

    memory_owner_id = build_memory_owner_id(
        user_id=None,
        guest_id=request.guestId,
    )

    print(
        "MEMORY OWNER DEBUG:",
        {
            "guestId": request.guestId,
            "memory_owner_id": memory_owner_id,
        },
    )

    detected_language = detect_message_language(request.message)
    language_warning = build_language_warning(app_language, detected_language)

    if language_warning:
        return {
            "reply": language_warning,
            "ragSources": [],
            "memoryOwnerId": memory_owner_id,
        }

    explicit_overrides = detect_explicit_style_overrides(request.message)

    effective_tone = normalize_tone(request.tone or explicit_overrides["tone"])
    effective_answer_length = normalize_answer_length(
        request.answerLength or explicit_overrides["answerLength"]
    )
    effective_response_format = normalize_response_format(
        request.responseFormat or explicit_overrides["responseFormat"]
    )

    print(
        "STYLE DEBUG:",
        {
            "request_tone": request.tone,
            "request_answerLength": request.answerLength,
            "request_responseFormat": request.responseFormat,
            "explicit_tone_override": explicit_overrides["tone"],
            "explicit_answerLength_override": explicit_overrides["answerLength"],
            "explicit_responseFormat_override": explicit_overrides["responseFormat"],
            "effective_tone": effective_tone,
            "effective_answer_length": effective_answer_length,
            "effective_response_format": effective_response_format,
        },
    )

    style_instructions = build_style_instructions(
        effective_tone,
        effective_answer_length,
        effective_response_format,
        app_language,
    )

    memory_data = load_user_memory(memory_owner_id)
    memory_context = build_memory_context(memory_data)

    relevant_rag_chunks = []

    if message_looks_like_coaching_topic(request.message):
        relevant_rag_chunks = retrieve_relevant_rag_chunks(
            client=client,
            user_message=request.message,
            max_entries=3,
        )

    knowledge_context = build_rag_chunks_context(relevant_rag_chunks)
    rag_sources = build_rag_sources(relevant_rag_chunks)

    print(
        "RAG DEBUG:",
        {
            "looks_like_coaching_topic": message_looks_like_coaching_topic(
                request.message
            ),
            "rag_count": len(relevant_rag_chunks),
            "rag_titles": [chunk.get("title") for chunk in relevant_rag_chunks],
            "rag_similarities": [
                chunk.get("similarity") for chunk in relevant_rag_chunks
            ],
        },
    )

    unknown_language_context = None

    if detected_language == "Unknown":
        unknown_language_context = build_unknown_language_context(app_language)

    conversation_context = []

    if request.chatHistory:
        for chat_message in request.chatHistory[-20:]:
            if chat_message.role in ["user", "assistant"]:
                conversation_context.append(
                    {
                        "role": chat_message.role,
                        "content": chat_message.content,
                    }
                )

    model_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if unknown_language_context:
        model_messages.append(
            {"role": "system", "content": unknown_language_context}
        )

    if memory_context:
        model_messages.append({"role": "system", "content": memory_context})

    if knowledge_context:
        model_messages.append({"role": "system", "content": knowledge_context})

    model_messages.extend(conversation_context)

    model_messages.append({"role": "system", "content": style_instructions})

    model_messages.append(
        {
            "role": "system",
            "content": build_final_response_instruction(
                tone=effective_tone,
                answer_length=effective_answer_length,
                response_format=effective_response_format,
                app_language=app_language,
            ),
        }
    )

    model_messages.append(
        {"role": "system", "content": build_final_language_guard(app_language)}
    )

    model_messages.append({"role": "user", "content": request.message})

    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.7,
            messages=model_messages,
        )

        reply = response.choices[0].message.content

        if reply:
            reply = reply.strip()

            if len(reply) >= 2:
                starts_with_quote = reply[0] in ['"', "'", "“", "„", "”"]
                ends_with_quote = reply[-1] in ['"', "'", "“", "„", "”"]

                if starts_with_quote and ends_with_quote:
                    reply = reply[1:-1].strip()

            try:
                updated_memory = update_memory_summary(
                    client=client,
                    model_name=model_name,
                    current_memory=memory_data,
                    user_message=request.message,
                    assistant_reply=reply,
                    app_language=app_language,
                )

                print(
                    "UPDATED MEMORY BEFORE SAVE:",
                    json.dumps(updated_memory, ensure_ascii=False),
                )

                save_user_memory(memory_owner_id, updated_memory)

                saved_memory_check = load_user_memory(memory_owner_id)

                print(
                    "SAVED MEMORY AFTER SAVE:",
                    json.dumps(saved_memory_check, ensure_ascii=False),
                )

            except Exception as memory_error:
                print(f"Memory update/save error: {memory_error}")

        return {
            "reply": reply,
            "ragSources": rag_sources,
            "memoryOwnerId": memory_owner_id,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Azure OpenAI error: {str(e)}",
        )