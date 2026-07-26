from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface

from church_presenter.remote.server import DEFAULT_PORT, LAST_PORT, RemoteServerThread


@dataclass(frozen=True, slots=True)
class LocalAddress:
    address: str
    interface_name: str
    private: bool

    @property
    def label(self) -> str:
        return f"{self.address} · {self.interface_name}"


def discover_local_addresses() -> list[LocalAddress]:
    """Return active, non-loopback IPv4 interfaces without internet probing."""
    candidates: list[LocalAddress] = []
    required = (
        QNetworkInterface.InterfaceFlag.IsUp
        | QNetworkInterface.InterfaceFlag.IsRunning
    )
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if flags & required != required:
            continue
        if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            address = entry.ip()
            if address.protocol() is not QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            text = address.toString()
            try:
                parsed = ipaddress.ip_address(text)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
                continue
            candidates.append(
                LocalAddress(
                    text,
                    interface.humanReadableName() or interface.name(),
                    parsed.is_private,
                )
            )
    unique = {candidate.address: candidate for candidate in candidates}
    return sorted(
        unique.values(),
        key=lambda candidate: (not candidate.private, candidate.interface_name, candidate.address),
    )


class RemoteNetworkService(QObject):
    """Qt-facing lifecycle facade for the asyncio server thread."""

    state_changed = Signal(str, str)
    server_started = Signal(str, int, str)
    client_count_changed = Signal(int)
    input_received = Signal(object)
    _worker_started = Signal(int)
    _worker_state = Signal(str, str)
    _worker_clients = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: RemoteServerThread | None = None
        self._selected_address = ""
        self._token = ""
        self._port = 0
        self._client_count = 0
        self._worker_started.connect(self._on_started)
        self._worker_state.connect(self._on_state)
        self._worker_clients.connect(self._on_clients)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def client_count(self) -> int:
        return self._client_count

    @property
    def connection_url(self) -> str:
        if not self._selected_address or not self._port or not self._token:
            return ""
        return (
            f"http://{self._selected_address}:{self._port}/connect"
            f"?token={self._token}"
        )

    @property
    def token(self) -> str:
        return self._token

    def addresses(self) -> list[LocalAddress]:
        return discover_local_addresses()

    def start(self, address: str | None = None) -> bool:
        if self.running:
            if self.connection_url:
                self.server_started.emit(
                    self._selected_address,
                    self._port,
                    self.connection_url,
                )
            return True
        candidates = self.addresses()
        selected = address or (candidates[0].address if candidates else "")
        if selected not in {candidate.address for candidate in candidates}:
            self.state_changed.emit("no_address", "사용 가능한 로컬 IP가 없습니다.")
            return False
        self._selected_address = selected
        self._token = secrets.token_urlsafe(32)
        self._port = 0
        self._client_count = 0
        self.state_changed.emit("starting", "")
        thread = RemoteServerThread(
            token=self._token,
            first_port=DEFAULT_PORT,
            last_port=LAST_PORT,
            started=self._worker_started.emit,
            state_changed=self._worker_state.emit,
            client_count_changed=self._worker_clients.emit,
            input_received=self.input_received.emit,
        )
        self._thread = thread
        thread.start()
        return True

    def restart(self, address: str | None = None) -> bool:
        self.stop()
        return self.start(address)

    def stop(self) -> None:
        thread = self._thread
        self._token = ""
        self._port = 0
        self._client_count = 0
        if thread is not None:
            thread.request_stop()
            thread.join(timeout=2.0)
        self._thread = None
        self.client_count_changed.emit(0)
        self.state_changed.emit("stopped", "")

    def publish_frame(self, jpeg: bytes, metadata: dict[str, object]) -> None:
        thread = self._thread
        if thread is not None:
            thread.publish_frame(jpeg, metadata)

    @Slot(int)
    def _on_started(self, port: int) -> None:
        self._port = port
        self.server_started.emit(
            self._selected_address,
            port,
            self.connection_url,
        )

    @Slot(str, str)
    def _on_state(self, state: str, message: str) -> None:
        if state == "error":
            self._token = ""
            self._port = 0
        self.state_changed.emit(state, message)

    @Slot(int)
    def _on_clients(self, count: int) -> None:
        self._client_count = count
        self.client_count_changed.emit(count)
