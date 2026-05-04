"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { supabase } from "@/lib/supabaseClient";

type RagSource = {
  id: string;
  title: string;
  tags: string[];
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  ragSources?: RagSource[];
};

type AuthUser = {
  id: string;
  email?: string;
};

type AppLanguage = "Hrvatski" | "English" | "Deutsch";
type Tone = "Smiren" | "Motivirajući" | "Direktan" | "Nježan";
type AnswerLength = "Kratko" | "Srednje" | "Dugačko";
type ResponseFormat =
  | "Slobodno"
  | "U 3 koraka"
  | "Kratka vježba"
  | "Pitanja za refleksiju"
  | "Mini plan"
  | "Jedan konkretan zadatak";

const validTones: Tone[] = ["Smiren", "Motivirajući", "Direktan", "Nježan"];

const validAnswerLengths: AnswerLength[] = ["Kratko", "Srednje", "Dugačko"];

const validResponseFormats: ResponseFormat[] = [
  "Slobodno",
  "U 3 koraka",
  "Kratka vježba",
  "Pitanja za refleksiju",
  "Mini plan",
  "Jedan konkretan zadatak",
];

const validAppLanguages: AppLanguage[] = ["Hrvatski", "English", "Deutsch"];

function getOrCreateGuestId() {
  const storageKey = "mental-coach-guest-id";

  let guestId = localStorage.getItem(storageKey);

  if (!guestId) {
    guestId = crypto.randomUUID();
    localStorage.setItem(storageKey, guestId);
  }

  return guestId;
}

function getChatStorageKey(userId?: string) {
  if (userId) {
    return `mental-coach-chat-history:user:${userId}`;
  }

  const guestId = getOrCreateGuestId();
  return `mental-coach-chat-history:guest:${guestId}`;
}

const translations = {
  Hrvatski: {
    badge: "AI mentalni trener",
    title: "Treniraj svoj um, jedan miran korak po korak.",
    subtitle: "Razgovaraj, smiri misli i pripremi se za sljedeći korak.",
    moodTitle: "Kako se danas osjećaš?",
    suggestionsTitle: "Možeš probati pitati:",
    chatTitle: "Razgovor",
    chatSubtitle: "Napiši što te muči ili što želiš mentalno pripremiti.",
    clearChat: "Očisti chat",
    clearMemory: "Očisti memoriju",
    emptyChat:
      "Još nema poruka. Odaberi prijedlog ili napiši kako se osjećaš.",
    userLabel: "Ti",
    assistantLabel: "Mentalni trener",
    thinking: "Mentalni trener razmišlja...",
    placeholder: "Npr. Imam prezentaciju za 30 minuta i osjećam nervozu...",
    enterHint: "Enter šalje poruku, Shift + Enter dodaje novi red.",
    send: "Pošalji",
    sending: "Razmišljam...",
    settingsTitle: "Postavke mentalnog trenera",
    tone: "Ton",
    length: "Duljina",
    format: "Format odgovora",
    language: "Jezik aplikacije",
    quickExercises: "Brze mentalne vježbe",
    errorFallback: "Dogodila se greška.",
    unknownError: "Nepoznata greška.",
    memoryCleared: "Memorija ovog browsera je obrisana.",
    userMemoryCleared:
      "Memorija računa i trenutni razgovor su obrisani. Krenimo ispočetka.",
    ragSourcesLabel: "Korištena baza znanja",
    guestMemoryNotice:
      "Nisi prijavljen. Memorija je spremljena samo za ovaj browser. Prijava omogućuje sigurnu memoriju na svim uređajima.",

    toneCalm: "Smiren",
    toneMotivating: "Motivirajući",
    toneDirect: "Direktan",
    toneGentle: "Nježan",

    lengthShort: "Kratko",
    lengthMedium: "Srednje",
    lengthLong: "Dugačko",

    formatFree: "Slobodno",
    formatThreeSteps: "U 3 koraka",
    formatExercise: "Kratka vježba",
    formatReflection: "Pitanja za refleksiju",
    formatMiniPlan: "Mini plan",
    formatOneTask: "Jedan konkretan zadatak",

    noReply: "Nema odgovora.",

    moods: [
      {
        label: "Pod stresom",
        prompt:
          "Osjećam se pod stresom. Možeš li mi pomoći da se smirim i fokusiram?",
      },
      {
        label: "Nervozan/na",
        prompt:
          "Osjećam nervozu. Možeš li me provesti kroz vježbu smirivanja?",
      },
      {
        label: "Bez fokusa",
        prompt:
          "Teško se fokusiram. Možeš li mi dati mentalnu vježbu za bolji fokus?",
      },
      {
        label: "Umoran/na",
        prompt:
          "Osjećam se umorno i mentalno iscrpljeno. Što mogu napraviti da se malo oporavim?",
      },
      {
        label: "Trebam motivaciju",
        prompt: "Trebam motivaciju i jasniji plan za nastavak dana.",
      },
    ],

    suggestions: [
      "Pomozi mi da se smirim prije ispita.",
      "Daj mi vježbu disanja.",
      "Pomozi mi izgraditi samopouzdanje prije razgovora za posao.",
      "Trebam mentalnu pripremu za prezentaciju.",
    ],

    quickActions: [
      {
        label: "Plan za danas",
        prompt:
          "Napravi mi mentalni trening plan za danas. Uključi jutarnju vježbu, fokus reset tijekom dana i večernju refleksiju.",
      },
      {
        label: "Smirivanje",
        prompt:
          "Provedi me kroz vježbu smirivanja. Želim nešto jednostavno i odmah primjenjivo.",
      },
      {
        label: "Fokus reset",
        prompt:
          "Daj mi fokus reset koji mogu napraviti sada kako bih se vratio/la učenju ili poslu.",
      },
      {
        label: "Večernja refleksija",
        prompt:
          "Vodi me kroz večernju refleksiju. Želim smiriti misli, pregledati dan i pripremiti se za sutra.",
      },
    ],
  },

  English: {
    badge: "AI mental coach",
    title: "Train your mind, one calm step at a time.",
    subtitle: "Talk, calm your thoughts, and prepare for your next step.",
    moodTitle: "How are you feeling today?",
    suggestionsTitle: "You can try asking:",
    chatTitle: "Conversation",
    chatSubtitle:
      "Write what is bothering you or what you want to mentally prepare for.",
    clearChat: "Clear chat",
    clearMemory: "Clear memory",
    emptyChat: "No messages yet. Choose a suggestion or write how you feel.",
    userLabel: "You",
    assistantLabel: "Mental coach",
    thinking: "The mental coach is thinking...",
    placeholder: "E.g. I have a presentation in 30 minutes and I feel nervous...",
    enterHint: "Enter sends the message, Shift + Enter adds a new line.",
    send: "Send",
    sending: "Thinking...",
    settingsTitle: "Mental coach settings",
    tone: "Tone",
    length: "Length",
    format: "Response format",
    language: "App language",
    quickExercises: "Quick mental exercises",
    errorFallback: "Something went wrong.",
    unknownError: "Unknown error.",
    memoryCleared: "This browser's memory has been cleared.",
    userMemoryCleared:
      "Account memory and the current conversation have been cleared. Let's start fresh.",
    ragSourcesLabel: "Knowledge base used",
    guestMemoryNotice:
      "You are not signed in. Memory is saved only for this browser. Signing in allows secure memory across devices.",

    toneCalm: "Calm",
    toneMotivating: "Motivating",
    toneDirect: "Direct",
    toneGentle: "Gentle",

    lengthShort: "Short",
    lengthMedium: "Medium",
    lengthLong: "Long",

    formatFree: "Free form",
    formatThreeSteps: "In 3 steps",
    formatExercise: "Short exercise",
    formatReflection: "Reflection questions",
    formatMiniPlan: "Mini plan",
    formatOneTask: "One concrete task",

    noReply: "No reply.",

    moods: [
      {
        label: "Stressed",
        prompt: "I feel stressed. Can you help me calm down and focus?",
      },
      {
        label: "Nervous",
        prompt: "I feel nervous. Can you guide me through a calming exercise?",
      },
      {
        label: "Unfocused",
        prompt:
          "I am having trouble focusing. Can you give me a mental exercise for better focus?",
      },
      {
        label: "Tired",
        prompt:
          "I feel tired and mentally drained. What can I do to recover a little?",
      },
      {
        label: "Need motivation",
        prompt: "I need motivation and a clearer plan for the rest of the day.",
      },
    ],

    suggestions: [
      "Help me calm down before an exam.",
      "Give me a breathing exercise.",
      "Help me build confidence before a job interview.",
      "I need mental preparation for a presentation.",
    ],

    quickActions: [
      {
        label: "Plan for today",
        prompt:
          "Create a mental training plan for today. Include a morning exercise, a focus reset during the day, and an evening reflection.",
      },
      {
        label: "Calming",
        prompt:
          "Guide me through a calming exercise. I want something simple and immediately usable.",
      },
      {
        label: "Focus reset",
        prompt:
          "Give me a focus reset I can do now to return to studying or work.",
      },
      {
        label: "Evening reflection",
        prompt:
          "Guide me through an evening reflection. I want to calm my thoughts, review the day, and prepare for tomorrow.",
      },
    ],
  },

  Deutsch: {
    badge: "KI-Mentaltrainer",
    title: "Trainiere deinen Geist, einen ruhigen Schritt nach dem anderen.",
    subtitle:
      "Sprich, beruhige deine Gedanken und bereite dich auf deinen nächsten Schritt vor.",
    moodTitle: "Wie fühlst du dich heute?",
    suggestionsTitle: "Du kannst zum Beispiel fragen:",
    chatTitle: "Gespräch",
    chatSubtitle:
      "Schreibe, was dich beschäftigt oder worauf du dich mental vorbereiten möchtest.",
    clearChat: "Chat löschen",
    clearMemory: "Speicher löschen",
    emptyChat:
      "Noch keine Nachrichten. Wähle einen Vorschlag oder schreibe, wie du dich fühlst.",
    userLabel: "Du",
    assistantLabel: "Mentaltrainer",
    thinking: "Der Mentaltrainer denkt nach...",
    placeholder:
      "Z. B. Ich habe in 30 Minuten eine Präsentation und bin nervös...",
    enterHint:
      "Enter sendet die Nachricht, Shift + Enter fügt eine neue Zeile hinzu.",
    send: "Senden",
    sending: "Denke nach...",
    settingsTitle: "Einstellungen des Mentaltrainers",
    tone: "Ton",
    length: "Länge",
    format: "Antwortformat",
    language: "App-Sprache",
    quickExercises: "Schnelle mentale Übungen",
    errorFallback: "Ein Fehler ist aufgetreten.",
    unknownError: "Unbekannter Fehler.",
    memoryCleared: "Der Speicher dieses Browsers wurde gelöscht.",
    userMemoryCleared:
      "Der Kontospeicher und das aktuelle Gespräch wurden gelöscht. Wir starten neu.",
    ragSourcesLabel: "Verwendete Wissensbasis",
    guestMemoryNotice:
      "Du bist nicht angemeldet. Der Speicher wird nur für diesen Browser gespeichert. Eine Anmeldung ermöglicht sicheren Speicher auf allen Geräten.",

    toneCalm: "Ruhig",
    toneMotivating: "Motivierend",
    toneDirect: "Direkt",
    toneGentle: "Sanft",

    lengthShort: "Kurz",
    lengthMedium: "Mittel",
    lengthLong: "Lang",

    formatFree: "Frei",
    formatThreeSteps: "In 3 Schritten",
    formatExercise: "Kurze Übung",
    formatReflection: "Reflexionsfragen",
    formatMiniPlan: "Mini-Plan",
    formatOneTask: "Eine konkrete Aufgabe",

    noReply: "Keine Antwort.",

    moods: [
      {
        label: "Gestresst",
        prompt:
          "Ich fühle mich gestresst. Kannst du mir helfen, ruhiger zu werden und mich zu fokussieren?",
      },
      {
        label: "Nervös",
        prompt:
          "Ich bin nervös. Kannst du mich durch eine beruhigende Übung führen?",
      },
      {
        label: "Unfokussiert",
        prompt:
          "Ich kann mich schwer konzentrieren. Kannst du mir eine mentale Übung für besseren Fokus geben?",
      },
      {
        label: "Müde",
        prompt:
          "Ich fühle mich müde und mental erschöpft. Was kann ich tun, um mich ein wenig zu erholen?",
      },
      {
        label: "Brauche Motivation",
        prompt:
          "Ich brauche Motivation und einen klareren Plan für den restlichen Tag.",
      },
    ],

    suggestions: [
      "Hilf mir, mich vor einer Prüfung zu beruhigen.",
      "Gib mir eine Atemübung.",
      "Hilf mir, vor einem Vorstellungsgespräch Selbstvertrauen aufzubauen.",
      "Ich brauche mentale Vorbereitung für eine Präsentation.",
    ],

    quickActions: [
      {
        label: "Plan für heute",
        prompt:
          "Erstelle mir einen mentalen Trainingsplan für heute. Integriere eine Morgenübung, einen Fokus-Reset während des Tages und eine Abendreflexion.",
      },
      {
        label: "Beruhigung",
        prompt:
          "Führe mich durch eine beruhigende Übung. Ich möchte etwas Einfaches und sofort Anwendbares.",
      },
      {
        label: "Fokus-Reset",
        prompt:
          "Gib mir einen Fokus-Reset, den ich jetzt machen kann, um wieder ins Lernen oder Arbeiten zu kommen.",
      },
      {
        label: "Abendreflexion",
        prompt:
          "Führe mich durch eine Abendreflexion. Ich möchte meine Gedanken beruhigen, den Tag betrachten und mich auf morgen vorbereiten.",
      },
    ],
  },
};

function isValidTone(value: string | null): value is Tone {
  return value !== null && validTones.includes(value as Tone);
}

function isValidAnswerLength(value: string | null): value is AnswerLength {
  return value !== null && validAnswerLengths.includes(value as AnswerLength);
}

function isValidResponseFormat(value: string | null): value is ResponseFormat {
  return (
    value !== null && validResponseFormats.includes(value as ResponseFormat)
  );
}

function isValidAppLanguage(value: string | null): value is AppLanguage {
  return value !== null && validAppLanguages.includes(value as AppLanguage);
}

function safeParseMessages(value: string | null): ChatMessage[] {
  if (!value) return [];

  try {
    const parsed = JSON.parse(value);

    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter((item) => {
      return (
        item &&
        typeof item === "object" &&
        (item.role === "user" || item.role === "assistant") &&
        typeof item.content === "string"
      );
    });
  } catch {
    return [];
  }
}

export default function Home() {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [isPasswordRecovery, setIsPasswordRecovery] = useState(false);

  const [activeChatStorageKey, setActiveChatStorageKey] = useState("");
  const [chatLoaded, setChatLoaded] = useState(false);

  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const [tone, setTone] = useState<Tone>("Smiren");
  const [answerLength, setAnswerLength] = useState<AnswerLength>("Kratko");
  const [responseFormat, setResponseFormat] =
    useState<ResponseFormat>("Slobodno");
  const [appLanguage, setAppLanguage] = useState<AppLanguage>("Hrvatski");

  const t = translations[appLanguage];

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    const oldSharedChatHistory = localStorage.getItem(
      "mental-coach-chat-history"
    );

    if (oldSharedChatHistory) {
      localStorage.removeItem("mental-coach-chat-history");
    }

    const savedTone = localStorage.getItem("mental-coach-tone");
    const savedAnswerLength = localStorage.getItem("mental-coach-answer-length");
    const savedResponseFormat = localStorage.getItem(
      "mental-coach-response-format"
    );
    const savedAppLanguage = localStorage.getItem("mental-coach-app-language");

    if (isValidTone(savedTone)) {
      setTone(savedTone);
    } else {
      localStorage.removeItem("mental-coach-tone");
    }

    if (isValidAnswerLength(savedAnswerLength)) {
      setAnswerLength(savedAnswerLength);
    } else {
      localStorage.removeItem("mental-coach-answer-length");
    }

    if (isValidResponseFormat(savedResponseFormat)) {
      setResponseFormat(savedResponseFormat);
    } else {
      localStorage.removeItem("mental-coach-response-format");
    }

    if (isValidAppLanguage(savedAppLanguage)) {
      setAppLanguage(savedAppLanguage);
    } else {
      localStorage.removeItem("mental-coach-app-language");
    }
  }, []);

  useEffect(() => {
    const nextChatStorageKey = getChatStorageKey(authUser?.id);

    setChatLoaded(false);
    setActiveChatStorageKey(nextChatStorageKey);

    const savedMessages = localStorage.getItem(nextChatStorageKey);
    setMessages(safeParseMessages(savedMessages));

    setMessage("");
    setError("");
    setChatLoaded(true);
  }, [authUser?.id]);

  useEffect(() => {
    if (!chatLoaded || !activeChatStorageKey) return;

    localStorage.setItem(activeChatStorageKey, JSON.stringify(messages));
  }, [messages, activeChatStorageKey, chatLoaded]);

  useEffect(() => {
    localStorage.setItem("mental-coach-tone", tone);
    localStorage.setItem("mental-coach-answer-length", answerLength);
    localStorage.setItem("mental-coach-response-format", responseFormat);
    localStorage.setItem("mental-coach-app-language", appLanguage);
  }, [tone, answerLength, responseFormat, appLanguage]);

  useEffect(() => {
    const isMobile = window.innerWidth < 768;

    if (isMobile) {
      return;
    }

    scrollToBottom();
  }, [messages, loading]);

  useEffect(() => {
    const loadSession = async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session?.user) {
        setAuthUser(null);
        return;
      }

      const { data, error } = await supabase.auth.getUser();

      if (error || !data.user) {
        await supabase.auth.signOut({ scope: "local" });
        setAuthUser(null);
        return;
      }

      setAuthUser({
        id: data.user.id,
        email: data.user.email || undefined,
      });
    };

    loadSession();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY") {
        setIsPasswordRecovery(true);
        setAuthMessage(
          appLanguage === "English"
            ? "Enter your new password."
            : appLanguage === "Deutsch"
            ? "Gib dein neues Passwort ein."
            : "Upiši novu lozinku."
        );
      }

      if (session?.user) {
        setAuthUser({
          id: session.user.id,
          email: session.user.email || undefined,
        });
      } else {
        setAuthUser(null);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, [appLanguage]);

  const handleRegister = async () => {
    if (!authEmail.trim() || !authPassword.trim() || authLoading) return;

    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const redirectUrl = window.location.origin;

      const { error } = await supabase.auth.signUp({
        email: authEmail.trim(),
        password: authPassword,
        options: {
          emailRedirectTo: redirectUrl,
        },
      });

      if (error) {
        throw error;
      }

      setAuthMessage(
        appLanguage === "English"
          ? "If this email is new, registration was started. If you already have an account, log in or reset your password."
          : appLanguage === "Deutsch"
          ? "Wenn diese E-Mail neu ist, wurde die Registrierung gestartet. Wenn du bereits ein Konto hast, melde dich an oder setze dein Passwort zurück."
          : "Ako je ovaj email novi, registracija je pokrenuta. Ako račun već postoji, prijavi se ili resetiraj lozinku."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogin = async () => {
    if (!authEmail.trim() || !authPassword.trim() || authLoading) return;

    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: authEmail.trim(),
        password: authPassword,
      });

      if (error) {
        throw error;
      }

      setAuthMessage(
        appLanguage === "English"
          ? "Login successful."
          : appLanguage === "Deutsch"
          ? "Anmeldung erfolgreich."
          : "Prijava uspješna."
      );

      setAuthPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setAuthLoading(false);
    }
  };

  const handlePasswordReset = async () => {
    if (!authEmail.trim() || authLoading) return;

    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const redirectUrl = window.location.origin;

      const { error } = await supabase.auth.resetPasswordForEmail(
        authEmail.trim(),
        {
          redirectTo: redirectUrl,
        }
      );

      if (error) {
        throw error;
      }

      setAuthMessage(
        appLanguage === "English"
          ? "If this email has an account, a password reset link has been sent."
          : appLanguage === "Deutsch"
          ? "Wenn es für diese E-Mail ein Konto gibt, wurde ein Link zum Zurücksetzen des Passworts gesendet."
          : "Ako za ovaj email postoji račun, poslan je link za reset lozinke."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleUpdatePassword = async () => {
    if (!newPassword.trim() || authLoading) return;

    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const { error } = await supabase.auth.updateUser({
        password: newPassword,
      });

      if (error) {
        throw error;
      }

      setNewPassword("");
      setIsPasswordRecovery(false);

      setAuthMessage(
        appLanguage === "English"
          ? "Password updated successfully. You can now use your new password."
          : appLanguage === "Deutsch"
          ? "Passwort erfolgreich geändert. Du kannst jetzt dein neues Passwort verwenden."
          : "Lozinka je uspješno promijenjena. Sada možeš koristiti novu lozinku."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const { error } = await supabase.auth.signOut();

      if (error) {
        throw error;
      }

      setAuthUser(null);
      setAuthPassword("");
      setNewPassword("");
      setIsPasswordRecovery(false);

      setAuthMessage(
        appLanguage === "English"
          ? "Logged out."
          : appLanguage === "Deutsch"
          ? "Abgemeldet."
          : "Odjavljen/a si."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!authUser || authLoading) return;

    const confirmed = window.confirm(
      appLanguage === "English"
        ? "Are you sure you want to delete your account? This will permanently delete your account and saved memory."
        : appLanguage === "Deutsch"
        ? "Bist du sicher, dass du dein Konto löschen möchtest? Dein Konto und gespeicherter Speicher werden dauerhaft gelöscht."
        : "Jesi li siguran/sigurna da želiš obrisati račun? Račun i spremljena memorija bit će trajno obrisani."
    );

    if (!confirmed) return;

    setAuthLoading(true);
    setError("");
    setAuthMessage("");

    try {
      const userChatStorageKey = getChatStorageKey(authUser.id);

      const {
        data: { session },
      } = await supabase.auth.getSession();

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
      }

      const res = await fetch(`${apiUrl}/api/account`, {
        method: "DELETE",
        headers,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || t.errorFallback);
      }

      localStorage.removeItem(userChatStorageKey);

      await supabase.auth.signOut({ scope: "local" });

      setAuthUser(null);
      setAuthEmail("");
      setAuthPassword("");
      setNewPassword("");
      setIsPasswordRecovery(false);
      setError("");
      setAuthMessage("");

      window.location.href = window.location.origin;
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
      setAuthLoading(false);
    }
  };

  const handleSend = async () => {
    if (!message.trim() || loading) return;

    const currentMessage = message.trim();
    const guestId = getOrCreateGuestId();

    console.log("FRONTEND GUEST ID:", guestId);

    const userMessage: ChatMessage = {
      role: "user",
      content: currentMessage,
    };

    const chatHistoryForRequest = messages.slice(-20);

    setMessages((previousMessages) => [...previousMessages, userMessage]);

    setLoading(true);
    setError("");
    setMessage("");

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
      }

      const res = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: currentMessage,
          chatHistory: chatHistoryForRequest,
          tone,
          answerLength,
          responseFormat,
          appLanguage,
          guestId,
        }),
      });

      const data = await res.json();

      console.log("CHAT RESPONSE:", data);

      if (!res.ok) {
        throw new Error(data.detail || t.errorFallback);
      }

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: data.reply || t.noReply,
        ragSources: data.ragSources || [],
      };

      setMessages((previousMessages) => [
        ...previousMessages,
        assistantMessage,
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setMessage("");
    setMessages([]);
    setError("");

    if (activeChatStorageKey) {
      localStorage.removeItem(activeChatStorageKey);
    }
  };

  const handleClearMemory = async () => {
    setError("");

    try {
      const guestId = getOrCreateGuestId();

      const {
        data: { session },
      } = await supabase.auth.getSession();

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
      }

      console.log("CLEARING MEMORY:", {
        isLoggedIn: Boolean(session?.access_token),
        guestId,
        authUserId: authUser?.id,
      });

      const res = await fetch(
        `${apiUrl}/api/memory?guestId=${encodeURIComponent(guestId)}`,
        {
          method: "DELETE",
          headers,
        }
      );

      const data = await res.json();

      console.log("CLEAR MEMORY RESPONSE:", data);

      if (!res.ok) {
        throw new Error(data.detail || t.errorFallback);
      }

      if (activeChatStorageKey) {
        localStorage.removeItem(activeChatStorageKey);
      }

      setMessage("");

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: authUser ? t.userMemoryCleared : t.memoryCleared,
        ragSources: [],
      };

      setMessages([assistantMessage]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.unknownError);
    }
  };

  return (
    <main className="relative min-h-screen overflow-x-hidden overflow-y-auto bg-white text-white">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat opacity-30 sm:opacity-50 lg:bg-contain lg:bg-left lg:opacity-95"
        style={{ backgroundImage: "url('/mental-coaching1.jpg')" }}
      />

      <div className="absolute inset-0 bg-gradient-to-b from-black/75 via-slate-950/80 to-black/95 lg:bg-gradient-to-r lg:from-white/0 lg:via-slate-900/45 lg:to-black/90" />

      <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-blue-500/20 blur-3xl sm:right-20 sm:h-96 sm:w-96" />

      <div className="relative z-10 flex min-h-screen w-full items-start justify-center p-4 sm:p-6 lg:items-center lg:justify-end lg:pl-[420px]">
        <div className="grid w-full max-w-4xl min-w-0 gap-4 sm:gap-3 lg:grid-cols-[0.95fr_1.25fr]">
          <section className="min-w-0 rounded-3xl border border-white/10 bg-black/60 p-4 shadow-2xl backdrop-blur-md sm:p-4">
            <p className="mb-2 inline-flex rounded-full border border-blue-400/30 bg-blue-400/10 px-3 py-1 text-xs text-blue-200">
              {t.badge}
            </p>

            <p className="mb-3 text-sm text-white/75">{t.subtitle}</p>

            <div className="mb-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <h2 className="mb-2 text-base font-semibold">{t.moodTitle}</h2>

              <div className="flex flex-wrap gap-2">
                {t.moods.map((item) => (
                  <button
                    key={item.label}
                    onClick={() => setMessage(item.prompt)}
                    className="rounded-full border border-white/10 bg-white/10 px-3 py-2 text-xs text-white/90 transition hover:border-blue-300/50 hover:bg-blue-500/20"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
              <h2 className="mb-2 text-base font-semibold">
                {t.suggestionsTitle}
              </h2>

              <div className="space-y-2">
                {t.suggestions.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => setMessage(prompt)}
                    className="w-full rounded-2xl border border-white/10 bg-black/30 p-2 text-left text-xs text-white/85 transition hover:border-blue-300/50 hover:bg-blue-500/15"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <h2 className="mb-2 text-base font-semibold">
                {appLanguage === "English"
                  ? "Account"
                  : appLanguage === "Deutsch"
                  ? "Konto"
                  : "Račun"}
              </h2>

              {isPasswordRecovery ? (
                <div className="space-y-2">
                  <p className="text-xs text-white/70">
                    {appLanguage === "English"
                      ? "Enter a new password for your account."
                      : appLanguage === "Deutsch"
                      ? "Gib dein neues Passwort für dein Konto ein."
                      : "Upiši novu lozinku za svoj račun."}
                  </p>

                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder={
                      appLanguage === "English"
                        ? "New password"
                        : appLanguage === "Deutsch"
                        ? "Neues Passwort"
                        : "Nova lozinka"
                    }
                    autoComplete="new-password"
                    className="w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none placeholder:text-white/40 focus:border-blue-400/60"
                  />

                  <button
                    onClick={handleUpdatePassword}
                    disabled={authLoading}
                    className="w-full rounded-xl bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {authLoading
                      ? appLanguage === "English"
                        ? "Saving..."
                        : appLanguage === "Deutsch"
                        ? "Speichern..."
                        : "Spremam..."
                      : appLanguage === "English"
                      ? "Save new password"
                      : appLanguage === "Deutsch"
                      ? "Neues Passwort speichern"
                      : "Spremi novu lozinku"}
                  </button>
                </div>
              ) : authUser ? (
                <div className="space-y-2">
                  <p className="break-words text-xs text-white/70 [overflow-wrap:anywhere]">
                    {appLanguage === "English"
                      ? `Signed in as ${authUser.email || authUser.id}`
                      : appLanguage === "Deutsch"
                      ? `Angemeldet als ${authUser.email || authUser.id}`
                      : `Prijavljen/a kao ${authUser.email || authUser.id}`}
                  </p>

                  <button
                    onClick={handleLogout}
                    disabled={authLoading}
                    className="w-full rounded-xl border border-white/10 px-3 py-2 text-xs text-white/80 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {authLoading
                      ? appLanguage === "English"
                        ? "Please wait..."
                        : appLanguage === "Deutsch"
                        ? "Bitte warten..."
                        : "Pričekaj..."
                      : appLanguage === "English"
                      ? "Log out"
                      : appLanguage === "Deutsch"
                      ? "Abmelden"
                      : "Odjava"}
                  </button>

                  <button
                    onClick={handleDeleteAccount}
                    disabled={authLoading}
                    className="w-full rounded-xl border border-red-400/30 px-3 py-2 text-xs text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {authLoading
                      ? appLanguage === "English"
                        ? "Please wait..."
                        : appLanguage === "Deutsch"
                        ? "Bitte warten..."
                        : "Pričekaj..."
                      : appLanguage === "English"
                      ? "Delete account"
                      : appLanguage === "Deutsch"
                      ? "Konto löschen"
                      : "Obriši račun"}
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <input
                    type="email"
                    name="mental-coach-email"
                    value={authEmail}
                    onChange={(e) => setAuthEmail(e.target.value)}
                    placeholder="email@example.com"
                    autoComplete="off"
                    className="w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none placeholder:text-white/40 focus:border-blue-400/60"
                  />

                  <input
                    type="password"
                    name="mental-coach-password"
                    value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    placeholder={
                      appLanguage === "English"
                        ? "Password"
                        : appLanguage === "Deutsch"
                        ? "Passwort"
                        : "Lozinka"
                    }
                    autoComplete="new-password"
                    className="w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none placeholder:text-white/40 focus:border-blue-400/60"
                  />

                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <button
                      onClick={handleLogin}
                      disabled={authLoading}
                      className="rounded-xl bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {appLanguage === "English"
                        ? "Log in"
                        : appLanguage === "Deutsch"
                        ? "Anmelden"
                        : "Prijava"}
                    </button>

                    <button
                      onClick={handleRegister}
                      disabled={authLoading}
                      className="rounded-xl border border-white/10 px-3 py-2 text-xs text-white/80 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {appLanguage === "English"
                        ? "Register"
                        : appLanguage === "Deutsch"
                        ? "Registrieren"
                        : "Registracija"}
                    </button>
                  </div>

                  <button
                    onClick={handlePasswordReset}
                    disabled={authLoading}
                    className="w-full rounded-xl border border-yellow-400/20 px-3 py-2 text-xs text-yellow-100 transition hover:bg-yellow-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {appLanguage === "English"
                      ? "Forgot password?"
                      : appLanguage === "Deutsch"
                      ? "Passwort vergessen?"
                      : "Zaboravio/la si lozinku?"}
                  </button>
                </div>
              )}

              {authMessage && (
                <p className="mt-2 text-xs text-emerald-200">{authMessage}</p>
              )}

              {error && (
                <p className="mt-2 rounded-xl border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
                  {error}
                </p>
              )}
            </div>

            {!authUser && !isPasswordRecovery && (
              <div className="mt-3 rounded-2xl border border-yellow-400/20 bg-yellow-500/10 p-3 text-xs text-yellow-100">
                {t.guestMemoryNotice}
              </div>
            )}
          </section>

          <section className="min-w-0 rounded-3xl border border-white/10 bg-black/65 p-4 shadow-2xl backdrop-blur-md sm:p-4">
            <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <h2 className="text-2xl font-bold">{t.chatTitle}</h2>
                <p className="text-xs text-white/60">{t.chatSubtitle}</p>
              </div>

              <div className="grid shrink-0 grid-cols-2 gap-2 sm:flex sm:flex-row">
                <button
                  onClick={handleClear}
                  className="rounded-xl border border-white/10 px-3 py-2 text-xs text-white/70 transition hover:bg-white/10 hover:text-white"
                >
                  {t.clearChat}
                </button>

                <button
                  onClick={handleClearMemory}
                  className="rounded-xl border border-red-400/20 px-3 py-2 text-xs text-red-200/80 transition hover:bg-red-500/10 hover:text-red-100"
                >
                  {t.clearMemory}
                </button>
              </div>
            </div>

            <div className="mb-3 max-h-[34vh] min-w-0 space-y-2 overflow-y-auto rounded-2xl border border-white/10 bg-black/30 p-3 sm:max-h-52">
              {messages.length === 0 && (
                <p className="text-xs text-white/50">{t.emptyChat}</p>
              )}

              {messages.map((chatMessage, index) => (
                <div
                  key={index}
                  className={`overflow-hidden rounded-2xl p-3 text-sm ${
                    chatMessage.role === "user"
                      ? "ml-auto max-w-[92%] bg-blue-600/80 text-white sm:max-w-[85%]"
                      : "mr-auto max-w-[94%] border border-blue-400/20 bg-black/45 text-white/90 sm:max-w-[90%]"
                  }`}
                >
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/60">
                    {chatMessage.role === "user"
                      ? t.userLabel
                      : t.assistantLabel}
                  </p>

                  <div className="prose prose-invert prose-sm max-w-none whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
                    <ReactMarkdown>{chatMessage.content}</ReactMarkdown>
                  </div>

                  {chatMessage.role === "assistant" &&
                    chatMessage.ragSources &&
                    chatMessage.ragSources.length > 0 && (
                      <div className="mt-3 overflow-hidden rounded-xl border border-emerald-400/20 bg-emerald-500/10 p-2">
                        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-emerald-200">
                          {t.ragSourcesLabel}
                        </p>

                        <div className="flex flex-wrap gap-2">
                          {chatMessage.ragSources.map((source) => (
                            <span
                              key={source.id}
                              className="max-w-full break-words rounded-full border border-emerald-300/20 bg-black/30 px-2 py-1 text-[10px] text-emerald-100 [overflow-wrap:anywhere]"
                            >
                              {source.title}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                </div>
              ))}

              {loading && (
                <div className="mr-auto max-w-[90%] rounded-2xl border border-white/10 bg-black/45 p-3 text-sm text-white/70">
                  {t.thinking}
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            <textarea
              className="min-h-16 w-full rounded-2xl border border-white/10 bg-black/50 p-3 text-sm text-white outline-none placeholder:text-white/40 focus:border-blue-400/60 sm:min-h-20"
              placeholder={t.placeholder}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();

                  if (!loading) {
                    handleSend();
                  }
                }
              }}
            />

            <p className="mt-1 text-xs text-white/45">{t.enterHint}</p>

            <button
              onClick={handleSend}
              disabled={loading}
              className="mt-2 w-full rounded-2xl bg-blue-600 px-5 py-2.5 text-sm font-medium transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? t.sending : t.send}
            </button>

            <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <h2 className="mb-2 text-base font-semibold">
                {t.settingsTitle}
              </h2>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-xs text-white/70">
                  {t.tone}
                  <select
                    value={tone}
                    onChange={(e) => setTone(e.target.value as Tone)}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none focus:border-blue-400/60"
                  >
                    <option value="Smiren">{t.toneCalm}</option>
                    <option value="Motivirajući">{t.toneMotivating}</option>
                    <option value="Direktan">{t.toneDirect}</option>
                    <option value="Nježan">{t.toneGentle}</option>
                  </select>
                </label>

                <label className="block text-xs text-white/70">
                  {t.length}
                  <select
                    value={answerLength}
                    onChange={(e) =>
                      setAnswerLength(e.target.value as AnswerLength)
                    }
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none focus:border-blue-400/60"
                  >
                    <option value="Kratko">{t.lengthShort}</option>
                    <option value="Srednje">{t.lengthMedium}</option>
                    <option value="Dugačko">{t.lengthLong}</option>
                  </select>
                </label>

                <label className="block text-xs text-white/70">
                  {t.format}
                  <select
                    value={responseFormat}
                    onChange={(e) =>
                      setResponseFormat(e.target.value as ResponseFormat)
                    }
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none focus:border-blue-400/60"
                  >
                    <option value="Slobodno">{t.formatFree}</option>
                    <option value="U 3 koraka">{t.formatThreeSteps}</option>
                    <option value="Kratka vježba">{t.formatExercise}</option>
                    <option value="Pitanja za refleksiju">
                      {t.formatReflection}
                    </option>
                    <option value="Mini plan">{t.formatMiniPlan}</option>
                    <option value="Jedan konkretan zadatak">
                      {t.formatOneTask}
                    </option>
                  </select>
                </label>

                <label className="block text-xs text-white/70">
                  {t.language}
                  <select
                    value={appLanguage}
                    onChange={(e) =>
                      setAppLanguage(e.target.value as AppLanguage)
                    }
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/50 p-2 text-sm text-white outline-none focus:border-blue-400/60"
                  >
                    <option value="Hrvatski">Hrvatski</option>
                    <option value="English">English</option>
                    <option value="Deutsch">Deutsch</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <h2 className="mb-2 text-base font-semibold">
                {t.quickExercises}
              </h2>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {t.quickActions.map((action) => (
                  <button
                    key={action.label}
                    onClick={() => setMessage(action.prompt)}
                    className="rounded-2xl border border-white/10 bg-blue-500/10 p-2 text-left text-xs text-white/85 transition hover:border-blue-300/50 hover:bg-blue-500/20"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}