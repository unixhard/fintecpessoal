# Dívidas (app `debts`)

Gerencia **dívidas** (empréstimo, financiamento, parcelamento externo, outro):
valor total, valor pago, taxa de juros, vencimento, credor e estado.

## Regras de negócio

- Cada **pagamento** cria uma **`Transaction.EXPENSE` real** na conta do usuário via
  `transactions_svc.record_expense` (rastreabilidade vem do sistema de contas já existente —
  sem modelo de pagamento novo nem contabilidade paralela). Tudo em `db_transaction.atomic()`.
- `Debt.paid_amount` acumula os pagamentos.
- Recusa pagamento acima do saldo restante (nunca negativo), em dívida `paid_off` e com
  valor não-positivo; exige conta e dívida do mesmo usuário.
- Auto-marca `PAID_OFF` quando `paid_amount >= total_amount`.
- `update_debt`: se o total cair abaixo do já pago, `paid_amount` é limitado ao novo total
  (não cria negativo); reaprecia o estado `PAID_OFF`.
- `set_debt_status` (via `DebtStatusView`): apenas `ACTIVE`, `DEFAULTED`, `ARCHIVED`; rejeita
  classificar manualmente `PAID_OFF` e reclassificar dívida já quitada.
- `remaining_amount` = `total_amount - paid_amount`.

## Arquitetura

- **Services** (`apps/debts/services/debts.py`): `create_debt`, `update_debt`, `delete_debt`,
  `get_debt`, `get_debts`, `set_debt_status`, `record_debt_payment`, `get_debt_progress`,
  `get_debt_summary`. Leitura agregada em `services/reads.py`.
- **Views finas** (`apps/debts/views.py`): `request -> form -> service -> redirect/render`.
  Ownership via `_OwnedDebtMixin` (404 para recurso alheio). `DebtPaymentView` renderiza o
  detail com `pay_form` e `payment_error`.
- **Forms** (`apps/debts/forms.py`): `DebtForm` e `DebtPaymentForm` (conta filtrada por
  `for_user` + `ACTIVE`; `date` inicial = hoje).

## Rotas (`/app/dividas/`)

`debt_list`, `debt_create`, `debt_detail`, `debt_edit`, `debt_pay`, `debt_default`
(inadimplente), `debt_activate`, `debt_archive`, `debt_delete`.

## Cálculo

- `remaining = total - paid`; `percent = round(paid / total * 100)`.
- Resumo: `total_amount`, `paid_amount`, `total_remaining`, `overall_percent`, `overdue`
  (inadimplentes ou vencidas ativas) e `next_due` (ativas ordenadas por vencimento).

## Testes

- `tests_services.py`: criação (ativa/quitada, rejeição de total inválido e paid>total),
  ownership em update/get/delete, pagamento (cria UMA expense, acumula, `PAID_OFF`,
  rejeições: overpayment/quitada/conta alheia/dívida alheia/valor não-positivo), transições
  de status e resumo.
- `tests_web.py`: anônimo redirecionado, isolamento A/B, create/edit, 404 para recurso alheio,
  pagamento pelo form (cria expense e acumula), rejeição de conta alheia e transições por POST.