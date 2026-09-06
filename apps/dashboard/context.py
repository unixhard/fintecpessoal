"""Context processors do shell da aplicação (nav principal)."""

from django.urls import resolve, reverse

# Mapeia um url_name resolvido para a chave de seção ativa da nav (5 seções).
_ACTIVE_BY_NAME = {
    # Início
    "index": "inicio",
    # Extrato — movimentações, contas, categorias, recorrências
    "transaction_list": "extrato",
    "transaction_detail": "extrato",
    "transaction_edit": "extrato",
    "transaction_delete": "extrato",
    "income_create": "extrato",
    "expense_create": "extrato",
    "transfer_create": "extrato",
    "account_list": "extrato",
    "account_create": "extrato",
    "account_detail": "extrato",
    "account_edit": "extrato",
    "account_archive": "extrato",
    "account_reactivate": "extrato",
    "category_list": "extrato",
    "category_create": "extrato",
    "category_edit": "extrato",
    "category_archive": "extrato",
    "recurring_list": "extrato",
    "recurring_create": "extrato",
    "recurring_edit": "extrato",
    "recurring_pause": "extrato",
    "recurring_activate": "extrato",
    "recurring_end": "extrato",
    # Cartões
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
    # Planejamento
    "budget_list": "planejamento",
    "budget_create": "planejamento",
    "budget_detail": "planejamento",
    "budget_edit": "planejamento",
    "budget_toggle": "planejamento",
    "budget_delete": "planejamento",
    "goal_list": "planejamento",
    "goal_create": "planejamento",
    "goal_detail": "planejamento",
    "goal_edit": "planejamento",
    "goal_contribute": "planejamento",
    "goal_pause": "planejamento",
    "goal_activate": "planejamento",
    "goal_archive": "planejamento",
    "goal_delete": "planejamento",
    "debt_list": "planejamento",
    "debt_create": "planejamento",
    "debt_detail": "planejamento",
    "debt_edit": "planejamento",
    "debt_pay": "planejamento",
    "debt_default": "planejamento",
    "debt_activate": "planejamento",
    "debt_archive": "planejamento",
    "debt_delete": "planejamento",
    # Mais — importar, análise, administrativo, configurações
    "imports:import_upload": "mais",
    "imports:review": "mais",
    "imports:result": "mais",
    "networth:index": "mais",
    "networth:register": "mais",
    "reports:index": "mais",
    "reports:ai_report": "mais",
    "reports:csv": "mais",
    "reports:print": "mais",
    "reminders:index": "mais",
    "comprovantes:list": "mais",
    "comprovantes:create": "mais",
    "comprovantes:edit": "mais",
    "comprovantes:delete": "mais",
    "comprovantes:download": "mais",
    "finance:rule_list": "mais",
    "finance:rule_create": "mais",
    "finance:rule_edit": "mais",
    "finance:rule_delete": "mais",
    "finance:rule_toggle": "mais",
    "finance:review_queue": "mais",
    "finance:review_bulk": "mais",
    "finance:backfill": "mais",
    # Configurações (substitui o placeholder do dashboard)
    "user_settings:index": "mais",
    "user_settings:profile": "mais",
    "user_settings:password": "mais",
    "user_settings:backup_export": "mais",
    "user_settings:backup_restore": "mais",
    "user_settings:wipe": "mais",
    "user_settings:delete_account": "mais",
}


def _nav_items():
    """Navegação simplificada em 5 seções grandes (Ordem UX/UI).

    Estrutura aninhada: cada seção top-level tem `key`, `label`, `icon`, `url`
    e uma lista `children` de sub-itens. Administração/Configurações ficam em
    "Mais". Renderizada no `_shell.html` (sidebar desktop + barra mobile).
    """
    return [
        # 1) Início — o dashboard responde "quanto tenho / posso gastar / a seguir / atenção"
        {"group": "inicio", "key": "inicio", "label": "Início", "icon": "⌂",
         "url": reverse("dashboard:index"), "children": []},

        # 2) Extrato — núcleo de lançamentos, contas, categorias e recorrências
        {"group": "extrato", "key": "extrato", "label": "Extrato", "icon": "⇄",
         "url": reverse("finance:transaction_list"), "children": [
            {"key": "movimentacoes", "label": "Movimentações", "icon": "⇄",
             "url": reverse("finance:transaction_list")},
            {"key": "contas", "label": "Contas", "icon": "◫",
             "url": reverse("finance:account_list")},
            {"key": "categorias", "label": "Categorias", "icon": "▤",
             "url": reverse("finance:category_list")},
            {"key": "recorrencias", "label": "Recorrências", "icon": "↻",
             "url": reverse("finance:recurring_list")},
        ]},

        # 3) Cartões
        {"group": "cartoes", "key": "cartoes", "label": "Cartões", "icon": "▰",
         "url": reverse("cards:card_list"), "children": [
            {"key": "compras", "label": "Compras", "icon": "▤",
             "url": reverse("cards:purchase_list")},
        ]},

        # 4) Planejamento
        {"group": "planejamento", "key": "planejamento", "label": "Planejamento", "icon": "◎",
         "url": reverse("budgets:budget_list"), "children": [
            {"key": "orcamentos", "label": "Orçamentos", "icon": "▤",
             "url": reverse("budgets:budget_list")},
            {"key": "metas", "label": "Metas", "icon": "◎",
             "url": reverse("goals:goal_list")},
            {"key": "dividas", "label": "Dívidas", "icon": "☰",
             "url": reverse("debts:debt_list")},
        ]},

        # 5) Mais — importação, análise, administrativo, configurações
        {"group": "mais", "key": "mais", "label": "Mais", "icon": "⋯",
         "url": reverse("imports:import_upload"), "children": [
            {"key": "importar", "label": "Importar", "icon": "⇊",
             "url": reverse("imports:import_upload")},
            {"key": "patrimonio", "label": "Patrimônio", "icon": "◧",
             "url": reverse("networth:index")},
            {"key": "relatorios", "label": "Relatórios", "icon": "▦",
             "url": reverse("reports:index")},
            {"key": "ia", "label": "Análise IA", "icon": "✦",
             "url": reverse("reports:ai_report")},
            {"key": "lembretes", "label": "Lembretes", "icon": "◷",
             "url": reverse("reminders:index")},
            {"key": "comprovantes", "label": "Comprovantes", "icon": "🖹",
             "url": reverse("comprovantes:list")},
            {"key": "regras", "label": "Regras de Classificação", "icon": "⊞",
             "url": reverse("finance:rule_list")},
            {"key": "revisao", "label": "Revisão", "icon": "⚑",
             "url": reverse("finance:review_queue")},
            {"key": "configuracoes", "label": "Configurações", "icon": "⚙",
             "url": reverse("settings:index")},
        ]},
    ]


def app_navigation(request):
    """Fornece `nav_items`, `active_nav` e `review_pending` para o shell."""
    nav_items = _nav_items()
    active = ""
    review_pending = 0
    try:
        match = resolve(request.path)
    except Exception:
        match = None
    if match is not None:
        url_name = match.url_name
        qualified = f"{match.app_name}:{url_name}"
        active = _ACTIVE_BY_NAME.get(qualified)
        if active is None:
            active = _ACTIVE_BY_NAME.get(url_name)
        if active is None and url_name == "section":
            active = match.kwargs.get("section", "")
    # Contagem de transações pendentes de revisão (Ordem 18 — badge na nav).
    try:
        from apps.finance.services.review import review_count
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            review_pending = review_count(user)
    except Exception:
        pass
    return {"nav_items": nav_items, "active_nav": active, "review_pending": review_pending}
