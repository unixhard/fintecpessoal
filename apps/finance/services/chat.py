"""Serviço de orquestração do Assistente Fintec (MÓDULO CHAT).

Organiza o fluxo  ``mensagem -> parser -> rascunho -> confirmação -> services``:

- ``interpret``  : interpreta a mensagem e devolve um RASCUNHO (sem gravar nada);
- ``confirm``    : valida TUDO no servidor, reaplica o parser na mensagem
  original e persiste via os services financeiros JÁ existentes.

Regras garantidas:
- nenhuma escrita antes de ``confirm``;
- ``confirm`` nunca confia em valores vindos do cliente: re-deriva o lançamento
  da mensagem original e re-valida cada campo (edição manual também é validada);
- ownership de conta/cartão/categoria sempre via ``for_user``;
- receita NUNCA vai para cartão de crédito;
- despesa em cartão usa ``create_card_purchase`` (fatura/limite), nunca um
  débito manual direto no saldo;
- idempotência no backend (cache) para impedir duplo clique / refresh / retry
  de gerar lançamentos duplicados.
"""

import hashlib
import random
from datetime import date as _date

from django.core.cache import cache

from apps.cards.models import CreditCard
from apps.cards.services.purchases import create_card_purchase

from ..models import Account, Category, Transaction
from . import transactions as transactions_svc
from .base import ensure_owned_integer_amount
from .errors import FinancialServiceError, InvalidAmountError
from .chat_parser import (
    MAX_AMOUNT_CENTS,
    MAX_DESCRIPTION_LEN,
    MAX_MESSAGE_LEN,
    _GROUP_PARENT_NAME,
    normalize_accents,
    parse_date_hint,
    parse_decimal_override,
    parse_message,
)

# Tempo de janela de idempotência (segundos) para confirmações repetidas.
IDEMPOTENCY_TTL = 120

CHAT_NOTES = "Criado pelo Assistente Fintec"

_OK_VARIANTS = (
    "Entendi. Montei este lançamento para você revisar.",
    "Certo. Interpretei sua mensagem desta forma:",
    "Beleza. Confira os dados antes de salvar.",
    "Identifiquei a movimentação. Veja se está tudo correto.",
)
_SUCCESS_VARIANTS = (
    "Lançamento registrado com sucesso!",
    "Pronto, lançamento salvo!",
    "Tudo certo, seu lançamento foi salvo.",
)


def _first_name(user):
    return user.first_name or user.username or "usuário"


def _variant(variants):
    return random.choice(variants)


# --------------------------------------------------------------------------- #
# Resolução de categoria (grupo do parser -> categoria REAL do usuário)
# --------------------------------------------------------------------------- #


def resolve_category(user, group, kind):
    """Associa o grupo de categoria detectado a uma Category real do usuário.

    Nunca cria categoria — se nada corresponder, devolve None (a UI permite
    seleção manual). Só categorias ativas e do ``kind`` correto são aceitas.
    """
    if not group:
        return None
    if kind == "income":
        candidates = ("Rendimentos", "Renda extra")
    elif group == "Renda":
        candidates = ("Rendimentos", "Renda extra")
    else:
        candidates = (_GROUP_PARENT_NAME.get(group),)
        if not candidates[0]:
            return None

    kind_model = (
        Category.Kind.INCOME if kind == "income" else Category.Kind.EXPENSE
    )
    cats = list(
        Category.objects.for_user(user)
        .filter(status=Category.Status.ACTIVE, kind=kind_model)
    )
    candidates_norm = {normalize_accents(c) for c in candidates if c}
    for cat in cats:
        if normalize_accents(cat.name) in candidates_norm:
            return cat
    return None


# --------------------------------------------------------------------------- #
# Interpretação (rascunho — NÃO grava)
# --------------------------------------------------------------------------- #


def _accounts_payload(user):
    return [
        {"id": acc.pk, "name": acc.name, "type_label": acc.get_type_display()}
        for acc in (
            Account.objects.for_user(user)
            .filter(status=Account.Status.ACTIVE)
            .order_by("name")
        )
    ]


def _cards_payload(user):
    return [
        {"id": card.pk, "name": card.name}
        for card in (
            CreditCard.objects.for_user(user)
            .filter(status=CreditCard.Status.ACTIVE)
            .order_by("name")
        )
    ]


def _categories_payload(user):
    return [
        {"id": cat.pk, "name": cat.name, "kind": cat.kind}
        for cat in (
            Category.objects.for_user(user)
            .filter(status=Category.Status.ACTIVE)
            .order_by("kind", "name")
        )
    ]


def _outcome_message(first, outcome):
    if outcome == "scope":
        return (
            f"{first}, meu foco aqui é registrar suas entradas e saídas. "
            'Envie algo como "Gastei 20 no café" ou "Recebi 200 de uma venda".'
        )
    if outcome == "no_value":
        return (
            f"{first}, não consegui encontrar o valor da transação. "
            'Tente algo como "Gastei 58 no Uber".'
        )
    if outcome == "too_long":
        return (
            f"{first}, essa mensagem é muito longa. Tente algo como "
            f'"Gastei 58 no Uber" (máximo de {MAX_MESSAGE_LEN} caracteres).'
        )
    if outcome == "invalid_value":
        return (
            f"{first}, o valor informado não é válido. "
            "O lançamento precisa de um valor maior que zero."
        )
    return f"{first}, não consegui interpretar essa mensagem. Tente de novo."


def interpret(*, user, text):
    """Endpoint 1 do fluxo: interpreta e devolve o rascunho + opções mínimas.

    Retorna um dicionário pronto para ``JsonResponse`` (``success``,
    ``message``, ``draft``, ``accounts``, ``cards``, ``categories``).
    """
    first = _first_name(user)
    text = (text or "").strip()

    parsed = parse_message(text)
    if parsed["outcome"] != "ok":
        return {
            "success": False,
            "message": _outcome_message(first, parsed["outcome"]),
            "type_ambiguous": False,
            "draft": None,
            "accounts": _accounts_payload(user),
            "cards": _cards_payload(user),
            "categories": _categories_payload(user),
        }

    kind = parsed["type"]
    category = None
    if kind is not None:
        category = resolve_category(user, parsed["category_group"], kind)

    draft = {
        "type": kind,
        "type_ambiguous": parsed["type_ambiguous"],
        "amount": parsed["amount"],
        "amount_cents": parsed["amount_cents"],
        "description": parsed["description"],
        "category_id": category.pk if category else None,
        "category_label": category.name if category else parsed["category_group"],
        "category_group": parsed["category_group"],
        "date": parsed["date"],
        "date_label": parsed["date_label"],
    }

    if parsed["type_ambiguous"]:
        message = (
            _variant(_OK_VARIANTS)
            + f" {first}, esse valor foi uma entrada ou uma saída?"
        )
    else:
        message = _variant(_OK_VARIANTS)

    return {
        "success": True,
        "message": message,
        "type_ambiguous": parsed["type_ambiguous"],
        "draft": draft,
        "accounts": _accounts_payload(user),
        "cards": _cards_payload(user),
        "categories": _categories_payload(user),
    }


# --------------------------------------------------------------------------- #
# Confirmação (persistência via services existentes)
# --------------------------------------------------------------------------- #


def confirm(
    *,
    user,
    message,
    kind=None,
    account_id=None,
    card_id=None,
    category_id=None,
    date=None,
    amount=None,
    description=None,
):
    """Endpoint 2 do fluxo: re-valida e grava o lançamento.

    Retorna dicionário para ``JsonResponse`` (sucesso em ``success``).
    ``already_exists`` indica que a requisição repetida foi bloqueada.
    """
    first = _first_name(user)
    message = (message or "").strip()

    if not message:
        return _error(first, "Não recebi a frase do lançamento. Tente de novo.")

    parsed = parse_message(message)
    if parsed["outcome"] != "ok":
        return _error(first, _outcome_message(first, parsed["outcome"]))

    # 1. Tipo — preferência explícita do usuário OU intenção parseada.
    ttype = kind if kind in ("income", "expense") else parsed["type"]
    if ttype not in ("income", "expense"):
        return _error(
            first,
            f"{first}, preciso saber se esse valor foi uma entrada ou uma saída.",
        )
    kind_model = (
        Category.Kind.INCOME if ttype == "income" else Category.Kind.EXPENSE
    )

    # 2. Valor — palavra digitada vence, mas SEMPRE re-validada (Decimal).
    try:
        if amount is not None and str(amount).strip():
            cents = parse_decimal_override(str(amount))
            ensure_owned_integer_amount(cents, field="valor")
        else:
            cents = ensure_owned_integer_amount(parsed["amount_cents"], field="valor")
    except InvalidAmountError:
        cents = None
    if cents is None or cents <= 0 or cents > MAX_AMOUNT_CENTS:
        return _error(
            first,
            f"{first}, o valor informado não é válido. O lançamento precisa "
            "de um valor maior que zero e dentro dos limites do sistema.",
        )

    # 3. Data — re-validada sempre no servidor.
    if date and str(date).strip():
        try:
            tx_date = _date.fromisoformat(str(date).strip())
        except (ValueError, TypeError):
            return _error(first, "A data informada não é válida.")
    else:
        tx_date, _ = parse_date_hint(message)

    # 4. Descrição — edição manual é aceita, mas limitada e re-validada.
    if description is not None and str(description).strip():
        description = (description or "").strip()[:MAX_DESCRIPTION_LEN]
    else:
        description = parsed["description"]

    # 5. Categoria — ownership + kind sempre verificados.
    category = None
    if category_id:
        category = (
            Category.objects.for_user(user)
            .filter(status=Category.Status.ACTIVE, pk=category_id, kind=kind_model)
            .first()
        )
        if not category:
            return _error(
                first,
                "A categoria escolhida não existe ou não combina com o tipo de "
                "lançamento.",
            )
    else:
        category = resolve_category(user, parsed["category_group"], ttype)

    # 6. Conta x cartão — receita NUNCA em cartão.
    account = None
    card = None
    if ttype == "income":
        if card_id:
            return _error(
                first,
                "Receitas não são lançadas em cartão de crédito. Escolha uma conta.",
            )
        if not account_id:
            return _error(first, "Escolha a conta de destino da receita.")
        account = (
            Account.objects.for_user(user)
            .filter(status=Account.Status.ACTIVE, pk=account_id)
            .first()
        )
        if not account:
            return _error(first, "Conta não encontrada ou indisponível.")
    else:
        if account_id and card_id:
            return _error(
                first, "Escolha uma forma de pagamento: conta OU cartão."
            )
        if not account_id and not card_id:
            return _error(
                first,
                "Selecione a conta de onde o dinheiro saiu (ou o cartão) para "
                "concluir o lançamento.",
            )
        if account_id:
            account = (
                Account.objects.for_user(user)
                .filter(status=Account.Status.ACTIVE, pk=account_id)
                .first()
            )
            if not account:
                return _error(first, "Conta não encontrada ou indisponível.")
        else:
            card = (
                CreditCard.objects.for_user(user)
                .filter(status=CreditCard.Status.ACTIVE, pk=card_id)
                .first()
            )
            if not card:
                return _error(first, "Cartão não encontrado ou indisponível.")

    # 7. Idempotência (bloqueia duplo clique / refresh / retry no backend).
    key_source = "|".join(
        [
            str(user.pk),
            normalize_accents(message),
            ttype,
            str(account.pk if account else card.pk),
            str(category.pk if category else ""),
            tx_date.isoformat(),
        ]
    )
    key = "fintec.chat.confirm.v1:" + hashlib.sha256(key_source.encode()).hexdigest()
    if not cache.add(key, "1", IDEMPOTENCY_TTL):
        return {
            "success": True,
            "already_exists": True,
            "message": (
                "Pronto — este lançamento já foi registrado há pouco "
                "(evitamos duplicar)."
            ),
        }

    # 8. Persistência via services existentes (única fonte de regras).
    try:
        if ttype == "income":
            transactions_svc.record_income(
                user=user,
                account=account,
                amount=cents,
                date=tx_date,
                description=description,
                category=category,
                source=Transaction.Source.MANUAL,
                notes=CHAT_NOTES,
            )
        elif account is not None:
            transactions_svc.record_expense(
                user=user,
                account=account,
                amount=cents,
                date=tx_date,
                description=description,
                category=category,
                source=Transaction.Source.MANUAL,
                notes=CHAT_NOTES,
            )
        else:
            purchase = create_card_purchase(
                user=user,
                card=card,
                description=description,
                total_amount=cents,
                installment_count=1,
                first_due_date=tx_date,
            )
    except (FinancialServiceError, InvalidAmountError) as exc:
        cache.delete(key)
        return _error(first, str(exc) or "Não foi possível registrar o lançamento.")

    if card is not None:
        success_message = (
            "Compra registrada no cartão! O valor entrará na fatura do "
            f"cartão {card.name}."
        )
    else:
        success_message = _variant(_SUCCESS_VARIANTS)

    return {
        "success": True,
        "already_exists": False,
        "message": success_message,
    }


def _error(first, message):
    return {"success": False, "message": message}