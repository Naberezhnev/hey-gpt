"""Read an optional GPT-written briefing; conservative local fallback, no API."""
from dataclasses import dataclass
import re

VOICE_INSTRUCTION = (
    "Режим Hey GPT: после основного ответа добавь отдельный раздел «Голосовая сводка» "
    "с итогом в 1–2 предложениях, не более 40 слов: что сделано, результат, ошибки и что осталось. "
    "Не объявляй действие выполненным без подтверждения. Если ждёшь моего ответа, добавь раздел "
    "«Вопросы к тебе»: перечисли все вопросы и необходимые варианты выбора полностью. "
    "Нумеруй только вопросы; варианты выбора обозначай буквами. "
    "Если вопросов нет, этот раздел не добавляй. Это формат ответа, не дополнительная задача."
)


def with_voice_instruction(text):
    return text if VOICE_INSTRUCTION in text else text.rstrip() + "\n\n" + VOICE_INSTRUCTION


def plain(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^\n)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "ссылка в чате", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*|[-*•]\s+|>\s*)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"[ \t]+", " ", text).strip()


@dataclass(frozen=True)
class Briefing:
    summary: str
    questions: tuple[str, ...] = ()
    generated_by_gpt: bool = False

    @property
    def spoken(self):
        parts = [self.summary] if self.summary else []
        if self.questions:
            parts.append("Требуется твой ответ.")
            parts.extend((f"Вопрос {index}. " if len(self.questions) > 1 else "") + question
                         for index, question in enumerate(self.questions, 1))
        return "\n".join(parts)


def _sections(text):
    result = {}
    current = None
    for line in text.splitlines():
        heading = line.strip().strip("#* _:").casefold()
        if heading in ("голосовая сводка", "voice summary"):
            current = "summary"
            result[current] = []
        elif heading in ("вопросы к тебе", "questions for you"):
            current = "questions"
            result[current] = []
        elif current:
            result[current].append(line)
    return {name: plain("\n".join(lines)) for name, lines in result.items()}


def _questions(text, explicit=False):
    if not text or text.casefold().rstrip(".! ") in ("нет", "нет вопросов", "вопросов нет", "none", "no questions"):
        return ()
    if explicit:
        # Numbered questions retain all following option lines in their group.
        groups = re.split(r"(?m)^\s*\d+[.)]\s+", text)
        return tuple(group.strip() for group in groups if group.strip())
    lines = text.splitlines()
    groups = []
    for index, line in enumerate(lines):
        if "?" not in line:
            continue
        # Keep the whole question paragraph and immediately following choices.
        beginning = index
        while beginning > 0 and lines[beginning - 1].strip() and "?" not in lines[beginning - 1]:
            beginning -= 1
        group = [value.strip() for value in lines[beginning:index + 1]]
        for following in lines[index + 1:]:
            if not following.strip() or "?" in following:
                break
            group.append(following.strip())
        value = plain("\n".join(group))
        if value not in groups:
            groups.append(value)
    return tuple(groups)


def make_briefing(response):
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Не удалось прочитать текст последнего ответа.")
    sections = _sections(response)
    body = re.split(r"(?im)^\s*[#* _]*голосовая сводка[* _:]*\s*$", response)[0]
    questions = _questions(sections.get("questions", ""), explicit=True)
    # Questions outside the optional section must not disappear from the readout.
    for question in _questions(re.sub(r"```.*?```", "", body, flags=re.S)):
        if not any(question in existing or existing in question for existing in questions):
            questions += (question,)
    summary = sections.get("summary", "")
    if summary:
        if len(summary.split()) > 40:
            summary = " ".join(summary.split()[:40]) + ". Сводка сокращена; полный текст в чате."
        return Briefing(summary, questions, True)
    cleaned = plain(response)
    paragraphs = [line.strip() for line in cleaned.splitlines() if line.strip() and "?" not in line]
    candidates = re.split(r"(?<=[.!])\s+(?=[A-ZА-ЯЁ])", " ".join(paragraphs))
    important = re.compile(r"не удалось|не выполн|не провер|не прош|ошибк|осталось|требуется|failed|error|not tested|remaining", re.I)
    chosen = [sentence for sentence in candidates if important.search(sentence)]
    for sentence in candidates[:2]:
        if sentence not in chosen:
            chosen.append(sentence)
    fragment = " ".join(chosen)
    if len(fragment) > 600:
        fragment = fragment[:600].rsplit(" ", 1)[0] + ". Полный текст в чате."
    summary = "Краткий фрагмент ответа. " + fragment if fragment else "В чате есть вопрос."
    return Briefing(summary, questions)
