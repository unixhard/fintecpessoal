# FINTECPESSOAL — Resumo do Projeto (para análise por IA)

> Documento conciso com as informações essenciais do projeto, para que uma IA
> entenda o que é, como está estruturado, o que é regra de negócio (não alterável)
> e o estado atual, antes de propor mudanças.

---

## 1. O que é

- **Nome:** FINTECPESSOAL
- **Proposta:** aplicação **local, gratuita** de **controle e inteligência financeira pessoal**, com aparência de fintech profissional. Funciona 100% local, **sem APIs pagas e sem LLM**.
- **Localização:** `C:\fintecpessoal`
- **Status:** plataforma financeira operacional completa (núcleo do domínio + isolamento multiusuário + serviços + CRUDs + dashboard + orçamentos/metas/dívidas + patrimônio + relatórios + lembretes + comprovantes).

---

## 2. Stack e ambiente

| Camada | Tecnologia |
|---|---|
| Backend | **Django 6.1** (Python 3.12) |
| Banco | SQLite (`db.sqlite3`; migração futura p/ PostgreSQL = só configuração) |
| Frontend | Tailwind CSS 4 (build real via CLI) + HTML semântico, sem JS framework |
| API externa | Nenhuma. Sem React/Next/Vue/Bootstrap. Sem LLM. |

- **Ambiente:** `.venv\Scripts\python.exe` (Python). `node_modules` (assets).
- **Dependências Python:** apenas `Django` + `python-dotenv`. Princípio: **"sem dependências desnecessárias"** (não adicionar libs pesadas).
- **Comandos:**
  - Build do CSS: `npm run tailwind:build` (fonte `static/css/input.css` → `static/css/tailwind.css`)
  - Dev server: `python manage.py runserver` (porta 8000, auto-reload)
  - Migrations: `python manage.py makemigrations` / `migrate`
  - Testes: `python manage.py test --settings=config.settings.test`
- **Cache do CSS:** o template `base.html` carrega `tailwind.css?v=<n>` (incrementar a cada mudança visual).

---

## 3. Estrutura da aplicação

- **Settings:** `config/settings/{base,development,production,test}.py` (base seria o modello comum; teste usa SQLite em memória + hasher MD5 p/ rapidez).
- **URLs globais:** `config/urls.py` — prefixes:
  - `admin/`, raiz (core), `contas/` (accounts), e área autenticada sob `/app/...`.
- **Apps** em `apps/`:

| App | Responsabilidade |
|---|---|
| `core` | `OwnedModel`, `BRLField`, filtro `money` (`centavos`) |
| `accounts` | cadastro/login/onboarding/recuperação (model `User` custom) |
| `dashboard` | shell da aplicação + dashboard data-driven (read layer em `queries.py`, ViewModel) |
| `finance` | contas, categorias, lançamentos, transferências, recorrências |
| `cards` | cartões, compras parceladas, faturas, pagamentos |
| `budgets` | orçamentos |
| `goals` | metas |
| `debts` | dívidas |
| `networth` | patrimônio líquido consolidado + evolução (snapshots) |
| `reports` | relatórios + exportação CSV + relatório imprimível/PDF |
| `reminders` | agenda de vencimentos (faturas, recorrências, dívidas) |
| `comprovantes` | organizador de comprovantes/garantias (upload limitado a 2 MB) |

---

## 4. Convenções de arquitetura (IMPORTANTE — não quebrar)

1. **Isolamento multiusuário:** todo model herda `OwnedModel` (de `apps/core/ownership.py`) → campo `owner` + `objects.for_user(user)`. Toda consulta usa `.for_user(user)`; nunca confiar em `owner_id` vindo da interface (regra do projeto).
2. **Dinheiro = inteiro em centavos** (`IntegerField`), nunca float. Formulários usam `BRLField` (de `apps.core.forms`) que traduz `"1.500,00"` → centavos.
3. **Camada de serviços:** regras de negócio ficam em `services` (ex.: `apps/networth/services.py`, `apps/finance/services/`). Views chamam serviços com **argumentos keyword-only e `user` como primeiro parâmetro**.
4. **Formulários:** usar `forms.Form` (NÃO `ModelForm`), que **delegam escrita às services**. `validate` extra por `clean_*`.
5. **Views:** sempre `LoginRequiredMixin`. Leituras com `ListView/TemplateView`; escritas com `FormView`/`View`. Ownership com mixin próprio que usa `objects.for_user(user)` (404 se não for do usuário).
6. **Templates:** em `templates/<app>/...` (global, via `DIRS`), estendem `app/_shell.html` no bloco `app_content`, com `{% load money %}` para `|centavos`. Componentes em `templates/components/` (`page_header`, `empty_state`, `field`, `money`, `status_badge`, `progress`, `pagination`, `messages`, `alert` etc.).
7. **Nav lateral:** itens em `apps/dashboard/context.py` — `_nav_items()` (lista) + `_ACTIVE_BY_NAME` (url_name→seção; chaves qualificadas por app para nomes ambíguos como `index`). Shell filtra "Menu" vs "Administração".
8. **Testes:** arquivos `tests.py`/`tests_*.py` por app; `TestCase` com dois usuários (A/B) para testar isolamento; login via `self.client.login(...)`; dados criados **via services**.

---

## 5. Estados / regras de negócio principais (não alterar)

- **Contas:** status `ACTIVE/CLOSED/ARCHIVED`; saldo sempre **derivado** (`initial_balance` + efeito das transações), sem saldo mutável redundante.
- **Transações:** tipos `INCOME/EXPENSE/TRANSFER/ADJUSTMENT`; `Transfer` soma zero no patrimônio (uma − e uma +).
- **Cartões:** parcelas `PENDING/OVERDUE/PAID`; fatura = soma das parcelas do período; comprometido = parcelas pendentes/vencidas.
- **Orçamentos:** base por categoria ou global; comparativo contra gastos do mês.
- **Metas:** `progress_percent`, pausa/arquivo, aportes.
- **Dívidas:** `remaining = total − paid`, status ativa/inadimplente.
- **Patrimônio (networth):** **Ativos** (soma saldos contas) **− Passivos** (restante dívidas + parcelas cartão comprometidas) = **Patrimônio líquido**; **Reservas em metas** exibidas em separado (intenção, não necessariamente saldo em conta).
- **Dashboard (read layer)** em `apps/dashboard/queries.py`: `cash_flow`, `spending_by_category`, `monthly_evolution`, `upcoming_events`, `account_balances`, `committed`, etc. — reutilizados por reports/reminders/networth (não duplicar).
- **Comprovantes:** upload máximo **2 MB**, tipos `receipt/invoice/warranty/health/other`, com `warranty_expiry` (+ alerta de expiração em 60 dias). Validação de tamanho/tipo no servidor (defesa em profundidade).

---

## 6. Estado atual e métricas

- **Testes:** **286 testes, todos OK** (262 preexistentes + 24 dos 4 apps novos). Comando para validar: `python manage.py test --settings=config.settings.test`.
- **Migrations:** aplicadas (inclui `networth.0001`, `comprovantes.0001`).
- **CSS:** UI estilizada em Tailwind com dark mode completo (classe `.app-shell`), cor de marca `#9a87fd`, cache-busting `?v=22`.
- **UX recentes:** menu "Rápido +" (ações rápidas na topbar + atalho `N`), faixa de atalhos no dashboard, correção de link "Ver contas", autofocus em formulário, **Modo Privacidade Instantânea** (botão olho + `Shift+P` que desfoca valores `.num`).
- **Páginas novas (renderizam 200):**
  - `/app/patrimonio/` (networth), `/app/relatorios/` (reports), `/app/lembretes/` (reminders), `/app/comprovantes/` (comprovantes).

---

## 7. Como validar (p/ a IA verificar, se reprodutível)

1. `cd C:\fintecpessoal`
2. `.venv\Scripts\python.exe manage.py test --settings=config.settings.test`
3. `npm run tailwind:build` (se alterar CSS/templates)
4. `.venv\Scripts\python.exe manage.py runserver` → acessar `http://localhost:8000`
   - Test client use `Client(HTTP_HOST="localhost")` (ALLOWED_HOSTS não inclui `testserver`).
