import json
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - handled at runtime
    httpx = None


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout_seconds: float = 60.0,
    ) -> None:
        if httpx is None:
            raise RuntimeError(
                "httpx is required for DeepSeek integration. "
                "Please install dependencies from requirements.txt."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = self._post_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return self._extract_content(payload)

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = self._post_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
        )
        content = self._extract_content(payload)
        if not content:
            raise ValueError("DeepSeek returned empty content for JSON output.")
        return json.loads(content)

    def _post_chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "max_tokens": 1200,
        }
        if response_format is not None:
            body["response_format"] = response_format

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            return response.json()

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("DeepSeek response did not contain choices.")
        message = choices[0].get("message", {})
        return message.get("content", "") or ""
