"""Normalizador universal de colunas de extrato (agnóstico de banco).

Cada cliente envia extratos de bancos diferentes (Itaú, Bradesco, Santander,
Inter, C6, Nubank, etc.), em XLSX/CSV/OFX, com NOMES de coluna e formatos
variados. Este módulo identifica dinamicamente o PAPEL de cada coluna a partir
de sinônimos + expressões regulares, normalizando o cabeçalho (minúsculas, sem
acento, espaços colapsados) e casando contra os papéis conhecidos.

Não depende de IA e não assume layout fixo: se Data/Descrição/Valor forem
encontrados, o processamento ocorre direto — nunca trava por incompatibilidade
de cabeçalho.
"""

import re
import unicodedata
from typing import Optional

from .csv_parser import CsvConfig

# Papéis de coluna e seus sinônimos normalizados (minúsculas, sem acento).
_COLUMN_ROLES = {
    "date": [
        "data", "dt", "data lancamento", "data do lancamento", "data transacao",
        "data transacoes", "date", "data do movimento", "data pagamento",
        "data do pagamento", "data de lancamento", "data da transacao",
        "dat", "data mov", "data balancete", "vencimento", "dia",
    ],
    "description": [
        "descricao", "descrição", "descri", "desc", "historico", "histórico",
        "lancamento", "lançamento", "detalhe", "detalhes", "memo",
        "estabelecimento", "memorando", "nome", "favor", "favorecido",
        "identificacao", "identificação", "discriminacao", "discriminação",
        "transacao", "transação", "movimento", "descricao do lancamento",
        "descricao da transacao", "summary", "narracao", "narrativa",
        "titulo", "titulo da transacao", "conta", "company",
    ],
    "amount": [
        "valor", "valor (r$)", "amount", "vlr", "value", "valor (r$)",
        "valor r$", "valor (r)", "importancia", "importância", "total",
        "montante", "valor da transacao", "valor do lancamento", "ammount",
        "foreigncurrencyamount", "localcurrencyamount",
    ],
    "debit": [
        "debito", "débito", "debit", "saida", "saída", "pagamento",
        "saiu", "débitos", "debitos", "valor debito", "valor do debito",
        "valor saida", "valor (debito)", "payment", "dupl",
    ],
    "credit": [
        "credito", "crédito", "credit", "entrada", "deposito", "depósito",
        "recebimento", "créditos", "creditos", "valor credito",
        "valor do credito", "valor entrada", "valor (credito)", "income",
        "deposit", "receita",
    ],
    "type": [
        "tipo", "natureza", "d/c", "dc", "tipo de lancamento", "tipo lancamento",
        "tipo da transacao", "tipo de transacao", "tipo movimentacao", "type",
        "tipo (d/c)", "tipo d/c", "classificacao", "classifica", "sinal",
        "tipo transacao", "debito/credito", "operacao", "crd/dbt",
    ],
    "category": [
        "categoria", "categoria sugerida", "categoria sujerida", "categoria (sugerida)",
        "classificacao sugerida", "category", "categoria prevista", "categoria estimada",
        "categoria da transacao", "categoria da despesa", "grupo",
    ],
    "balance": [
        "saldo", "balance", "balanco", "saldo apurado", "saldo final",
        "saldo disponivel", "saldo da conta",
    ],
}

# Expressões regulares por papel (casam variações livres, ex.: "valor (R$)").
_ROLE_REGEX = {
    "date": [
        re.compile(r"^dat", re.I),
        re.compile(r"^vencim", re.I),
        re.compile(r"lan[çc]ament", re.I),
    ],
    "description": [
        re.compile(r"descri", re.I),
        re.compile(r"histor", re.I),
        re.compile(r"estabelecim", re.I),
        re.compile(r"memo", re.I),
        re.compile(r"favorecid", re.I),
        re.compile(r"movimento", re.I),
        re.compile(r"lancamento", re.I),
        re.compile(r"discrimin", re.I),
        re.compile(r"detalhe", re.I),
    ],
    "amount": [
        re.compile(r"valo|amount|vlr|total|montante|importancia", re.I),
        re.compile(r".*currency.*amount", re.I),
    ],
    "debit": [
        re.compile(r"debit|sa[ií]da|pagamento", re.I),
    ],
    "credit": [
        re.compile(r"credit|entrada|dep[oó]sito?|recebim", re.I),
    ],
    "type": [
        re.compile(r"^tipo|natureza|^d/?c\b|classific|sinal|operacao|crd/?dbt", re.I),
    ],
    "category": [
        re.compile(r"categor", re.I),
        re.compile(r"classificac", re.I),
    ],
    "balance": [
        re.compile(r"saldo|balance", re.I),
    ],
}

# Papéis de valor único vs. dividido — evitam conflito entre "amount" e "debit/credit".
_SINGLE_VALUE_ROLES = ("amount",)
_SPLIT_VALUE_ROLES = ("debit", "credit")


def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_header(value: str) -> str:
    """Minúsculas + sem acento + espaços colapsados (para casar sinônimos)."""
    return re.sub(r"\s+", " ", _strip_accents(value or "").strip().lower())


def _match_role(header_norm: str, role: str) -> bool:
    """Casa um cabeçalho normalizado contra sinônimos e regex de um papel."""
    if header_norm in _COLUMN_ROLES[role]:
        return True
    for pat in _ROLE_REGEX[role]:
        if pat.search(header_norm):
            return True
    return False


def detect_role(header: str) -> Optional[str]:
    """Detecta o papel de uma coluna pelo seu nome de cabeçalho (ou None)."""
    norm = _normalize_header(header)
    if not norm:
        return None
    for role in _COLUMN_ROLES:
        if _match_role(norm, role):
            # D/C ("tipo") exige ser exato para não confundir com descrição.
            if role == "type" and norm not in _COLUMN_ROLES["type"]:
                continue
            return role
    return None


def detect_and_map_columns(header_row) -> CsvConfig:
    """Mapeia a linha de cabeçalho para um ``CsvConfig``.

    Recebe a primeira linha (tokens crus) e devolve o mapeamento de papéis
    (date, description, amount e/ou debit+credit, type, category, balance).
    Se não houver cabeçalho reconhecível, retorna config com ``has_header=False``
    e mapeamento posicional Data=0, Descrição=1, Valor=2.
    """
    cfg = CsvConfig()
    roles_found = []
    seen_roles = set()

    for idx, raw in enumerate(header_row or []):
        role = detect_role(raw)
        if role is None:
            continue
        # primeiro papel de cada tipo; prioriza valor único sobre dividido
        if role in seen_roles:
            continue
        seen_roles.add(role)
        roles_found.append((role, idx))

    # Aplica valor único OU dividido (débito/crédito) — se houver 'amount',
    # ignora debit/credit para usar a coluna única com sinal.
    has_amount = any(r == "amount" for r, _ in roles_found)
    for role, idx in roles_found:
        if role == "date":
            cfg.date = idx
        elif role == "description":
            cfg.description = idx
        elif role == "amount":
            cfg.amount = idx
        elif role == "debit" and not has_amount:
            cfg.debit = idx
        elif role == "credit" and not has_amount:
            cfg.credit = idx
        elif role == "type":
            cfg.type = idx
        elif role == "category":
            cfg.category = idx
        elif role == "balance":
            cfg.balance = idx

    # Validação: precisa de Data + Valor para ser um extrato processável.
    has_value = cfg.amount >= 0 or cfg.debit >= 0 or cfg.credit >= 0
    if cfg.date >= 0 and has_value:
        cfg.has_header = True
    else:
        # fallback posicional
        cfg.has_header = False
        cfg.date, cfg.description, cfg.amount = 0, 1, 2
    return cfg
