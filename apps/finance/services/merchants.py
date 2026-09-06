"""Camada de identidade e normalização de estabelecimentos (Ordem 18 — FASE 4).

Responsabilidades:
  - NORMALIZAÇÃO: deriva uma ``normalized_description`` a partir da descrição
    original SEM nunca substituí-la (auditoria preservada).
  - MATCHING/RESOLUÇÃO: mapeia uma descrição bruta para um ``Merchant`` usando
    a hierarquia de aliases (pessoal > global), SEM IA por transação.
  - APRENDIZADO determinístico: ``learn_alias`` cria/fortalece a memória do
    usuário a partir de uma correção/confirmação manual.

A hierarquia (Ordem 18 §5) é implementada pelo model híbrido:
  - Merchant/Alias GLOBAL (owner IS NULL)  = regras globais / catálogo;
  - Merchant/Alias PESSOAL (owner definido) = regras personalizadas + histórico
    de correções do usuário (maior precedência).
IA permanece for a deste fluxo (fallback só em FASE 11; nunca por transação).
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from ..models import Merchant, MerchantAlias

# Tokens genéricos de ruído (localidades, conectivos, formas jurídicas,
# sufixos de adquirente). Lista CONSERVADORA: só removemos o que é claramente
# ruído, nunca palavras que distinguem estabelecimentos.
_STOPWORDS = frozenset(
    {
        "SAO", "PAULO", "SP", "RJ", "MG", "RS", "BRASIL", "DO", "DA", "DAS",
        "DE", "E", "TRANSP", "PAG", "PAGTO", "PAGAMENTO", "COMPRA", "PEDIDO",
        "TRIP", "TECNOLOGIA", "LTDA", "SA", "S/A", "CIA", "COM", "BANCO",
    }
)

_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)

# Prefixos de Estabelecimento (PAG, MOB, IFD, IO, C6S, NXPG) e alguns codes que
# aparecem ANTES do nome do merchant em extratos. Mantidos em ASCII (sem acento).

# Padrões de prefixo de banco/adquirente que precisam ser removidos ANTES da
# tokenização. A ordem importa: padrões mais longos primeiro para evitar
# conflito parcial (ex.: "NAO CATEGORIZADO" antes de "CATEGORIZADO").
_PREFIX_PATTERNS = [
    re.compile(r"NAO\s*CATEGORIZADO\*?", re.IGNORECASE),
    re.compile(r"CATEGORIZADO\*?", re.IGNORECASE),
    re.compile(r"COMPRA\s*(?:DEBITO|CREDITO|NO\s*DEBITO|NO\s*CREDITO)?", re.IGNORECASE),
    re.compile(r"DEBITO\s*AUTOMATICO", re.IGNORECASE),
    re.compile(r"DEBITO\s*AVULSO", re.IGNORECASE),
    re.compile(r"CARTAO\s*(?:DE\s*)?(?:CREDITO|DEBITO)", re.IGNORECASE),
    re.compile(r"PAGAMENTO", re.IGNORECASE),
    re.compile(r"PAGTO", re.IGNORECASE),
    re.compile(r"PAG\s*\*", re.IGNORECASE),  # PAG* (mantém o merchant seguinte)
    re.compile(r"NXPG\s*\*", re.IGNORECASE),  # Nubank (mantém o merchant seguinte)
    re.compile(r"IO\s*\*\s*", re.IGNORECASE),  # Inter (mantém o merchant seguinte)
    re.compile(r"C6S\s*\*\s*", re.IGNORECASE),  # C6 Bank (mantém o merchant seguinte)
]

# Datas (DD/MM, MM/YYYY, DD/MM/YYYY, DD-MM-YYYY)
_DATE_RE = re.compile(
    r"\b\d{1,2}[/\-]\d{2,4}\b"
)

# Tokens alfanuméricos curtos com muitos dígitos (códigos: ABC123, 123456)
_CODE_RE = re.compile(r"\b\w*\d+\w*\b(?:\s*\b\w*\d+\w*\b)*")  # ex.: NXPG, 3A1B2C
_NUM_RE = re.compile(r"\b\d{4,}\b")  # números longos (ids, valores, datas)


def _strip_accents(value: str) -> str:
    """Remove diacríticos (é->e, ç->c, ã->a...) mantendo caractere ASCII."""
    nfkd = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokens(value: str):
    """Divide em tokens MAIÚSCULOS e SEM ACENTO (para matching consistente).

    Remover acentos garante que "FARMÁCIA" -> "FARMACIA" case com aliases
    armazenados em ASCII ("FARMACIA") e evita que acentos fragmentem palavras
    (que era o bug em que "Farmácia" virava "FARM"+"CIA").
    """
    return [t for t in _ALNUM_RE.split(_strip_accents(value or "").upper()) if t]


def normalize_description(raw: str) -> str:
    """Deriva a descrição normalizada (conservadora) a partir da original.

    Regras (Ordem 18 §4):
      - remove prefixos de banco/adquirente (PAG*, NXPG*, IO*, C6S*,
        NAO CATEGORIZADO, COMPRA DEBITO, etc.);
      - remove datas (DD/MM/YYYY, etc.);
      - remove códigos alfanuméricos curtos (NXPG, 3A1B2C);
      - remove números longos (ids de pedido, valores, autorização);
      - remove tokens de ruído evidente (stopwords);
      - colapsa espaços.
    NÃO faz limpeza agressiva (não funde estabelecimentos distintos).
    """
    if not raw:
        return ""

    # Fase 1: remover prefixos de banco (antes da tokenização, no texto bruto).
    cleaned = raw
    for pat in _PREFIX_PATTERNS:
        cleaned = pat.sub(" ", cleaned)

    # Fase 2: remover datas e códigos avulsos.
    cleaned = _DATE_RE.sub(" ", cleaned)
    cleaned = _CODE_RE.sub(" ", cleaned)
    cleaned = _NUM_RE.sub(" ", cleaned)

    # Fase 3: tokenizar e filtrar.
    tokens = _tokens(cleaned)
    meaningful = [t for t in tokens if not t.isdigit() and t not in _STOPWORDS]
    return " ".join(meaningful)


def normalize_merchant_candidate(raw: str) -> str:
    """Candidato a nome de estabelecimento a partir da descrição.

    Usa o primeiro token significativo (ex.: "UBER" de "UBER *TRIP ...").
    Serve para criar um Merchant pessoal a partir de uma correção manual.
    """
    norm = normalize_description(raw)
    if not norm:
        return ""
    return norm.split(" ", 1)[0]


@dataclass
class MerchantResolution:
    """Resultado da identificação de um estabelecimento."""

    merchant: Optional[Merchant] = None
    matched_alias: Optional[MerchantAlias] = None
    normalized_description: str = ""
    confidence: float = 0.0
    method: str = ""          # nome do método/origem (ex.: 'user_alias', 'catalog_alias')
    matched: bool = False


def resolve_merchant(user, description: str) -> MerchantResolution:
    """Resolve um Merchant a partir da descrição bruta.

    Ordem (Ordem 18 §5, §7):
      1. Alias PESSOAL do usuário (regras personalizadas + histórico de
         correções) — maior precedência;
      2. Alias GLOBAL (regras globais / catálogo);
      3. Nome do Merchant (global ou pessoal);
      4. Sem IA por transação — ausência de match -> ``matched=False``.

    Confiança DERIVADA POR REGRA OBJETIVA (nunca inventada):
      - alias exato  : 1.0
      - alias contido: 0.95
      - match por nome: 0.90
    """
    nr = MerchantResolution(normalized_description=normalize_description(description))
    if not description or not description.strip():
        return nr

    desc_tokens = set(_tokens(description))
    if not desc_tokens:
        return nr

    alias_hits = []
    for alias in MerchantAlias.objects.for_user(user):
        alias_tokens = _tokens(alias.alias)
        if not alias_tokens:
            continue
        if set(alias_tokens).issubset(desc_tokens):
            exact = set(alias_tokens) == desc_tokens
            conf = 1.0 if exact else 0.95
            alias_hits.append((conf, alias))

    if alias_hits:
        # precedência: alias pessoal (owner!=None) antes de global; depois por
        # confiança; depois alias mais específico (mais tokens / mais longo).
        def _sort_key(hit):
            conf, alias = hit
            return (
                alias.owner_id is not None,   # pessoal primeiro (True > False)
                conf,
                len(_tokens(alias.alias)),
                len(alias.alias),
            )

        alias_hits.sort(key=_sort_key, reverse=True)
        best_conf, best_alias = alias_hits[0]
        if best_alias.owner_id is not None:
            method = "user_alias"
            conf = max(best_conf, 0.95)
        else:
            method = "catalog_alias"
            conf = best_conf
        nr.merchant = best_alias.merchant
        nr.matched_alias = best_alias
        nr.confidence = round(conf, 3)
        nr.method = method
        nr.matched = True
        return nr

    # match direto pelo nome do Merchant (sem alias)
    for m in Merchant.objects.for_user(user):
        name_tokens = set(_tokens(m.name))
        if name_tokens and name_tokens.issubset(desc_tokens):
            nr.merchant = m
            nr.confidence = 0.90
            nr.method = "merchant_name"
            nr.matched = True
            return nr

    return nr


def learn_alias(*, user, alias, merchant, source=MerchantAlias.Source.USER):
    """Cria/fortalece a memória determinística do usuário (Ordem 18 §6).

    Registra um alias PESSOAL (owner=user) resolvendo para ``merchant``
    (pessoal ou global). Uma correção manual futura chama este serviço para que
    ocorrências semelhantes sejam reconhecidas automaticamente.
    """
    alias = (alias or "").strip().upper()
    if not alias:
        raise ValueError("Alias não pode ficar vazio.")
    if merchant is None:
        raise ValueError("Merchant de destino obrigatório.")
    if merchant.owner_id is not None and merchant.owner_id != user.id:
        raise ValueError("Merchant pessoal deve pertencer ao mesmo usuário.")

    personal, created = MerchantAlias.objects.get_or_create(
        owner=user,
        alias=alias,
        defaults={
            "merchant": merchant,
            "source": source,
            "confidence": 1.0,
        },
    )
    if not created:
        if personal.merchant_id != merchant.id:
            personal.merchant = merchant
            personal.source = source
            personal.confidence = 1.0
        personal.use_count += 1
        personal.save()
    else:
        personal.use_count = 1
        personal.save(update_fields=["use_count"])
    return personal


def record_use(alias: MerchantAlias) -> None:
    """Incrementa o contador de usos de um alias (fortalece precedência)."""
    alias.use_count += 1
    alias.save(update_fields=["use_count"])
