"""LLM client: DeepSeek + Gemini.

Unified interface for all LLM calls used by the Wiki system.
Phase 3: Added exponential backoff retry for API resilience.
"""
import json
import time
import random
import warnings
from functools import wraps
from typing import Generator, Optional

# Suppress urllib3 compatibility warnings (happens at requests import time)
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*charset_normalizer.*")

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from core.config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, GEMINI_API_KEY, GEMINI_API_URL, MODEL_PRO, MODEL_FAST, MODEL_VISION

MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds


def retry_with_backoff(func):
    """Decorator: retry API calls with exponential backoff + jitter."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.RequestException, requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                    print(f"\n  \033[90m[Retry {attempt + 1}/{MAX_RETRIES}] LLM call failed, retrying in {delay:.1f}s...\033[0m")
                    time.sleep(delay)
                else:
                    raise
        raise last_exception
    return wrapper


class LLMClient:
    """Unified LLM client supporting DeepSeek (text) and Gemini (vision)."""

    def __init__(self, api_key: str = None):
        self.deepseek_key = api_key or DEEPSEEK_API_KEY

    @retry_with_backoff
    def chat_sync(self, messages: list[dict], model: str = MODEL_PRO,
                  temperature: float = 0.7, max_tokens: int = 4096) -> str:
        """Synchronous chat completion. For classification / short tasks.
        Retries with exponential backoff on network errors."""
        headers = {"Authorization": f"Bearer {self.deepseek_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, verify=False, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _stream_request(self, messages: list[dict], model: str,
                        temperature: float, max_tokens: int):
        """Make the streaming HTTP request with retry. Returns response object."""
        headers = {"Authorization": f"Bearer {self.deepseek_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload,
                                     verify=False, stream=True, timeout=(10, 300))
                resp.raise_for_status()
                return resp
            except (requests.exceptions.RequestException, requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as e:
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                    print(f"\n  \033[90m[Retry {attempt + 1}/{MAX_RETRIES}] LLM stream failed, retrying in {delay:.1f}s...\033[0m")
                    time.sleep(delay)
                else:
                    raise
        raise RuntimeError("Stream request failed after all retries")

    def chat_stream(self, messages: list[dict], model: str = MODEL_FAST,
                    temperature: float = 0.7, max_tokens: int = 4096) -> Generator[str, None, str]:
        """Streaming chat completion. Yields tokens, returns final full response.
        
        For deepseek-reasoner, reasoning_content is shown in dim text prefix.
        Retries with exponential backoff on connection failures.
        """
        resp = self._stream_request(messages, model, temperature, max_tokens)

        full_response = ""
        is_reasoner = "reasoner" in model
        reasoning_done = False

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"]

                # Handle reasoning_content (deepseek-reasoner only)
                if is_reasoner and "reasoning_content" in delta and delta["reasoning_content"]:
                    if not reasoning_done:
                        yield "\n  [thinking...] "
                        reasoning_done = True
                    yield delta["reasoning_content"]
                    continue

                if "content" in delta and delta["content"] is not None:
                    if is_reasoner and reasoning_done:
                        yield "\n  [response]\n"
                        reasoning_done = True  # prevent duplicate marker
                    reasoning_done = True
                    token = delta["content"]
                    yield token
                    full_response += token
            except (KeyError, json.JSONDecodeError):
                continue
        return full_response

    def classify(self, text: str, categories: list[str] = None) -> str:
        """Lightweight classification. Returns category string."""
        if categories is None:
            categories = ["study", "fitness", "economy", "general"]
        prompt = (
            f"Classify this user message into one category: {', '.join(categories)}.\n"
            f"Respond with only the category name, nothing else.\n\n"
            f"Message: {text}\n\n"
            f"Category:"
        )
        result = self.chat_sync(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_FAST,
            temperature=0.0,
            max_tokens=10,
        )
        return result.strip().lower()

    def summarize(self, text: str, max_chars: int = 300) -> str:
        """Summarize text concisely."""
        prompt = f"Summarize the following in Korean, under {max_chars} characters. Be concise:\n\n{text}"
        return self.chat_sync(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_FAST,
            temperature=0.3,
            max_tokens=min(max_chars // 2, 500),
        )

    @retry_with_backoff
    def vision(self, image_path: str, prompt: str) -> str:
        """Gemini Vision API for image analysis."""
        import base64
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set.")

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        mime = "image/png"
        if image_path.lower().endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": image_data}},
                ]
            }]
        }
        resp = requests.post(
            f"{GEMINI_API_URL}/{MODEL_VISION}:generateContent?key={GEMINI_API_KEY}",
            json=payload,
            verify=False,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
