"""Local multi-model debate table orchestrator for Ollama."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
import os
import random
import re
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from debate import argument_memory, prompt_contract
from debate import turn_completion as tc
from debate.output_guard import OutputGuard
from debate.sentence_buffer import SentenceBuffer


ROOT = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", ROOT / "config.json")).resolve()

DEFAULTS = {
    "ollama_url": "http://127.0.0.1:11434",
    "port": 8700,
    "topic_rotate_turns": 24,
    "anchor_every_turns": 10,
    "turn_delay_ms": 1500,
    "context_turns": 8,
    "min_turn_chars": 120,
    "num_predict": 320,
    "temperature": 0.7,
    "top_p": 0.9,
    "insight_panel": False,
    "extractor_model": "dolphin-llama3:8b",
    "insight_timeout_seconds": 10,
    "insight_queue_max": 2,
    "empty_spoken_retry_count": 1,
    "repetition_overlap_threshold": 0.60,
    "repetition_min_tokens": 20,
    "turn_word_min": 110,
    "turn_word_max": 160,
    "consensus_window_turns": 4,
    "consensus_challenge_weight": 3.0,
}


def _valid_number(value, default, minimum, maximum, integer=False):
    if isinstance(value, bool):
        return default
    try:
        converted = int(value) if integer else float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not minimum <= converted <= maximum:
        return default
    return converted


def atomic_write_json(path: Path, document: dict) -> None:
    data = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def load_config(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            document = {}
    except (OSError, json.JSONDecodeError):
        document = {}
    normalized = dict(document)
    for key, default in DEFAULTS.items():
        normalized.setdefault(key, default)

    numeric_rules = {
        "port": (1, 65535, True),
        "topic_rotate_turns": (0, 10000, True),
        "anchor_every_turns": (0, 10000, True),
        "turn_delay_ms": (0, 60000, True),
        "context_turns": (1, 100, True),
        "min_turn_chars": (0, 10000, True),
        "num_predict": (32, 8192, True),
        "temperature": (0, 2, False),
        "top_p": (0.01, 1, False),
        "insight_timeout_seconds": (1, 120, False),
        "insight_queue_max": (1, 100, True),
        "empty_spoken_retry_count": (0, 3, True),
        "repetition_overlap_threshold": (0, 1, False),
        "repetition_min_tokens": (1, 1000, True),
        "turn_word_min": (20, 2000, True),
        "turn_word_max": (20, 4000, True),
        "consensus_window_turns": (1, 100, True),
        "consensus_challenge_weight": (1, 20, False),
    }
    for key, (minimum, maximum, integer) in numeric_rules.items():
        normalized[key] = _valid_number(
            normalized.get(key), DEFAULTS[key], minimum, maximum, integer
        )
    if not isinstance(normalized.get("insight_panel"), bool):
        normalized["insight_panel"] = False
    for key in ("ollama_url", "extractor_model"):
        if not isinstance(normalized.get(key), str) or not normalized[key].strip():
            normalized[key] = DEFAULTS[key]

    seats = normalized.get("seats")
    if not isinstance(seats, list):
        seats = []
    valid_seats = []
    for index, seat in enumerate(seats[:4]):
        if not isinstance(seat, dict):
            continue
        name = str(seat.get("name", f"Seat {index + 1}")).strip()
        model = str(seat.get("model", "")).strip()
        persona = str(seat.get("persona", "A careful, direct debater.")).strip()
        color = str(seat.get("color", "#7dd3fc")).strip()
        thesis = str(seat.get("thesis", "")).strip()
        if name and model:
            valid_seats.append(
                {
                    "name": name,
                    "model": model,
                    "persona": persona,
                    "color": color,
                    "thesis": thesis,
                }
            )
    if len(valid_seats) < 2:
        valid_seats = [
            {
                "name": "Neo",
                "model": "qwen3:14b",
                "color": "#4fd1ff",
                "persona": "A constructive systems thinker who concedes clean hits.",
                "thesis": "",
            },
            {
                "name": "Clue",
                "model": "dolphin-llama3:8b",
                "color": "#7dffa0",
                "persona": "A skeptical challenger who demands concrete stakes.",
                "thesis": "",
            },
        ]
    normalized["seats"] = valid_seats
    if normalized != document:
        atomic_write_json(path, normalized)
    return normalized


CONFIG = load_config(CONFIG_PATH)
OLLAMA = os.environ.get("OLLAMA_URL", CONFIG["ollama_url"]).rstrip("/")
SEATS = CONFIG["seats"][:4]
TOPIC_ROTATE_TURNS = CONFIG["topic_rotate_turns"]
ANCHOR_EVERY_TURNS = CONFIG["anchor_every_turns"]
TURN_DELAY_S = CONFIG["turn_delay_ms"] / 1000.0
CONTEXT_TURNS = CONFIG["context_turns"]
GEN_OPTIONS = {
    "num_predict": CONFIG["num_predict"],
    "temperature": CONFIG["temperature"],
    "top_p": CONFIG["top_p"],
}

argument_memory_tracker = argument_memory.ArgumentMemory(
    [seat["name"] for seat in SEATS]
)

LABEL_TOPIC = "TOPIC:"
LABEL_ANCHOR = "CONTINUITY ANCHOR:"
LABEL_TRANSCRIPT = "RECENT TABLE TRANSCRIPT:"
LABEL_OPERATOR_NOTE = "OPERATOR NOTE:"
LABEL_MOVE = "YOUR MOVE:"
LABEL_RECENT_ARGUMENTS = "YOUR RECENT ARGUMENTS:"
TURN_PROMPT_LABELS = (
    LABEL_TOPIC,
    LABEL_ANCHOR,
    LABEL_TRANSCRIPT,
    LABEL_OPERATOR_NOTE,
    LABEL_MOVE,
    LABEL_RECENT_ARGUMENTS,
)

TURN_WORD_MIN = int(CONFIG["turn_word_min"])
TURN_WORD_MAX = int(CONFIG["turn_word_max"])
PUBLIC_TITLE_MAX_CHARS = 300
DEBATE_BRIEF_MAX_CHARS = 20000

MOVE_TEXT = {
    "challenge": "Test the strongest prior claim. State what evidence or logic would overturn it; do not invent disagreement.",
    "concur-extend": "Concede the best prior point explicitly, then extend it into new ground.",
    "analyze": "Analyze exactly where the positions at the table diverge and why it matters.",
    "cross-examine": "Ask one sharp directed question, then give your provisional answer.",
    "reframe": "Show why the current framing is incomplete and offer a more useful frame.",
    "evidence": "Supply or demand a concrete example, case, or thought experiment.",
    "synthesize": "Synthesize compatible claims, then identify what remains unresolved.",
    "escalate": "Trace the current claim to its hardest logical consequence.",
    "answer-then-advance": "Answer the directed question plainly first, then advance the debate with one new implication.",
}
MOVE_WEIGHTS = {
    "challenge": 3.0,
    "concur-extend": 2.0,
    "analyze": 2.0,
    "cross-examine": 2.0,
    "reframe": 1.0,
    "evidence": 2.0,
    "synthesize": 1.0,
    "escalate": 1.0,
}
DISAGREEMENT_MARKERS = (
    "disagree",
    "however",
    "counterpoint",
    "incorrect",
    "doubt",
    "but",
    "what evidence",
    "i reject",
    "not convinced",
    "challenge",
    "on the contrary",
    "fails because",
)
INTERROGATIVE_WORDS = (
    "why",
    "how",
    "what",
    "when",
    "where",
    "which",
    "who",
    "would",
    "could",
    "can",
    "do",
    "does",
    "is",
    "are",
    "should",
)

TOPIC_DOMAINS = [
    "philosophy of mind",
    "ethics",
    "AI futures",
    "cosmology",
    "evolutionary biology",
    "economics",
    "game theory",
    "language and meaning",
    "consciousness",
    "political philosophy",
    "engineering trade-offs",
    "information theory",
    "epistemology",
    "complex systems",
    "human flourishing",
]
FALLBACK_TOPICS = [
    "Is intelligence better measured by what it builds or what it refuses to build?",
    "Can meaning be defined operationally without destroying it?",
    "Does compression explain understanding, or merely imitate it?",
    "What would a good post-human future actually optimize?",
    "Is disagreement between honest reasoners evidence that truth is plural?",
    "Does free will survive contact with good enough prediction?",
]


def speech_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def repetition_overlap(previous: str, current: str, minimum: int) -> float:
    prior_tokens = speech_tokens(previous)
    current_tokens = speech_tokens(current)
    if len(prior_tokens) < minimum or len(current_tokens) < minimum:
        return 0.0
    union = prior_tokens | current_tokens
    return len(prior_tokens & current_tokens) / len(union) if union else 0.0


def disagreement_present(turns: list[dict]) -> bool:
    joined = " ".join(turn.get("text", "") for turn in turns).lower()
    return any(marker in joined for marker in DISAGREEMENT_MARKERS)


def detect_directed_questions(text: str, speaker: str, seat_names: list[str]) -> set[str]:
    """Find explicit questions directed to another named seat."""
    found = set()
    clauses = re.split(r"(?<=[.!?])\s+|\n+", text)
    for target in seat_names:
        if target == speaker:
            continue
        target_pattern = re.compile(rf"\b{re.escape(target)}\b", re.I)
        for clause in clauses:
            if not target_pattern.search(clause):
                continue
            has_question_mark = "?" in clause
            has_interrogative = re.search(
                rf"\b(?:{'|'.join(INTERROGATIVE_WORDS)})\b", clause, re.I
            )
            if has_question_mark or has_interrogative:
                found.add(target)
                break
    return found


class State:
    def __init__(self):
        self.topic = ""  # debate_brief: drawer + model prompt context (§6)
        self.public_title = ""  # stage-only caption, separate from topic/brief (§6)
        self.topic_epoch = 0
        self.turn = 0
        self.anchor = ""
        self.transcript: list[dict] = []
        self.paused = False
        self.interject: str | None = None
        self.pending_topic: dict | None = None
        self.speaker_idx = 0
        self.last_move: str | None = None
        self.status = "starting"
        self.interrupt_generation = asyncio.Event()
        self.pending_questions: dict[str, deque[str]] = {
            seat["name"]: deque() for seat in SEATS
        }
        self.previous_public: dict[str, str] = {}
        self.repetition_pending: float | None = None
        self.repetition_alternator = False
        self.pending_reframe: dict[str, str] = {}
        self.recent_turns: deque[dict] = deque(
            maxlen=int(CONFIG["consensus_window_turns"])
        )
        self.last_move_reason = ""
        self.last_move_turn = 0
        self.generation_active = False
        self.shutting_down = False

    def reset_debate_state(self):
        self.pending_questions = {seat["name"]: deque() for seat in SEATS}
        self.previous_public = {}
        self.repetition_pending = None
        self.repetition_alternator = False
        self.pending_reframe = {}
        self.recent_turns.clear()
        self.last_move = None
        self.last_move_reason = ""
        self.last_move_turn = 0

    def observe_public_turn(self, speaker: str, text: str):
        for target in detect_directed_questions(
            text, speaker, [seat["name"] for seat in SEATS]
        ):
            self.pending_questions[target].append(speaker)
        previous = self.previous_public.get(speaker, "")
        overlap = repetition_overlap(
            previous, text, int(CONFIG["repetition_min_tokens"])
        )
        self.previous_public[speaker] = text
        if overlap >= float(CONFIG["repetition_overlap_threshold"]):
            self.repetition_pending = overlap
        self.recent_turns.append({"name": speaker, "text": text})


state = State()


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def send(self, event: dict):
        message = json.dumps(event, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_text(message)
            except Exception:
                self.clients.discard(ws)


hub = Hub()
seat_mutation_lock = asyncio.Lock()


class TurnInterrupted(Exception):
    """An operator action intentionally abandoned an in-flight generation."""


class PublicStreamFilter:
    """Incrementally remove hidden-reasoning regions before any broadcast."""

    OPEN_TAGS = ("<think>", "<analysis>", "<reasoning>")
    CLOSE_TAGS = ("</think>", "</analysis>", "</reasoning>")

    def __init__(self):
        self.buffer = ""
        self.hidden_tag: str | None = None

    def feed(self, fragment: str, final: bool = False) -> str:
        self.buffer += fragment
        output = []
        while self.buffer:
            lower = self.buffer.lower()
            if self.hidden_tag:
                close = f"</{self.hidden_tag}>"
                index = lower.find(close)
                if index < 0:
                    keep = max(len(close) - 1, 0)
                    self.buffer = self.buffer[-keep:] if keep else ""
                    break
                self.buffer = self.buffer[index + len(close) :]
                self.hidden_tag = None
                continue

            positions = [
                (lower.find(tag), tag)
                for tag in self.OPEN_TAGS
                if lower.find(tag) >= 0
            ]
            if positions:
                index, tag = min(positions, key=lambda item: item[0])
                output.append(self.buffer[:index])
                self.buffer = self.buffer[index + len(tag) :]
                self.hidden_tag = tag[1:-1]
                continue

            if final:
                output.append(self.buffer)
                self.buffer = ""
                break
            keep = 0
            for tag in self.OPEN_TAGS:
                for length in range(1, min(len(tag), len(lower)) + 1):
                    if lower.endswith(tag[:length]):
                        keep = max(keep, length)
            if keep:
                output.append(self.buffer[:-keep])
                self.buffer = self.buffer[-keep:]
            else:
                output.append(self.buffer)
                self.buffer = ""
            break
        return "".join(output)


def _clean_prefix_pattern() -> re.Pattern:
    # Narrowed on purpose (§4.4 of the v1.1 directive): the old pattern
    # stripped ANY leading "Word:", destroying legitimate openings like
    # "In short: ..." or "Fact: ...". This only matches the known control
    # labels (derived from turn_prompt, not hand-duplicated) and seat names.
    names = [label.rstrip(":") for label in TURN_PROMPT_LABELS]
    names += [seat["name"] for seat in SEATS]
    alternatives = "|".join(re.escape(name) for name in names if name)
    if not alternatives:
        return re.compile(r"(?!x)x")  # matches nothing
    return re.compile(rf"^\s*(?:\*\*)?(?:{alternatives})\s*:\s*", re.I)


def clean(text: str) -> str:
    text = re.sub(
        r"<(?:think|analysis|reasoning)>.*?</(?:think|analysis|reasoning)>",
        "",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"</?(?:think|analysis|reasoning)>", "", text, flags=re.I)
    text = _clean_prefix_pattern().sub("", text.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def ollama_chat(
    model: str,
    messages: list,
    on_public: Callable[[str], Awaitable[None]] | None = None,
    interruptible: bool = False,
    metrics: dict | None = None,
) -> str:
    started_at = time.monotonic()
    if metrics is not None:
        metrics.update(
            {
                "first_raw_seconds": None,
                "first_public_seconds": None,
                "duration_seconds": None,
                "hidden_reasoning_present": False,
                "budget_exhausted": False,
                "eval_count": None,
                "prompt_eval_count": None,
            }
        )
    payload = {
        "model": model,
        "messages": messages,
        "stream": on_public is not None,
        "options": GEN_OPTIONS,
    }
    timeout = httpx.Timeout(600.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if on_public is None:
            response = await client.post(f"{OLLAMA}/api/chat", json=payload)
            response.raise_for_status()
            return clean(response.json().get("message", {}).get("content", ""))

        public_parts = []
        filter_ = PublicStreamFilter()
        async with client.stream("POST", f"{OLLAMA}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if interruptible and state.interrupt_generation.is_set():
                    raise TurnInterrupted
                if not line.strip():
                    continue
                data = json.loads(line)
                message = data.get("message", {})
                raw = message.get("content", "")
                thinking = message.get("thinking", "")
                if metrics is not None:
                    if metrics["first_raw_seconds"] is None and (raw or thinking):
                        metrics["first_raw_seconds"] = time.monotonic() - started_at
                    if thinking or re.search(
                        r"<(?:think|analysis|reasoning)>", raw, re.I
                    ):
                        metrics["hidden_reasoning_present"] = True
                # Ollama's separate `thinking` field is intentionally ignored.
                public = filter_.feed(raw)
                if public:
                    if (
                        metrics is not None
                        and metrics["first_public_seconds"] is None
                    ):
                        metrics["first_public_seconds"] = time.monotonic() - started_at
                    public_parts.append(public)
                    await on_public(public)
                if data.get("done"):
                    if metrics is not None:
                        metrics["budget_exhausted"] = (
                            data.get("done_reason") == "length"
                        )
                        metrics["eval_count"] = data.get("eval_count")
                        metrics["prompt_eval_count"] = data.get("prompt_eval_count")
                    tail = filter_.feed("", final=True)
                    if tail:
                        if (
                            metrics is not None
                            and metrics["first_public_seconds"] is None
                        ):
                            metrics["first_public_seconds"] = (
                                time.monotonic() - started_at
                            )
                        public_parts.append(tail)
                        await on_public(tail)
                    break
        if metrics is not None:
            metrics["duration_seconds"] = time.monotonic() - started_at
        return clean("".join(public_parts))


async def installed_models() -> list[str]:
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{OLLAMA}/api/tags")
        response.raise_for_status()
    return sorted(
        {
            item["name"]
            for item in response.json().get("models", [])
            if item.get("name")
        }
    )


def public_seats() -> list[dict]:
    return [
        {"name": seat["name"], "model": seat["model"], "color": seat["color"]}
        for seat in SEATS
    ]


def persist_seat_model(seat_name: str, model: str) -> None:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    target = next(
        (
            seat
            for seat in document.get("seats", [])
            if seat.get("name") == seat_name
        ),
        None,
    )
    if target is None:
        raise ValueError("seat is missing from persisted configuration")
    target["model"] = model
    atomic_write_json(CONFIG_PATH, document)


def persist_seat_thesis(seat_name: str, thesis: str) -> None:
    document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    target = next(
        (
            seat
            for seat in document.get("seats", [])
            if seat.get("name") == seat_name
        ),
        None,
    )
    if target is None:
        raise ValueError("seat is missing from persisted configuration")
    target["thesis"] = thesis
    atomic_write_json(CONFIG_PATH, document)


def other_names(seat: dict) -> str:
    return " and ".join(
        candidate["name"] for candidate in SEATS if candidate["name"] != seat["name"]
    )


def system_prompt(seat: dict) -> str:
    thesis = str(seat.get("thesis", "")).strip()
    thesis_block = (
        f"Your thesis (durable; a tactical move may change every turn but "
        f"your thesis normally may not -- you may concede a subsidiary "
        f"point without abandoning it): {thesis}\n"
        if thesis
        else ""
    )
    return (
        f"You are {seat['name']}, one of {len(SEATS)} panelists at a live debate "
        f"table. The other panelist(s): {other_names(seat)}.\n"
        f"Your persona: {seat['persona']}\n"
        f"{thesis_block}"
        "Address other panelists directly by name when engaging them, but never "
        "in sentence 1. Use 4 to 8 sentences of "
        "plain prose with no lists, headings, stage directions, or meta-commentary. "
        "Engage a specific prior point and advance the discussion. Stay in character.\n"
        f"{prompt_contract.contract_instructions(TURN_WORD_MIN, TURN_WORD_MAX)}\n"
        "The user message below has two sections. PRIVATE CONTROL is an "
        "instruction to you, never dialogue: never quote, paraphrase, or "
        "restate a control label or its text. PUBLIC CONTEXT is background "
        "only. Output nothing but your own spoken contribution -- begin "
        "directly with public speech, with no label, heading, or prefix of "
        "any kind."
    )


def turn_prompt(
    seat: dict,
    move_text: str,
    interject: str | None,
    recent_arguments: list[str] | None = None,
) -> str:
    control_lines = [f"{LABEL_MOVE} {move_text}"]
    if interject:
        control_lines += [f"{LABEL_OPERATOR_NOTE} {interject}"]
    if recent_arguments:
        control_lines += [
            f"{LABEL_RECENT_ARGUMENTS} {'; '.join(recent_arguments)} "
            "-- do not reuse these unless directly rebutting a new challenge."
        ]

    context_lines = [f"{LABEL_TOPIC} {state.topic}"]
    if state.anchor:
        context_lines += ["", LABEL_ANCHOR, state.anchor]
    if state.transcript:
        context_lines += ["", LABEL_TRANSCRIPT]
        context_lines.extend(
            f"{turn['name']}: {turn['text']}"
            for turn in state.transcript[-CONTEXT_TURNS:]
        )
    else:
        context_lines += ["", "The table is silent. Open the discussion."]

    lines = [
        "PRIVATE CONTROL (instruction only -- never quote, paraphrase, or "
        "restate any label or text in this section; it is not dialogue):",
        *control_lines,
        "",
        "PUBLIC CONTEXT (background for your response; do not restate these "
        "labels):",
        *context_lines,
        "",
        f"Speak now as {seat['name']}. Begin directly with your public speech.",
    ]
    return "\n".join(lines)


def turn_prompt_dynamic_values(move_text: str, interject: str | None) -> list[str]:
    """The per-turn control values that must also be blocked if a model
    echoes them verbatim without their label (see debate/output_guard.py)."""
    values = [move_text]
    if interject:
        values.append(interject)
    return values


def _weighted_choice(weights: dict[str, float]) -> str:
    total = sum(weights.values())
    point = random.uniform(0, total)
    for key, weight in weights.items():
        point -= weight
        if point <= 0:
            return key
    return next(reversed(weights))


def pick_move(seat: dict, turn_id: int) -> tuple[str, str, str]:
    pending = state.pending_questions.get(seat["name"])
    if pending:
        source = pending.popleft()
        key = "answer-then-advance"
        reason = f"directed_question_from:{source}"
    elif seat["name"] in state.pending_reframe:
        concept = state.pending_reframe.pop(seat["name"])
        key = "reframe"
        reason = f"repeated_argument:{concept}"
    elif state.repetition_pending is not None:
        key = "challenge" if state.repetition_alternator else "reframe"
        state.repetition_alternator = not state.repetition_alternator
        reason = f"self_repetition_overlap:{state.repetition_pending:.2f}"
        state.repetition_pending = None
    else:
        window = int(CONFIG["consensus_window_turns"])
        consensus = (
            len(state.recent_turns) >= window
            and not disagreement_present(list(state.recent_turns)[-window:])
        )
        weights = dict(MOVE_WEIGHTS)
        if consensus:
            multiplier = float(CONFIG["consensus_challenge_weight"])
            weights["challenge"] *= multiplier
            weights["cross-examine"] *= multiplier
            reason = f"consensus_breaker:no_disagreement_in_{window}_turns"
        else:
            reason = "weighted_fallback"
        if state.last_move in weights and len(weights) > 1:
            weights.pop(state.last_move)
        key = _weighted_choice(weights)
    state.last_move = key
    state.last_move_reason = reason
    state.last_move_turn = turn_id
    return key, MOVE_TEXT[key], reason


async def generate_topic(seed: str) -> str:
    first, second = random.sample(TOPIC_DOMAINS, 2)
    prompt = (
        "Return one provocative debate question under 25 words, and nothing else. "
        f"Combine {first} with {second}. Avoid factual lookup."
        + (f" Avoid resembling: {seed}" if seed else "")
    )
    try:
        output = await ollama_chat(
            SEATS[0]["model"], [{"role": "user", "content": prompt}]
        )
        output = output.splitlines()[0].strip().strip('"')
        if 10 <= len(output) <= 300:
            return output
    except Exception:
        await hub.send({"type": "status", "text": "Topic generator unavailable; using fallback."})
    choices = [topic for topic in FALLBACK_TOPICS if topic != seed]
    return random.choice(choices or FALLBACK_TOPICS)


async def set_topic(brief: str, title: str | None = None):
    """`brief` is the debate_brief (drawer + model prompt context). `title`
    is the public_title (stage caption); a bare call (title=None) sets
    both to `brief`, so old callers and old clients keep working (§6)."""
    if title is None:
        title = brief
    state.topic = brief
    state.public_title = title
    state.topic_epoch += 1
    state.turn = 0
    state.anchor = ""
    state.transcript = []
    state.speaker_idx = 0
    state.reset_debate_state()
    argument_memory_tracker.reset()
    if insight_manager:
        await insight_manager.reset()
    await hub.send({"type": "topic", "text": title})
    await hub.send({"type": "brief", "text": brief})


async def refresh_anchor():
    conversation = "\n".join(
        f"{turn['name']}: {turn['text']}"
        for turn in state.transcript[-CONTEXT_TURNS:]
    )
    prompt = (
        "Write a compact continuity anchor using only claims actually made.\n"
        f"TOPIC: {state.topic}\nRECENT TRANSCRIPT:\n{conversation}"
    )
    try:
        state.anchor = await ollama_chat(
            SEATS[0]["model"], [{"role": "user", "content": prompt}]
        )
        await hub.send({"type": "anchor", "text": state.anchor})
    except Exception:
        await hub.send({"type": "status", "text": "Continuity refresh unavailable."})


class InsightManager:
    """One bounded, preemptible heuristic extractor worker."""

    def __init__(self, queue_max: int, timeout: float, extractor_model: str):
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_max)
        self.timeout = timeout
        self.extractor_model = extractor_model
        self.worker_task: asyncio.Task | None = None
        self.active_task: asyncio.Task | None = None
        self.installed: bool | None = None

    def start(self):
        if not self.worker_task:
            self.worker_task = asyncio.create_task(self._worker(), name="insight-worker")

    async def stop(self):
        await self.preempt()
        if self.worker_task:
            self.worker_task.cancel()
            await asyncio.gather(self.worker_task, return_exceptions=True)
            self.worker_task = None

    async def reset(self):
        await self.preempt()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        await hub.send({"type": "insight_reset", "heuristic": True})

    async def preempt(self):
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
            await asyncio.gather(self.active_task, return_exceptions=True)
        self.active_task = None

    def enqueue(self, job: dict):
        if not job.get("text"):
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(job)

    async def _worker(self):
        while True:
            job = await self.queue.get()
            try:
                if job["topic_epoch"] != state.topic_epoch or state.generation_active:
                    continue
                self.active_task = asyncio.create_task(self._extract(job))
                try:
                    await self.active_task
                except asyncio.CancelledError:
                    pass
                finally:
                    self.active_task = None
            finally:
                self.queue.task_done()

    async def _extract(self, job: dict):
        if self.installed is None:
            try:
                self.installed = self.extractor_model in await installed_models()
            except Exception:
                self.installed = False
        if not self.installed:
            await self._unavailable(job)
            return
        names = ", ".join(seat["name"] for seat in SEATS)
        prompt = (
            "Heuristically extract the public statement below. Return one JSON object "
            'with keys "stance" (short string), "addressed_seat" (participant name or '
            'empty string), "claims" (array of 1-3 short strings), and "question" '
            "(short string or empty string). Do not infer hidden thoughts.\n"
            f"Participants: {names}\nPublic statement:\n{job['text']}"
        )
        try:
            output = await asyncio.wait_for(
                ollama_chat(
                    self.extractor_model,
                    [{"role": "user", "content": prompt}],
                ),
                timeout=self.timeout,
            )
            match = re.search(r"\{.*\}", output, re.S)
            parsed = json.loads(match.group(0) if match else output)
            claims = parsed.get("claims", [])
            if not isinstance(claims, list):
                claims = []
            event = {
                "type": "insight",
                "heuristic": True,
                "status": "complete",
                "seat": job["seat"],
                "turn": job["turn"],
                "stance": str(parsed.get("stance", ""))[:300] or "—",
                "addressed_seat": str(parsed.get("addressed_seat", ""))[:100] or "—",
                "claims": [str(item)[:300] for item in claims[:3]] or ["—"],
                "question": str(parsed.get("question", ""))[:300] or "—",
            }
            if job["topic_epoch"] == state.topic_epoch:
                await hub.send(event)
        except (asyncio.TimeoutError, httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError):
            await self._unavailable(job)

    async def _unavailable(self, job: dict):
        if job["topic_epoch"] == state.topic_epoch:
            await hub.send(
                {
                    "type": "insight",
                    "heuristic": True,
                    "status": "unavailable",
                    "seat": job["seat"],
                    "turn": job["turn"],
                    "stance": "—",
                    "addressed_seat": "—",
                    "claims": ["—"],
                    "question": "—",
                }
            )


insight_manager: InsightManager | None = None
if CONFIG["insight_panel"]:
    insight_manager = InsightManager(
        int(CONFIG["insight_queue_max"]),
        float(CONFIG["insight_timeout_seconds"]),
        CONFIG["extractor_model"],
    )


async def run_turn(seat: dict, turn_number: int):
    model = seat["model"]
    state.interrupt_generation.clear()
    state.generation_active = True
    if insight_manager:
        await insight_manager.preempt()
    move_key, move_text, move_reason = pick_move(seat, turn_number)
    interject, state.interject = state.interject, None
    await hub.send(
        {
            "type": "turn_start",
            "seat": seat["name"],
            "turn": turn_number,
            "move": move_key,
            "move_reason": move_reason,
            "model": model,
            "interjection": bool(interject),
        }
    )
    recent_arguments = argument_memory_tracker.recent(seat["name"])
    messages = [
        {"role": "system", "content": system_prompt(seat)},
        {
            "role": "user",
            "content": turn_prompt(seat, move_text, interject, recent_arguments),
        },
    ]
    dynamic_values = turn_prompt_dynamic_values(move_text, interject)

    text = ""
    attempt_metrics = []
    max_attempts = 1 + int(CONFIG["empty_spoken_retry_count"])
    for attempt in range(max_attempts):
        one_attempt = {"attempt": attempt + 1, "first_sentence_seconds": None}
        attempt_metrics.append(one_attempt)

        guard = OutputGuard(TURN_PROMPT_LABELS, dynamic_values)
        buffer = SentenceBuffer(guard)
        emitted_sentences: list[str] = []
        spoke = False
        attempt_started = time.monotonic()

        async def emit_sentence(sentence: str):
            emitted_sentences.append(sentence)
            if one_attempt["first_sentence_seconds"] is None:
                one_attempt["first_sentence_seconds"] = (
                    time.monotonic() - attempt_started
                )
            await hub.send({"type": "token", "seat": seat["name"], "text": sentence})

        async def emit_blocked(labels: list[str]):
            for label in labels:
                await hub.send(
                    {
                        "type": "diagnostic",
                        "kind": "CONTROL_TEXT_LEAK_BLOCKED",
                        "seat": seat["name"],
                        "turn": turn_number,
                        "model": model,
                        "label": label,
                    }
                )

        async def on_public(fragment: str):
            nonlocal spoke
            if not fragment:
                return
            if not spoke:
                spoke = True
                await hub.send(
                    {"type": "speaking", "seat": seat["name"], "turn": turn_number}
                )
            sentences, blocked = buffer.feed(fragment)
            await emit_blocked(blocked)
            for sentence in sentences:
                await emit_sentence(sentence)

        try:
            await ollama_chat(
                model,
                messages,
                on_public=on_public,
                interruptible=True,
                metrics=one_attempt,
            )
        except TurnInterrupted:
            raise
        except Exception as exc:
            state.generation_active = False
            one_attempt["error_type"] = type(exc).__name__
            await hub.send(
                {
                    "type": "status",
                    "text": f"{seat['name']}: response unavailable; turn skipped.",
                }
            )
            await hub.send(
                {
                    "type": "turn_skipped",
                    "seat": seat["name"],
                    "turn": turn_number,
                    "reason": "generation_error",
                }
            )
            await hub.send(
                {
                    "type": "turn_end",
                    "seat": seat["name"],
                    "turn": turn_number,
                    "text": "",
                }
            )
            await hub.send(
                {
                    "type": "turn_metrics",
                    "seat": seat["name"],
                    "turn": turn_number,
                    "model": model,
                    "attempts": attempt_metrics,
                    "public_empty": True,
                }
            )
            return

        finish_sentences, tail, finish_blocked = buffer.finish()
        await emit_blocked(finish_blocked)
        for sentence in finish_sentences:
            await emit_sentence(sentence)

        joined_so_far = " ".join(s.strip() for s in emitted_sentences if s.strip())
        classify_text = (joined_so_far + (" " + tail if tail else "")).strip()
        completion_state, signals, confident = tc.classify(
            text=classify_text,
            budget_exhausted=bool(one_attempt.get("budget_exhausted")),
            hidden_reasoning_present=bool(one_attempt.get("hidden_reasoning_present")),
        )
        one_attempt["completion_state"] = completion_state
        one_attempt["completion_signals"] = signals

        if tail:
            if completion_state == tc.TURN_TRUNCATED_BY_BUDGET and confident:
                continuation_messages = messages + [
                    {"role": "assistant", "content": classify_text},
                    {
                        "role": "user",
                        "content": (
                            "Your previous message was cut off mid-sentence by a "
                            "length limit. Complete only that single unfinished "
                            "sentence, in 35 words or fewer. Output only the "
                            "missing words -- no new sentence, no new argument, "
                            "no restatement."
                        ),
                    },
                ]
                continuation_metrics = {"attempt": "continuation"}
                try:
                    continuation_text = await ollama_chat(
                        model, continuation_messages, metrics=continuation_metrics
                    )
                except Exception:
                    continuation_text = ""
                continuation_text = tc.bound_continuation(continuation_text)
                one_attempt["continuation_metrics"] = continuation_metrics
                if continuation_text.strip():
                    merged = tc.merge_continuation(tail, continuation_text)
                    one_attempt["continuation_overlap_trimmed"] = (
                        len(f"{tail.rstrip()} {continuation_text.strip()}".strip())
                        - len(merged)
                    )
                    await emit_sentence(merged)
                    one_attempt["continuation_applied"] = True
                else:
                    await emit_sentence(tail)
                    one_attempt["continuation_applied"] = False
            else:
                await emit_sentence(tail)

        text = " ".join(s.strip() for s in emitted_sentences if s.strip())

        # Make the turn contract measurable rather than aspirational (v1.1
        # targeted 110-160 words and shipped a measured mean of 188 / max 305,
        # unrecorded). Diagnostic only: speech is never rejected or rewritten.
        word_count, word_status = prompt_contract.word_count_status(
            text, TURN_WORD_MIN, TURN_WORD_MAX
        )
        one_attempt["word_count"] = word_count
        one_attempt["word_contract"] = word_status
        opener = prompt_contract.opens_with_agreement(text)
        if opener:
            one_attempt["agreement_opener"] = opener

        # Opening-move constraint (v1.1 closeout): sentence 1 must not
        # name, second-person-address, or opponent-validate. Diagnostic
        # only -- never used to reject or rewrite speech.
        opponent_names = [
            candidate["name"] for candidate in SEATS if candidate["name"] != seat["name"]
        ]
        opening_violation = prompt_contract.opening_move_violation(text, opponent_names)
        if opening_violation:
            one_attempt["opening_violation"] = opening_violation

        if text:
            break
        if attempt + 1 < max_attempts:
            await hub.send(
                {
                    "type": "status",
                    "text": f"{seat['name']}: retrying empty public response.",
                }
            )
            messages[1]["content"] += (
                "\n\nYour prior attempt contained no public speech. Respond now with "
                "plain public prose and no hidden reasoning."
            )
    state.generation_active = False
    if not text:
        await hub.send(
            {
                "type": "turn_skipped",
                "seat": seat["name"],
                "turn": turn_number,
                "reason": "empty_public_response",
            }
        )
        await hub.send(
            {"type": "turn_end", "seat": seat["name"], "turn": turn_number, "text": ""}
        )
        await hub.send(
            {
                "type": "turn_metrics",
                "seat": seat["name"],
                "turn": turn_number,
                "model": model,
                "attempts": attempt_metrics,
                "public_empty": True,
            }
        )
        return

    state.transcript.append({"name": seat["name"], "text": text})
    state.transcript = state.transcript[-40:]
    state.observe_public_turn(seat["name"], text)
    repeated_concept = argument_memory_tracker.check_and_record(seat["name"], text)
    if repeated_concept:
        state.pending_reframe[seat["name"]] = repeated_concept
    await hub.send(
        {
            "type": "turn_end",
            "seat": seat["name"],
            "turn": turn_number,
            "text": text,
        }
    )
    await hub.send(
        {
            "type": "turn_metrics",
            "seat": seat["name"],
            "turn": turn_number,
            "model": model,
            "attempts": attempt_metrics,
            "public_empty": False,
        }
    )
    if insight_manager:
        insight_manager.enqueue(
            {
                "seat": seat["name"],
                "turn": turn_number,
                "text": text,
                "topic_epoch": state.topic_epoch,
                "queued_at": time.monotonic(),
            }
        )


async def orchestrator():
    state.status = "generating first topic"
    await hub.send({"type": "status", "text": "generating first topic"})
    await set_topic(await generate_topic(""))
    state.status = "live"
    while not state.shutting_down:
        try:
            if state.paused:
                await asyncio.sleep(0.3)
                continue
            if state.pending_topic:
                payload, state.pending_topic = state.pending_topic, None
                await set_topic(payload["debate_brief"], payload["public_title"])
            if TOPIC_ROTATE_TURNS > 0 and state.turn >= TOPIC_ROTATE_TURNS:
                await hub.send({"type": "status", "text": "rotating topic"})
                await set_topic(await generate_topic(state.topic))
            # A pause can arrive while a non-streaming topic generation call is
            # in flight. Re-check before selecting a seat so the completed topic
            # may publish, but no debate turn starts until resume.
            if state.paused:
                continue
            seat = SEATS[state.speaker_idx % len(SEATS)]
            next_turn = state.turn + 1
            await run_turn(seat, next_turn)
            state.turn = next_turn
            state.speaker_idx += 1
            if ANCHOR_EVERY_TURNS > 0 and state.turn % ANCHOR_EVERY_TURNS == 0:
                await refresh_anchor()
            await asyncio.sleep(TURN_DELAY_S)
        except TurnInterrupted:
            state.generation_active = False
            if state.shutting_down:
                break
            await hub.send(
                {
                    "type": "turn_skipped",
                    "seat": seat["name"],
                    "turn": next_turn,
                    "reason": "operator_interruption",
                }
            )
            await hub.send(
                {
                    "type": "turn_end",
                    "seat": seat["name"],
                    "turn": next_turn,
                    "text": "",
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            state.generation_active = False
            await hub.send(
                {"type": "status", "text": "Turn unavailable; continuing debate."}
            )
            await asyncio.sleep(2.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state.shutting_down = False
    if insight_manager:
        insight_manager.start()
    task = asyncio.create_task(orchestrator(), name="debate-orchestrator")
    try:
        yield
    finally:
        state.shutting_down = True
        state.interrupt_generation.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if insight_manager:
            await insight_manager.stop()


app = FastAPI(title="Debate Table", lifespan=lifespan)


class TextIn(BaseModel):
    text: str


class SeatModelIn(BaseModel):
    seat: str
    model: str


class BriefIn(BaseModel):
    public_title: str
    debate_brief: str


class SeatThesisIn(BaseModel):
    seat: str
    thesis: str
    reason: str = ""


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        models = await installed_models()
    except Exception:
        models = []
    await ws.send_text(
        json.dumps(
            {
                "type": "snapshot",
                "seats": public_seats(),
                "models": models,
                "topic": state.public_title,
                "public_title": state.public_title,
                "debate_brief": state.topic,
                "public_title_max_chars": PUBLIC_TITLE_MAX_CHARS,
                "debate_brief_max_chars": DEBATE_BRIEF_MAX_CHARS,
                "seat_theses": {seat["name"]: seat.get("thesis", "") for seat in SEATS},
                "transcript": state.transcript[-CONTEXT_TURNS:],
                "paused": state.paused,
                "status": state.status,
                "insight_enabled": bool(insight_manager),
                "diagnostics": {
                    "move": state.last_move,
                    "move_reason": state.last_move_reason,
                    "turn": state.last_move_turn,
                },
            },
            ensure_ascii=False,
        )
    )
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        hub.clients.discard(ws)


@app.get("/api/models")
async def api_models():
    try:
        return JSONResponse({"models": await installed_models()})
    except Exception:
        return JSONResponse({"error": "Ollama unavailable"}, status_code=502)


@app.post("/api/seat_model")
async def api_seat_model(body: SeatModelIn):
    seat = next((item for item in SEATS if item["name"] == body.seat), None)
    if seat is None:
        return JSONResponse({"error": "unknown seat"}, status_code=400)
    try:
        models = await installed_models()
    except Exception:
        return JSONResponse(
            {"error": "could not validate installed models"}, status_code=502
        )
    if body.model not in models:
        return JSONResponse({"error": "model is not installed"}, status_code=400)
    async with seat_mutation_lock:
        try:
            persist_seat_model(body.seat, body.model)
        except Exception:
            return JSONResponse({"error": "configuration write failed"}, status_code=500)
        seat["model"] = body.model
        CONFIG["seats"] = SEATS
    await hub.send({"type": "seats", "seats": public_seats()})
    return JSONResponse({"ok": True})


@app.post("/api/topic")
async def api_topic(body: TextIn):
    topic = body.text.strip()
    if not topic:
        return JSONResponse({"error": "topic is empty"}, status_code=400)
    if len(topic) > PUBLIC_TITLE_MAX_CHARS:
        return JSONResponse(
            {
                "error": (
                    f"topic exceeds {PUBLIC_TITLE_MAX_CHARS} characters; use "
                    "/api/brief to set a longer debate_brief with a shorter "
                    "public_title"
                )
            },
            status_code=400,
        )
    state.pending_topic = {"public_title": topic, "debate_brief": topic}
    state.interrupt_generation.set()
    return JSONResponse({"ok": True})


@app.post("/api/brief")
async def api_brief(body: BriefIn):
    title = body.public_title.strip()
    brief = body.debate_brief.strip()
    if not title or not brief:
        return JSONResponse(
            {"error": "public_title and debate_brief are both required"},
            status_code=400,
        )
    if len(title) > PUBLIC_TITLE_MAX_CHARS:
        return JSONResponse(
            {"error": f"public_title exceeds {PUBLIC_TITLE_MAX_CHARS} characters"},
            status_code=400,
        )
    if len(brief) > DEBATE_BRIEF_MAX_CHARS:
        return JSONResponse(
            {"error": f"debate_brief exceeds {DEBATE_BRIEF_MAX_CHARS} characters"},
            status_code=400,
        )
    state.pending_topic = {"public_title": title, "debate_brief": brief}
    state.interrupt_generation.set()
    return JSONResponse({"ok": True})


@app.post("/api/seat_thesis")
async def api_seat_thesis(body: SeatThesisIn):
    seat = next((item for item in SEATS if item["name"] == body.seat), None)
    if seat is None:
        return JSONResponse({"error": "unknown seat"}, status_code=400)
    thesis = body.thesis.strip()
    if not thesis:
        return JSONResponse({"error": "thesis is empty"}, status_code=400)
    previous = seat.get("thesis", "")
    async with seat_mutation_lock:
        try:
            persist_seat_thesis(body.seat, thesis)
        except Exception:
            return JSONResponse({"error": "configuration write failed"}, status_code=500)
        seat["thesis"] = thesis
        CONFIG["seats"] = SEATS
    await hub.send(
        {
            "type": "position_revision",
            "seat": body.seat,
            "previous_thesis": previous,
            "revised_thesis": thesis,
            "reason": body.reason.strip() or "operator_revision",
        }
    )
    return JSONResponse({"ok": True})


@app.post("/api/interject")
async def api_interject(body: TextIn):
    note = body.text.strip()
    if not note:
        return JSONResponse({"error": "interjection is empty"}, status_code=400)
    state.interject = note
    return JSONResponse({"ok": True})


@app.post("/api/pause")
async def api_pause():
    state.paused = True
    state.status = "paused"
    state.interrupt_generation.set()
    await hub.send({"type": "status", "text": "paused"})
    return JSONResponse({"ok": True})


@app.post("/api/resume")
async def api_resume():
    state.paused = False
    state.status = "live"
    await hub.send({"type": "status", "text": "live"})
    return JSONResponse({"ok": True})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(CONFIG["port"]),
        log_level="warning",
    )
