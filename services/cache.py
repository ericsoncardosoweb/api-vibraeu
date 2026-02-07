"""
In-Memory TTL Cache for VibraEU API.
Lightweight cache to avoid redundant Supabase queries.
"""

import time
from typing import Any, Optional, Dict
from loguru import logger


class TTLCache:
    """Simple in-memory cache with TTL (Time To Live)."""
    
    def __init__(self, default_ttl: int = 300):
        """
        Args:
            default_ttl: Default TTL in seconds (5 min)
        """
        self._store: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache. Returns None if expired or missing."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        
        if time.time() > entry["expires_at"]:
            del self._store[key]
            self._misses += 1
            return None
        
        self._hits += 1
        return entry["value"]
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache with optional custom TTL."""
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + (ttl or self._default_ttl)
        }
    
    def invalidate(self, key: str):
        """Remove specific key from cache."""
        self._store.pop(key, None)
    
    def invalidate_prefix(self, prefix: str):
        """Remove all keys starting with prefix."""
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._store[k]
    
    def clear(self):
        """Clear entire cache."""
        self._store.clear()
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{(self._hits / total * 100):.1f}%" if total > 0 else "0%",
            "entries": len(self._store),
            "total_requests": total
        }


# === Global cache instances ===
# Dados que mudam raramente (templates, variáveis)
db_cache = TTLCache(default_ttl=300)  # 5 min

# Respostas de endpoints públicos (frases do dia)
response_cache = TTLCache(default_ttl=120)  # 2 min
