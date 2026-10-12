"""
Stateless answer generation.

The server no longer stores or retrieves documents. The client does its own
chunking, embedding and vector search on its own machine, and sends only the
handful of chunks it already decided are relevant. This module turns those
chunks plus a question into a grounded English answer.

Nothing here touches disk or a database: the same request from any tenant
produces the same answer, and no document text is retained after the response.

The grounding rules are the ones proven on the server-side pipeline:
  - invented names, numbers and counts are removed
  - a sentence wholly unrelated to the supplied context is removed
  - an answer that does not address the question is refused
"""

import os
import re

from langchain_ollama import OllamaLLM

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAIN_LLM_MODEL = os.getenv("MAIN_LLM_MODEL", "llama3.2:latest")

# How much of a sentence's wording must come from the supplied context.
# 0.65 strict/clipped, 0.40 flowing (default), 0.25 loosest.
GROUNDING_MIN_RATIO = float(os.getenv("GROUNDING_MIN_RATIO", "0.4"))

NOT_IN_CONTEXT = "This information is not available in the provided context."

# The model often refuses in prose instead of emitting NOT_IN_DOCUMENT. Those
# sentences are about the document rather than from it, so the grounding filter
# deletes them - and whatever hedge followed survives as if it were an answer.
# Catch the refusal in the raw output, before filtering.
REFUSAL_PHRASES = (
    "does not mention", "does not specify", "does not contain", "does not state",
    "does not provide", "doesn't mention", "doesn't specify", "doesn't contain",
    "no information about", "no mention of", "not mentioned in", "not specified in",
    "is not available in", "cannot be determined", "unable to determine",
    "there is no information", "no details about",
)

REFUSAL_PATTERN = re.compile(
    r"\bno\s+(?:\w+\s+){0,2}(?:mention|information|details?|reference|record)\s+(?:of|about|on|for)\b"
    r"|\bnot\s+(?:\w+\s+){0,2}(?:mentioned|specified|stated|provided|included|discussed)\b"
)


def is_refusal_text(text: str) -> bool:
    """Whether this sentence says the context lacks the answer."""
    lowered = (text or "").lower()

    return any(phrase in lowered for phrase in REFUSAL_PHRASES) or bool(
        REFUSAL_PATTERN.search(lowered)
    )


# Speculation: the model guessing past the context.
SPECULATION_PHRASES = (
    "could be interpreted", "may be interpreted", "it is possible that",
    "presumably", "it is likely that", "one could assume", "this suggests that",
    "might include", "could include", "may include", "it seems that",
    "appears to suggest", "we can infer", "can be inferred",
)

llm = OllamaLLM(
    model=MAIN_LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    # Low temperature keeps answers close to the context instead of creative.
    temperature=0.2,
)

# A second handle on the same model for query expansion. This version of
# langchain_ollama fixes options at construction, and the defaults are wrong
# for this job: left uncapped the model wrote prose and took 7 seconds, where
# a hard token cap and temperature 0 bring it under 1.
expansion_llm = OllamaLLM(
    model=MAIN_LLM_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=0.0,
    num_predict=48,
    stop=["\n\n", "QUESTION:"],
)


# -----------------------------
# TEXT HELPERS
# -----------------------------
TOPIC_TYPO_FIXES = {
    "developemnt": "development",
    "develoment": "development",
    "devlopment": "development",
    "javscript": "javascript",
    "java script": "javascript",
    "mongo db": "mongodb",
}


def normalize_plain_for_match(text: str) -> str:
    text = (text or "").lower()

    for wrong, right in TOPIC_TYPO_FIXES.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text)

    text = text.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def clean_model_output(text: str) -> str:
    if not text:
        return ""

    cleaned = str(text).strip()

    prefixes = ["Answer:", "Final Answer:", "Output:", "Here is the answer:"]

    for prefix in prefixes:
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()

    cleaned = cleaned.replace("```", "")

    # Small models append notes like "(Translation: ...)" or "(Note: ...)".
    cleaned = re.sub(r"\((?:note|translation|in english)[^)]*\)", "", cleaned, flags=re.IGNORECASE)

    # Labels and headings.
    cleaned = re.sub(
        r"(?im)^\s*(?:\*\*)?(?:definition|explanation|answer)(?:\*\*)?\s*:\s*", "", cleaned
    )

    # Source markers copied out of the context.
    cleaned = re.sub(r"\[?\s*Source\s*\d+\s*\|[^\]]*\]?", "", cleaned, flags=re.IGNORECASE)

    # "According to the context, X is ..." -> "X is ..."
    cleaned = re.sub(
        r"(?i)^\s*(?:according to|as (?:stated|mentioned) in|based on)\s+"
        r"(?:the\s+)?(?:provided\s+)?(?:context|document|text|passage|sources?)\s*,?\s*",
        "",
        cleaned,
        flags=re.MULTILINE,
    )

    # A trailing "..., as stated in the document." is a clause, not a noun.
    # Removing only the noun used to leave the sentence hanging on "as stated
    # in", so the whole clause goes - up to the end of its sentence.
    cleaned = re.sub(
        r"(?i),?\s*\b(?:as|which is|this is)\s+"
        r"(?:clearly\s+|directly\s+|explicitly\s+)?"
        r"(?:stated|mentioned|described|noted|outlined|specified|shown|indicated)\s+"
        r"(?:\w+\s+)?(?:in|by|under)\b[^.!?]*?"
        r"\b(?:context|document|text|passage|sources?|extract|handbook|above|below)\b"
        r"[^.!?]*",
        "",
        cleaned,
    )

    # The same phrase mid-sentence, with the document named explicitly.
    cleaned = re.sub(
        r"(?i)\b(?:according to|as (?:stated|mentioned) in|based on)\s+"
        r"(?:the\s+)?(?:provided\s+)?(?:context|document|text|passage|sources?)\s*,?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\bthe\s+(?:context|document|text|extract)\s+(?:also\s+|further\s+|only\s+)?"
        r"(?:says|states|suggests|mentions|indicates|notes|adds)\s+(?:that\s+)?",
        "",
        cleaned,
    )

    # "within 30 days of the expense.." - the model quoted the context and the
    # trim left its punctuation behind. Two dots only; three is an ellipsis.
    cleaned = re.sub(r"(?<!\.)\.\.(?!\.)", ".", cleaned)

    # A quote mark with no partner is the other half of the same artifact.
    # Balanced quotes are someone's actual words and are left alone.
    if cleaned.count('"') % 2 == 1:
        cleaned = re.sub(r'(?<=[.,;:!?])\s*"', "", cleaned)
        cleaned = re.sub(r'"\s*(?=[.,;:!?])', "", cleaned)

        # Still unbalanced: the stray one is somewhere less obvious, and a
        # lone quote reads worse than none.
        if cleaned.count('"') % 2 == 1:
            cleaned = cleaned.replace('"', "")

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    # Stripping a lead-in like "the document states that" leaves the sentence
    # starting in lower case.
    def capitalize_start(match):
        lead, word = match.group(1), match.group(2)

        # Leave identifiers alone: "nomic-embed-text" and "api_key" are names,
        # not sentences that lost their capital.
        if any(character in word for character in "-_."):
            return lead + word

        return lead + word[0].upper() + word[1:]

    cleaned = re.sub(r"(^|[.!?]\s+)([a-z][\w.\-]*)", capitalize_start, cleaned)

    # Removing a phrase or a source marker mid-sentence leaves its punctuation
    # behind, which reads as ", ." at the end of an otherwise fine sentence.
    cleaned = re.sub(r"\s+([,;:.!?])", r"\1", cleaned)
    cleaned = re.sub(r"[,;:]\s*([.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([.!?])\s*[.;,:]+(?=\s|$)", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned.strip()


STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "how", "to", "in", "on", "about",
    "use", "used", "uses", "why", "who", "when", "where", "of", "this", "that",
    "it", "its", "be", "tell", "show", "give", "explain", "find", "get",
    "describe", "say", "please", "can", "you", "me", "my", "your", "do",
    "does", "did", "and", "or", "for", "with", "from",
}


def get_query_keywords(text: str) -> list:
    """The content words of a question, used to check the answer is on topic."""
    normalized = normalize_plain_for_match(text)
    normalized = re.sub(
        r"\b(what is|what are|how to|how does|tell me about|explain|meaning of)\b",
        " ",
        normalized,
    )

    keywords = []

    for word in re.findall(r"[a-zA-Z0-9]+", normalized):
        if word in STOPWORDS or len(word) < 2:
            continue

        # Treat singular and plural as the same word.
        if word not in {"css", "js"} and word.endswith("s") and len(word) > 4:
            word = word[:-1]

        keywords.append(word)

    return list(dict.fromkeys(keywords))


def word_in_text(word: str, text: str) -> bool:
    # Allow the plural form: the context may say "databases" for "database".
    return bool(re.search(rf"\b{re.escape(word)}(?:s|es)?\b", normalize_plain_for_match(text)))


# -----------------------------
# GROUNDING
# -----------------------------
GROUNDING_COMMON_WORDS = {
    "the", "and", "for", "with", "that", "this", "these", "those", "from",
    "into", "used", "uses", "using", "use", "can", "you", "your", "are",
    "was", "were", "will", "also", "such", "like", "when", "where", "which",
    "what", "how", "why", "who", "its", "it", "is", "of", "to", "in", "on",
    "a", "an", "be", "as", "by", "or", "at", "not", "but", "they", "them",
    "there", "their", "then", "than", "other", "more", "most", "some", "all",
    "it's", "example", "means", "make", "makes", "made", "get", "gets",
    "help", "helps", "need", "needs", "user", "users", "way", "ways",
    "different", "simple", "easy", "important",
    # Linking words a flowing explanation is built from. Without these they
    # look like proper nouns at the start of a sentence and get dropped.
    "specifically", "additionally", "overall", "essentially", "importantly",
    "furthermore", "moreover", "however", "therefore", "finally", "generally",
    "typically", "basically", "ultimately", "instead", "together", "because",
    "although", "while", "since", "both", "each", "every", "meanwhile",
    "consequently", "similarly", "likewise", "rather", "often", "usually",
    "always", "never", "sometimes", "mainly", "mostly",
}

NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "first", "second", "third", "fourth", "fifth",
    "single", "double", "triple", "several", "dozen",
}


def find_unsupported_specifics(sentence: str, context: str) -> list:
    """Names, numbers and counts in a sentence that the context never states."""
    normalized_context = normalize_plain_for_match(context)
    context_words = set(re.findall(r"[a-z0-9.+#]+", normalized_context))

    unsupported = []

    # Counts stated as words are invented as often as digits ("three students"
    # where the context lists four).
    for token in re.findall(r"[A-Za-z]+", sentence):
        if token.lower() in NUMBER_WORDS and token.lower() not in context_words:
            unsupported.append(token)

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#]*|\d[\d,.%]*", sentence)

    for position, token in enumerate(tokens):
        lower = token.lower().strip(".,")

        if not lower or lower in GROUNDING_COMMON_WORDS or lower in context_words:
            continue

        is_number = bool(re.match(r"^\d", lower))

        # A capital at the start of a sentence is grammar, not a name.
        sentence_start = position == 0
        shouted = token.isupper() and len(token) > 1
        has_digit = any(c.isdigit() for c in token)
        is_name_like = has_digit or shouted or (token[:1].isupper() and not sentence_start)

        if not (is_number or is_name_like):
            continue

        if lower in normalized_context:
            continue

        unsupported.append(token)

    return unsupported


def sentence_support_ratio(sentence: str, context_words: set, context: str) -> float:
    words = [
        w for w in re.findall(r"[a-z0-9.+#]+", normalize_plain_for_match(sentence))
        if len(w) >= 4 and w not in GROUNDING_COMMON_WORDS
    ]

    if not words:
        return 1.0

    supported = sum(1 for w in words if w in context_words or w in context)
    return supported / len(words)


# How many words either side of a number count as part of its own phrase
# rather than as the subject it is being attached to.
QUALIFIER_WINDOW = 3

# Units travel with the number they measure, so they are never the subject of
# a sentence. Without this, "within 4 hours during business days" lends its
# "days" to a question about something else entirely and the misattribution
# goes unnoticed.
UNIT_WORDS = {
    "second", "seconds", "minute", "minutes", "hour", "hours", "day", "days",
    "week", "weeks", "month", "months", "year", "years", "working", "business",
    "calendar", "rupee", "rupees", "percent", "page", "pages", "time", "times",
}


# "This is stated directly in the context", "That is specified under the
# leave policy", "It is mentioned above" - a sentence whose subject is a
# demonstrative and whose verb is a reporting verb is commentary on where the
# answer came from, never part of the answer. Matching the shape catches every
# wording of it; matching the wordings never ends.
COMMENTARY_PATTERN = re.compile(
    r"^(?:this|that|it|these|those|the\s+above|the\s+same)\b[^.!?]*?"
    r"\b(?:is|are|was|were|has\s+been|have\s+been)\b[^.!?]*?"
    r"\b(?:stated|specified|mentioned|outlined|described|noted|indicated|"
    r"listed|documented|written|recorded|covered|confirmed|detailed)\b",
    re.IGNORECASE,
)


# "This is because tier one answers within 4 hours." Every word of that is in
# the document; the *because* is not. A sentence that opens by drawing a
# conclusion is the model reasoning, and the one thing this engine must not do
# is pass its reasoning off as the document's.
INFERENCE_PATTERN = re.compile(
    r"^(?:this|that|it|which)\s+(?:is|was)\s+because\b"
    r"|^(?:this|that|which)\s+(?:means|implies|indicates|shows|suggests|"
    r"explains|reflects|confirms)\b"
    r"|^(?:therefore|thus|hence|consequently|as\s+a\s+result|"
    r"in\s+other\s+words|essentially|in\s+essence)\b",
    re.IGNORECASE,
)


def is_commentary(sentence: str) -> bool:
    sentence = (sentence or "").strip()

    return bool(COMMENTARY_PATTERN.match(sentence)) or bool(
        INFERENCE_PATTERN.match(sentence)
    )


def context_sentences(context: str) -> list:
    """The context as individual statements. Each one is a separate rule."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+", context or "")

    return [piece.strip() for piece in pieces if piece.strip()]


def terms_of(text: str) -> list:
    """
    Words, with sentence punctuation removed.

    The trailing dot matters: "days." and "days" are the same word, and
    treating them as different let a unit slip past UNIT_WORDS and vouch for a
    number it had nothing to do with. Dots inside a word ("node.js", "3.5")
    are kept.
    """
    words = re.findall(r"[a-z0-9.+#%]+", normalize_plain_for_match(text))

    return [word.strip(".") for word in words if word.strip(".")]


def content_terms(text: str) -> set:
    return {
        word for word in terms_of(text)
        if len(word) >= 3 and word not in GROUNDING_COMMON_WORDS
    }


def is_number(word: str) -> bool:
    """A number, not merely a word with a digit in it: "sev1" is not a number."""
    return bool(re.match(r"^\d", word))


def misattributed_numbers(sentence: str, statements) -> list:
    """
    Numbers the sentence took from a statement about something else.

    This is the hallucination that word-level grounding cannot see. Given
    "Tier one answers within 4 hours" and "A Sev1 incident pages the on-call
    engineer immediately" in one passage, a small model happily answers that a
    Sev1 incident is paged "within 4 hours during business days". Every word of
    that is in the document. The claim is not.

    So for each number in the answer, the statement that supplies it must also
    be about the same subject: the words around the number are ignored - they
    are the number's own phrase, and get copied along with it - and what is
    left has to overlap the supplying statement.
    """
    words = terms_of(sentence)
    offending = []

    for position, word in enumerate(words):
        if not is_number(word):
            continue

        # The subject of the sentence: everything outside this number's phrase.
        subject = {
            other for index, other in enumerate(words)
            if abs(index - position) > QUALIFIER_WINDOW
            and len(other) >= 3
            and other not in GROUNDING_COMMON_WORDS
            and other not in UNIT_WORDS
            and not is_number(other)
        }

        if not subject:
            # A short sentence ("Annual leave is 30 days.") has nothing
            # outside the window, so use everything in it that is not the
            # number or its unit.
            subject = {
                other for other in words
                if len(other) >= 3
                and other not in GROUNDING_COMMON_WORDS
                and other not in UNIT_WORDS
                and not is_number(other)
            }

        if not subject:
            continue

        sources = [
            statement for statement in statements
            if word in terms_of(statement)
        ]

        if not sources:
            # Not in the context at all - find_unsupported_specifics has this.
            continue

        if not any(
            subject & (content_terms(statement) - UNIT_WORDS)
            for statement in sources
        ):
            offending.append(word)

    return offending


def keep_only_grounded_sentences(answer: str, context: str, min_ratio: float = None) -> str:
    """
    Remove sentences the context does not support, without policing style.

    Invented specifics are always removed. Wording is checked only loosely, so
    the model is free to paraphrase into readable prose - that freedom is what
    makes answers flow, and it is why min_ratio is a setting, not a constant.
    """
    if not answer or not context:
        return ""

    if min_ratio is None:
        min_ratio = GROUNDING_MIN_RATIO

    normalized_context = normalize_plain_for_match(context)
    context_words = set(re.findall(r"[a-z0-9.+#]+", normalized_context))
    statements = context_sentences(context)

    kept = []

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        sentence = sentence.strip()

        if not sentence:
            continue

        lowered_sentence = sentence.lower()

        if any(phrase in lowered_sentence for phrase in SPECULATION_PHRASES):
            print(f"🚫 Dropped - speculation: {sentence[:70]}")
            continue

        if is_commentary(sentence):
            print(f"🚫 Dropped - commentary: {sentence[:70]}")
            continue

        # A hedge like "the context does not provide further details" is
        # dropped on its own. Judging the whole answer by it threw away the
        # correct sentence standing next to it.
        if is_refusal_text(sentence):
            print(f"🚫 Dropped - hedge: {sentence[:70]}")
            continue

        unsupported = find_unsupported_specifics(sentence, context)

        if unsupported:
            print(f"🚫 Dropped - not in context {unsupported[:4]}: {sentence[:70]}")
            continue

        misattributed = misattributed_numbers(sentence, statements)

        if misattributed:
            print(f"🚫 Dropped - number from another rule {misattributed}: {sentence[:70]}")
            continue

        ratio = sentence_support_ratio(sentence, context_words, normalized_context)

        if ratio < min_ratio:
            print(f"🚫 Dropped - only {ratio:.0%} from context: {sentence[:70]}")
            continue

        kept.append(sentence)

    return " ".join(kept).strip()


def answer_addresses_question(question: str, answer: str) -> bool:
    """Catches an answer about a different part of the context than was asked."""
    keywords = get_query_keywords(question)

    if not keywords or not answer:
        return True

    if any(word_in_text(keyword, answer) for keyword in keywords):
        return True

    print(f"🚫 Answer rejected - does not mention {keywords}: {answer[:70]}")
    return False


# -----------------------------
# PROMPTING
# -----------------------------
def get_answer_length_instruction(question: str) -> str:
    lowered = (question or "").lower()

    if any(word in lowered for word in ["short", "brief", "one line", "quick", "in a sentence"]):
        return (
            "ANSWER LENGTH:\n"
            "- Give a short answer, at most 2 sentences.\n"
        )

    if any(word in lowered for word in ["detail", "detailed", "full", "explain", "complete", "deep"]):
        return (
            "ANSWER LENGTH:\n"
            "- Give a thorough, detailed explanation of 6 to 10 sentences.\n"
            "- Walk through it step by step, covering everything the context says.\n"
            "- Write flowing prose, not clipped fragments.\n"
        )

    return (
        "ANSWER LENGTH:\n"
        "- Give a complete, well-explained answer of 4 to 7 sentences.\n"
        "- Direct answer first, then the supporting detail from the context.\n"
        "- Write flowing prose, not clipped fragments or bullet points.\n"
    )


def build_prompt(question: str, context: str) -> str:
    return f"""
You are a document question-answering assistant.

The CONTEXT below was retrieved from the user's own document. Answer the
QUESTION using ONLY this CONTEXT.

GROUNDING RULES (absolute):
- Every fact, name, number, date and technical term must come from the CONTEXT.
- Never add knowledge from outside the CONTEXT, however certain you are of it.
- Never state a count or total unless the CONTEXT states that number.
- Report only what the CONTEXT states. Do not infer, conclude, or combine two
  separate statements into a new claim.
- If the CONTEXT does not actually answer the QUESTION, reply with exactly:
  NOT_IN_DOCUMENT - nothing else. Never guess, never say what the answer
  "could be interpreted as", and never answer a nearby question instead.

WRITING RULES:
- Explain in your own words. You may rephrase, connect and organise the
  CONTEXT's facts into a flowing explanation - you are not limited to copying
  its wording. Rewriting is encouraged; inventing is not.
- Be comprehensive: cover every part of the CONTEXT that bears on the question.
- Write a complete, professional explanation a beginner can follow.
- Never answer in a single sentence unless the QUESTION asks for a short answer.
- Open with one sentence that answers the question directly, then develop it.
- Write as if you know the subject. Never mention the context, the document or
  yourself: no "according to the context", no "the document says".
- Never copy "[Source 2 | Page 4]" markers or page numbers into your answer.
- Never comment on whether something is relevant, useful or worth mentioning.
  Include the detail or leave it out; do not narrate the decision.
- Plain sentences. No headings or labels.

{get_answer_length_instruction(question)}

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:
"""


def build_extractive_prompt(question: str, context: str) -> str:
    return f"""
Answer the QUESTION using ONLY words and phrases copied from the CONTEXT.

RULES:
- Copy the wording from the CONTEXT. You may join or shorten its sentences.
- Do NOT add explanations or vocabulary of your own.
- If the CONTEXT does not answer the QUESTION, reply with exactly: NOT_IN_DOCUMENT

CONTEXT:
{context}

QUESTION:
{question}

ANSWER (context's own words):
"""


def format_context(chunks) -> str:
    """Number the chunks so the model can tell them apart."""
    parts = []

    for index, chunk in enumerate(chunks, start=1):
        text = chunk if isinstance(chunk, str) else (chunk.get("text") or "")
        text = (text or "").strip()

        if not text:
            continue

        if isinstance(chunk, dict) and chunk.get("page"):
            parts.append(f"[Source {index} | Page {chunk['page']}]\n{text}")
        else:
            parts.append(f"[Source {index}]\n{text}")

    return "\n\n".join(parts)


DOCUMENT_WORDS = {
    "document", "documents", "doc", "docs", "pdf", "file", "report",
    "handbook", "guide", "paper", "book",
}

OVERVIEW_WORDS = {
    "summary", "summarize", "summarise", "overview", "about", "explain",
    "content", "contents", "describe", "gist", "brief", "topic", "topics",
    "what",
}


def is_document_level_question(question: str) -> bool:
    """
    True for "summarize this pdf", "what is this document about" and similar:
    questions about the document as a whole rather than one topic inside it.

    They need their own prompt. The normal one tells the model to answer one
    exact thing and not to range beyond it, which is the opposite of a summary,
    so it used to reply NOT_IN_DOCUMENT and the question looked unanswerable.
    """
    words = set(re.findall(r"[a-z]+", (question or "").lower()))

    if {"summary", "summarize", "summarise", "overview"} & words:
        return True

    return bool(words & DOCUMENT_WORDS) and bool(words & OVERVIEW_WORDS)


def build_summary_prompt(context: str) -> str:
    return f"""
The DOCUMENT EXTRACT below comes from a document the user uploaded.

Say what this document is about, in 3 to 6 short sentences.

RULES:
- Use ONLY what is in the DOCUMENT EXTRACT.
- Reuse its own words, names and terms. Do not introduce outside vocabulary.
- Do NOT invent facts, numbers or names that are not in the extract.
- Do NOT describe the extract itself ("this text contains..."). Describe the
  document's subject and main points.
- Plain sentences. No headings, labels or bullet markers.

DOCUMENT EXTRACT:
{context}

WHAT THIS DOCUMENT IS ABOUT:
"""


# A summary restates a whole document in a few lines, so little of its wording
# matches any single passage. Invented names and numbers are still blocked by
# the specifics check, which is the part that actually prevents hallucination.
SUMMARY_MIN_RATIO = 0.25


def summarize_context(context: str) -> dict:
    answer = clean_model_output(llm.invoke(build_summary_prompt(context)))

    if not answer or "NOT_IN_DOCUMENT" in answer.upper():
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    grounded = keep_only_grounded_sentences(
        answer, context, min_ratio=SUMMARY_MIN_RATIO
    )

    if not grounded:
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    return {"answer": grounded, "grounded": True}


DEFINITION_PATTERN = re.compile(
    r"^\s*(?:what\s+(?:is|are|was|were)|what(?:'s|s)|define|explain|describe|"
    r"tell\s+me\s+about|meaning\s+of)\s+(.{2,80})$",
    re.IGNORECASE,
)

DEFINITION_FILLER = {
    "the", "a", "an", "this", "that", "these", "those", "its", "their", "our",
    "mean", "means", "meaning", "about", "exactly", "actually", "document",
    "documents", "doc", "pdf", "file", "text", "page",
}


def definition_subject(question: str) -> list:
    """
    The thing a definitional question asks to have defined.

    "what is quantum computing" -> ["quantum", "computing"]. Returns [] for
    anything that is not asking for a definition.
    """
    match = DEFINITION_PATTERN.match((question or "").strip().rstrip("?"))

    if not match:
        return []

    words = re.findall(r"[a-z0-9.+#]+", normalize_plain_for_match(match.group(1)))

    return [
        word for word in words
        if len(word) > 2
        and word not in DEFINITION_FILLER
        and word not in GROUNDING_COMMON_WORDS
    ]


# Structural nouns that appear in almost any business document. A question
# about "the offside rule in football" matching on "rule" tells you nothing
# about whether the document covers football, so these do not count as
# evidence that the subject is present.
GENERIC_SUBJECT_WORDS = {
    "rule", "rules", "policy", "policies", "price", "prices", "cost", "costs",
    "process", "processes", "procedure", "procedures", "section", "sections",
    "list", "type", "types", "kind", "detail", "details", "requirement",
    "requirements", "term", "terms", "limit", "limits", "amount", "value",
    "number", "name", "date", "time", "today", "work", "system", "service",
}


def subject_is_absent(question: str, context: str) -> bool:
    """
    True when a definitional question names something the context never does.

    "What is X" can only be answered by a passage that mentions X. Asked about
    something absent, a small model will take any passage and prefix it -
    "This type of computing is built for the AI/automation tool layer" for a
    document that has never heard of quantum computing. Every word of that is
    from the document, so the grounding checks pass it, and the answer echoes
    "computing" from the question, so the relevance check passes it too.

    This is checked before generating rather than after, because the cheapest
    way to not hallucinate an answer is to not ask for one.

    Only definitional questions go through here. "How much holiday am I
    entitled to" names nothing that has to appear in the text - its answer is
    "21 days of paid annual leave" - and would be wrongly refused by this rule.
    """
    subject = definition_subject(question)

    if not subject:
        return False

    haystack = normalize_plain_for_match(context)

    # The distinctive half of the subject is what has to be there. Asking
    # about "the offside rule" and finding "rules" in a security policy is not
    # a match; asking about "the training budget" and finding "training" is.
    distinctive = [term for term in subject if term not in GENERIC_SUBJECT_WORDS]

    # A subject made only of generic words ("what is the policy") has nothing
    # distinctive to demand, so any of its words will do.
    required = distinctive or subject

    for term in required:
        root = term[:-1] if len(term) > 4 and term.endswith("s") else term

        if root in haystack:
            return False

    return True


EXPANSION_PROMPT = """List words a document would use to answer this question.
Reply with 6 to 10 comma-separated words only. No sentences, no explanation.

QUESTION: {question}
WORDS:"""

# Long enough for ten words, short enough that the model cannot wander into
# prose - the whole value of this call is that it stays cheap.
EXPANSION_TOKENS = 48

EXPANSION_STOP = {
    "question", "words", "answer", "document", "none", "n/a",
}


def expand_query(question: str) -> list:
    """
    Words a document answering this question might use.

    Measured on a 40-page manual, this makes retrieval worse when it replaces
    the question (15 of 18 answers found, against 18 of 18 without it): a 3B
    model does not know the document, so "when are appraisals" comes back as
    property valuation and "nightly hotel limit" as room occupancy. It is
    useful only as extra terms fused beside the original query, never instead
    of it - see KRISH_QUERY_EXPANSION in client_gateway.py.
    """
    question = (question or "").strip()

    if not question:
        return []

    raw = expansion_llm.invoke(EXPANSION_PROMPT.format(question=question))

    terms = []

    for piece in re.split(r"[,\n;]+", clean_model_output(raw)):
        term = piece.strip(" .:-\"'").lower()

        # Drop anything that came back as a sentence rather than a term.
        if not term or len(term.split()) > 3 or term in EXPANSION_STOP:
            continue

        if term not in terms:
            terms.append(term)

    return terms[:10]


def answer_from_context(question: str, chunks, min_ratio: float = None) -> dict:
    """
    Generate a grounded answer from client-supplied context.

    Returns the answer plus whether it was grounded, so the caller can tell a
    real answer from a refusal without string matching.
    """
    question = (question or "").strip()
    context = format_context(chunks)

    if not question:
        return {"answer": "No question was provided.", "grounded": False}

    if not context.strip():
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    if is_document_level_question(question):
        return summarize_context(context)

    if subject_is_absent(question, context):
        print(f"🚫 Refused before generating - subject not in context: {question[:60]}")
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    answer = clean_model_output(llm.invoke(build_prompt(question, context)))

    if not answer or "NOT_IN_DOCUMENT" in answer.upper():
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    grounded = keep_only_grounded_sentences(answer, context, min_ratio=min_ratio)

    # A surviving fragment is not an answer: ask once more, extractively.
    if not grounded or len(grounded.split()) < 6:
        retry = clean_model_output(llm.invoke(build_extractive_prompt(question, context)))

        if retry and "NOT_IN_DOCUMENT" not in retry.upper():
            extracted = keep_only_grounded_sentences(retry, context, min_ratio=min_ratio)

            if len(extracted.split()) > len(grounded.split()):
                grounded = extracted

    if not grounded:
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    if not answer_addresses_question(question, grounded):
        return {"answer": NOT_IN_CONTEXT, "grounded": False}

    return {"answer": grounded, "grounded": True}
