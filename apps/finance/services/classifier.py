"""Motor determinístico de classificação financeira (Ordem 18 — FASE 5).

Princípio: Complexidade para o sistema, simplicidade para o usuário.
Não dependemos de IA por transação. Resolução totalmente local e determinística.

Fluxo (§2): normalização -> Merchant -> regra do usuário -> histórico do
usuário -> regra global -> contexto -> classificação -> confiança -> decisão
(automático / revisão).

Ordem/prioridade determinística (§3, §16) — documentada e nunca aleatória:
    1. Movimentação neutra (não consumo)  [method=movement]
    2. Correção explícita do usuário       [method=user_correction]
    3. Regra personalizada do usuário      [method=user_rule]
    4. Merchant + associação conhecida     [method=merchant]
    5. Histórico do próprio usuário        [method=history]
    6. Regra global                        [method=global_rule]
    7. Contexto (palavras-chave)           [method=context]
    8. Sem evidência                       [method=none -> revisão humana]

Confiança DERIVADA POR REGRA OBJETIVA (§12) — nunca inventada:
    user_correction : 0.97
    user_rule       : 0.96
    merchant        : 0.92
    history         : 0.85
    global_rule     : 0.80
    context         : 0.70
    none            : 0.00
needs_review = confidence < 0.75

Uma regra de baixa qualidade NUNCA sobrescreve uma decisão explícita do usuário
(correção do usuário tem a maior prioridade entre as fontes de categoria).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.db.models import Count

from ..models import (
    Category,
    ClassificationRule,
    Merchant,
    Transaction,
    TransactionAnalysis,
    UserPreference,
)
from .merchants import _strip_accents, normalize_description

# Palavras-chave de contexto -> categoria da taxonomia FASE 3 (ordem de match).
_CONTEXT_KEYWORDS = [
    # Alimentação
    ("Supermercado", ("MERCADO", "SUPERMERCADO", "ATACADAO", "HORTIFRUTI", "SACOLAO")),
    ("Padaria", ("PADARIA",)),
    ("Açougue", ("ACOUGUE", "CARNES")),
    ("Restaurante", ("RESTAURANTE", "LANCHONETE", "HAMBURGUER", "PIZZARIA")),
    ("Delivery", ("DELIVERY", "IFOOD", "IFD")),
    ("Cafeteria", ("CAFE", "CAFETERIA")),
    # Transporte
    ("Aplicativos", ("UBER", "99TAXI", "99 POP")),
    ("Combustível", ("POSTO", "GASOLINA", "COMBUSTIVEL", "ETANOL", "DIESEL")),
    ("Transporte público", ("METRO", "ONIBUS", "BILHETE", "VLT", "TRAM")),
    ("Estacionamento", ("ESTACIONAMENTO", "PARK", "ZONA AZUL")),
    ("Pedágio", ("PEDAGIO", "PEDÁGIO", "SEM PARAR", "SEMPARAR")),
    # Moradia
    ("Aluguel", ("ALUGUEL",)),
    ("Condomínio", ("CONDOMINIO", "COND")),
    ("Energia elétrica", ("ENERGIA", "ENEL", "ELETRO", "LUZ")),
    ("Água e esgoto", ("AGUA", "SABESP")),
    ("Gás", ("GAS",)),
    ("Internet", ("INTERNET",)),
    ("Telefone", ("TELEFONE", "CELULAR", "VIVO", "TIM", "CLARO")),
    # Saúde
    ("Farmácia", ("FARMACIA", "DROGARIA", "FARMA")),
    ("Consultas", ("MEDICO", "CONSULTA", "CLINICA")),
    ("Plano de saúde", ("UNIMED", "AMIL", "SULAMERICA", "PLANO DE SAUDE")),
    ("Dentista", ("DENTE", "DENTAL", "ORTO")),
    # Entretenimento / Assinaturas
    ("Streaming de vídeo", ("NETFLIX", "PRIME VIDEO", "DISNEY", "HBO", "GLOBOPLAY", "YOUTUBE")),
    ("Streaming de música", ("SPOTIFY", "DEEZER", "APPLE MUSIC")),
    ("Jogos", ("STEAM", "PLAYSTATION", "XBOX", "NINTENDO", "EPIC GAMES")),
    ("Cinema", ("CINEMA", "CINEPOLIS", "KINOPLEX")),
    # Educação
    ("Cursos", ("CURSO", "DESCOMPLICA", "ALURA", "UDEMY")),
    ("Escola", ("ESCOLA", "MENSALIDADE", "COLEGIO", "FACULDADE")),
    # Compras pessoais
    ("Vestuário", ("RENNER", "CEA", "MARISA", "RUY BARBOSA")),
    # Salário / renda
    ("Salário", ("SALARIO", "SALÁRIO", "FOLHA", "PAGAMENTO DE SALARIO")),
    ("Freelancer", ("FREELA", "FREELANCER", "CONSULTORIA")),
]

# Sufixos/palavras que indicam MOVIMENTAÇÃO NEUTRA (não consumo) — §8/§9/§10.
# Verificados na descrição ORIGINAL (maúscula) porque a normalização remove
# stopwords como "PAGAMENTO"/"DE" que compõem os padrões.
_MOVEMENT_HINTS = (
    "DIVIDA",
    "TRANSFERENCIA",
    "PIX ENTRE CONTAS",
    "APLICACAO",
    "RESGATE",
    "PAGAMENTO DE EMPRESTIMO",
    "RECEBIMENTO DE EMPRESTIMO",
    "INVESTIMENTO",
    "PAGAMENTO DE PRINCIPAL",
)

_CONFIDENCE = {
    TransactionAnalysis.Source.USER_CORRECTION: Decimal("0.97"),
    TransactionAnalysis.Source.USER_RULE: Decimal("0.96"),
    TransactionAnalysis.Source.MERCHANT: Decimal("0.92"),
    TransactionAnalysis.Source.HISTORY: Decimal("0.85"),
    TransactionAnalysis.Source.GLOBAL_RULE: Decimal("0.80"),
    TransactionAnalysis.Source.CONTEXT: Decimal("0.70"),
    TransactionAnalysis.Source.MOVEMENT: Decimal("0.95"),
    TransactionAnalysis.Source.NATURE: Decimal("0.95"),
    TransactionAnalysis.Source.SUGGESTED: Decimal("0.94"),
    TransactionAnalysis.Source.NONE: Decimal("0.00"),
}

# --------------------------------------------------------------------------- #
# Camada de NATUREZA da transação (agnóstica de banco).
#
# Reconhece o CARÁTER estrutural de uma movimentação a partir do layout da
# descrição (PIX/TED/fatura/salário/tarifa/rendimento/reembolso), INDEPENDENTE
# do catálogo de estabelecimentos e do banco de origem. Estas regras são 100%
# determinísticas e se aplicam a qualquer provedor. Possuem confiança alta
# porque a evidência é estrutural, não lexical do comerciante.
#
# Semântica de retorno: cada entrada é uma tupla
#   (regex_compilada, kind_alvo, categoria_natureza|None, é_movimentação)
# - categoria_natureza: nome da categoria na taxonomia (self.leaf ou categoria)
# - é_movimentação=True: movimento neutro (não consumo) -> nenhuma categoria.
# --------------------------------------------------------------------------- #

# Padrões de RECEITA inequívocos (renda/benefício/investimento/reembolso).
_NATURE_INCOME = [
    (re.compile(r"PAGAMENTO\s*(?:DE\s*)?SALAR\w*", re.I), "Salário"),
    (re.compile(r"FOLHA\s*(?:DE\s*)?PAGAMENTO", re.I), "Salário"),
    (re.compile(r"SALAR\w*\s*(?:DE\s*PAGAMENTO)?", re.I), "Salário"),
    (re.compile(r"REMUNERACAO", re.I), "Salário"),
    (re.compile(r"\b13[°º]?\s*SALAR\w*", re.I), "Salário"),
    (re.compile(r"APOSENTADORIA|\bPENSAO\b", re.I), "Benefícios"),
    (re.compile(r"\bINSS\b|\bBPC\b|\bAUXILIO\b|\bBOLSA", re.I), "Benefícios"),
    (re.compile(r"DIVIDENDOS", re.I), "Dividendos"),
    (re.compile(r"RENDIMENTO|REMUNERACAO\s*(?:DO|DA)\s*CONTA", re.I), "Retorno de aplicações"),
    (re.compile(r"JUROS|\bPOUPANCA\b|\bCDB\b|\bLCI\b|\bLCA\b", re.I), "Retorno de aplicações"),
    (re.compile(r"REEMBOLSO|RESTITUICAO|ESTORNO", re.I), "Reembolso"),
    (re.compile(r"CREDITO\s*DE?\s*REEMBOLSO", re.I), "Reembolso"),
    (re.compile(r"PIX\s+CREDITO", re.I), "Recebimento de PIX"),
    (re.compile(r"PIX\s+RECEBIDO", re.I), "Recebimento de PIX"),
]

# Padrões de DESPESA inequívocos (tarifa/encargo de banco).
_NATURE_EXPENSE = [
    (re.compile(r"TARIFA|\bIOF\b|\bSPREAD\b", re.I), "Tarifas bancárias"),
    (re.compile(r"MANUTENCAO\s*(?:DE\s*)?CONTA", re.I), "Tarifas bancárias"),
    (re.compile(r"PACOTE\s*(?:DE\s*)?SERVICOS", re.I), "Tarifas bancárias"),
    (re.compile(r"CUSTODIA", re.I), "Tarifas bancárias"),
    (re.compile(r"ENCARGOS", re.I), "Encargos"),
    (re.compile(r"^PIX\s+ENVIADO", re.I), "Envio de PIX"),
    (re.compile(r"FATURA|\bFAT\.?\b|PAG(?:TO|\.)?\s*FAT|PGTO\s*FAT", re.I), "Transferência para cartão"),
]

# Movimentação NEUTRA (não consumo) — independe de categoria; fica sem categoria.
_NATURE_MOVEMENT = [
    (re.compile(r"PAGAMENTO\s*DE?\s*EMPRESTIMO", re.I), "Empréstimo"),
    (re.compile(r"RECEBIMENTO\s*DE?\s*EMPRESTIMO", re.I), "Empréstimo"),
    (re.compile(r"PIX\s+(?:ENTRE\s+)?CONTAS", re.I), "Transferência entre contas"),
    (re.compile(r"TRANSFERENCIA\s+ENVIADA", re.I), "Transferência enviada"),
    (re.compile(r"APLICACAO", re.I), "Aplicação"),
    (re.compile(r"RESGATE", re.I), "Resgate"),
    (re.compile(r"INVESTIMENTO", re.I), "Transferência entre investimentos"),
    (re.compile(r"PAGAMENTO\s*DE?\s*PRINCIPAL", re.I), "Pagamento de principal"),
    (re.compile(r"DIVIDA", re.I), "Pagamento de dívida"),
]


def _nature(user, up: str, direction: str):
    """Retorna decisão por NATUREZA (agnóstica de banco) ou (None, False, 0).

    ``up`` deve ser a descrição original em MAIÚSCULO e SEM acento.

    Retorna ``(category, is_movement, confidence)``:
      - category: Category resolvida (ou None se movimento/neutro);
      - is_movement: True se for movimentação neutra (sem categoria).
    """
    kind = Category.Kind.INCOME if direction == "income" else Category.Kind.EXPENSE
    is_income = direction == "income"

    # 1) Movimentação neutra (não consumo) — despesa que não é consumo comum.
    if not is_income:
        for pat, label in _NATURE_MOVEMENT:
            if pat.search(up):
                return None, True, _confidence(TransactionAnalysis.Source.NATURE)

    # 2) Receita inequívoca (salário, benefício, rendimento, reembolso).
    if is_income:
        for pat, cat_name in _NATURE_INCOME:
            if pat.search(up):
                cat = _resolve_category(user, cat_name, kind)
                if cat:
                    return cat, False, _confidence(TransactionAnalysis.Source.NATURE)

    # 3) Despesa inequívoca (tarifas/encargos bancários).
    if not is_income:
        for pat, cat_name in _NATURE_EXPENSE:
            if pat.search(up):
                cat = _resolve_category(user, cat_name, kind)
                if cat:
                    return cat, False, _confidence(TransactionAnalysis.Source.NATURE)

    return None, False, Decimal("0.00")


# --------------------------------------------------------------------------- #
# Extração de nome do cartão a partir da descrição da fatura.
#
# Padrões brasileiros comuns 2025-2026:
#   "FATURA NUBANK", "PAGTO FATURA INTER", "PAG. FAT. BRADESCO"
#   "FATURA C6 BANK", "FAT SICREDI", "FAT. ITAU PERSONALITE"
#   "FATURA DO CARTAO NU", "PGTO FATURA ITAU CLICK"
# --------------------------------------------------------------------------- #

_CARD_NAME_PATTERNS = [
    (re.compile(r"(?:FATURA|FAT\.?|PAG(?:TO|\.)?\s*(?:FAT(?:URA)?\.?)?|PGTO\s*FAT\.?)\s*(?:DO\s*CART[AÃ]O\s*)?(?:[\*]*\s*)?", re.I), None),
    (re.compile(r"NUBANK|\bNU\b|NU\s*PAGAMENTOS|NU\s*FINANCEIRA", re.I), "Nubank"),
    (re.compile(r"\bINTER\b|BANCO\s*INTER", re.I), "Inter"),
    (re.compile(r"ITAU|ITAU\s*PERSONALITE|ITAU\s*CLICK|Banco\s*Itaú", re.I), "Itaú"),
    (re.compile(r"BRADESCO|BRADESCO\s*EXCEL", re.I), "Bradesco"),
    (re.compile(r"C6\s*BANK|C6\s*BANKING", re.I), "C6 Bank"),
    (re.compile(r"SICREDI", re.I), "Sicredi"),
    (re.compile(r"BTG|BTG\s*PACTUAL", re.I), "BTG Pactual"),
    (re.compile(r"BANCO\s*247|247", re.I), "Banco 24 Horas"),
    (re.compile(r"AMEX|AMERICAN\s*EXPRESS", re.I), "Amex"),
    (re.compile(r"ELO", re.I), "Elo"),
    (re.compile(r"HIPER", re.I), "Hiper"),
]


def extract_card_name(description: str) -> str | None:
    """Extrai o nome do cartão a partir de uma descrição de fatura/pagamento.

    Exemplos:
        "PAGTO FATURA NUBANK"         -> "Nubank"
        "FAT. INTER"                  -> "Inter"
        "PGTO FATURA ITAU CLICK"      -> "Itaú"
        "FATURA C6 BANK"              -> "C6 Bank"
        "FAT SICREDI"                 -> "Sicredi"
        "PAG. FAT. BRADESCO"          -> "Bradesco"
        "FATURA DO CARTAO NU"         -> "Nubank"
    """
    if not description:
        return None
    up = _strip_accents(description).upper()

    # Verifica se é uma descrição de fatura/pagamento de cartão
    is_fatura = bool(re.search(
        r"FATURA|\bFAT\.?\b|PAG(?:TO|\.)?\s*FAT|PGTO\s*FAT",
        up, re.I,
    ))
    if not is_fatura:
        return None

    # Busca o nome do cartão em toda a descrição
    for pat, card_name in _CARD_NAME_PATTERNS[1:]:
        if pat.search(up):
            return card_name

    return None

_REVIEW_THRESHOLD = Decimal("0.75")


@dataclass
class ClassificationResult:
    category: Optional[Category] = None
    category_name: str = ""
    subcategory_name: str = ""
    merchant: Optional[Merchant] = None
    rule: Optional[ClassificationRule] = None
    confidence: Decimal = Decimal("0.00")
    method: str = TransactionAnalysis.Source.NONE
    needs_review: bool = True
    is_movement: bool = False
    normalized_description: str = ""

    @property
    def leaf_name(self) -> str:
        return self.subcategory_name or self.category_name


def classify(
    *,
    user,
    description: str,
    direction: str,
    merchant=None,
    source=Transaction.Source.IMPORTED_CSV,
    suggested_category: str = "",
) -> ClassificationResult:
    """Classifica uma movimentação (staging/transteração) de forma determinística.

    ``direction``: 'income' | 'expense' (Category.Kind).
    ``suggested_category``: categoria vinda do arquivo do cliente (coluna
    "Categoria Sugerida"), usada como sinal autoritativo quando a camada
    estrutural (natureza/movimentação) não decidiu — acima de merchant/contexto.
    """
    kind = Category.Kind.INCOME if direction == "income" else Category.Kind.EXPENSE
    normalized = normalize_description(description)
    up = _strip_accents(description or "").upper()
    result = ClassificationResult(
        merchant=merchant,
        normalized_description=normalized,
        confidence=Decimal("0.00"),
        needs_review=True,
        method=TransactionAnalysis.Source.NONE,
    )

    if not normalized:
        return result

    # Passo 1 — Movimentação neutra (não consumo).
    if _is_movement(description):
        result.method = TransactionAnalysis.Source.MOVEMENT
        result.confidence = _confidence(TransactionAnalysis.Source.MOVEMENT)
        result.is_movement = True
        result.needs_review = False
        return result

    # Passo 2 — Correção explícita do usuário (memória).
    pref = _user_preference(user, normalized, kind)
    if pref and pref.category:
        result.method = TransactionAnalysis.Source.USER_CORRECTION
        result.confidence = _confidence(TransactionAnalysis.Source.USER_CORRECTION)
        _apply_category(result, pref.category)
        result.needs_review = False
        return result

    # Passo 3 — Regra personalizada do usuário.
    rule = _match_rule(user, merchant_id=getattr(merchant, "pk", None), normalized=normalized, kind=kind, global_only=False)
    rule_cat = _rule_category(user, rule, kind)
    if rule and rule_cat:
        result.method = TransactionAnalysis.Source.USER_RULE
        result.confidence = _confidence(TransactionAnalysis.Source.USER_RULE)
        result.rule = rule
        _apply_category(result, rule_cat)
        result.needs_review = False
        return result

    # Passo 3b — Natureza da transação (agnóstica de banco, estrutural).
    nature_cat, nature_move, nature_conf = _nature(user, up, direction)
    if nature_move:
        result.method = TransactionAnalysis.Source.MOVEMENT
        result.confidence = nature_conf
        result.is_movement = True
        result.needs_review = False
        return result
    if nature_cat:
        result.method = TransactionAnalysis.Source.NATURE
        result.confidence = nature_conf
        _apply_category(result, nature_cat)
        result.needs_review = False
        return result

    # Passo 3c — Categoria sugerida pelo cliente/arquivo (sinal autoritativo).
    if suggested_category and suggested_category.strip():
        cat = _resolve_suggested_category(user, suggested_category, kind)
        if cat:
            result.method = TransactionAnalysis.Source.SUGGESTED
            result.confidence = _confidence(TransactionAnalysis.Source.SUGGESTED)
            _apply_category(result, cat)
            result.needs_review = False
            return result

    # Passo 4 — Merchant + associação conhecida.
    if merchant and merchant.default_category_name:
        cat = _resolve_category(user, merchant.default_category_name, kind)
        if cat:
            result.method = TransactionAnalysis.Source.MERCHANT
            result.confidence = _confidence(TransactionAnalysis.Source.MERCHANT)
            _apply_category(result, cat)
            result.needs_review = False
            return result

    # Passo 5 — Histórico do usuário (mesmo Merchant ou token significativo).
    history_cat, history_conf = _history(user, description, merchant, kind)
    if history_cat:
        result.category = history_cat
        _apply_category(result, history_cat)
        result.method = TransactionAnalysis.Source.HISTORY
        result.confidence = history_conf
        result.needs_review = history_conf < _REVIEW_THRESHOLD
        return result

    # Passo 6 — Regra global.
    global_rule = _match_rule(user, merchant_id=getattr(merchant, "pk", None), normalized=normalized, kind=kind, global_only=True)
    global_cat = _rule_category(user, global_rule, kind)
    if global_rule and global_cat:
        result.method = TransactionAnalysis.Source.GLOBAL_RULE
        result.confidence = _confidence(TransactionAnalysis.Source.GLOBAL_RULE)
        result.rule = global_rule
        _apply_category(result, global_cat)
        result.needs_review = False
        return result

    # Passo 7 — Contexto (palavras-chave).
    context_cat = _context_category(user, normalized, kind)
    if context_cat:
        _apply_category(result, context_cat)
        result.method = TransactionAnalysis.Source.CONTEXT
        result.confidence = _confidence(TransactionAnalysis.Source.CONTEXT)
        result.needs_review = result.confidence < _REVIEW_THRESHOLD
        return result

    # Passo 8 — Sem evidência -> revisão humana.
    result.method = TransactionAnalysis.Source.NONE
    result.confidence = Decimal("0.00")
    result.needs_review = True
    return result


def classify_transaction(user, transaction) -> ClassificationResult:
    """Classifica uma Transaction já existente (income/expense)."""
    direction = (
        "income" if transaction.type == Transaction.Type.INCOME else "expense"
    )
    merchant = transaction.merchant
    if merchant is None and (transaction.description or "").strip():
        merchant = _resolve_merchant(user, transaction.description)
    return classify(
        user=user,
        description=transaction.description or "",
        direction=direction,
        merchant=merchant,
        source=transaction.source,
    )


# --------------------------------------------------------------------------- #
# Aplicação e persistência (FASE 5 §14)

def apply_classification(user, transaction, result: ClassificationResult):
    """Aplica o resultado a uma Transaction (categoria) e persiste a decisão.

    Idempotente: cria/atualiza o TransactionAnalysis 1:1.
    Só altera ``transaction.category`` se o motor sugeriu uma categoria e a
    transação ainda não tem (ou está sendo sobreposta por correção explícita).
    """
    changed = False
    if (
        result.category is not None
        and result.category.owner_id == user.id
        and (transaction.category_id is None or result.method == TransactionAnalysis.Source.USER_CORRECTION)
    ):
        transaction.category = result.category
        changed = True
    if result.normalized_description and not transaction.normalized_description:
        transaction.normalized_description = result.normalized_description
        changed = True
    if changed:
        transaction.save()

    record_analysis(user, transaction, result)
    return transaction


def record_analysis(user, transaction, result: ClassificationResult, *, user_corrected=False) -> TransactionAnalysis:
    """Persiste/atualiza o snapshot 1:1 da decisão (FASE 5 §14)."""
    cat = result.category if (result.category and result.category.owner_id == user.id) else transaction.category
    analysis, _ = TransactionAnalysis.objects.update_or_create(
        transaction=transaction,
        defaults={
            "owner": user,
            "category": cat,
            "category_name": _parent_name(cat),
            "subcategory_name": cat.name if (cat and cat.parent_id) else "",
            "merchant": result.merchant or transaction.merchant,
            "rule": result.rule,
            "normalized_description": result.normalized_description or transaction.normalized_description or "",
            "confidence": result.confidence,
            "classification_source": result.method,
            "needs_review": result.needs_review,
            "is_movement": result.is_movement,
            "user_corrected": user_corrected,
        },
    )
    return analysis


def record_movement_analysis(*, user, transaction, normalized_description="", method=None):
    """Registra snapshot de MOVIMENTAÇÃO NEUTRA (FASE 8).

    Usado por fluxos que criam EXPENSE de natureza de movimentação (pagamento
    de fatura/dívida) — sem alterar accounting core: apenas marca no
    TransactionAnalysis que NÃO é consumo comum, evitando classificação errada.
    """
    TransactionAnalysis.objects.update_or_create(
        transaction=transaction,
        defaults={
            "owner": user,
            "category": None,
            "category_name": "",
            "subcategory_name": "",
            "merchant": transaction.merchant,
            "normalized_description": normalized_description or transaction.normalized_description or "",
            "confidence": _confidence(TransactionAnalysis.Source.MOVEMENT),
            "classification_source": method or TransactionAnalysis.Source.MOVEMENT,
            "needs_review": False,
            "is_movement": True,
            "user_corrected": False,
        },
    )


def apply_user_correction(*, user, transaction, category, merchant=None):
    """Fluxo de correção manual (§4): decide, aprende e persiste.

    - Aplica a categoria escolhida pelo usuário à Transaction;
    - registra TransactionAnalysis (user_correction);
    - aprende na UserPreference (memória determinística) para reutilização.
    """
    from .memory import learn

    if category is not None and category.owner_id != user.id:
        raise ValueError("Categoria deve pertencer ao usuário.")
    if merchant is not None and merchant.owner_id is not None and merchant.owner_id != user.id:
        raise ValueError("Estabelecimento pessoal deve pertencer ao usuário.")

    transaction.category = category
    transaction.save()

    kind = Category.Kind.INCOME if transaction.type == Transaction.Type.INCOME else Category.Kind.EXPENSE
    normalized = normalize_description(transaction.description or "")
    result = ClassificationResult(
        category=category,
        category_name=_parent_name(category),
        subcategory_name=category.name if (category and category.parent_id) else "",
        merchant=merchant or transaction.merchant,
        confidence=Decimal("0.97"),
        method=TransactionAnalysis.Source.USER_CORRECTION,
        needs_review=False,
        normalized_description=normalized,
    )
    record_analysis(user, transaction, result, user_corrected=True)

    if category:
        if merchant:
            from .merchants import learn_alias

            learn_alias(
                user=user,
                alias=normalized or (transaction.description or "")[:60],
                merchant=merchant,
            )
        learn(
            user=user,
            key=normalized or (transaction.description or "")[:120],
            category=category,
            merchant=merchant,
            kind=kind,
        )
    return transaction


# --------------------------------------------------------------------------- #
# Helpers internos (determinísticos)

def _confidence(source) -> Decimal:
    return _CONFIDENCE.get(source, Decimal("0.00"))


def _is_movement(normalized: str) -> bool:
    up = normalized.upper()
    return any(hint in up for hint in _MOVEMENT_HINTS)


def _user_preference(user, normalized, kind):
    if not normalized:
        return None
    return (
        UserPreference.objects.for_user(user)
        .filter(key=normalized, kind=kind)
        .first()
    )


def _match_rule(user, *, merchant_id, normalized, kind, global_only):
    q = {"is_active": True}
    if global_only:
        q["owner__isnull"] = True
    else:
        q["owner"] = user
        q["owner__isnull"] = False
    rules = (
        ClassificationRule.objects.filter(**q)
        .select_related("category", "merchant")
        .order_by("priority", "pk")
    )
    for rule in rules:
        if rule.kind != ClassificationRule.Kind.ANY and rule.kind != kind:
            continue
        if rule.matches(
            merchant_id=merchant_id,
            normalized_description=normalized,
        ):
            return rule
    return None


def _rule_category(user, rule, kind):
    """Categoria-alvo de uma regra, resolvida para o usuário em runtime.

    Usa ``rule.category`` (se pertencer ao usuário) ou resolve ``category_name``
    da taxonomia real do usuário. Nunca aponta para categoria de outro usuário.
    """
    if rule is None:
        return None
    if rule.category_id and rule.category.owner_id == user.id:
        return rule.category
    return _resolve_category(user, rule.category_name, kind)


def _resolve_category(user, name, kind):
    if not name:
        return None
    return (
        Category.objects.for_user(user)
        .filter(name__iexact=name, kind=kind, status=Category.Status.ACTIVE)
        .first()
    )


def _resolve_suggested_category(user, name, kind):
    """Resolve a categoria sugerida pelo arquivo do cliente.

    A coluna "Categoria Sugerida" pode conter nome do leaf ("Restaurante"),
    categoria-pai ("Alimentação"), pai+sub ("Restaurante / Delivery"),
    ou nome livre. Tenta a primeira parte separável que resolva.
    """
    name = (name or "").strip()
    if not name:
        return None
    cats = list(
        Category.objects.for_user(user).filter(
            kind=kind, status=Category.Status.ACTIVE
        ).select_related("parent")
    )
    if not cats:
        return None

    def _norm(c):
        return _strip_accents(c.name).lower()

    def _try(part):
        part = part.strip()
        if not part:
            return None
        norm = _strip_accents(part).lower()
        for c in cats:
            if _norm(c) == norm:
                return c
        for c in cats:
            if c.parent and c.parent.name and _norm(c.parent) == norm:
                return c
        tokens = set(t for t in re.split(r"[\s/]+", norm) if len(t) >= 3)
        if tokens:
            for c in cats:
                scope = _norm(c)
                if c.parent and c.parent.name:
                    scope = scope + " " + _norm(c.parent)
                scope_set = set(scope.split())
                if tokens.issubset(scope_set):
                    return c
        return None

    # 1) tenta a string inteira
    hit = _try(name)
    if hit:
        return hit
    # 2) separa por delimitadores comuns (pai / sub, pai - sub, pai (sub), pai|sub)
    for part in re.split(r"[/|\-;\u2013\u2014()]", name):
        hit = _try(part)
        if hit:
            return hit
    return None


def _apply_category(result: ClassificationResult, category):
    result.category = category
    result.category_name = _parent_name(category)
    result.subcategory_name = category.name if category.parent_id else ""


def _parent_name(category):
    if not category:
        return ""
    if category.parent_id:
        return category.parent.name
    return category.name


def _history(user, description, merchant, kind):
    """Determinístico: frequência de categoria do usuário para a mesma
    descrição/estabelecimento. Retorna (category, confidence) ou (None, 0)."""
    qs = Transaction.objects.for_user(user).filter(
        type__in=(Transaction.Type.INCOME, Transaction.Type.EXPENSE),
        category__isnull=False,
        category__kind=kind,
    )
    if merchant:
        qs = qs.filter(merchant=merchant)
    else:
        tokens = _tokens_meaningful(description)
        if not tokens:
            return None, Decimal("0.00")
        first = tokens[0]
        qs = qs.filter(description__icontains=first)

    row = (
        qs.values("category_id")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )
    if not row:
        return None, Decimal("0.00")
    cat = (
        Category.objects.for_user(user)
        .filter(pk=row["category_id"], status=Category.Status.ACTIVE)
        .first()
    )
    if not cat:
        return None, Decimal("0.00")
    conf = _confidence(TransactionAnalysis.Source.HISTORY)
    return cat, conf


def _context_category(user, normalized, kind):
    up = normalized.upper()
    for cat, keywords in _CONTEXT_KEYWORDS:
        if any(kw in up for kw in keywords):
            cat = _resolve_category(user, cat, kind)
            if cat:
                return cat
    return None


def _resolve_merchant(user, description):
    """Resolve Merchant para classificação autônoma (backfill).

    Só retorna merchant resolvido (não força/sobrescreve nada). Usado quando a
    Transaction ainda não tem merchant atribuído.
    """
    from .merchants import resolve_merchant

    try:
        res = resolve_merchant(user, description)
    except Exception:
        return None
    if res.matched and res.merchant is not None:
        return res.merchant
    return None


def _tokens_meaningful(description):
    words = re.split(r"[^A-Za-zÀ-ÿ0-9]+", (description or "").upper())
    return [w for w in words if len(w) >= 4]
