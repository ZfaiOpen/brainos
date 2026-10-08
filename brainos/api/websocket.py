# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See the LICENSE file for details.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.websocket")


class WSMessageType(Enum):
    TEXT = "text"
    BINARY = "binary"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    ERROR = "error"


@dataclass
class WSMessage:
    message_id: str = ""
    msg_type: WSMessageType = WSMessageType.TEXT
    payload: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""

    def __post_init__(self) -> None:
        if not self.message_id:
            self.message_id = f"wsmsg_{uuid.uuid4().hex[:8]}"

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "type": self.msg_type.value,
            "payload": self.payload,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    @logged()
    @safe_execute
    def to_json(self):
        pass


    @classmethod
    @logged()
    @safe_execute
    def from_json(cls, raw: str) -> WSMessage:
        try:
            data = json.loads(raw)
            return cls(
                message_id=data.get("message_id", ""),
                msg_type=WSMessageType(data.get("type", "text")),
                payload=data.get("payload", ""),
                data=data.get("data", {}),
                source=data.get("source", ""),
            )
        except (json.JSONDecodeError, ValueError):
            return cls(payload=raw)



    def _json_default(obj):
        pass
@dataclass
class WSClient:
    client_id: str = ""
    connection_id: str = ""
    channels: set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    messages_sent: int = 0
    messages_received: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.client_id:
            self.client_id = f"wsclient_{uuid.uuid4().hex[:8]}"
        if not self.connection_id:
            self.connection_id = f"conn_{uuid.uuid4().hex[:6]}"

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "connection_id": self.connection_id,
            "channels": list(self.channels),
            "connected_at": self.connected_at,
            "last_active": self.last_active,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
        }

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.connected_at


@dataclass
class Channel:
    name: str = ""
    subscribers: set[str] = field(default_factory=set)
    message_count: int = 0
    created_at: float = field(default_factory=time.time)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "subscriber_count": len(self.subscribers),
            "message_count": self.message_count,
        }


@dataclass
class WebSocketConfig:
    max_clients: int = 100
    max_channels: int = 50
    max_message_size: int = 65536
    heartbeat_interval_seconds: float = 30.0
    idle_timeout_seconds: float = 300.0
    max_messages_per_second: float = 10.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "max_clients": self.max_clients,
            "max_channels": self.max_channels,
            "max_message_size": self.max_message_size,
        }


WSMessageHandler = Callable[[WSClient, WSMessage], WSMessage | None]


class WebSocketHub:
    def __init__(self, config: WebSocketConfig | None = None) -> None:
        self._config = config or WebSocketConfig()
        self._clients: dict[str, WSClient] = {}
        self._channels: dict[str, Channel] = {}
        self._message_handlers: list[WSMessageHandler] = []
        self._message_history: list[dict[str, Any]] = []
        self._total_messages: int = 0
        self._start_time: float = time.time()

    @logged()
    @safe_execute
    def connect(self, client_id: str = "", metadata: dict[str, Any] | None = None) -> WSClient:
        if len(self._clients) >= self._config.max_clients:
            msg = f"Max clients reached ({self._config.max_clients})"
            raise ConnectionRefusedError(msg)
        client = WSClient(client_id=client_id, metadata=metadata or {})
        self._clients[client.client_id] = client
        logger.info("WebSocket client connected: %s", client.client_id)
        return client

    @logged()
    @safe_execute
    def disconnect(self, client_id: str) -> bool:
        client = self._clients.pop(client_id, None)
        if client is None:
            return False
        for channel_name in client.channels:
            channel = self._channels.get(channel_name)
            if channel:
                channel.subscribers.discard(client_id)
        logger.info("WebSocket client disconnected: %s", client_id)
        return True

    @logged()
    @safe_execute
    def subscribe(self, client_id: str, channel_name: str) -> bool:
        client = self._clients.get(client_id)
        if client is None:
            return False
        if channel_name not in self._channels:
            if len(self._channels) >= self._config.max_channels:
                return False
            self._channels[channel_name] = Channel(name=channel_name)
        self._channels[channel_name].subscribers.add(client_id)
        client.channels.add(channel_name)
        client.last_active = time.monotonic()
        logger.debug("Client %s subscribed to %s", client_id, channel_name)
        return True

    @logged()
    @safe_execute
    def unsubscribe(self, client_id: str, channel_name: str) -> bool:
        client = self._clients.get(client_id)
        if client is None:
            return False
        channel = self._channels.get(channel_name)
        if channel:
            channel.subscribers.discard(client_id)
        client.channels.discard(channel_name)
        return True

    @logged()
    @safe_execute
    def broadcast(self, message: WSMessage, channel: str | None = None, exclude: str | None = None) -> int:
        recipients: list[str] = []
        if channel:
            ch = self._channels.get(channel)
            if ch is None:
                return 0
            recipients = [cid for cid in ch.subscribers if cid != exclude]
        else:
            recipients = [cid for cid in self._clients if cid != exclude]

        for handler in self._message_handlers:
            try:
                for cid in recipients:
                    client = self._clients.get(cid)
                    if client:
                        result = handler(client, message)
                        if result:
                            self._total_messages += 1
                            client.messages_received += 1
            except Exception as _exc:
                logger.exception("Message handler error")

        self._record_message(message, channel, len(recipients))
        return len(recipients)

    @logged()
    @safe_execute
    def send_to(self, client_id: str, message: WSMessage) -> bool:
        client = self._clients.get(client_id)
        if client is None:
            return False
        client.messages_received += 1
        client.last_active = time.monotonic()
        self._total_messages += 1
        self._record_message(message, None, 1)
        return True

    @logged()
    @safe_execute
    def add_handler(self, handler: WSMessageHandler) -> None:
        self._message_handlers.append(handler)

    def _record_message(self, message: WSMessage, channel: str | None, recipient_count: int) -> None:
        self._message_history.append(
            {
                "message_id": message.message_id,
                "type": message.msg_type.value,
                "channel": channel,
                "recipient_count": recipient_count,
                "timestamp": message.timestamp,
            }
        )
        if len(self._message_history) > 500:
            self._message_history = self._message_history[-500:]

    @logged()
    @safe_execute
    def get_client(self, client_id: str) -> WSClient | None:
        return self._clients.get(client_id)

    @logged()
    @safe_execute
    def list_clients(self, channel: str | None = None) -> list[dict[str, Any]]:
        clients = list(self._clients.values())
        if channel:
            clients = [c for c in clients if channel in c.channels]
        return [c.to_dict() for c in clients]

    @logged()
    @safe_execute
    def list_channels(self) -> list[dict[str, Any]]:
        return [ch.to_dict() for ch in self._channels.values()]

    @logged()
    @safe_execute
    def get_channel_info(self, name: str) -> dict[str, Any] | None:
        ch = self._channels.get(name)
        return ch.to_dict() if ch else None

    @logged()
    @safe_execute
    def cleanup_idle(self) -> int:
        cutoff = time.monotonic() - self._config.idle_timeout_seconds
        idle = [cid for cid, c in self._clients.items() if c.last_active < cutoff]
        for cid in idle:
            self.disconnect(cid)
        if idle:
            logger.info("Cleaned up %d idle WebSocket clients", len(idle))
        return len(idle)

    @logged()
    @safe_execute
    def get_message_history(self, channel: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        history = self._message_history
        if channel:
            history = [h for h in history if h.get("channel") == channel]
        return history[-limit:]

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time
        return {
            "connected_clients": len(self._clients),
            "total_channels": len(self._channels),
            "total_messages": self._total_messages,
            "uptime_seconds": round(uptime, 1),
            "history_size": len(self._message_history),
            "config": self._config.to_dict(),
        }
