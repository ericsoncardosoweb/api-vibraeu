"""
LLM Gateway with fallback support and connection pooling.
Abstract interface for multiple LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from loguru import logger
import httpx
import json

from config import get_settings


# ============================================================================
# Global HTTP client with connection pooling
# Reused across all LLM providers — avoids TCP+TLS handshake per request
# ============================================================================
_http_client: Optional[httpx.AsyncClient] = None


async def get_http_client() -> httpx.AsyncClient:
    """Get or create the global HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30
            ),
            timeout=httpx.Timeout(120.0, connect=10.0)
        )
        logger.info("🔌 HTTP connection pool initialized (max=20, keepalive=10)")
    return _http_client


async def close_http_client():
    """Close the global HTTP client (call on shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
        logger.info("🔌 HTTP connection pool closed")


# ============================================================================
# LLM Providers
# ============================================================================

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate text from prompt."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""
    
    def __init__(self, api_key: str, model: str = "gpt-4.1-mini"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.openai.com/v1/chat/completions"
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        client = await get_http_client()
        response = await client.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


class GroqProvider(LLMProvider):
    """Groq API provider for fast inference."""
    
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        client = await get_http_client()
        response = await client.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""
    
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Entendido. Vou seguir essas instruções."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        client = await get_http_client()
        response = await client.post(
            f"{self.base_url}?key={self.api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens
                }
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


# ============================================================================
# LLM Gateway (singleton)
# ============================================================================

class LLMGateway:
    """
    LLM Gateway with automatic fallback support.
    Tries primary provider first, falls back on failure.
    """
    
    _instance: Optional['LLMGateway'] = None
    
    def __init__(self):
        self.settings = get_settings()
        self._providers: Dict[str, LLMProvider] = {}
        self._call_count = 0
        self._error_count = 0
        self._initialize_providers()
    
    @classmethod
    def get_instance(cls) -> 'LLMGateway':
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _initialize_providers(self):
        """Initialize available providers based on API keys."""
        # Diagnostic: log loaded settings
        openai_key = self.settings.openai_api_key or ""
        groq_key = self.settings.groq_api_key or ""
        logger.info(
            f"LLM Config loaded: "
            f"default={self.settings.default_provider}/{self.settings.default_model}, "
            f"fallback={self.settings.fallback_provider}/{self.settings.fallback_model}, "
            f"openai_key={openai_key[:8]}...{openai_key[-4:] if len(openai_key) > 12 else '??'}, "
            f"groq_key={groq_key[:8]}...{groq_key[-4:] if len(groq_key) > 12 else '??'}"
        )
        
        if self.settings.openai_api_key:
            self._providers["openai"] = OpenAIProvider(
                self.settings.openai_api_key,
                "gpt-4.1-mini"
            )
        
        if self.settings.groq_api_key:
            self._providers["groq"] = GroqProvider(
                self.settings.groq_api_key,
                "llama-3.3-70b-versatile"
            )
        
        if self.settings.gemini_api_key:
            self._providers["gemini"] = GeminiProvider(
                self.settings.gemini_api_key
            )
        
        logger.info(f"Initialized LLM providers: {list(self._providers.keys())}")
    
    def _get_provider(self, name: str, model: Optional[str] = None) -> Optional[LLMProvider]:
        """Get a provider by name, optionally with custom model."""
        provider = self._providers.get(name)
        if provider and model:
            # Create new instance with custom model
            if name == "openai":
                return OpenAIProvider(self.settings.openai_api_key, model)
            elif name == "groq":
                return GroqProvider(self.settings.groq_api_key, model)
            elif name == "gemini":
                return GeminiProvider(self.settings.gemini_api_key, model)
        return provider
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get gateway statistics."""
        return {
            "providers": list(self._providers.keys()),
            "total_calls": self._call_count,
            "errors": self._error_count,
            "error_rate": f"{(self._error_count / self._call_count * 100):.1f}%" if self._call_count > 0 else "0%"
        }
    
    async def generate(
        self,
        prompt: str,
        config: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generate text using configured LLM with fallback support.
        
        Args:
            prompt: The user prompt
            config: LLM configuration (provider, model, fallback, temperature, max_tokens)
            system_prompt: Optional system prompt
            
        Returns:
            Generated text
            
        Raises:
            Exception if all providers fail
        """
        self._call_count += 1
        config = config or {}
        
        # Get config values
        primary_provider = config.get("provider", self.settings.default_provider)
        primary_model = config.get("model", self.settings.default_model)
        fallback_provider = config.get("fallback_provider", self.settings.fallback_provider)
        fallback_model = config.get("fallback_model", self.settings.fallback_model)
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)
        
        # Try primary provider
        provider = self._get_provider(primary_provider, primary_model)
        if provider:
            try:
                logger.info(f"Calling {primary_provider} with model {primary_model}")
                result = await provider.generate(
                    prompt, 
                    system_prompt, 
                    temperature, 
                    max_tokens
                )
                logger.info(f"Successfully generated with {primary_provider}")
                return result
            except Exception as e:
                self._error_count += 1
                logger.warning(f"Primary provider {primary_provider} failed: {e}")
        
        # Try fallback provider
        if fallback_provider:
            fallback = self._get_provider(fallback_provider, fallback_model)
            if fallback:
                try:
                    logger.info(f"Falling back to {fallback_provider} with model {fallback_model}")
                    result = await fallback.generate(
                        prompt,
                        system_prompt,
                        temperature,
                        max_tokens
                    )
                    logger.info(f"Successfully generated with fallback {fallback_provider}")
                    return result
                except Exception as e:
                    self._error_count += 1
                    logger.error(f"Fallback provider {fallback_provider} also failed: {e}")
                    raise
        
        raise Exception("No LLM providers available or all failed")
