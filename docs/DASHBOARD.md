# Dashboard Financeiro — Métricas, Fórmulas e Regras (Ordem 7)

> Documento de referência do **Dashboard Financeiro V1**. Define, de forma
> inequívoca, o que cada número significa, como é calculado (em **centavos**,
> nunca `float`), quais períodos existem, os estados vazios e as regras
> **determinísticas** do motor de insights (sem IA/LLM).

---

## 1. Camadas e fluxo

```
DB → MODELS → SERVICES/QUERIES (read layer) → VIEWMODEL → TEMPLATE → TAILWIND
```

- **`apps/dashboard/queries.py`** — leitura agregada (read layer). Centraliza
  todo cálculo; nenhum cálculo financeiro fica em view/template.
- **`apps/dashboard/viewmodel.py`** — `build_dashboard(...)` monta o contexto
  do template e o formatador BRL (`R$ 1.234,56`).
- **`apps/dashboard/insights.py`** — regras determinísticas sobre o ViewModel.
- **`templates/app/dashboard.html` + `templates/components/*`** — apresentação.

Isolamento multiusuário: toda query passa por `for_user(user)`/`owner=user`.
Regras idênticas às de domínio reutilizam os serviços existentes em
`apps/finance/services/*` e `apps/cards/services/*` — nunca são reimplementadas
no template.

---

## 2. Medidas de valor (fundos)

| Medida | Onde é calculada | Definição |
|---|---|---|
| `disponivel` | `queries.disponivel`/`net_balance` | Soma dos saldos das **contas ATIVAS** do usuário |
| `comprometido` | `queries.committed` | Soma das parcelas **pendentes/atrasadas** de cartão (`installment_obligations`) |
| `disponivel_apos` | viewmodel | `disponivel − comprometido` |

## 3. Fluxo de caixa (período)

| Medida | Definição |
|---|---|
| `receitas` | Soma de `Transaction` `INCOME` (+ `ADJUSTMENT` de ajuste positivo) no período |
| `despesas` | Soma de `Transaction` `EXPENSE` (+ `ADJUSTMENT`) no período |
| `resultado` | `receitas − despesas` |

**Regras anti dupla contabilização:**
- **Compra no cartão NÃO é despesa** até o pagamento da fatura (a dívida está em
  `comprometido`). Quando a fatura é paga, o pagamento gera **uma única** despesa.
- **Transferência interna não é** receita nem despesa (duas pernas na mesma
  conta de patrimônio).
- Filtros de cartão restringem as despesas de pagamento de fatura desse cartão,
  sem "inventar" receita.

## 4. Períodos

| Chave | Rótulo | Janela |
|---|---|---|
| `7d` | Últimos 7 dias | `today − 6` .. `today` |
| `30d` | Últimos 30 dias (default) | `today − 29` .. `today` |
| `3m` | Últimos 3 meses | Primeiro dia do mês corrente − 2 meses .. fim do mês corrente |
| `6m` | Últimos 6 meses | idem com 5 meses |
| `12m` | Últimos 12 meses | idem com 11 meses |

Filtros adicionais: `?account=<pk>` (restringe contas), `?card=<pk>` (restringe
cartões). `account`/`card` de outro usuário são **ignorados silenciosamente**
(ownership).

## 5. Gastos por categoria (top categorias)

- `spending_by_category`: soma de despesas por `Category` no período, ordenado
  decrescente, com `share_percent` (participação %) e comparação com o período
  anterior (`delta`) para leitura de tendência.
- `monthly_evolution`: agregação **por mês** (`TruncMonth`) de receitas/despesas
  + `saldo`, com barras normalizadas (`receitas_ratio`/`despesas_ratio`).

## 6. Timeline — próximos 30 dias (`upcoming_events`)

Eventos dos próximos 30 dias, ordenados:
- **Faturas de cartão** abertas/overdue (com valor e data de vencimento).
- **Recorrências ativas** projetadas via `occurrence_date` (regras, não
  transações gravadas).

## 7. Cartões / faturas / parcelamentos

- **Cartão**: `used` (obrigações futuras), `available = limit − used`,
  `used_pct`, `usage_tone` (`healthy`/`attention`/`exceeded`).
- **Faturas**: lista de faturas com valor, status e vencimento.
- **Parcelamentos**: parcelas com `amount`, `due_date` e status
  (pago/pendente/atrasado).

## 8. Orçamentos / Metas / Dívidas

- **Orçamento** (`BudgetRow`): `spent`, `limit`, `percent`, `status`
  (`healthy`/`attention`/`exceeded`).
- **Meta** (`GoalRow`): `current_amount`, `target_amount`,
  `progress_percent`, `status`, `target_date`.
- **Dívida** (`DebtRow`): `remaining_amount`, progresso de quitação.

## 9. Estados vazios (acessibilidade)

Cada seção, sem dados, exibe uma mensagem clara em vez de uma tabela vazia
(componente `empty_state.html`), ex.: "Sem movimentações neste período",
"Sem cartões", "Sem metas". O template `dashboard.html` também possui
alternativa textual `<table class="sr-only">` para o gráfico de barras.

## 10. Motor de insights — regras determinísticas

Fonte: `apps/dashboard/insights.py`. Severidade: `critical > attention > info`.
Fora de ordem, o motor permanece **puro/testável** (recebe o ViewModel).

| Regra | Condição | Severidade |
|---|---|---|
| Risco de liquidez | `comprometido > 0` e `disponivel − comprometido < constantes` (ou negativo) | critical / attention |
| Fatura acima do saldo | fatura vencendo em ≤ 3 dias e `amount > disponivel` | critical |
| Padrão pessoal | categoria com gasto em **≥ 2 dos 3 meses anteriores** e gasto atual **≥ 30% acima** da média mensal | attention |
| Despesa excepcional | `amount >= 3 × average_expense` **e** `amount >= R$ 500` | attention |
| Concentração | top categoria **≥ 50%** das despesas do período | attention |
| Maior categoria | sempre (info) | info |
| Limite do cartão | uso **≥ 80%** do limite | attention |
| Orçamento | status `exceeded` / `attention` | attention / info |
| Meta vencida | `target_date < today` e `current < target` | attention |
| Dívidas | resumo (quando existe dívida ativa) | info |

**Regra de ouro:** sem amostra suficiente a regra **não emite** afirmação —
nunca estima/inventa. São exibidos no máximo **6 insights** no template
(reordenados por severidade, depois por prioridade de impacto).

## 11. Constantes de regras

```python
MIN_PATTERN_SAMPLE  = 2    # gasto em >= 2 dos 3 meses anteriores
PATTERN_OVERRUN_PCT = 30   # % acima do padrão pessoal => attention
ANOMALY_MULTIPLE    = 3    # 3x a média da despesa
ANOMALY_FLOOR       = 50_000  # R$ 500,00
CONCENTRATION_PCT   = 50   # top categoria >= 50% das despesas
LIMIT_ALERT_PCT     = 80   # uso do limite do cartão
INVOICE_NEAR_DAYS   = 3    # fatura "vence em breve"
```

> Referência cruzada: `docs/ARQUITETURA_DOMINIO.md` → "Dashboard Financeiro e
> Read Layer (Ordem 7)" para o fluxo completo e decisões de arquitetura.
