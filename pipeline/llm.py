"""LLM clients.

LocalClient    an open-weight model on an OpenAI-compatible server such as Ollama (the default)
AmplifyClient  Vanderbilt's Amplify API (needs AMPLIFY_API_KEY in the environment or .env)
ReplayClient   canned replies for tests and dry runs

.env is gitignored. Never commit a key.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE_URL = "https://prod-api.vanderbilt.ai"


def load_api_key():
    key = os.environ.get("AMPLIFY_API_KEY")
    env = REPO / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "AMPLIFY_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("No Amplify key. Put AMPLIFY_API_KEY=... in .env at the repo root.")
    return key


class AmplifyClient:
    name = "amplify"

    def __init__(self, model, temperature=0.7, max_tokens=8000, timeout=300, api_key=None):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.api_key = api_key or load_api_key()

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def chat(self, messages):
        import requests

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        body = {"data": {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "dataSources": [],
            "messages": messages,
            # The Amplify docs show options.prompt next to the messages; we send the system prompt
            # there. Confirm against a live response once a key is available.
            "options": {"ragOnly": False, "skipRag": True, "model": {"id": self.model}, "prompt": system},
        }}
        resp = requests.post(f"{BASE_URL}/chat", headers=self._headers(), json=body, timeout=self.timeout)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return resp.text  # streamed plain text
        if not payload.get("success", True):
            raise RuntimeError(f"Amplify error: {payload.get('message')}")
        return payload.get("data", "")

    def describe(self):
        return {"client": self.name, "model": self.model, "temperature": self.temperature,
                "max_tokens": self.max_tokens}


def list_models(api_key=None):
    import requests

    key = api_key or load_api_key()
    resp = requests.get(f"{BASE_URL}/available_models", headers={"Authorization": f"Bearer {key}"},
                        timeout=60)
    resp.raise_for_status()
    return resp.json()


LOCAL_URL = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")


class LocalClient:
    """Any OpenAI-compatible server: Ollama (default port 11434), LM Studio, vLLM.
    Set the server with --base-url or LOCAL_LLM_URL."""
    name = "local"

    def __init__(self, model, temperature=0.7, max_tokens=8000, timeout=900, base_url=LOCAL_URL, seed=None):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.seed = seed

    def chat(self, messages):
        import requests

        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens, "stream": False}
        if self.seed is not None:
            body["seed"] = self.seed
        resp = requests.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def describe(self):
        return {"client": self.name, "model": self.model, "temperature": self.temperature,
                "max_tokens": self.max_tokens, "base_url": self.base_url, "seed": self.seed}


def list_local_models(base_url=LOCAL_URL):
    import requests

    resp = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=30)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]


class ReplayClient:
    """Returns the given replies in order. For tests and offline dry runs."""
    name = "replay"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        if not self.replies:
            raise RuntimeError("ReplayClient ran out of replies")
        return self.replies.pop(0)

    def describe(self):
        return {"client": self.name}
