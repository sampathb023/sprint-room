from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import secrets
import signal
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
STATIC_DIR = Path(__file__).parent / "static"
DATA_FILE = Path(os.environ.get("DATA_FILE", Path(__file__).parent / "data" / "sessions.json"))
SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "30"))
STORY_POINTS = ["0", "1", "2", "3", "5", "8", "13", "21", "?"]


@dataclass
class Participant:
    id: str
    name: str
    vote: str | None = None
    connected: bool = True


@dataclass
class Story:
    id: str
    title: str = ""
    description: str = ""
    estimate: str | None = None
    average: float | None = None
    completed: bool = False
    revealed: bool = False
    votes: dict[str, str] = field(default_factory=dict)


@dataclass
class RetroItem:
    id: str
    category: str
    text: str
    author: str
    author_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    mode: str = "pointing"
    facilitator_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    stories: list[Story] = field(default_factory=list)
    retro_items: list[RetroItem] = field(default_factory=list)
    retro_revealed: bool = False
    active_story_id: str = ""
    revealed: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    participants: dict[str, Participant] = field(default_factory=dict)
    sockets: set["WebSocket"] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.stories:
            story = Story(id=secrets.token_urlsafe(6), title="First story")
            self.stories.append(story)
            self.active_story_id = story.id
        if not self.active_story_id:
            self.active_story_id = self.stories[0].id

    @property
    def active_story(self) -> Story:
        for story in self.stories:
            if story.id == self.active_story_id:
                return story
        self.active_story_id = self.stories[0].id
        return self.stories[0]


class Store:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = self._load()
        self.lock = asyncio.Lock()

    async def get_or_create(self, session_id: str | None = None, mode: str = "pointing") -> Session:
        async with self.lock:
            self._prune_expired()
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                session.updated_at = time.time()
                self._save()
                return session
            new_id = session_id or secrets.token_urlsafe(5).replace("_", "").replace("-", "")[:8]
            while new_id in self.sessions:
                new_id = secrets.token_urlsafe(5).replace("_", "").replace("-", "")[:8]
            session = Session(id=new_id, mode=mode if mode in {"pointing", "retro"} else "pointing")
            self.sessions[new_id] = session
            self._save()
            return session

    async def get(self, session_id: str | None) -> Session | None:
        async with self.lock:
            self._prune_expired()
            if not session_id:
                return None
            session = self.sessions.get(session_id)
            if session:
                session.updated_at = time.time()
                self._save()
            return session

    async def save(self, session: Session) -> None:
        async with self.lock:
            session.updated_at = time.time()
            self.sessions[session.id] = session
            self._save()

    def _load(self) -> dict[str, Session]:
        if not DATA_FILE.exists():
            return {}
        try:
            raw_sessions = json.loads(DATA_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        sessions = {}
        for raw in raw_sessions:
            stories = [Story(**story) for story in raw.get("stories", [])]
            retro_items = [
                RetroItem(
                    id=item["id"],
                    category=item["category"],
                    text=item["text"],
                    author=item.get("author", "Teammate"),
                    author_id=item.get("author_id", ""),
                    created_at=item.get("created_at", time.time()),
                )
                for item in raw.get("retro_items", [])
            ]
            participants = {
                item["id"]: Participant(
                    id=item["id"],
                    name=item.get("name", "Teammate"),
                    vote=item.get("vote"),
                    connected=False,
                )
                for item in raw.get("participants", [])
                if item.get("id")
            }
            session = Session(
                id=raw["id"],
                mode=raw.get("mode", "pointing"),
                facilitator_key=raw.get("facilitator_key", secrets.token_urlsafe(24)),
                stories=stories,
                retro_items=retro_items,
                retro_revealed=raw.get("retro_revealed", False),
                active_story_id=raw.get("active_story_id", ""),
                revealed=raw.get("revealed", False),
                created_at=raw.get("created_at", time.time()),
                updated_at=raw.get("updated_at", time.time()),
                participants=participants,
            )
            if session.active_story and not session.active_story.votes:
                session.active_story.votes = {
                    participant.id: participant.vote
                    for participant in participants.values()
                    if participant.vote
                }
            session.revealed = session.active_story.revealed
            sessions[session.id] = session
        return sessions

    def _save(self) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for session in self.sessions.values():
            payload.append(
                {
                    "id": session.id,
                    "mode": session.mode,
                    "facilitator_key": session.facilitator_key,
                    "retro_revealed": session.retro_revealed,
                    "active_story_id": session.active_story_id,
                    "revealed": session.revealed,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "stories": [
                        {
                            "id": story.id,
                            "title": story.title,
                            "description": story.description,
                            "estimate": story.estimate,
                            "average": story.average,
                            "completed": story.completed,
                            "revealed": story.revealed,
                            "votes": story.votes,
                        }
                        for story in session.stories
                    ],
                    "retro_items": [
                        {
                            "id": item.id,
                            "category": item.category,
                            "text": item.text,
                            "author": item.author,
                            "author_id": item.author_id,
                            "created_at": item.created_at,
                        }
                        for item in session.retro_items
                    ],
                    "participants": [
                        {"id": participant.id, "name": participant.name, "vote": participant.vote}
                        for participant in session.participants.values()
                    ],
                }
            )
        DATA_FILE.write_text(json.dumps(payload, indent=2))

    def _prune_expired(self) -> None:
        cutoff = time.time() - SESSION_TTL_DAYS * 24 * 60 * 60
        before = len(self.sessions)
        self.sessions = {
            session_id: session
            for session_id, session in self.sessions.items()
            if session.updated_at >= cutoff
        }
        if len(self.sessions) != before:
            self._save()


store = Store()


def numeric_votes(session: Session) -> list[int]:
    return [
        int(vote)
        for vote in session.active_story.votes.values()
        if vote.isdigit()
    ]


def vote_distribution(session: Session) -> list[dict[str, int | str]]:
    counts = {
        point: sum(1 for vote in session.active_story.votes.values() if vote == point)
        for point in STORY_POINTS
    }
    return [
        {"point": point, "count": count}
        for point, count in counts.items()
        if count
    ]


def reset_votes(session: Session) -> None:
    session.revealed = False
    session.active_story.revealed = False
    session.active_story.votes.clear()


def complete_active_story(session: Session) -> None:
    story = session.active_story
    if not story.revealed:
        return
    votes = numeric_votes(session)
    if votes:
        story.average = round(sum(votes) / len(votes), 1)
        story.estimate = str(story.average).rstrip("0").rstrip(".")
    elif session.revealed:
        story.average = None
        story.estimate = "No votes"
    story.completed = bool(story.estimate)


def add_story(session: Session, title: str = "", description: str = "") -> Story:
    story = Story(
        id=secrets.token_urlsafe(6),
        title=title[:140],
        description=description[:2000],
    )
    session.stories.append(story)
    return story


def add_retro_item(session: Session, category: str, text: str, author: str, author_id: str) -> RetroItem | None:
    if category not in {"wentWell", "improve", "feedback"}:
        return None
    clean_text = text.strip()[:1000]
    if not clean_text:
        return None
    item = RetroItem(
        id=secrets.token_urlsafe(6),
        category=category,
        text=clean_text,
        author=author[:40] or "Teammate",
        author_id=author_id,
    )
    session.retro_items.append(item)
    return item


def activate_story(session: Session, story_id: str) -> None:
    if story_id == session.active_story_id:
        return
    for story in session.stories:
        if story.id == story_id:
            complete_active_story(session)
            session.active_story_id = story_id
            session.revealed = story.revealed
            return


class WebSocket:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def handshake(self, headers: dict[str, str]) -> None:
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + self.GUID).encode()).digest()).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.writer.write(response.encode())
        await self.writer.drain()

    async def receive(self) -> dict[str, Any] | None:
        first = await self.reader.readexactly(2)
        opcode = first[0] & 0x0F
        masked = first[1] & 0x80
        length = first[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await self.reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self.reader.readexactly(8), "big")
        mask = await self.reader.readexactly(4) if masked else b""
        payload = await self.reader.readexactly(length) if length else b""
        if opcode == 8:
            return None
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return json.loads(payload.decode())

    async def send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.extend([126, *length.to_bytes(2, "big")])
        else:
            header.extend([127, *length.to_bytes(8, "big")])
        self.writer.write(bytes(header) + data)
        await self.writer.drain()

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


def render_state(
    session: Session,
    facilitator_key: str | None = None,
    viewer_participant_id: str | None = None,
) -> dict[str, Any]:
    votes = numeric_votes(session)
    can_manage = bool(facilitator_key and secrets.compare_digest(facilitator_key, session.facilitator_key))
    active_story = session.active_story
    average = round(sum(votes) / len(votes), 1) if votes and active_story.revealed else None
    visible_retro_items = [
        item
        for item in session.retro_items
        if session.retro_revealed or can_manage or item.author_id == viewer_participant_id
    ]
    return {
        "type": "state",
        "session": {
            "id": session.id,
            "mode": session.mode,
            "title": active_story.title,
            "description": active_story.description,
            "activeStoryId": active_story.id,
            "revealed": active_story.revealed,
            "canManage": can_manage,
            "retroRevealed": session.retro_revealed,
            "points": STORY_POINTS,
            "average": average,
            "distribution": vote_distribution(session) if active_story.revealed else [],
            "stories": [
                {
                    "id": story.id,
                    "title": story.title,
                    "description": story.description,
                    "estimate": story.estimate,
                    "average": story.average,
                    "completed": story.completed,
                    "active": story.id == session.active_story_id,
                }
                for story in session.stories
            ],
            "retroItems": [
                {
                    "id": item.id,
                    "category": item.category,
                    "text": item.text,
                    "author": item.author,
                    "createdAt": item.created_at,
                }
                for item in sorted(visible_retro_items, key=lambda item: item.created_at)
            ],
            "participants": [
                {
                    "id": participant.id,
                    "name": participant.name,
                    "vote": (
                        active_story.votes.get(participant.id)
                        if active_story.revealed or participant.id == viewer_participant_id
                        else None
                    ),
                    "hasVoted": participant.id in active_story.votes,
                    "connected": participant.connected,
                }
                for participant in session.participants.values()
            ],
        },
    }


async def broadcast(session: Session) -> None:
    dead: list[WebSocket] = []
    for socket in session.sockets:
        try:
            await socket.send(
                render_state(
                    session,
                    getattr(socket, "facilitator_key", None),
                    getattr(socket, "participant_id", None),
                )
            )
        except (ConnectionError, OSError):
            dead.append(socket)
    for socket in dead:
        session.sockets.discard(socket)


async def handle_websocket(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    headers: dict[str, str],
    path: str,
) -> None:
    socket = WebSocket(reader, writer)
    await socket.handshake(headers)
    query = parse_qs(urlparse(path).query)
    session_id = query.get("session", [None])[0]
    facilitator_key = query.get("facilitatorKey", [None])[0]
    session = await store.get(session_id)
    if not session:
        await socket.send({"type": "error", "message": "No active session"})
        await socket.close()
        return
    participant_id: str | None = None
    socket.facilitator_key = facilitator_key
    socket.participant_id = None
    session.sockets.add(socket)

    try:
        await socket.send(render_state(session, facilitator_key))
        while True:
            message = await socket.receive()
            if message is None:
                break
            action = message.get("type")
            can_manage = bool(facilitator_key and secrets.compare_digest(facilitator_key, session.facilitator_key))

            if action == "join":
                name = str(message.get("name", "")).strip()[:40] or "Teammate"
                participant_id = str(message.get("participantId") or secrets.token_urlsafe(10))
                socket.participant_id = participant_id
                existing = session.participants.get(participant_id)
                if existing:
                    existing.name = name
                    existing.connected = True
                else:
                    session.participants[participant_id] = Participant(id=participant_id, name=name)
                await store.save(session)
                await broadcast(session)

            if action == "addRetroItem" and participant_id:
                participant = session.participants.get(participant_id)
                author = participant.name if participant else "Teammate"
                item = add_retro_item(
                    session,
                    str(message.get("category", "")),
                    str(message.get("text", "")),
                    author,
                    participant_id,
                )
                if item:
                    await store.save(session)
                    await broadcast(session)

            if action == "revealRetro" and can_manage:
                session.retro_revealed = True
                await store.save(session)
                await broadcast(session)

            if action == "title" and can_manage:
                session.active_story.title = str(message.get("title", ""))[:140]
                await store.save(session)
                await broadcast(session)

            if action == "description" and can_manage:
                session.active_story.description = str(message.get("description", ""))[:2000]
                await store.save(session)
                await broadcast(session)

            if action == "addStory" and can_manage:
                story = add_story(
                    session,
                    str(message.get("title", "")).strip(),
                    str(message.get("description", "")).strip(),
                )
                if len(session.stories) == 1:
                    session.active_story_id = story.id
                await store.save(session)
                await broadcast(session)

            if action == "selectStory":
                complete_active_story(session)
                activate_story(session, str(message.get("storyId", "")))
                await store.save(session)
                await broadcast(session)

            if action == "vote" and participant_id:
                value = str(message.get("value"))
                if value in STORY_POINTS:
                    session.active_story.votes[participant_id] = value
                    session.revealed = False
                    session.active_story.revealed = False
                    session.active_story.estimate = None
                    session.active_story.average = None
                    session.active_story.completed = False
                    await store.save(session)
                    await broadcast(session)

            if action == "reveal" and can_manage:
                session.revealed = True
                session.active_story.revealed = True
                complete_active_story(session)
                await store.save(session)
                await broadcast(session)

            if action == "reset" and can_manage:
                reset_votes(session)
                session.active_story.estimate = None
                session.active_story.average = None
                session.active_story.completed = False
                await store.save(session)
                await broadcast(session)

            if action == "next" and can_manage:
                complete_active_story(session)
                next_story = next(
                    (story for story in session.stories if not story.completed and story.id != session.active_story_id),
                    None,
                )
                if not next_story:
                    next_story = add_story(session)
                session.active_story_id = next_story.id
                reset_votes(session)
                await store.save(session)
                await broadcast(session)
    except (asyncio.IncompleteReadError, ConnectionError, OSError, json.JSONDecodeError):
        pass
    finally:
        session.sockets.discard(socket)
        if participant_id and participant_id in session.participants:
            session.participants[participant_id].connected = False
            await broadcast(session)


async def read_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str], bytes]:
    raw = await reader.readuntil(b"\r\n\r\n")
    head = raw.decode(errors="replace").split("\r\n")
    method, path, _version = head[0].split(" ", 2)
    headers = {}
    for line in head[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    content_length = int(headers.get("content-length", "0"))
    body = await reader.readexactly(content_length) if content_length else b""
    return method, path, headers, body


async def send_response(
    writer: asyncio.StreamWriter,
    status: HTTPStatus,
    body: bytes,
    content_type: str = "text/plain; charset=utf-8",
    headers: dict[str, str] | None = None,
) -> None:
    extra = "".join(f"{key}: {value}\r\n" for key, value in (headers or {}).items())
    response = (
        f"HTTP/1.1 {status.value} {status.phrase}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Cache-Control: no-store\r\n"
        f"{extra}\r\n"
    ).encode() + body
    writer.write(response)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        method, path, headers, body = await read_request(reader)
        parsed = urlparse(path)

        if headers.get("upgrade", "").lower() == "websocket":
            await handle_websocket(reader, writer, headers, path)
            return

        if method == "POST" and parsed.path == "/api/sessions":
            payload = json.loads(body.decode() or "{}") if body else {}
            session = await store.get_or_create(mode=str(payload.get("mode", "pointing")))
            response_body = json.dumps(
                {"id": session.id, "mode": session.mode, "facilitatorKey": session.facilitator_key}
            ).encode()
            await send_response(writer, HTTPStatus.CREATED, response_body, "application/json")
            return

        if method == "GET" and parsed.path.startswith("/api/sessions/"):
            session_id = parsed.path.removeprefix("/api/sessions/").strip("/")
            session = await store.get(session_id)
            if not session:
                body = json.dumps({"error": "No active session"}).encode()
                await send_response(writer, HTTPStatus.NOT_FOUND, body, "application/json")
                return
            body = json.dumps({"id": session.id, "mode": session.mode}).encode()
            await send_response(writer, HTTPStatus.OK, body, "application/json")
            return

        if parsed.path == "/health":
            await send_response(writer, HTTPStatus.OK, b"ok")
            return

        file_path = STATIC_DIR / (parsed.path.strip("/") or "index.html")
        if not file_path.exists() or not file_path.is_file() or STATIC_DIR not in file_path.resolve().parents:
            file_path = STATIC_DIR / "index.html"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        await send_response(writer, HTTPStatus.OK, file_path.read_bytes(), content_type)
    except Exception as exc:
        await send_response(writer, HTTPStatus.INTERNAL_SERVER_ERROR, str(exc).encode())


async def main() -> None:
    server = await asyncio.start_server(handle_http, HOST, PORT)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"Sprint Room running on {sockets}")
    async with server:
        await stop.wait()


if __name__ == "__main__":
    asyncio.run(main())
