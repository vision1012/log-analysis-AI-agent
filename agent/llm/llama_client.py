"""
LLaMA Client

OpenAI-compatible client for LLaMA models with retry handling.
Reads API key and base URL from environment variables.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class LLaMAClient:
    """
    Client for LLaMA models using OpenAI-compatible API.

    Reads configuration from environment variables:
        - LLAMA_API_KEY: API key for authentication
        - LLAMA_BASE_URL: Base URL for the API endpoint

    Usage:
        client = LLaMAClient()
        response = client.chat(
            messages=[{"role": "user", "content": "Hello"}],
            model="llama-3.1-8b",
            temperature=0.7
        )
    """

    def __init__(self):
        """
        Initialize the LLaMA client.

        Raises:
            ImportError: If openai package is not installed.
            ValueError: If required environment variables are not set.
        """
        if OpenAI is None:
            raise ImportError(
                "openai package is required. Install with: pip install openai"
            )

        self.api_key = os.getenv("LLAMA_API_KEY")
        self.base_url = os.getenv("LLAMA_BASE_URL")

        if not self.api_key:
            raise ValueError(
                "LLAMA_API_KEY environment variable is required but not set."
            )
        if not self.base_url:
            raise ValueError(
                "LLAMA_BASE_URL environment variable is required but not set."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> str:
        """
        Send a chat request to the LLaMA model.

        Args:
            messages: List of message dicts with "role" and "content" keys.
                     Example: [{"role": "user", "content": "Hello"}]
            model: Model name (e.g. "llama-3.1-8b", "llama-3.1-70b").
            temperature: Sampling temperature (0.0 to 2.0). Default: 0.7.

        Returns:
            Assistant's text response as a string.

        Raises:
            ValueError: If messages format is invalid.
            RuntimeError: If all retries are exhausted.
        """
        if not messages:
            raise ValueError("messages list cannot be empty")

        if not isinstance(messages, list):
            raise ValueError("messages must be a list of dicts")

        for msg in messages:
            if not isinstance(msg, dict):
                raise ValueError("Each message must be a dict")
            if "role" not in msg or "content" not in msg:
                raise ValueError(
                    'Each message must have "role" and "content" keys'
                )

        max_retries = 2
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )

                if not response.choices:
                    raise RuntimeError("Empty response from API")

                assistant_message = response.choices[0].message
                if not assistant_message or not assistant_message.content:
                    raise RuntimeError("No content in assistant message")

                return assistant_message.content.strip()

            except Exception as exc:
                error_str = str(exc).lower()
                is_retryable = any(
                    keyword in error_str
                    for keyword in [
                        "rate limit",
                        "timeout",
                        "server error",
                        "503",
                        "502",
                        "500",
                        "429",
                        "connection",
                    ]
                )

                if attempt < max_retries and is_retryable:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue

                raise RuntimeError(
                    f"LLaMA API call failed after {attempt + 1} attempt(s): {exc}"
                ) from exc

        raise RuntimeError("Unexpected error: retry loop exhausted")
