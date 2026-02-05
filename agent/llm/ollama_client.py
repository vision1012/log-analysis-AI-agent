"""
Ollama client for local LLM inference.

This module provides an HTTP client for interacting with Ollama's API,
which serves local language models.
"""

import json
import time
from typing import List, Dict, Optional
import requests


class OllamaClient:
    """
    Client for interacting with Ollama API via HTTP.
    
    Ollama runs locally and serves models at http://localhost:11434/api/chat.
    This client converts OpenAI-style message formats to Ollama's format.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout: int = 120,
        max_retries: int = 2,
    ):
        """
        Initialize the Ollama client.

        Args:
            base_url: Base URL for Ollama API. Default: http://localhost:11434
            model: Model name to use. Default: llama3
            timeout: Request timeout in seconds. Default: 120
            max_retries: Maximum number of retries for transient failures. Default: 2
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.chat_endpoint = f"{self.base_url}/api/chat"

    def _check_ollama_running(self) -> bool:
        """
        Check if Ollama service is running.

        Returns:
            True if Ollama is accessible, False otherwise.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            return response.status_code == 200
        except (requests.exceptions.RequestException, requests.exceptions.Timeout):
            return False

    def _convert_messages_to_ollama_format(
        self, messages: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Convert OpenAI-style messages to Ollama format.

        Ollama expects messages in the format:
        [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
        ]

        Args:
            messages: List of messages in OpenAI format (role: system|user|assistant, content: str)

        Returns:
            List of messages in Ollama format
        """
        ollama_messages = []
        system_prompt_parts = []

        for msg in messages:
            role = msg.get("role", "").lower()
            content = msg.get("content", "")

            if role == "system":
                # Ollama doesn't have a separate system role, so we prepend it to the first user message
                system_prompt_parts.append(content)
            elif role == "user":
                # If we have accumulated system prompts, prepend them to this user message
                if system_prompt_parts:
                    full_content = "\n\n".join(system_prompt_parts) + "\n\n" + content
                    ollama_messages.append({"role": "user", "content": full_content})
                    system_prompt_parts = []  # Clear after using
                else:
                    ollama_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                ollama_messages.append({"role": "assistant", "content": content})

        # If there are leftover system prompts and no user messages, add them as the first user message
        if system_prompt_parts and not ollama_messages:
            ollama_messages.append(
                {"role": "user", "content": "\n\n".join(system_prompt_parts)}
            )

        return ollama_messages

    def chat(
        self, messages: List[Dict[str, str]], temperature: float = 0.2
    ) -> str:
        """
        Send a chat request to Ollama and return the assistant's response.

        Args:
            messages: List of messages in OpenAI format:
                [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: Sampling temperature (0.0 to 1.0). Default: 0.2

        Returns:
            The assistant's message content as a string.

        Raises:
            RuntimeError: If Ollama is not running or if the request fails after retries.
        """
        # Check if Ollama is running
        if not self._check_ollama_running():
            raise RuntimeError(
                f"Ollama is not running. Please start Ollama service at {self.base_url}"
            )

        # Convert messages to Ollama format
        ollama_messages = self._convert_messages_to_ollama_format(messages)

        # Prepare request payload
        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self.chat_endpoint,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                # Parse response
                result = response.json()
                assistant_message = result.get("message", {}).get("content", "")

                if not assistant_message:
                    raise RuntimeError(
                        f"Ollama returned empty response: {result}"
                    )

                return assistant_message

            except requests.exceptions.Timeout as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt  # Exponential backoff
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(
                    f"Ollama request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries + 1})"
                ) from e

            except requests.exceptions.ConnectionError as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(
                    f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"
                ) from e

            except requests.exceptions.HTTPError as e:
                # HTTP errors (4xx, 5xx) are not retried
                raise RuntimeError(
                    f"Ollama API returned error: {e.response.status_code} - {e.response.text}"
                ) from e

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(
                    f"Ollama request failed after {attempt + 1} attempts: {str(e)}"
                ) from e

        # Should not reach here, but handle edge case
        raise RuntimeError(
            f"Ollama request failed after all retries: {str(last_exception)}"
        ) from last_exception
