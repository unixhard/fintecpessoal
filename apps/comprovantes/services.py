"""Serviços do app comprovantes.

Valida upload no servidor (limite de tamanho e tipos aceitos) para garantir
que os anexos nunca ocupem espaço desnecessário — sem dependências externas de
compressão, o piso de segurança é o limite de tamanho e o tipo de arquivo.
"""

import os
from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from apps.core.services.ai import AIServiceError, ai_enabled, generate_json
from apps.finance.services.base import require_owned

from .models import Comprovante

_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB — arquivos pequenos por padrão
ALLOWED_EXTENSIONS = {
    "pdf": "PDF",
    "jpg": "Imagem JPG",
    "jpeg": "Imagem JPG",
    "png": "Imagem PNG",
    "txt": "Texto",
}
WARRANTY_WINDOW_DAYS = 60


class UploadError(Exception):
    pass


def _validate_upload(uploaded):
    """Valida tipo e tamanho do arquivo antes de gravar (limite de espaço)."""
    if uploaded is None:
        raise UploadError("Nenhum arquivo enviado.")
    size = uploaded.size
    if size <= 0:
        raise UploadError("O arquivo enviado está vazio.")
    if size > MAX_FILE_SIZE:
        desc = f"{size / (1024 * 1024):.2f} MB"
        raise UploadError(
            f"Arquivo muito grande ({desc}). O limite é de 2 MB para "
            f"economizar espaço. Use uma versão comprimida do arquivo."
        )
    name = (getattr(uploaded, "name", "") or "").lower()
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"Tipo de arquivo não suportado (.{ext}). Aceitos: "
            f"{', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    return ext


def create_comprovante(
    *, user, title, kind, uploaded, warranty_expiry=None, notes=""
):
    _validate_upload(uploaded)
    code = uuid4().hex[:12]
    obj = Comprovante.objects.create(
        owner=user,
        slug=code,
        title=title,
        kind=kind,
        file=uploaded,
        warranty_expiry=warranty_expiry or None,
        notes=notes or "",
    )
    return obj


def update_details(*, user, comprovante, title=None, kind=None, warranty_expiry=None, notes=None):
    require_owned(Comprovante.objects, user, model_label="Comprovante", object_id=comprovante.pk)
    if title is not None:
        comprovante.title = title
    if kind is not None:
        comprovante.kind = kind
    comprovante.warranty_expiry = warranty_expiry
    if notes is not None:
        comprovante.notes = notes
    comprovante.save()
    return comprovante


def delete_comprovante(*, user, comprovante):
    require_owned(Comprovante.objects, user, model_label="Comprovante", object_id=comprovante.pk)
    if comprovante.file:
        comprovante.file.delete(save=False)
    comprovante.delete()


def get_comprovantes(*, user, kind=None, warranty=None):
    qs = Comprovante.objects.for_user(user)
    if kind:
        qs = qs.filter(kind=kind)
    today = timezone.localdate()
    items = list(qs)
    output = []
    for c in items:
        row = {
            "pk": c.pk,
            "title": c.title,
            "kind": c.kind,
            "kind_label": c.get_kind_display(),
            "file_name": c.file.name.rsplit("/", 1)[-1],
            "warranty_expiry": c.warranty_expiry,
            "warranty_status": c.warranty_status(today),
            "notes": c.notes,
            "created_at": c.created_at,
            "file_url": c.file.url,
        }
        output.append(row)
    if warranty == "expiring":
        output = [
            r for r in output
            if r["warranty_expiry"]
            and r["warranty_status"] in ("expiring", "expired")
        ]
    elif warranty == "active":
        output = [r for r in output if r["warranty_status"] == "active"]
    return output


def warranty_alert_count(*, user):
    today = timezone.localdate()
    limit = today + timedelta(days=WARRANTY_WINDOW_DAYS)
    return (
        Comprovante.objects.for_user(user)
        .filter(warranty_expiry__lte=limit)
        .count()
    )


# --------------------------------------------------------------------------- #
# IA opcional: leitura inteligente de comprovantes
# --------------------------------------------------------------------------- #
_SYSTEM_PARSE_PROMPT = (
    "Você é um assistente de finanças pessoais. Analise o documento anexado "
    "e extraia as informações solicitadas. Responda APENAS com JSON no formato: "
    '{"estabelecimento": "string", "valor_centavos": 0, "data": "YYYY-MM-DD", '
    '"categoria_sugerida": "string"}. '
    "valor_centavos deve ser um INTEIRO em centavos (ex.: R$ 12,90 -> 1290; "
    "R$ 1.234,56 -> 123456). data use o formato ISO ano-mês-dia (ex.: 2026-03-14). "
    "categoria_sugerida deve ser uma categoria financeira curta como "
    "Alimentação, Transporte, Moradia, Saúde, Lazer, Educação, Compras ou Outros. "
    "Use string vazia quando um campo não for identificável."
)


def _coerce_kv_int(value):
    """Normaliza o valor monetário retornado pela IA para centavos (int)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    # Caso a IA tenha devolvido reais como texto/float ("1234.56")
    try:
        f = float(str(value).replace(",", "."))
        if abs(f) > 0 and abs(f) < 10_000:
            return int(round(f * 100))
        return None
    except (TypeError, ValueError):
        return None


def _read_document_bytes(uploaded):
    """Lê os bytes de um arquivo de upload ou de um FileField armazenado."""
    try:
        uploaded.open("rb")
    except Exception:
        pass
    data = uploaded.read()
    return data or b""


def parse_comprovante_with_ai(*, user, comprovante_id_or_file):
    """Extrai dados de um comprovante usando IA (Gemini Flash Lite).

    ``comprovante_id_or_file`` aceita o ``pk`` de um ``Comprovante`` (ownership
    validado via ``for_user``) OU um arquivo igual ao ``file`` do form (ex.:
    ``UploadedFile``). Nunca envia dados além do próprio documento.

    Retorna um dict::

        {
            "ok": True,
            "estabelecimento": str,
            "valor_centavos": int | None,
            "data": "YYYY-MM-DD" | "",
            "categoria_sugerida": str,
        }

    Se a IA estiver indisponível (sem chave, sem internet, erro/parse) lança
    ``AIServiceError`` — o chamador deve cair para o fluxo manual sem quebrar.
    """
    if not ai_enabled():
        raise AIServiceError("IA não configurada (GEMINI_API_KEY ausente).")

    if isinstance(comprovante_id_or_file, int):
        comprovante = (
            Comprovante.objects.for_user(user)
            .filter(pk=comprovante_id_or_file)
            .first()
        )
        if comprovante is None:
            raise UploadError("Comprovante não encontrado.")
        if not comprovante.file:
            raise UploadError("Comprovante sem arquivo.")
        uploaded = comprovante.file
    else:
        uploaded = comprovante_id_or_file
        _validate_upload(uploaded)

    name = (getattr(uploaded, "name", "") or "").lower()
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    mime = _MIME_BY_EXT.get(ext, "application/octet-stream")

    if ext == "txt":
        raw_text = _read_document_bytes(uploaded).decode("utf-8", "ignore").strip()
        result = generate_json(
            system_prompt=_SYSTEM_PARSE_PROMPT,
            user_prompt=f"Extraia os dados deste documento:\n\n{raw_text or '(documento vazio)'}",
        )
    else:
        result = generate_json(
            system_prompt=_SYSTEM_PARSE_PROMPT,
            user_prompt="Extraia os dados deste comprovante.",
            image_bytes=_read_document_bytes(uploaded),
            image_mime=mime,
        )

    return {
        "ok": True,
        "estabelecimento": str(result.get("estabelecimento") or "").strip(),
        "valor_centavos": _coerce_kv_int(result.get("valor_centavos")),
        "data": str(result.get("data") or "").strip(),
        "categoria_sugerida": str(result.get("categoria_sugerida") or "").strip(),
    }
