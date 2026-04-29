from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from lingua import Language, LanguageDetectorBuilder
from pathlib import Path
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
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


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
        with urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8")

            if not response_body:
                return None

            return json.loads(response_body)

    except HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Supabase HTTP error {e.code}: {error_body}") from e

    except URLError as e:
        raise RuntimeError(f"Supabase URL error: {e}") from e


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


def load_user_memory() -> dict:
    if is_supabase_configured():
        try:
            rows = supabase_request(
                method="GET",
                path="user_memory?id=eq.default&select=data",
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


def save_user_memory(memory_data: dict) -> None:
    normalized_memory = normalize_memory_data(memory_data)

    if is_supabase_configured():
        try:
            supabase_request(
                method="POST",
                path="user_memory?on_conflict=id",
                payload={
                    "id": "default",
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


def score_knowledge_entry(user_message: str, entry: dict) -> int:
    message_tokens = tokenize_text(user_message)

    if not message_tokens:
        return 0

    title = normalize_search_text(entry.get("title", ""))
    content = normalize_search_text(entry.get("content", ""))
    tags = entry.get("tags", [])

    normalized_tags = [normalize_search_text(tag) for tag in tags]

    score = 0

    for token in message_tokens:
        if token in normalized_tags:
            score += 5

        if token in title:
            score += 3

        if token in content:
            score += 1

    phrase_boosts = {
        "prezent": ["prezentacija", "trema", "javni nastup", "samopouzdanje"],
        "ispit": ["ispit", "učenje", "stres", "fokus"],
        "ucen": ["učenje", "ispit", "fokus", "plan"],
        "fokus": ["fokus", "koncentracija", "distrakcije"],
        "stres": ["stres", "smirivanje", "disanje"],
        "nervoz": ["nervoza", "smirivanje", "disanje"],
        "trem": ["trema", "prezentacija", "samopouzdanje"],
        "motiv": ["motivacija", "početak", "navike"],
        "samopouzdan": ["samopouzdanje", "intervju", "prezentacija"],
        "razgovor": ["razgovor za posao", "intervju", "samopouzdanje"],
        "intervju": ["razgovor za posao", "intervju", "samopouzdanje"],
        "posao": ["razgovor za posao", "intervju", "samopouzdanje"],
        "spav": ["spavanje", "večer", "smirivanje"],
        "vecer": ["večer", "refleksija", "smirivanje"],
        "disan": ["disanje", "smirivanje", "stres"],
        "navik": ["navike", "rutina", "motivacija"],
        "prokrast": ["prokrastinacija", "početak", "akcija"],
    }

    normalized_message = normalize_search_text(user_message)

    for phrase, related_tags in phrase_boosts.items():
        if phrase in normalized_message:
            for related_tag in related_tags:
                if normalize_search_text(related_tag) in normalized_tags:
                    score += 4

    return score


def retrieve_relevant_knowledge(
    user_message: str,
    max_entries: int = 3,
    minimum_score: int = 4,
) -> list[dict]:
    knowledge_base = load_knowledge_base()

    scored_entries = []

    for entry in knowledge_base:
        score = score_knowledge_entry(user_message, entry)

        if score >= minimum_score:
            scored_entries.append(
                {
                    "score": score,
                    "entry": entry,
                }
            )

    scored_entries.sort(key=lambda item: item["score"], reverse=True)

    top_entries = []

    for item in scored_entries[:max_entries]:
        top_entries.append(item["entry"])

    return top_entries


def build_knowledge_context(entries: list[dict]) -> str | None:
    if not entries:
        return None

    formatted_entries = []

    for index, entry in enumerate(entries, start=1):
        title = entry.get("title", "")
        tags = ", ".join(entry.get("tags", []))
        content = entry.get("content", "")

        formatted_entries.append(
            f"""
Knowledge entry {index}
Title: {title}
Tags: {tags}
Content: {content}
""".strip()
        )

    joined_entries = "\n\n---\n\n".join(formatted_entries)

    return f"""
RELEVANT KNOWLEDGE BASE CONTEXT:

{joined_entries}

How to use this knowledge:
- Use this knowledge only if it is relevant to the user's message.
- Do not mention the knowledge base unless the user asks.
- Do not invent knowledge base entries.
- If the knowledge is not enough, answer normally as an AI mental coach.
- Current user message, safety rules, app language, selected tone, selected length, and selected format still have priority.
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
        "veliki",
        "velika",
        "veliko",
        "mali",
        "mala",
        "malo",
        "pas",
        "macka",
        "trci",
        "trcim",
        "trcati",
        "biljka",
        "rastrkana",
        "crna",
        "crni",
        "crno",
        "bijela",
        "bijeli",
        "bijelo",
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
        "dog",
        "cat",
        "plant",
        "big",
        "small",
        "black",
        "white",
        "running",
        "run",
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
        "hund",
        "katze",
        "pflanze",
        "gross",
        "grosser",
        "klein",
        "schwarz",
        "weiss",
        "rennt",
        "laufe",
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
        "veliki pas",
        "veliki pas trci",
        "mali pas",
        "pas trci",
        "crna macka",
        "crna mačka",
        "rastrkana biljka",
        "etim okolo",
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
        "big dog",
        "big dog runs",
        "dog runs",
        "black cat",
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
        "grosser hund",
        "grosser hund rennt",
        "der hund rennt",
        "schwarze katze",
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


def detect_user_overrides(message: str) -> dict:
    text = message.lower()

    detected = {
        "tone": None,
        "answerLength": None,
        "responseFormat": None,
        "hasOverride": False,
    }

    if any(
        word in text
        for word in [
            "kratko",
            "kratak",
            "kratka",
            "ukratko",
            "sažeto",
            "sazeto",
            "sažet",
            "sazet",
            "brief",
            "short",
            "kurz",
        ]
    ):
        detected["answerLength"] = "Kratko"

    if any(
        word in text
        for word in [
            "srednje",
            "umjereno",
            "normalno dugo",
            "srednje dugo",
            "medium",
            "mittel",
        ]
    ):
        detected["answerLength"] = "Srednje"

    if any(
        word in text
        for word in [
            "dugačko",
            "dugacko",
            "dugo",
            "detaljno",
            "opširno",
            "opsirno",
            "detaljan",
            "detaljna",
            "long",
            "detailed",
            "lang",
            "ausführlich",
            "ausfuhrlich",
        ]
    ):
        detected["answerLength"] = "Dugačko"

    if any(
        word in text
        for word in [
            "smireno",
            "smiren",
            "mirno",
            "miran",
            "calm",
            "ruhig",
            "beruhigend",
        ]
    ):
        detected["tone"] = "Smiren"

    if any(
        word in text
        for word in [
            "motivirajuće",
            "motivirajuce",
            "motivirajući",
            "motivirajuci",
            "motivacijski",
            "motiviraj me",
            "nabrij",
            "nabrijano",
            "motivational",
            "motivierend",
            "motiviere",
        ]
    ):
        detected["tone"] = "Motivirajući"

    if any(
        word in text
        for word in [
            "direktno",
            "direktan",
            "direktna",
            "izravno",
            "bez okolišanja",
            "bez okolisanja",
            "direct",
            "direkt",
        ]
    ):
        detected["tone"] = "Direktan"

    if any(
        word in text
        for word in [
            "nježno",
            "njezno",
            "nježan",
            "njezan",
            "nježna",
            "njezna",
            "toplo",
            "blago",
            "gentle",
            "sanft",
            "weich",
        ]
    ):
        detected["tone"] = "Nježan"

    if any(
        phrase in text
        for phrase in [
            "format neka bude u 3 koraka",
            "format odgovora neka bude u 3 koraka",
            "odgovori u 3 koraka",
            "strukturiraj u 3 koraka",
            "strukturiraj odgovor u 3 koraka",
            "daj odgovor u 3 koraka",
            "u obliku 3 koraka",
            "u obliku tri koraka",
            "kao 3 koraka",
            "kao tri koraka",
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
            "format neka bude kratka vježba",
            "format neka bude kratka vjezba",
            "format odgovora neka bude kratka vježba",
            "format odgovora neka bude kratka vjezba",
            "odgovori kao kratka vježba",
            "odgovori kao kratka vjezba",
            "strukturiraj kao vježbu",
            "strukturiraj kao vjezbu",
            "strukturiraj odgovor kao vježbu",
            "strukturiraj odgovor kao vjezbu",
            "u obliku kratke vježbe",
            "u obliku kratke vjezbe",
            "answer as a short exercise",
            "format as a short exercise",
            "als kurze übung",
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
            "strukturiraj kao pitanja za refleksiju",
            "strukturiraj odgovor kao pitanja za refleksiju",
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
            "strukturiraj odgovor kao mini plan",
            "u obliku mini plana",
            "kao mini plan",
            "answer as a mini plan",
            "format as a mini plan",
            "als mini-plan",
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
            "strukturiraj odgovor kao jedan konkretan zadatak",
            "u obliku jednog konkretnog zadatka",
            "daj odgovor kao jedan konkretan zadatak",
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
TONE MODE: CALM
Use a calm, grounded, peaceful and emotionally steady tone.
Mention breathing, relaxing the body, or taking one small step.
Avoid excitement, urgency, and motivational slogans.
""",
        "Motivirajući": """
TONE MODE: MOTIVATING
Use an energetic, encouraging, coach-like tone.
Use short and powerful sentences.
Make the user feel ready to act.
""",
        "Direktan": """
TONE MODE: DIRECT
Use a practical, firm, concise and action-oriented tone.
Prefer clear steps and direct instructions.
Avoid long emotional introductions.
""",
        "Nježan": """
TONE MODE: GENTLE
Use a warm, soft, comforting tone.
Validate the user's feeling.
Use invitations instead of harsh commands.
Avoid pressure.
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
"""


def build_final_language_guard(app_language: str) -> str:
    if app_language == "Deutsch":
        return """
FINAL LANGUAGE LOCK:
You must answer in German only.
Do not answer in Croatian.
Do not use Croatian words such as "Hej", "Udahni", "Idemo", "Možeš", "Polako", "Nježno", or "Hvala".
Even if the user writes Croatian, mixed Croatian, unclear text, or nonsense text, answer in German only.
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


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/api/memory")
def get_memory():
    memory_data = load_user_memory()
    return {"memory": memory_data}


@app.delete("/api/memory")
def clear_memory():
    save_user_memory(DEFAULT_MEMORY.copy())
    return {"memory": DEFAULT_MEMORY.copy(), "message": "Memory cleared."}


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

    detected_language = detect_message_language(request.message)
    language_warning = build_language_warning(app_language, detected_language)

    if language_warning:
        return {
            "reply": language_warning,
            "ragSources": [],
        }

    user_overrides = detect_user_overrides(request.message)

    effective_tone = user_overrides["tone"] or request.tone
    effective_answer_length = user_overrides["answerLength"] or request.answerLength
    effective_response_format = user_overrides["responseFormat"] or request.responseFormat

    style_instructions = build_style_instructions(
        effective_tone,
        effective_answer_length,
        effective_response_format,
        app_language,
    )

    memory_data = load_user_memory()
    memory_context = build_memory_context(memory_data)

    relevant_knowledge = retrieve_relevant_knowledge(request.message)
    knowledge_context = build_knowledge_context(relevant_knowledge)
    rag_sources = build_rag_sources(relevant_knowledge)

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
        {"role": "system", "content": style_instructions},
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

    model_messages.append(
        {"role": "system", "content": build_final_language_guard(app_language)}
    )

    model_messages.append({"role": "user", "content": request.message})

    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.4,
            messages=model_messages,
        )

        reply = response.choices[0].message.content

        if reply:
            reply = reply.strip()

            if user_overrides["hasOverride"]:
                selected_language = app_language

                if selected_language == "Hrvatski":
                    notice = (
                        "Napomena: ton, duljinu i format možeš podesiti i u "
                        "postavkama mentalnog trenera, ali poštovat ću tvoju "
                        "trenutnu želju.\n\n"
                    )
                    reply = notice + reply

                elif selected_language == "English":
                    notice = (
                        "Note: you can also adjust tone, length, and format "
                        "in the mental coach settings, but I will respect your "
                        "current request.\n\n"
                    )
                    reply = notice + reply

                elif selected_language == "Deutsch":
                    notice = (
                        "Hinweis: Ton, Länge und Format kannst du auch in den "
                        "Einstellungen des Mentaltrainers anpassen, aber ich "
                        "werde deinen aktuellen Wunsch berücksichtigen.\n\n"
                    )
                    reply = notice + reply

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

                save_user_memory(updated_memory)

                saved_memory_check = load_user_memory()

                print(
                    "SAVED MEMORY AFTER SAVE:",
                    json.dumps(saved_memory_check, ensure_ascii=False),
                )

            except Exception as memory_error:
                print(f"Memory update/save error: {memory_error}")

        return {
            "reply": reply,
            "ragSources": rag_sources,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Azure OpenAI error: {str(e)}",
        )