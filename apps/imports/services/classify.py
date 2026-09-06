"""Classificação de movimentações em camadas (Ordem 17).

CAMADA 1 — REGRAS       : mapeamentos de palavras-chave -> nome de categoria.
CAMADA 2 — HISTÓRICO    : reutiliza a categoria que o próprio usuário já usou
                          para descrições semelhantes.
CAMADA 3 — IA (opcional): nunca obrigatória; desligada por padrão nesta fase.

A classificação SUGERE um ``category_name``. A resolução para uma Category
real (e a eventual criação) acontece na confirmação, através dos services
existentes — esta camada nunca cria nada.
"""

from dataclasses import replace

from django.db.models import Count

from .candidates import Candidate

# CAMADA 1 — regras extensíveis (palavra-chave -> nome de categoria).
# Mantidas fora das views (Ordem 17: não criar centenas de condições na view).
_RULES = [
    # Alimentação
    ("IFOOD", "Alimentação"), ("iFood", "Alimentação"), ("RESTAURANTE", "Alimentação"),
    ("Restaurante", "Alimentação"), ("ACOUGUE", "Alimentação"), ("MERCADO", "Alimentação"),
    ("Supermercado", "Alimentação"), ("PADARIA", "Alimentação"), ("HORTIFRUTI", "Alimentação"),
    # Transporte
    ("UBER", "Transporte"), ("99TAXI", "Transporte"), ("IFOOD TRANSPORT", "Transporte"),
    ("POSTO", "Transporte"), ("GASOLINA", "Transporte"), ("COMBUSTIVEL", "Transporte"),
    ("SEM PARAR", "Transporte"), ("SEMPARAR", "Transporte"),
    # Assinaturas / Moradia
    ("NETFLIX", "Assinaturas"), ("SPOTIFY", "Assinaturas"), ("PRIME VIDEO", "Assinaturas"),
    ("AMAZON PRIME", "Assinaturas"), ("DISNEY", "Assinaturas"), ("APPLE.COM", "Assinaturas"),
    ("MICROSOFT", "Assinaturas"), ("GOOGLE", "Assinaturas"), ("STORE.GOOGLE", "Assinaturas"),
    ("ALURA", "Assinaturas"), ("GLOBOPLAY", "Assinaturas"), ("YOUTUBE", "Assinaturas"),
    # Moradia / contas
    ("ALUGUEL", "Moradia"), ("COND", "Moradia"), ("ENEL", "Moradia"), ("LUZ", "Moradia"),
    ("AGUA", "Moradia"), ("SABESP", "Moradia"), ("GAS", "Moradia"), ("INTERNET", "Moradia"),
    ("TELEFONE", "Moradia"), ("CELULAR", "Moradia"), ("VIVO", "Moradia"), ("TIM", "Moradia"),
    ("CLARO", "Moradia"), ("NET", "Moradia"), ("MERCADOPAGO", "Moradia"),
    # Saúde
    ("FARMACIA", "Saúde"), ("DROGARIA", "Saúde"), ("MEDICO", "Saúde"), ("CLINICA", "Saúde"),
    ("UNIMED", "Saúde"), ("AMIL", "Saúde"), ("SULAMERICA", "Saúde"), ("DENTE", "Saúde"),
    # Lazer / educação / renda
    ("CINEMA", "Lazer"), ("SHOPPING", "Lazer"), ("DESCOMPLICA", "Educação"),
    ("ESCOLA", "Educação"), ("SALARIO", "Salário"), ("PIX RECEBIDO", "Outras receitas"),
]

# Normalizados para busca (upper).
_RULES_UPPER = [(kw.upper(), cat) for kw, cat in _RULES]


def suggest_category_name(description: str) -> str:
    """CAMADA 1 — resolve o nome de categoria pela regra de palavras-chave."""
    if not description:
        return ""
    up = description.upper()
    for kw, cat in _RULES_UPPER:
        if kw in up:
            return cat
    return ""


def classify_candidate(user, candidate: Candidate) -> Candidate:
    """Aplica as camadas de classificação a um candidato.

    Retorna um novo Candidate com ``category_name`` (e ``category`` quando a
    categoria já existir para o usuário).
    """
    from ...finance.models import Category

    desc = (candidate.description or "").strip()
    if not desc:
        return candidate

    # CAMADA 2 — histórico do usuário (prioridade sobre regras, conforme ordem):
    # reutilizar a categoria que o usuário já escolheu para descrição semelhante.
    history_name = _from_history(user, desc)
    if history_name:
        category = _existing_category(user, history_name, kind_for(candidate.direction))
        return replace(candidate, category_name=history_name, category=category)

    # CAMADA 1 — regras.
    rule_name = suggest_category_name(desc)
    if rule_name:
        category = _existing_category(user, rule_name, kind_for(candidate.direction))
        return replace(candidate, category_name=rule_name, category=category)

    # CAMADA 3 — IA (opcional; desligada por padrão nesta fase). Deixamos sem
    # sugestão; a revisão manual cobre o restante.
    return candidate


def _from_history(user, description: str):
    from ...finance.models import Transaction

    tokens = _tokens(description)
    if not tokens:
        return ""
    # Descarta tokens genéricos muito curtos.
    meaningful = [t for t in tokens if len(t) >= 3]
    if not meaningful:
        return ""
    # Procura a categoria mais frequente usada pelo usuário para o token.
    best = None
    best_count = 0
    for token in meaningful:
        qs = (
            Transaction.objects.for_user(user)
            .filter(description__icontains=token, category__isnull=False)
            .values("category__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        row = qs.first()
        if row and (row["n"] > best_count):
            best = row["category__name"]
            best_count = row["n"]
    return best or ""


def _tokens(description: str):
    import re
    words = re.split(r"[^A-Za-zÀ-ÿ0-9]+", description.lower())
    return [w for w in words if w]


def _existing_category(user, name, kind):
    from ...finance.models import Category

    return (
        Category.objects.for_user(user)
        .filter(name__iexact=name, kind=kind, status=Category.Status.ACTIVE)
        .first()
    )


def kind_for(direction: str) -> str:
    from ...finance.models import Category

    return (
        Category.Kind.INCOME
        if direction == "income"
        else Category.Kind.EXPENSE
    )
