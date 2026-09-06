"""Parser de linguagem natural para o Assistente Fintec (MÓDULO CHAT).

Motor 100% determinístico (regex + dicionários de palavras-chave + normalização
de texto). NENHUMA API externa de IA é usada — esta camada apenas transforma uma
frase curta em um RASCUNHO de lançamento:

    "Gastei 58 no Uber"   ->  tipo=expense, R$ 58,00, desc="Uber", Transporte
    "Recebi 1500 de freela" -> tipo=income, R$ 1.500,00, desc="Freela"

Esta camada é PURA: não acessa o banco nem o request. A resolução das categorias
para as categorias REAIS do usuário acontece na camada de serviço (``chat.py``).

Regras obrigatórias da diretiva respeitadas aqui:
- valores monetários SEMPRE com ``decimal.Decimal`` (nunca float);
- convenção brasileira (1.500,50, 1.500, 58,50, R$58, 1500 reais, 1 conto);
- descrição preserva substantivos, sem remover "de/do/da" do meio da frase;
- data padrão = hoje (timezone do projeto); reconhece "hoje" e "ontem";
- limite de 500 caracteres;
- NUNCA decide "se não for receita = despesa": sem intenção clara,
  ``type_ambiguous=True`` é retornado.
"""

import re
import unicodedata
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

MAX_MESSAGE_LEN = 500
MAX_DESCRIPTION_LEN = 200
# Teto de segurança: R$ 10 bilhões (centavos). Acima disso, "valor inválido".
MAX_AMOUNT_CENTS = 10**12

# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #


def normalize_accents(text):
    """Remove acentos e converte para lowercase (para comparação)."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(
        ch for ch in decomposed if unicodedata.category(ch) != "Mn"
    )


def _tokens(text):
    """Tokens alfanuméricos da string normalizada (para match com borda)."""
    return re.findall(r"[a-z0-9]+", normalize_accents(text))


# --------------------------------------------------------------------------- #
# Dicionários de palavras-chave
# --------------------------------------------------------------------------- #

# Indicadores de DESPESA (sentido: saída de dinheiro).
_EXPENSE_VERBS = {
    "gastei", "paguei", "comprei", "saiu", "debitei", "custou", "torrei",
    "despesa", "racho", "saida", "compra", "pago", "gasto",
}

# Indicadores de RECEITA (sentido: entrada de dinheiro).
_INCOME_VERBS = {
    "recebi", "ganhei", "entrou", "vendi", "salario", "recebido", "dividendo",
    "renda", "comissao", "freela", "freelance", "cashback", "rendimento",
    "bonificacao", "bonus", "depositei", "caiu", "recebimento", "dividendos",
    "reembolso", "venda",
}

# Marcos de mensagem FORA DO ESCOPO (sem valor, conversa genérica).
_SCOPE_MARKERS = {
    "oi", "ola", "bom dia", "boa tarde", "boa noite", "e ai", "eai", "oii",
    "oie", "tudo bem", "quem e voce", "quem foi voce", "conte uma piada",
    "piada", "previsao do tempo", "tempo hoje", "obrigado", "obrigada",
    "ajuda", "help", "qual seu nome", "qual e seu nome",
}

# Grupos de categoria (taxonomia genérica da diretiva). A resolução para as
# categorias REAIS do usuário fica na camada de serviço (``chat.resolve_*``).
CATEGORY_KEYWORDS = {
    "Alimentação": {
        "mercado", "supermercado", "almoco", "jantar", "pizza", "ifood",
        "padaria", "restaurante", "cafe", "lanche", "comida", "lanchonete",
        "acougue", "feira", "hortifruti", "delivery", "sorvete", "doce",
    },
    "Transporte": {
        "uber", "99", "taxi", "gasolina", "combustivel", "estacionamento",
        "pedagio", "onibus", "metro", "mecanico", "manutencao", "posto",
        "etanol", "aplicativo", "conducao", "ipva", "seguro do carro",
    },
    "Lazer": {
        "cinema", "bar", "steam", "netflix", "spotify", "show", "jogos",
        "jogo", "festa", "viagem", "filme", "teatro", "parque", "passeio",
    },
    "Moradia": {
        "aluguel", "luz", "energia", "agua", "internet", "condominio",
        "gas", "faxina", "iptu", "conta de luz", "conta de agua",
    },
    "Saúde": {
        "farmacia", "remedio", "consulta", "medico", "dentista", "exame",
        "academia", "plano de saude", "drogasil", "drogaria",
    },
    "Renda": {
        "salario", "freela", "venda", "comissao", "rendimento", "cashback",
        "dividendo", "reembolso", "bonus", "bonificacao", "premio",
        "beneficio", "aluguel recebido",
    },
}

# Nome oficial na taxonomia FASE 3 para cada grupo (parent). "Renda" é tratado
# à parte porque só existe no lado de receitas ("Rendimentos"/"Renda extra").
_GROUP_PARENT_NAME = {
    "Alimentação": "Alimentação",
    "Transporte": "Transporte",
    "Lazer": "Entretenimento",
    "Moradia": "Moradia",
    "Saúde": "Saúde",
}


def category_group_for_text(text):
    """Retorna o grupo de categoria detectado (ou None). Palavras de 1-3 letras
    são casadas com borda de palavra para evitar falsos positivos."""
    norm = normalize_accents(text)
    tokens = set(_tokens(text))
    for group, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            kw = normalize_accents(keyword)
            if len(kw) >= 4:
                if kw in norm:
                    return group
            else:
                if kw in tokens:
                    return group
    return None


# --------------------------------------------------------------------------- #
# Valores monetários
# --------------------------------------------------------------------------- #

# Captura o valor (sem R$/palavra) no formato brasileiro:
#   1.500,50 | 1.500 | 58,50 | 58.50 | 58,5 | 58.5 | 58 | 1 conto
_VALUE_TOKEN = (
    r"(?:R\$\s*)?"
    r"(?P<value>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[,.]\d{1,2})?)"
    r"\s*(?P<unit>reais?|contos?)?"
)
_VALUE_RE = re.compile(_VALUE_TOKEN, re.IGNORECASE)

_CONTO_RE = re.compile(r"(?P<value>\d+)\s*contos?", re.IGNORECASE)


def _raw_to_cents(raw):
    """Converte o texto numérico em centavos (convenção brasileira)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if "," in raw:
        int_part, dec_part = raw.split(",", 1)
        if not dec_part.strip() or len(dec_part.strip()) > 2:
            return None
        reais = int(int_part.replace(".", "") or "0")
        cents = int(dec_part.strip().ljust(2, "0"))
        return reais * 100 + cents
    if "." in raw:
        parts = raw.split(".")
        # "1.500" / "1.500.000" -> milhar (inteiro)
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            return int(raw.replace(".", "")) * 100
        # "58.50" / "58.5" -> separador decimal (estilo US, aceito)
        int_part, dec_part = parts
        reais = int(int_part or "0")
        cents = int(dec_part.ljust(2, "0"))
        return reais * 100 + cents
    return int(raw or "0") * 100


def extract_value_cents(text):
    """Extrai o primeiro valor monetário da frase; retorna centavos (int) ou
    None. Não lança exceções: qualquer valor não analisável vira None."""
    if not text:
        return None
    match = _VALUE_RE.search(text)
    if not match:
        conto = _CONTO_RE.search(text)
        if not conto:
            return None
        try:
            return int(conto.group("value")) * 100_000
        except ValueError:
            return None
    if match.start() > 0 and text[match.start() - 1] == "-":
        return None
    try:
        cents = _raw_to_cents(match.group("value"))
        unit = (match.group("unit") or "").strip().lower()
        if unit.startswith("conto"):
            cents = cents * 1000
        return cents
    except (ValueError, TypeError):
        return None


def format_brl(cents):
    """Formata centavos como texto decimal '58.00' (usado no card)."""
    return (Decimal(cents) / 100).quantize(Decimal("0.01")).__str__()


def parse_decimal_override(text):
    """Converte uma edição manual de valor (ex.: '58,50') em centavos.

    Aceita os mesmos formatos da extração automática. Retorna None em caso de
    texto vazio ou inválido.
    """
    if not text:
        return None
    value = (text or "").strip().replace("R$", "").strip()
    if not value:
        return None
    try:
        return _raw_to_cents(value)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


def default_date():
    """Data de HOJE no timezone do projeto (usa sempre, salvo 'ontem')."""
    return timezone.localdate()


def parse_date_hint(text):
    """Retorna (date, label) — "hoje" (padrão) ou "ontem" quando citado."""
    today = default_date()
    if "ontem" in normalize_accents(text):
        return today - timedelta(days=1), "Ontem"
    return today, "Hoje"


# --------------------------------------------------------------------------- #
# Tipo (receita x despesa)
# --------------------------------------------------------------------------- #


def detect_type(text):
    """Detecta o tipo: 'income' | 'expense' | None (ambíguo).

    Retorna tupla (tipo, ambiguo). NUNCA assume despesa por eliminação.
    """
    tokens = set(_tokens(text))
    norm = normalize_accents(text)
    income = _has_any(tokens, norm, _INCOME_VERBS)
    expense = _has_any(tokens, norm, _EXPENSE_VERBS)
    if income and expense:
        return None, True
    if expense:
        return "expense", False
    if income:
        return "income", False
    return None, True


def _has_any(tokens, norm, keywords):
    for kw in keywords:
        nkw = normalize_accents(kw)
        if len(nkw) >= 4:
            if nkw in norm:
                return True
        else:
            if nkw in tokens:
                return True
    return False


# --------------------------------------------------------------------------- #
# Descrição
# --------------------------------------------------------------------------- #

# Verbos de ação + conectores removidos APENAS no início/fim da frase (nunca no
# meio — "mercado do bairro" permanece intacto).
_ACTION_PREFIXES = {
    "gastei", "paguei", "comprei", "recebi", "ganhei", "saiu", "debitei",
    "custou", "torrei", "vendi", "entrou", "racho", "caiu", "depositei",
    "tenho", "tive", "fiz", "fui", "registrei",
}
_FUNCTION_WORDS = {
    "no", "na", "nos", "nas", "de", "do", "da", "dos", "das", "em", "por",
    "com", "um", "uma", "uns", "umas", "pra", "pro", "para", "o", "a", "os",
    "as", "eu", "me", "minha", "meu", "hoje", "ontem", "agora", "amanha",
}
_TITLE_KEEP_LOWER = {
    "de", "do", "da", "dos", "das", "em", "na", "no", "por", "com", "para",
    "pra", "pro", "e", "ou",
}


def _strip_edges(tokens):
    while tokens and tokens[0].casefold() in _FUNCTION_WORDS | _ACTION_PREFIXES:
        tokens.pop(0)
    while tokens and tokens[-1].casefold() in _FUNCTION_WORDS:
        tokens.pop()
    return tokens


def _title_case(phrase):
    out = []
    for token in phrase.split():
        if token in _TITLE_KEEP_LOWER:
            out.append(token)
        else:
            out.append(token[0].upper() + token[1:])
    return " ".join(out)


def build_description(text, amount_cents, category_group):
    """Gera uma descrição útil a partir da frase original.

    Remove APENAS: o token de valor ("R$ 58,50"/"58 reais" etc.), verbos de
    ação e conectores no INÍCIO/FIM. Substantivos e preposições internas são
    preservados ("mercado do bairro" não é corrompido).
    """
    if not text:
        return "Lançamento"[:MAX_DESCRIPTION_LEN]
    work = text.strip()

    match = _VALUE_RE.search(work)
    if match:
        work = (work[: match.start()] + " " + work[match.end() :]).strip()
    conto = _CONTO_RE.search(work)
    if conto:
        work = (work[: conto.start()] + " " + work[conto.end() :]).strip()

    tokens = work.split()
    tokens = _strip_edges(tokens)
    phrase = _title_case(" ".join(tokens))
    if not phrase:
        if category_group:
            phrase = category_group
        else:
            phrase = "Lançamento"
    return phrase[:MAX_DESCRIPTION_LEN]


# --------------------------------------------------------------------------- #
# API pública (pura)
# --------------------------------------------------------------------------- #


def parse_message(text):
    """Interpreta uma mensagem e devolve um dicionário estruturado (sem banco).

    ``outcome`` pode ser: 'ok' | 'no_value' | 'scope' | 'too_long' |
    'invalid_value'.
    """
    text = (text or "").strip()
    norm = normalize_accents(text)

    if len(text) > MAX_MESSAGE_LEN:
        return {
            "outcome": "too_long",
            "type": None,
            "type_ambiguous": False,
            "amount_cents": None,
            "amount": None,
            "description": "",
            "category_group": None,
            "date": default_date().isoformat(),
            "date_label": "Hoje",
        }

    amount_cents = extract_value_cents(text)
    if amount_cents is None:
        if _is_out_of_scope(norm, text):
            outcome = "scope"
        else:
            outcome = "no_value"
        return {
            "outcome": outcome,
            "type": None,
            "type_ambiguous": False,
            "amount_cents": None,
            "amount": None,
            "description": "",
            "category_group": None,
            "date": default_date().isoformat(),
            "date_label": "Hoje",
        }

    if amount_cents <= 0 or amount_cents > MAX_AMOUNT_CENTS:
        return {
            "outcome": "invalid_value",
            "type": None,
            "type_ambiguous": False,
            "amount_cents": None,
            "amount": None,
            "description": "",
            "category_group": None,
            "date": default_date().isoformat(),
            "date_label": "Hoje",
        }

    ttype, ambiguous = detect_type(text)
    group = category_group_for_text(text)
    date, date_label = parse_date_hint(text)
    description = build_description(text, amount_cents, group)

    return {
        "outcome": "ok",
        "type": ttype,
        "type_ambiguous": ambiguous,
        "amount_cents": amount_cents,
        "amount": (Decimal(amount_cents) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ).__str__(),
        "description": description,
        "category_group": group,
        "date": date.isoformat(),
        "date_label": date_label,
    }


def _is_out_of_scope(norm, original):
    if any(marker in norm for marker in _SCOPE_MARKERS):
        return True
    if "?" in original:
        return True
    return False