import time
from typing import Any

import requests

from .log import log_fail, log_info, log_success



def run_llm(
    messages: list[dict[str, Any]],
    model: str,
    base_url: str,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """
    Return generated text; raise on request errors or incomplete output.

    :param messages: The input prompt
    :param model: The LLM model
    :param base_url: The URL of the LLM server
    :param temperature: The temperature for the LLM
    :param max_tokens: The maximum number of tokens to generate
    :return: Model generated text
    """

    if not messages:
        raise ValueError("At least one message is required.")
    if max_tokens is not None and max_tokens < 1:
        raise ValueError("max_tokens must be at least 1.")

    api_base = base_url.rstrip("/")
    if not api_base.endswith("/v1"):
        api_base += "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    log_info(f"Preparing request for model: {model}")
    log_info(f"Base URL: {base_url}")
    log_info(f"Temperature: {temperature}")
    log_info(f"Max tokens: {max_tokens if max_tokens is not None else 'default'}")
    log_info(f"Message count: {len(messages)}")

    response = None
    start_time = time.perf_counter()

    try:
        log_info("Sending request to LLM server...")
        response = requests.post(
            f"{api_base}/chat/completions",
            json=payload,
            timeout=(10, 5000),
        )
        elapsed = time.perf_counter() - start_time
        log_info(
            f"Received HTTP response: status={response.status_code}, "
            f"time={elapsed:.2f}s"
        )
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object.")

        choice = data["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError("LLM choice must be an object.")
        if choice.get("finish_reason") == "length":
            raise RuntimeError(
                "LLM output was truncated; the extracted JSON may be incomplete."
            )

        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("LLM message must be an object.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned no text content.")

        log_success(f"LLM response received successfully, length={len(content)} chars")
        usage = data.get("usage")
        if isinstance(usage, dict):
            log_info(
                f"Token usage: prompt={usage.get('prompt_tokens', 'N/A')}, "
                f"completion={usage.get('completion_tokens', 'N/A')}, "
                f"total={usage.get('total_tokens', 'N/A')}"
            )
        return content

    except requests.Timeout:
        log_fail("LLM request timed out")
        raise
    except requests.ConnectionError as exc:
        log_fail(f"Failed to connect to LLM server: {exc}")
        raise
    except requests.HTTPError as exc:
        if response is not None:
            log_fail(
                f"LLM server returned HTTP error: "
                f"{response.status_code} {response.text[:500]}"
            )
        else:
            log_fail(f"LLM HTTP error: {exc}")
        raise
    except requests.RequestException as exc:
        log_fail(f"LLM request or response failed: {exc}")
        raise
    except ValueError as exc:
        log_fail(f"Invalid LLM request or response: {exc}")
        raise
    except (KeyError, IndexError, TypeError) as exc:
        log_fail(f"Unexpected LLM request or response format: {exc}")
        raise
    except RuntimeError as exc:
        log_fail(f"LLM generation failed: {exc}")
        raise
    finally:
        if response is not None:
            response.close()
