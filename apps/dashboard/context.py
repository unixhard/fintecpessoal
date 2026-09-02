"""Context processors do shell da aplicação (nav principal)."""

from django.urls import resolve, reverse

# Mapeia um url_name resolvido para a chave de seção ativa da nav.
_ACTIVE_BY_NAME = {
    "index": "inicio",
    "transaction_list": "movimentacoes",
    "transaction_detail": "movimentacoes",
    "transaction_edit": "movimentacoes",
    "transaction_delete": "movimentacoes",
    "income_create": "movimentacoes",
    "expense_create": "movimentacoes",
    "transfer_create": "movimentacoes",
    "account_list": "contas",
    "account_create": "contas",
    "account_detail": "contas",
    "account_edit": "contas",
    "account_archive": "contas",
    "account_reactivate": "contas",
    "card_list": "cartoes",
    "card_create": "cartoes",
    "card_detail": "cartoes",
    "card_edit": "cartoes",
    "card_block": "cartoes",
    "card_close": "cartoes",
    "card_reactivate": "cartoes",
    "purchase_list": "cartoes",
    "purchase_create": "cartoes",
    "invoice_list": "cartoes",
    "invoice_detail": "cartoes",
    "invoice_pay": "cartoes",
    "category_list": "categorias",
    "category_create": "categorias",
    "category_edit": "categorias",
    "category_archive": "categorias",
    "recurring_list": "recorrencias",
    "recurring_create": "recorrencias",
    "recurring_edit": "recorrencias",
    "recurring_pause": "recorrencias",
    "recurring_activate": "recorrencias",
    "recurring_end": "recorrencias",
    "budget_list": "orcamentos",
    "budget_create": "orcamentos",
    "budget_detail": "orcamentos",
    "budget_edit": "orcamentos",
    "budget_toggle": "orcamentos",
    "budget_delete": "orcamentos",
    "goal_list": "metas",
    "goal_create": "metas",
    "goal_detail": "metas",
    "goal_edit": "metas",
    "goal_contribute": "metas",
    "goal_pause": "metas",
    "goal_activate": "metas",
    "goal_archive": "metas",
    "goal_delete": "metas",
    "debt_list": "dividas",
    "debt_create": "dividas",
    "debt_detail": "dividas",
    "debt_edit": "dividas",
    "debt_pay": "dividas",
    "debt_default": "dividas",
    "debt_activate": "dividas",
    "debt_archive": "dividas",
    "debt_delete": "dividas",
    # Patrimônio / Relatórios / Lembretes / Comprovantes
    # (chaves qualificadas por app: url_name ambíguo — "index" existe em vários apps)
    "networth:index": "patrimonio",
    "networth:register": "patrimonio",
    "reports:index": "relatorios",
    "reports:ai_report": "ia",
    "reports:csv": "relatorios",
    "reports:print": "relatorios",
    "reminders:index": "lembretes",
    "comprovantes:list": "comprovantes",
    "comprovantes:create": "comprovantes",
    "comprovantes:edit": "comprovantes",
    "comprovantes:delete": "comprovantes",
    "comprovantes:download": "comprovantes",
}


def _nav_items():
    return [
        # Menu principal — núcleo de registros do dia a dia
        {"group": "menu", "key": "inicio", "label": "Início", "icon": "⌂", "url": reverse("dashboard:index")},
        {"group": "menu", "key": "movimentacoes", "label": "Movimentações", "icon": "⇄", "url": reverse("finance:transaction_list")},
        {"group": "menu", "key": "contas", "label": "Contas", "icon": "◫", "url": reverse("finance:account_list")},
        {"group": "menu", "key": "cartoes", "label": "Cartões", "icon": "▰", "url": reverse("cards:card_list")},
        # Planejamento
        {"group": "planejamento", "label": "Planejamento", "_heading": True},
        {"group": "planejamento", "key": "orcamentos", "label": "Orçamentos", "icon": "▤", "url": reverse("budgets:budget_list")},
        {"group": "planejamento", "key": "metas", "label": "Metas", "icon": "◎", "url": reverse("goals:goal_list")},
        {"group": "planejamento", "key": "dividas", "label": "Dívidas", "icon": "☰", "url": reverse("debts:debt_list")},
        # Análise
        {"group": "analise", "label": "Análise", "_heading": True},
        {"group": "analise", "key": "patrimonio", "label": "Patrimônio", "icon": "◧", "url": reverse("networth:index")},
        {"group": "analise", "key": "relatorios", "label": "Relatórios", "icon": "▦", "url": reverse("reports:index")},
        {"group": "analise", "key": "ia", "label": "Análise IA", "icon": "✦", "url": reverse("reports:ai_report")},
        {"group": "analise", "key": "lembretes", "label": "Lembretes", "icon": "◷", "url": reverse("reminders:index")},
        {"group": "analise", "key": "comprovantes", "label": "Comprovantes", "icon": "🖹", "url": reverse("comprovantes:list")},
        # Administração
        {"group": "admin", "label": "Administração", "_heading": True},
        {"group": "admin", "key": "categorias", "label": "Categorias", "icon": "▤", "url": reverse("finance:category_list")},
        {"group": "admin", "key": "recorrencias", "label": "Recorrências", "icon": "↻", "url": reverse("finance:recurring_list")},
        {"group": "admin", "key": "configuracoes", "label": "Configurações", "icon": "⚙", "url": reverse("dashboard:section", args=["configuracoes"])},
    ]


def app_navigation(request):
    """Fornece `nav_items` e a chave da seção ativa para o shell."""
    nav_items = _nav_items()
    active = ""
    try:
        match = resolve(request.path)
    except Exception:
        match = None
    if match is not None:
        url_name = match.url_name
        # Preferência por chave qualificada (app:name) quando o url_name é
        # ambíguo (ex.: "index" existe em dashboard/networth/reports/reminders).
        qualified = f"{match.app_name}:{url_name}"
        active = _ACTIVE_BY_NAME.get(qualified)
        if active is None:
            active = _ACTIVE_BY_NAME.get(url_name)
        if active is None and url_name == "section":
            active = match.kwargs.get("section", "")
    return {"nav_items": nav_items, "active_nav": active}
