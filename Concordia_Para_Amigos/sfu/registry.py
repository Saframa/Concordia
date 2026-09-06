"""
SFU Client Registry Module.

Provides a thread-safe, Copy-on-Write (COW) client registry backed by an immutable dictionary.
Mutations (register / unregister) acquire a threading.Lock, while high-frequency read operations
(membership test, recipient snapshot list) on the audio forwarding path are completely lock-free.
"""

import threading
from typing import Dict, List, Tuple


ClientAddress = Tuple[str, int]


class ClientRegistry:
    """
    Thread-safe Copy-on-Write (COW) registry of connected client UDP addresses and usernames.

    Attributes:
        _lock (threading.Lock): Synchronizes write operations.
        _clients (dict): Immutable snapshot of active (ip, port) -> username mapping.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: Dict[ClientAddress, str] = {}

    def register(self, client: ClientAddress, username: str) -> bool:
        """
        Register a client address with a username.

        Returns True if the client was newly added or username changed.
        """
        with self._lock:
            if client in self._clients and self._clients[client] == username:
                return False
            
            # COW: Create a new dictionary and swap the reference
            new_clients = self._clients.copy()
            new_clients[client] = username
            self._clients = new_clients
            return True

    def unregister(self, client: ClientAddress) -> bool:
        """
        Unregister a client address.

        Idempotent: If client is not currently registered, returns False without error.
        Returns True if the client was removed.
        """
        with self._lock:
            if client not in self._clients:
                return False
            
            new_clients = self._clients.copy()
            del new_clients[client]
            self._clients = new_clients
            return True

    def is_registered(self, client: ClientAddress) -> bool:
        """
        Check if a client address is currently registered.
        Lock-free atomic reference lookup.
        """
        return client in self._clients

    def get_recipients(self, sender: ClientAddress) -> List[ClientAddress]:
        """
        Get the list of recipient client addresses for an audio packet from sender.
        
        Strict Anti-Echo Enforcement:
        - If sender is not in the registry, returns an empty list (packet must be dropped).
        - If sender is registered, returns all registered clients EXCEPT the sender.
        
        Lock-free atomic snapshot read:
        Safe against concurrent register/unregister calls without thread blocking.
        """
        snapshot = self._clients
        if sender not in snapshot:
            return []
        return [c for c in snapshot if c != sender]

    @property
    def clients(self) -> Dict[ClientAddress, str]:
        """Return an immutable snapshot of all currently registered client addresses and usernames."""
        return self._clients

    def get_all_usernames(self) -> List[str]:
        """Return a list of all currently connected usernames."""
        return list(self._clients.values())

    def clear(self) -> None:
        """Clear all registered clients."""
        with self._lock:
            self._clients = {}

    def __len__(self) -> int:
        """Return the number of currently registered clients."""
        return len(self._clients)

    def __contains__(self, client: ClientAddress) -> bool:
        """Membership test for client address."""
        return client in self._clients

    def __repr__(self) -> str:
        return f"ClientRegistry(count={len(self._clients)}, clients={self._clients})"
