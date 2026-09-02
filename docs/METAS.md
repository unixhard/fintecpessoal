# Metas financeiras (app `goals`)

Gerencia **metas** financeiras (ex.: reserva de emergência, viagem): valor alvo,
acumulado, prazo, prioridade e status. A meta acumula em `Goal.current_amount`
como **marcador de progresso**; o movimento financeiro real de aporte é feito na
camada de contas/transações existente (não se cria segunda contabilidade paralela).

## Regras de negócio

- A criação **não** expõe `current_amount` — a meta começa em `0`. O acumulado
  só muda por contribuição explícita (`add_goal_contribution`).
- `add_goal_contribution` é **rastreador apenas**: não cria `Transaction`. Capina no
  alvo (nunca excede) e auto-marca `ACHIEVED` quando `current_amount >= target_amount`.
- Não aceita aporte em meta `achieved` nem `archived`; rejeita valor não-positivo.
- `set_goal_status` permite apenas `active`, `paused`, `archived` (`achieved` é derivado).
- `required_monthly`: quanto por mês falta para atingir no prazo (apenas com `target_date`
  e meta ativa com saldo restante).
- `projected_completion`: estimativa de conclusão pelo ritmo observado — **só** emitida
  quando a meta tem amostra de >= 1 mês desde a criação e aporte observado; caso contrário
  `None` (evita previsão artificial).
- Status inicial: `ACTIVE`, ou `ACHIEVED` se o valor inicial já cobre o alvo (só por
  caminho de service que permita inicial != 0; o CRUD web mantém zero).

## Arquitetura

- **Services** (`apps/goals/services/goals.py`): `create_goal`, `update_goal`, `delete_goal`,
  `get_goal`, `get_goals`, `set_goal_status`, `add_goal_contribution`, `get_goal_progress`,
  `get_goal_summary`. Leitura agregada em `services/reads.py`.
- **Views finas** (`apps/goals/views.py`): `request -> form -> service -> redirect/render`.
  Ownership via `_OwnedGoalMixin` (404 para recurso alheio). `GoalContributionView`
  renderiza o detail com `contribution_form` e `contribution_error`.
- **Forms** (`apps/goals/forms.py`): `GoalForm` (sem `current_amount`) e
  `GoalContributionForm` (apenas `amount`).

## Rotas (`/app/metas/`)

`goal_list`, `goal_create`, `goal_detail`, `goal_edit`, `goal_contribute`, `goal_pause`,
`goal_activate`, `goal_archive`, `goal_delete`.

## Cálculo

- `remaining = max(target - current, 0)`; `percent = goal.progress_percent`.
- `required_monthly = ceil(remaining / months_left)` (só se `months_left > 0`).
- `months_between` arredonda para baixo; `_ceil_div(a,b) = -(-a//b)`.
- `projected_completion`: mantém o ritmo observado até quitar o saldo, nunca antes de hoje.

## Testes

- `tests_services.py`: criação zero/aceitação parcial, rejeição de alvo/valor inválidos,
  ownership em update/get/delete, contribuição (acúmulo, cap, auto-achieved, rejeições a
  achieved/archived/alheia), transições de status, progresso e resumo.
- `tests_web.py`: anônimo redirecionado, isolamento A/B, create/edit, 404 para recurso
  alheio, aporte pelo form (sem exceder alvo) e transições de status por POST.