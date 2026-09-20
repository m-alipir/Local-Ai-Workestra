from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx

from local_agent_orchestrator.services.resource_guard import (
    ResourceSnapshot,
    assert_safe_to_start_model,
    wait_for_model_release,
)


class LlamaServerError(RuntimeError):
    pass


class LlamaServerEmptyContentError(LlamaServerError):
    """The server completed without a textual assistant answer."""


class LlamaServer:
    def __init__(
        self,
        hf_model: str,
        context: int = 8192,
        port: int = 8080,
        binary: str | Path = "~/llama.cpp/build/bin/llama-server",
        model_path: str | Path | None = None,
        flash_attention: bool = False,
        minimum_free_ram_gb: float = 2.0,
        minimum_free_vram_gb: float = 1.0,
        start_timeout: int = 120,
        stop_timeout: int = 20,
        reasoning: str = "medium",
    ) -> None:
        self.hf_model = hf_model
        self.context = context
        self.port = port
        self.binary = Path(binary).expanduser()
        self.model_path = (
            Path(model_path).expanduser() if model_path is not None else None
        )
        self.flash_attention = flash_attention
        self.minimum_free_ram_gb = minimum_free_ram_gb
        self.minimum_free_vram_gb = minimum_free_vram_gb
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.reasoning = reasoning

        self.process: subprocess.Popen[str] | None = None
        self._baseline_resources: ResourceSnapshot | None = None

    def _reasoning_args(self) -> list[str]:
        if self.reasoning == "none":
            return [
                "--reasoning",
                "off",
            ]

        effort_map = {
            "low": "low",
            "medium": "medium",
            "medium_high": "high",
            "high": "xhigh",
        }

        try:
            effort = effort_map[self.reasoning]
        except KeyError as exc:
            raise LlamaServerError(
                f"Unsupported reasoning level: {self.reasoning}"
            ) from exc

        return [
            "--reasoning",
            "on",
            "--reasoning-effort",
            effort,
        ]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise LlamaServerError("llama-server is already running.")

        self._baseline_resources = assert_safe_to_start_model(
            self.minimum_free_ram_gb,
            self.minimum_free_vram_gb,
        )

        try:
            if not self.binary.exists():
                raise LlamaServerError(
                    f"llama-server binary not found: {self.binary}"
                )
            if self.model_path is not None and not self.model_path.exists():
                raise LlamaServerError(
                    f"local model not found: {self.model_path}"
                )

            command = [
                str(self.binary),
            ]
            if self.model_path is None:
                command.extend(["-hf", self.hf_model])
            else:
                command.extend(["-m", str(self.model_path)])

            command.extend([
                "-ngl",
                "99",
                "-c",
                str(self.context),
                "--port",
                str(self.port),
            ])
            if self.flash_attention:
                command.extend(["-fa", "on"])

            command.extend(
                self._reasoning_args()
            )

            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            deadline = time.monotonic() + self.start_timeout

            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise LlamaServerError(
                        "llama-server exited with code "
                        f"{self.process.returncode}"
                    )

                try:
                    response = httpx.get(
                        f"{self.base_url}/health",
                        timeout=2.0,
                    )
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass

                time.sleep(1)

            raise LlamaServerError(
                f"llama-server did not become ready within "
                f"{self.start_timeout} seconds."
            )
        except Exception as exc:
            try:
                self.stop()
            except Exception as cleanup_exc:
                exc.add_note(
                    f"llama-server cleanup failed: {cleanup_exc}"
                )
            raise

    def chat(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        response_format: dict | None = None,
        reasoning_effort: str | None = None,
        chat_template_kwargs: dict | None = None,
        require_content: bool = False,
    ) -> str:
        messages: list[dict[str, str]] = []

        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        request_body: dict = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if response_format is not None:
            request_body["response_format"] = response_format
        if reasoning_effort is not None:
            request_body["reasoning_effort"] = reasoning_effort
        if chat_template_kwargs is not None:
            request_body["chat_template_kwargs"] = chat_template_kwargs

        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=request_body,
            timeout=300.0,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlamaServerError(
                f"llama-server returned HTTP {response.status_code}: "
                f"{response.text[:4000]}"
            ) from exc

        data = response.json()

        try:
            message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError("message must be an object")

            content = message.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise TypeError("message.content must be text")
            if not content and require_content:
                finish_reason = data["choices"][0].get("finish_reason")
                fields = ",".join(sorted(message)) or "none"
                reasoning_present = bool(
                    message.get("reasoning_content")
                    or message.get("reasoning")
                )
                raise LlamaServerEmptyContentError(
                    "llama-server returned empty assistant content "
                    f"(finish_reason={finish_reason!r}; message_fields={fields}; "
                    f"reasoning_content_present={reasoning_present})"
                )
            return content
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaServerError(
                f"Unexpected llama-server response: {data}"
            ) from exc

    def stop(self) -> None:
        process = self.process
        self.process = None

        if process is not None:
            if process.poll() is None:
                process.terminate()

                try:
                    process.wait(timeout=self.stop_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        baseline = self._baseline_resources
        self._baseline_resources = None

        if baseline is not None:
            wait_for_model_release(
                baseline=baseline,
                timeout=self.stop_timeout,
            )

    def __enter__(self) -> LlamaServer:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
