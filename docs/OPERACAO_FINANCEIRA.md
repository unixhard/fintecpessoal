# Operação Financeira — Plataforma (Ordem 8)

Documento de referência da **plataforma financeira operacional completa**
entregue na Ordem 8: CRUD de contas, categorias, lançamentos, transferências,
recorrências, cartões, compras parceladas e faturas (com pagamento).

## 1. Princípios arquiteturais mantidos

- **Views finas**: `request → form → service → redirect/render`. Nenhuma regra
  financeira vive em view, form, template ou JS.
- **Regras financeiras nos services** (`apps/finance/services/*`,
  `apps/cards/services/*`): valores inteiros em centavos, ownership, atomicidade,
  validação de estado. **Nunca duplicados** na camada web.
- **Isolamento multiusuário**: toda consulta usa `for_user(user)`; toda escrita
  passa por services que validam `require_owned`. Nunca se confia em `pk` da URL.
- **Mobile-first**: shell com sidebar (desktop) + bottom bar com menu "Mais"
  (mobile); tabelas com scroll horizontal.

## 2. Serviços reutilizados

| Serviço | Uso |
|---|---|
| `finance.services.accounts` | create/update/archive/reactivate account |
| `finance.services.categories` | create/update/archive category |
| `finance.services.transactions` | record_income/record_expense/update/delete |
| `finance.services.transfers` | transfer_between (atômico, 2 pernas) |
| `finance.services.recurrences` | create_rule/update_rule/set_rule_status/generate_occurrence |
| `finance.services.balances` | account_balance (saldo derivado) |
| `cards.services.purchases` | create_card_purchase (à vista / parcelada) |
| `cards.services.invoices` | get_or_create_invoice / pay_invoice |
| `cards.services.reads` | card_usage / card_summary |
| `cards.services.cards` | update_card / set_card_status |

## 3. Regras financeiras preservadas (não reinventadas)

- **Dinheiro = inteiro em centavos** (D10); conversão reais→centavos ocorre na
  fronteira do form (`apps/core/forms.BRLField`).
- **Transferência** gera DUAS pernas `TRANSFER` atômicas; patrimônio total
  invariável. Não é receita + despesa.
- **Compra no cartão NÃO debita a conta** — é obrigação (InstallmentPurchase +
  Installments). A saída só ocorre no **pagamento da fatura**, que cria **UMA**
  Transaction EXPENSE (evita dupla contabilização).
- **Saldo de conta é derivado** (`initial_balance` + efeito das transações);
  não é armazenado redundante.
- **Edição/exclusão de lançamento**: permitida apenas para lançamentos simples
  (income/expense/adjustment) sem vínculo estrutural (transferência, compra de
  cartão, pagamento de fatura). O tipo não é editável.

## 4. Áreas e URLs (`/app/`)

| Área | Prefixo | Lista | Criar | Detalhe | Editar/Ação |
|---|---|---|---|---|---|
| Contas | `finance/contas` | `account_list` | `account_create` | `account_detail` | `account_edit`, `account_archive`, `account_reactivate` |
| Categorias | `finance/categorias` | `category_list` | `category_create` | — | `category_edit`, `category_archive` |
| Movimentações | `finance/movimentacoes` | `transaction_list` | `income_create`, `expense_create`, `transfer_create` | `transaction_detail` | `transaction_edit`, `transaction_delete` |
| Recorrências | `finance/recorrencias` | `recurring_list` | `recurring_create` | — | `recurring_edit`, `recurring_pause`, `recurring_activate`, `recurring_end` |
| Cartões | `cards/cartoes` | `card_list` | `card_create` | `card_detail` | `card_edit`, `card_block`, `card_close`, `card_reactivate` |
| Compras | `cards/compras` | `purchase_list` | `purchase_create` | — | — |
| Faturas | `cards/faturas` | `invoice_list` | (via compra) | `invoice_detail` | `invoice_pay` |

## 5. Formulários

- `apps/finance/forms.py`: `AccountCreateForm` (com saldo inicial),
  `AccountEditForm` (sem saldo inicial — saldo é derivado), `CategoryForm`,
  `IncomeForm`, `ExpenseForm`, `TransferForm`, `TransactionEditForm`,
  `RecurringForm`.
- `apps/cards/forms.py`: `CardCreateForm`/`CardEditForm`, `PurchaseForm`,
  `InvoicePayForm`.
- Todos filtram ForeignKeys (`account`, `category`, `payment_account`, `card`)
  por `for_user(user)` — impede seleção de objeto de outro usuário.

## 6. Pagamento de fatura

1. Usuário abre `invoice_detail`.
2. Confere o total (derivado da soma das parcelas do período).
3. Seleciona **conta de pagamento** (do próprio usuário) e data.
4. `cards.services.invoices.pay_invoice(...)` cria **UMA** Transaction EXPENSE,
   marca a fatura `PAID` e as parcelas como pagas — tudo em `atomic()`.
5. Fatura paga não pode ser paga novamente (estado `PAID`).

## 7. Testes

- `apps/finance/tests_web.py` (20): CRUD de contas/categorias/lançamentos/
  transferências/recorrências, filtros/busca, isolamento A/B, anônimo
  redirecionado, edição/exclusão.
- `apps/cards/tests_web.py` (16): CRUD de cartões, bloqueio/encerramento/
  reativação, compra à vista e parcelada, faturas, pagamento (uma despesa,
  sem dupla contabilização), isolamento A/B, pagamento com conta de outro
  usuário rejeitado.

**Total da suíte: 153 testes (117 pré-existentes + 36 novos).**

## 8. Navegação

`apps/dashboard/context.py` expõe 10 áreas e resolve a seção ativa por
`url_name`. No mobile, a bottom bar mostra 4 itens + menu "Mais" com o restante.
