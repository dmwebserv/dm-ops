"""
Shared helper for calling the Anthropic API. Used by every script that drafts
content or runs QC, so the "model got retired" failure mode is diagnosed the
same way everywhere instead of five near-identical copies of the same
error-handling logic drifting apart over time.
"""

import requests

API_URL = "https://api.anthropic.com/v1/messages"


def call_claude(api_key, model, prompt, max_tokens):
    """POST a single-turn message to the Anthropic API and return the text.

    If the API rejects the request with an error that names the model
    itself (not found, deprecated, invalid), this raises a RuntimeError
    that says so explicitly and points at business.anthropic_model in
    clients.yaml - that failure looks exactly like a bad ANTHROPIC_API_KEY
    otherwise, and shouldn't have to be deduced a month later. Every other
    failure (auth, rate limits, server errors) is left to raise exactly as
    it always did, via response.raise_for_status().
    """
    response = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
    )

    if response.status_code >= 400:
        try:
            error_message = response.json().get("error", {}).get("message", "")
        except ValueError:
            error_message = response.text
        if model in error_message:
            raise RuntimeError(
                f"Anthropic API rejected model '{model}' ({response.status_code}): {error_message}\n"
                f"This usually means the model has been retired, renamed, or was never valid - "
                f"not a bad API key. Update business.anthropic_model in clients.yaml to a current model ID."
            )

    response.raise_for_status()
    data = response.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")
