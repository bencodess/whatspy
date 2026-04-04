import asyncio
import json
import logging
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import qrcode

logger = logging.getLogger(__name__)


def render_qr_ascii(qr_data: str) -> str:
    try:
        qr = qrcode.QRCode(version=None, box_size=2, border=0)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        lines = []
        for y in range(img.height):
            line = ""
            for x in range(img.width):
                line += ("██" if img.getpixel((x, y)) else "  ")
            lines.append(line)
        
        return "\n".join(lines)
    except Exception:
        return f"QR: {qr_data[:50]}..."


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"


class BusinessCategory(Enum):
    UNDEFINED = "uncategorized"
    APPAREL = "apparel"
    BEAUTY = "beauty"
    ELECTRONICS = "electronics"
    FOOD = "food"
    HEALTH = "health"
    HOME = "home"
    PET = "pet"
    RETAIL = "retail"
    SERVICES = "services"
    SHOPPING = "shopping"
    TICKETS = "tickets"
    TRAVEL = "travel"
    AUTO = "auto"
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    FINANCE = "finance"
    FITNESS = "fitness"
    GROCERY = "grocery"
    HOTELS = "hotels"
    MEDICAL = "medical"
    NEWS = "news"
    OTHER = "other"


@dataclass
class Contact:
    jid: str
    name: Optional[str] = None
    push_name: Optional[str] = None
    is_business: bool = False
    business_profile: Optional[dict] = None
    is_group: bool = False
    group_metadata: Optional[dict] = None

    @property
    def phone_number(self) -> str:
        return self.jid.split("@")[0] if "@" in self.jid else self.jid


@dataclass
class Message:
    key: dict
    message: dict
    message_timestamp: int
    push_name: Optional[str]
    participant: Optional[str]
    jid: str
    message_type: MessageType = MessageType.TEXT

    @property
    def id(self) -> str:
        return self.key.get("id", "")

    @property
    def from_me(self) -> bool:
        return self.key.get("fromMe", False)

    @property
    def text(self) -> Optional[str]:
        return self.message.get("conversation") or self.message.get("extendedTextMessage", {}).get("text")

    @property
    def media_url(self) -> Optional[str]:
        msg = self.message
        for media_type in ["imageMessage", "videoMessage", "audioMessage", "documentMessage"]:
            if media_type in msg:
                return msg[media_type].get("url")
        return None

    @property
    def caption(self) -> Optional[str]:
        msg = self.message
        for key in ["imageMessage", "videoMessage", "documentMessage"]:
            if key in msg:
                return msg[key].get("caption")
        return None


@dataclass
class GroupMetadata:
    jid: str
    subject: str
    subject_owner: str
    subject_time: int
    creation: int
    description: Optional[str]
    desc_id: str
    desc_time: int
    owner: str
    participants: list[dict] = field(default_factory=list)
    ephemeral_duration: int = 0
    not_announcement: bool = False
    locked: bool = False


class WhatsSpyClient:
    def __init__(
        self,
        session_name: str = "whatsspy_session",
        session_dir: Optional[str] = None,
        browser: str = "WhatsSpy/1.0",
        headless: bool = True,
        debug: bool = False,
    ):
        self.session_name = session_name
        self.session_dir = Path(session_dir) if session_dir else Path.home() / ".whatsspy" / session_name
        self.browser = browser
        self.headless = headless
        self.debug = debug

        self._process: Optional[subprocess.Popen] = None
        self._event_callbacks: dict[str, list[Callable]] = {}
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._read_task: Optional[asyncio.Task] = None
        self._auth_callback: Optional[Callable] = None

        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _get_bridge_script(self) -> str:
        return """
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, proto, prepareWAMessageMedia } = require('@whiskeysockets/baileys');

let sock = null;
let eventHandlers = {};

function sendResponse(id, success, data) {
    console.log(JSON.stringify({ type: 'response', id, success, data, error: null }));
}

function sendEvent(type, data) {
    console.log(JSON.stringify({ type: 'event', event: type, data }));
}

async function handleCommand(cmd) {
    const { id, action, args } = cmd;
    
    try {
        switch(action) {
            case 'connect':
                const { state, saveCreds } = await useMultiFileAuthState(args.sessionDir);
                const { version } = await fetchLatestBaileysVersion();
                
                sock = makeWASocket({
                    version,
                    auth: state,
                    browser: [args.browser, 'Chrome', '120.0'],
                    headless: args.headless !== false,
                });

                sock.ev.on('connection.update', (update) => {
                    if (update.connection === 'open') {
                        sendEvent('connected', { jid: sock.user?.jid });
                    }
                    if (update.connection === 'close') {
                        sendEvent('disconnected', { reason: update.lastDisconnect?.error?.message });
                    }
                    if (update.qr) {
                        sendEvent('qr', { qr: update.qr });
                        if (eventHandlers['qr'] && eventHandlers['qr'].length > 0) {
                            eventHandlers['qr'][0](update.qr);
                        }
                    }
                });

                sock.ev.on('creds.update', saveCreds);
                
                sock.ev.on('messages.upsert', ({ messages }) => {
                    messages.forEach(msg => {
                        if (msg.message) {
                            sendEvent('message', {
                                key: msg.key,
                                message: msg.message,
                                messageTimestamp: msg.messageTimestamp,
                                pushName: msg.pushName,
                                participant: msg.participant,
                                jid: msg.key.remoteJid,
                            });
                        }
                    });
                });

                sock.ev.on('contacts.upsert', (contacts) => {
                    sendEvent('contacts_update', contacts);
                });

                sock.ev.on('groups.update', (groups) => {
                    sendEvent('groups_update', groups);
                });

                sock.ev.on('group-participants.update', (update) => {
                    sendEvent('group_participants_update', update);
                });

                sendResponse(id, true, { status: 'connecting' });
                break;

            case 'send_text':
                const jid = args.jid;
                const text = args.text;
                const options = args.options || {};
                await sock.sendMessage(jid, { text }, options);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_image':
                const imgJid = args.jid;
                const imgUrl = args.url;
                const imgCaption = args.caption;
                const imgOptions = args.options || {};
                const imgBuffer = await fetch(imgUrl).then(r => r.buffer());
                await sock.sendMessage(imgJid, { image: imgBuffer, caption: imgCaption }, imgOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_video':
                const vidJid = args.jid;
                const vidUrl = args.url;
                const vidCaption = args.caption;
                const vidOptions = args.options || {};
                const vidBuffer = await fetch(vidUrl).then(r => r.buffer());
                await sock.sendMessage(vidJid, { video: vidBuffer, caption: vidCaption }, vidOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'send_document':
                const docJid = args.jid;
                const docUrl = args.url;
                const docFilename = args.filename;
                const docOptions = args.options || {};
                const docBuffer = await fetch(docUrl).then(r => r.buffer());
                await sock.sendMessage(docJid, { document: docBuffer, fileName: docFilename }, docOptions);
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'reply':
                const replyJid = args.jid;
                const replyText = args.text;
                const replyTo = args.quotedMessageId;
                const replyOptions = args.options || {};
                await sock.sendMessage(replyJid, { text: replyText }, { ...replyOptions, quoted: { key: { id: replyTo } } });
                sendResponse(id, true, { status: 'sent' });
                break;

            case 'get_contacts':
                const contacts = Object.values(sock.store?.contacts || {});
                sendResponse(id, true, { contacts });
                break;

            case 'get_contact':
                const contactJid = args.jid;
                const contact = sock.store?.contacts?.[contactJid];
                sendResponse(id, true, { contact });
                break;

            case 'get_groups':
                const groups = Object.values(sock.store?.chats || {}).filter(c => c.jid?.endsWith('@g.us'));
                sendResponse(id, true, { groups });
                break;

            case 'get_group_metadata':
                const groupJid = args.jid;
                const metadata = await sock.groupMetadata(groupJid);
                sendResponse(id, true, { metadata });
                break;

            case 'create_group':
                const groupName = args.name;
                const groupParticipants = args.participants || [];
                const group = await sock.groupCreate(groupName, groupParticipants);
                sendResponse(id, true, { group });
                break;

            case 'add_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'add');
                sendResponse(id, true, { status: 'added' });
                break;

            case 'remove_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'remove');
                sendResponse(id, true, { status: 'removed' });
                break;

            case 'promote_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'promote');
                sendResponse(id, true, { status: 'promoted' });
                break;

            case 'demote_participant':
                await sock.groupParticipantsUpdate(args.jid, args.participants, 'demote');
                sendResponse(id, true, { status: 'demoted' });
                break;

            case 'leave_group':
                await sock.groupLeave(args.jid);
                sendResponse(id, true, { status: 'left' });
                break;

            case 'update_group_name':
                await sock.groupUpdateSubject(args.jid, args.name);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'update_group_description':
                await sock.groupUpdateDescription(args.jid, args.description);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'get_avatar':
                const avatarJid = args.jid;
                const avatarUrl = await sock.profilePictureUrl(avatarJid, 'image');
                sendResponse(id, true, { url: avatarUrl });
                break;

            case 'set_avatar':
                await sock.updateProfilePicture(args.jid, args.url);
                sendResponse(id, true, { status: 'updated' });
                break;

            case 'block_contact':
                await sock.updateBlockStatus(args.jid, 'block');
                sendResponse(id, true, { status: 'blocked' });
                break;

            case 'unblock_contact':
                await sock.updateBlockStatus(args.jid, 'unblock');
                sendResponse(id, true, { status: 'unblocked' });
                break;

            case 'get_blocklist':
                const blocklist = await sock.fetchBlocklist();
                sendResponse(id, true, { blocklist });
                break;

            case 'mark_read':
                await sock.chatModify({ markRead: true }, args.jid);
                sendResponse(id, true, { status: 'marked' });
                break;

            case 'delete_message':
                await sock.sendMessage(args.jid, { delete: { id: args.messageId } });
                sendResponse(id, true, { status: 'deleted' });
                break;

            case 'react':
                await sock.sendMessage(args.jid, { react: { text: args.emoji, key: { id: args.messageId } } });
                sendResponse(id, true, { status: 'reacted' });
                break;

            case 'get_my_number':
                sendResponse(id, true, { jid: sock.user?.jid, name: sock.user?.name });
                break;

            case 'logout':
                await sock.logout();
                sendResponse(id, true, { status: 'logged_out' });
                break;

            case 'disconnect':
                sock?.end(undefined);
                sendResponse(id, true, { status: 'disconnected' });
                break;

            default:
                sendResponse(id, false, null, 'Unknown action');
        }
    } catch (error) {
        console.error(JSON.stringify({ type: 'response', id, success: false, data: null, error: error.message }));
    }
}

process.stdin.on('data', (data) => {
    const lines = data.toString().split('\\n').filter(l => l.trim());
    lines.forEach(line => {
        try {
            const cmd = JSON.parse(line);
            handleCommand(cmd);
        } catch (e) {
            console.error(JSON.stringify({ type: 'error', error: 'Invalid JSON' }));
        }
    });
});

process.on('SIGTERM', () => {
    if (sock) sock.end(undefined);
    process.exit(0);
});
"""

    async def _start_bridge_async(self) -> None:
        self.session_dir = self.session_dir.resolve()
        node_script = self.session_dir / "bridge.js"
        node_script.write_text(self._get_bridge_script())

        node_modules = self.session_dir / "node_modules"
        if not node_modules.exists():
            self._install_dependencies(self.session_dir)

        self._process = await asyncio.create_subprocess_exec(
            "node", str(node_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.session_dir),
        )
        self._pending_commands: dict[str, asyncio.Future] = {}

    def _start_bridge(self) -> None:
        asyncio.run(self._start_bridge_async())

    def _install_dependencies(self, dir_path: Path) -> None:
        subprocess.run(
            ["npm", "init", "-y"],
            cwd=str(dir_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["npm", "install", "@whiskeysockets/baileys"],
            cwd=str(dir_path),
            capture_output=True,
            check=True,
        )

    async def _send_command_async(self, action: str, args: Optional[dict] = None) -> dict:
        if not self._process or self._process.returncode is not None:
            raise ConnectionError("Client is not connected")

        cmd_id = f"cmd_{os.urandom(8).hex()}"
        cmd = {"id": cmd_id, "action": action, "args": args or {}}

        self._process.stdin.write(json.dumps(cmd).encode() + b"\n")
        await self._process.stdin.drain()

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_commands[cmd_id] = future

        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            del self._pending_commands[cmd_id]
            raise TimeoutError("Command timed out")

    def _send_command(self, action: str, args: Optional[dict] = None) -> dict:
        return asyncio.run(self._send_command_async(action, args))

    async def _read_events(self) -> None:
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
            except Exception:
                break
            if not line:
                break
            try:
                data = json.loads(line.decode())
                if data.get("type") == "response" and "id" in data:
                    cmd_id = data["id"]
                    if cmd_id in self._pending_commands:
                        future = self._pending_commands.pop(cmd_id)
                        if data.get("success"):
                            future.set_result(data.get("data", {}))
                        else:
                            future.set_exception(Exception(data.get("error", "Unknown error")))
                elif data.get("type") == "event":
                    event_name = data.get("event")
                    event_data = data.get("data", {})
                    if event_name in self._event_callbacks:
                        for callback in self._event_callbacks[event_name]:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(event_data)
                            else:
                                callback(event_data)
            except json.JSONDecodeError:
                continue

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._event_callbacks:
            self._event_callbacks[event] = []
        self._event_callbacks[event].append(callback)

    def on_message(self, callback: Optional[Callable[[Message], None]] = None) -> Callable:
        def decorator(cb: Callable[[Message], None]) -> Callable:
            def handler(data: dict) -> None:
                msg = Message(
                    key=data["key"],
                    message=data["message"],
                    message_timestamp=data["messageTimestamp"],
                    push_name=data.get("pushName"),
                    participant=data.get("participant"),
                    jid=data["jid"],
                )
                cb(msg)
            self.on("message", handler)
            return cb
        if callback is not None:
            return decorator(callback)
        return decorator

    def on_qr(self, callback: Optional[Callable[[str], None]] = None) -> Callable:
        def decorator(cb: Callable[[str], None]) -> Callable:
            def handler(data: dict) -> None:
                cb(data["qr"])
            self.on("qr", handler)
            return cb
        if callback is not None:
            return decorator(callback)
        return decorator

    def on_connected(self, callback: Optional[Callable[[str], None]] = None) -> Callable:
        def decorator(cb: Callable[[str], None]) -> Callable:
            def handler(data: dict) -> None:
                cb(data["jid"])
            self.on("connected", handler)
            return cb
        if callback is not None:
            return decorator(callback)
        return decorator

    def on_disconnected(self, callback: Optional[Callable[[str], None]] = None) -> Callable:
        def decorator(cb: Callable[[str], None]) -> Callable:
            def handler(data: dict) -> None:
                cb(data["reason"])
            self.on("disconnected", handler)
            return cb
        if callback is not None:
            return decorator(callback)
        return decorator

    async def connect_async(self) -> None:
        await self._start_bridge_async()
        self._loop = asyncio.get_event_loop()
        self._read_task = self._loop.create_task(self._read_events())
        await self._send_command_async("connect", {
            "sessionDir": str(self.session_dir),
            "browser": self.browser,
            "headless": self.headless,
        })
        self._connected = True

    def connect(self) -> None:
        import threading
        
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._client_loop = loop
            try:
                loop.run_until_complete(self._run_loop())
            finally:
                loop.close()
                self._client_loop = None
        
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
        
        for _ in range(50):
            if self._connected:
                break
            import time
            time.sleep(0.1)

    async def _run_loop(self) -> None:
        await self.connect_async()
        while self._connected and self._process and self._process.returncode is None:
            await asyncio.sleep(0.5)

    async def disconnect_async(self) -> None:
        if self._process:
            try:
                await self._send_command_async("disconnect")
            except Exception:
                pass
            self._process.terminate()
            await self._process.wait()
            self._process = None
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        self._connected = False

    def disconnect(self) -> None:
        asyncio.run(self.disconnect_async())

    def send_text(self, jid: str, text: str, **kwargs) -> dict:
        return self._send_command("send_text", {"jid": jid, "text": text, "options": kwargs})

    async def send_text_async(self, jid: str, text: str, **kwargs) -> dict:
        return await asyncio.get_event_loop().run_in_executor(None, self.send_text, jid, text, **kwargs)

    def send_image(self, jid: str, url: str, caption: Optional[str] = None, **kwargs) -> dict:
        return self._send_command("send_image", {"jid": jid, "url": url, "caption": caption, "options": kwargs})

    def send_video(self, jid: str, url: str, caption: Optional[str] = None, **kwargs) -> dict:
        return self._send_command("send_video", {"jid": jid, "url": url, "caption": caption, "options": kwargs})

    def send_document(self, jid: str, url: str, filename: str, **kwargs) -> dict:
        return self._send_command("send_document", {"jid": jid, "url": url, "filename": filename, "options": kwargs})

    def reply(self, jid: str, text: str, quoted_message_id: str, **kwargs) -> dict:
        return self._send_command("reply", {
            "jid": jid,
            "text": text,
            "quotedMessageId": quoted_message_id,
            "options": kwargs,
        })

    def get_contacts(self) -> list[Contact]:
        data = self._send_command("get_contacts")
        return [Contact(**c) for c in data.get("contacts", [])]

    def get_contact(self, jid: str) -> Optional[Contact]:
        data = self._send_command("get_contact", {"jid": jid})
        contact_data = data.get("contact")
        return Contact(**contact_data) if contact_data else None

    def get_groups(self) -> list[Contact]:
        data = self._send_command("get_groups")
        return [Contact(**g) for g in data.get("groups", [])]

    def get_group_metadata(self, jid: str) -> GroupMetadata:
        data = self._send_command("get_group_metadata", {"jid": jid})
        return GroupMetadata(**data.get("metadata", {}))

    def create_group(self, name: str, participants: Optional[list[str]] = None) -> dict:
        return self._send_command("create_group", {"name": name, "participants": participants or []})

    def add_participants(self, jid: str, participants: list[str]) -> dict:
        return self._send_command("add_participant", {"jid": jid, "participants": participants})

    def remove_participants(self, jid: str, participants: list[str]) -> dict:
        return self._send_command("remove_participant", {"jid": jid, "participants": participants})

    def promote_participants(self, jid: str, participants: list[str]) -> dict:
        return self._send_command("promote_participant", {"jid": jid, "participants": participants})

    def demote_participants(self, jid: str, participants: list[str]) -> dict:
        return self._send_command("demote_participant", {"jid": jid, "participants": participants})

    def leave_group(self, jid: str) -> dict:
        return self._send_command("leave_group", {"jid": jid})

    def update_group_name(self, jid: str, name: str) -> dict:
        return self._send_command("update_group_name", {"jid": jid, "name": name})

    def update_group_description(self, jid: str, description: str) -> dict:
        return self._send_command("update_group_description", {"jid": jid, "description": description})

    def get_avatar(self, jid: str) -> Optional[str]:
        data = self._send_command("get_avatar", {"jid": jid})
        return data.get("url")

    def set_avatar(self, jid: str, url: str) -> dict:
        return self._send_command("set_avatar", {"jid": jid, "url": url})

    def block_contact(self, jid: str) -> dict:
        return self._send_command("block_contact", {"jid": jid})

    def unblock_contact(self, jid: str) -> dict:
        return self._send_command("unblock_contact", {"jid": jid})

    def get_blocklist(self) -> list[str]:
        data = self._send_command("get_blocklist")
        return data.get("blocklist", [])

    def mark_read(self, jid: str) -> dict:
        return self._send_command("mark_read", {"jid": jid})

    def delete_message(self, jid: str, message_id: str) -> dict:
        return self._send_command("delete_message", {"jid": jid, "messageId": message_id})

    def react(self, jid: str, message_id: str, emoji: str) -> dict:
        return self._send_command("react", {"jid": jid, "messageId": message_id, "emoji": emoji})

    def get_my_number(self) -> dict:
        return self._send_command("get_my_number")

    def logout(self) -> dict:
        return self._send_command("logout")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.returncode is None
