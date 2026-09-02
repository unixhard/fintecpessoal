"""Cliente leve e opcional do Google Gemini (Flash Lite).

Tudo aqui é OPTIONAL e fault-tolerant: se ``GEMINI_API_KEY`` não estiver
configurada ou a chamada falhar (sem internet, cota, etc.), lançamos
``AIServiceError`` para que o chamador caia para o fluxo manual sem expor
erros de rede ao usuário.

Usamos apenas ``urllib`` da biblioteca padrão — respeito à regra do projeto de
"sem dependências desnecessárias" (o pacote ``google-genai`` não é instalado).

Privacidade: apenas o mínimo necessário para a tarefa é enviado (imagem do
comprovante OU texto da descrição). Nenhum dado além disso, e nada de DPI se
não for estritamente exigido pela tarefa.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class AIServiceError(Exception):
    """Falha na infraestrutura de IA (rede, chave, resposta inválida).

    O chamador deve capturar esta exceção e usar o fluxo manual (fallback).
    """


def ai_enabled() -> bool:
    """True quando há chave de IA configurada (feature flag)."""
    return bool((getattr(settings, "GEMINI_API_KEY", "") or "").strip())


def _model() -> str:
    return getattr(settings, "GEMINI_MODEL", "gemini-3.5-flash-lite")


def _timeout() -> int:
    return int(getattr(settings, "GEMINI_TIMEOUT_SECONDS", 30) or 30)


def _parse_json_response(raw_text: str) -> dict:
    """Extrai um objeto JSON do texto de resposta (tolera cercas de code block)."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        # remove ```json ... ```
        lines = text.splitlines()
        if lines and lines[0].strip().lstrip("`").lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Se o modelo devolveu um objeto aninhado, localiza o primeiro { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        logger.warning("Gemini devolveu resposta não-JSON: %s", text[:300])
        raise AIServiceError("A IA não devolveu uma resposta válida.") from exc
    if not isinstance(data, dict):
        raise AIServiceError("A IA não devolveu um objeto de dados.")
    return data


def generate_json(
    *,
    system_prompt: str,
    user_prompt: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Chama o Gemini e devolve o JSON estruturado.

    Aceita texto puro (sugestão de categoria) ou texto + imagem/PDF inline
    (leitura de comprovante). Qualquer falha -> ``AIServiceError``.
    """
    if not ai_enabled():
        raise AIServiceError("IA não configurada (GEMINI_API_KEY ausente).")

    parts: list[dict] = []
    if image_bytes:
        mime = image_mime or "application/octet-stream"
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
        parts.append({"text": user_prompt})
    else:
        parts.append({"text": user_prompt})

    payload = {
        "contents": [
            {"parts": parts},
        ],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    model = _model()
    api_key = settings.GEMINI_API_KEY
    url = (
        f"{API_BASE}/{model}:generateContent"
        f"?key={urllib.parse.quote(api_key)}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=timeout or _timeout()
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200]
        logger.warning("Gemini HTTP %s: %s", exc.code, detail)
        raise AIServiceError(f"Serviço de IA indisponível (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Gemini indisponível: %s", exc)
        raise AIServiceError("Sem conexão com o serviço de IA.") from exc

    try:
        parsed = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise AIServiceError("Resposta inválida do serviço de IA.") from exc

    try:
        candidates = parsed["candidates"]
        text = candidates[0]["content"]["parts"][0].get("text", "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AIServiceError("Resposta inesperada do serviço de IA.") from exc

    return _parse_json_response(text)


def generate_text(
    *,
    system_prompt: str,
    user_prompt: str,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    timeout: int | None = None,
) -> str:
    """Chama o Gemini e devolve texto livre (ex.: relatório em Markdown).

    Diferente de ``generate_json``, não força a resposta como JSON — usado
    para relatórios/consultoria em texto. Em qualquer falha de infraestrutura
    lança ``AIServiceError`` (o chamador decide o fallback).
    """
    if not ai_enabled():
        raise AIServiceError("IA não configurada (GEMINI_API_KEY ausente).")

    parts: list[dict] = []
    if image_bytes:
        mime = image_mime or "application/octet-stream"
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
        parts.append({"text": user_prompt})
    else:
        parts.append({"text": user_prompt})

    payload = {
        "contents": [{"parts": parts}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "text/plain",
            "temperature": 0.4,
        },
    }

    model = _model()
    api_key = settings.GEMINI_API_KEY
    url = (
        f"{API_BASE}/{model}:generateContent"
        f"?key={urllib.parse.quote(api_key)}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=timeout or _timeout()
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200]
        logger.warning("Gemini HTTP %s: %s", exc.code, detail)
        raise AIServiceError(f"Serviço de IA indisponível (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Gemini indisponível: %s", exc)
        raise AIServiceError("Sem conexão com o serviço de IA.") from exc

    try:
        parsed = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise AIServiceError("Resposta inválida do serviço de IA.") from exc

    try:
        candidates = parsed["candidates"]
        text = candidates[0]["content"]["parts"][0].get("text", "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AIServiceError("Resposta inesperada do serviço de IA.") from exc
    return (text or "").strip()
