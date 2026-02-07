"""
LLM Gateway with fallback support.
Abstract interface for multiple LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from loguru import logger
import httpx
import json

from config import get_settings


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
        
        async with httpx.AsyncClient(timeout=120.0) as client:
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
        
        async with httpx.AsyncClient(timeout=60.0) as client:
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
        
        async with httpx.AsyncClient(timeout=120.0) as client:
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


class LLMGateway:
    """
    LLM Gateway with automatic fallback support.
    Tries primary provider first, falls back on failure.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._providers: Dict[str, LLMProvider] = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize available providers based on API keys."""
        if self.settings.openai_api_key:
            self._providers["openai"] = OpenAIProvider(
                self.settings.openai_api_key,
                self.settings.fallback_model
            )
        
        if self.settings.groq_api_key:
            self._providers["groq"] = GroqProvider(
                self.settings.groq_api_key,
                self.settings.default_model
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
                    logger.error(f"Fallback provider {fallback_provider} also failed: {e}")
                    raise
        
        raise Exception("No LLM providers available or all failed")
