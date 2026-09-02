# Orçamentos (app `budgets`)

Gerencia **orçamentos** de gasto: por **categoria** (incluindo subcategorias) ou
**global** (todo o volume de despesas do usuário). O valor "realizado" **não** é
armazenado — é calculado a partir dos lançamentos de despesa
(`Transaction.EXPENSE`), seguindo a mesma definição da read layer do dashboard.

## Regras de negócio

- `kind=category` exige `category` do mesmo usuário; `kind=global` não aceita categoria.
- `limit_amount` é um inteiro em centavos, positivo; negativo/não-inteiro é rejeitado.
- Períodos: `monthly`, `yearly`, `custom`. `monthly` usa o mês da data de referência;
  `yearly` o ano corrente; `custom` usa `start_date`/`end_date` (quando ambos presentes,
  têm prioridade).
- `budget_spent` soma apenas `Transaction.EXPENSE` sobrepostas ao período; para orçamento
  por categoria inclui as subcategorias (via `Category.subcategories`). Não duplica
  contabilidade: receitas e transferências não contam.
- **Situação** (`get_budget_progress`): `healthy` (<80%), `attention` (>=80%),
  `exceeded` (>=100%). Limiares em `ATTENTION_PCT=80` e `EXCEEDED_PCT=100`.
- `is_active` controla se o orçamento entra no resumo; inativos só aparecem com `include_inactive`.

## Arquitetura

- **Services** (`apps/budgets/services/budgets.py`): `create_budget`, `update_budget`,
  `delete_budget`, `get_budget`, `get_budgets`, `budget_spent`, `get_budget_progress`,
  `get_budget_summary`. Leitura agregada em `services/reads.py`.
- **Views finas** (`apps/budgets/views.py`): `request -> form -> service -> redirect/render`.
  Ownership por `for_user` via mixin `_OwnedBudgetMixin` (404 para recurso alheio).
- **Form** (`apps/budgets/forms.py`): `forms.Form` puro com `BRLField` (reais→centavos);
  categoria filtrada por `for_user` + `status=ACTIVE` + `kind=EXPENSE`.

## Rotas (`/app/orcamentos/`)

`budget_list`, `budget_create`, `budget_detail`, `budget_edit`, `budget_toggle` (ativo/inativo),
`budget_delete`.

## Cálculo

- `planned = limit_amount`; `realized = budget_spent(...)`; `remaining = max(planned - realized, 0)`.
- `percent = round(realized / planned * 100)`.
- Resumo: `total_planned`, `total_realized`, `total_remaining`, `total_percent`, listas
  `exceeded`/`attention` e `larger_deviations` ordenadas por desvio.

## Testes

- `tests_services.py`: criação global/por categoria, rejeição de categoria alheia, limite
  inválido, ownership em update/get/delete, `budget_spent` (categoria+sub, exclusão de outras,
  ignora receita/outros usuários), classificação healthy/attention/exceeded e resumo.
- `tests_web.py`: anônimo redirecionado, isolamento A/B, create/edit, 404 para recurso alheio,
  toggle e exibição de excesso no detail.