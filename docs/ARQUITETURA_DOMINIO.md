# FINTECPESSOAL — Modelagem do Domínio Financeiro (Multiusuário)

> **Status:** Modelagem conceitual **implementada (núcleo)** na Ordem 4.
> Modelos Django criados em `apps/{finance,cards,budgets,goals,debts}` com Validação,
> migrações e testes. Documento continua sendo a fonte de verdade; os ajustes de
> implementação estão registrados na seção "Ajustes de implementação (Ordem 4)" no final.

---

## 1. Resumo executivo

O FINTECPESSOAL será **multiusuário desde a primeira versão**. Cada `User` (autenticação nativa do Django) possui um ambiente financeiro **totalmente isolado** no backend. Toda entidade financeira pertence a um usuário, e nenhuma consulta, edição ou exclusão pode cruzar essa fronteira — a proteção é imposta no **nível do backend**, nunca confiando apenas na interface.

O domínio financeiro é modelado em torno de **princípios contábeis simples**:

- **Transferência** não altera patrimônio (lança duas pernas: origem/destino).
- **Compra no cartão** cria uma obrigação (não é saída imediata de dinheiro).
- **Pagamento de fatura** liquida a obrigação e movimenta dinheiro da conta.
- **Parcelamento** é tratado por entidade própria para permitir ver pago/falta/comprometimento.
- **Recorrências** não geram milhares de transações; são regras que projetam ocorrências sob demanda.
- **Dinheiro nunca é `float`** — usa-se valor inteiro em centavos (ou campo decimal com precisão fixa).

---

## 2. Arquitetura multiusuário (requisito oficial)

### 2.1 Modelo de isolamento

Cada usuário possui seu próprio grafo de entidades:

```
USUÁRIO A
├── accounts
├── cards ▸ invoices ▸ purchases/installments
├── categories ▸ budgets
├── transactions / transfers
├── recurring (expenses/revenues)
├── goals
└── debts
```

### 2.2 Como aplicar o isolamento

- **`owner` (FK para `User`)** em toda entidade financeira que contenha dados específicos do usuário.
- As entidades **compartilhadas do sistema** (e.g. taxonomias padrão) são duplicadas por usuário ou tratadas como "referência copiada" — decisão documentada na seção de Categorias.
- **Filtragem consistente no backend:** o acesso será feito por meio de um **QuerySet manager** (`OwnedQuerySet`/`OwnedManagerBase`) que força `filter(owner=request.user)` automaticamente. Views/viewsets usam esse manager, impedindo vazamento mesmo se um desenvolvedor esquecer de filtrar.
- **Todas as operações de escrita passam por serviços/views que validam `owner`**, nunca apenas pela interface.
- No futuro, com PostgreSQL, adicionam-se **RESTRICT/CHECK** e (opcionalmente) **Row-Level Security (RLS)** como defesa em profundidade. Não é prematuro incluir o padrão de manager; é barato e centraliza a segurança.

### 2.3 Defesa em profundidade (backend)

1. Manager padrão com filtro por `owner` (regra de ouro).
2. Verificações explícitas de posse em cada view de escrita (retornando 403/404).
3. Derivação do `owner` a partir do `request.user` autenticado — nunca recebido como parâmetro de formulário.
4. (Futuro/PostgreSQL) RLS como última camada.

> **Decisão:** este projeto **não** precisará de "organizações/famílias/planos" compartilhados na primeira versão. Multi-usuário significa **isolamento 1 usuário = 1 ambiente**. Recursos compartilhados mantêm-se para quando houver demanda clara (seção Escalabilidade).

---

## 3. Autenticação e cadastro

### 3.1 Stack de autenticação

- **User model:** será usado um **custom user model** (`User`), herdeiro de `AbstractUser`, **desde o início**. Motivo: substituir o `User` padrão do Django depois de pronta a base é custoso (migrations + chaves estrangeiras). Definir cedo evita esse retrabalho e também cria o ponto certo para o campo `point` de moeda/perfil futuro.
- **Fluxos** (futuros, não implementados agora): cadastro, login, logout, recuperação de acesso, alteração de senha, ativação/desativação, perfil — todos usando as **views nativas do Django** (`django.contrib.auth.views` + signals para criação de perfil).
- **Sessão:** sessões do Django (cookie), com `SESSION_COOKIE_HTTPONLY` etc. mantidas pela segurança padrão do framework.
- Configurar **`AUTH_USER_MODEL = "accounts.User"`** na implementação.

### 3.2 Posicionamento

O app `apps.accounts` será o lar do `User`, do `Profile` e dos fluxos de autenticação. Isso mantém o `apps.core` restrito a páginas técnicas/institucionais e o domínio financeiro separado.

---

## 4. Perfil do usuário (`Profile`)

### 4.1 Decisão: manter um `Profile` separado

O `User` do Django já guarda: `username`, `first_name`, `last_name`, `email`, `password`, `is_active`, `is_staff`, `date_joined`, `last_login`. **Não duplicar** essas informações.

Um **`Profile`** separado guarda apenas dados financeiros/de preferência que **não pertencem ao user**:

- `display_name` (nome de exibição — pode ser diferente dos nomes de cadastro);
- `preferred_currency` (moeda padrão, ex.: `BRL`);
- `default_account` (conta padrão para lançamentos rápidos — referência opcional);
- `preferences` (JSON: idioma, formato de data, temas — espaço para dark mode);
- `onboarding_completed` (flag de progresso);
- `created_at` / `updated_at`.

**Relação:** `User 1 — 1 Profile` (OneToOneField). Criado automaticamente por um **signal** `post_save` do `User`.

> **Por que não colar tudo no `User`?** Para não inflar a classe de autenticação com preocupações financeiras e para separar responsabilidades. Campos como `is_active`, datas e credenciais permanecem onde o framework espera.

---

## 5. Entidades financeiras (modelagem conceitual detalhada)

Abaixo cada entidade com responsabilidade, campos principais e justificativa. **Cardinalidades** e diagrama estão na seção 12.

### 5.1 Conta financeira (`Account`)

Representa **onde o dinheiro existe**.

- `owner` (FK User)
- `name` (ex.: "Nubank", "Carteira")
- `institution` (texto livre; nada de dependência externa)
- `type` (enum: `checking`, `savings`, `cash`, `digital`, `investment`, `other`)
- `initial_balance` (valor em centavos)
- `initial_balance_date` (DateTime/Date)
- `currency` (ISO 4217, ex.: `BRL`)
- `status` (enum: `active`, `archived`, `closed`)
- `balance` — **não é campo armazenado**; é **derivado** de transações + saldo inicial (ver seção Saldos). Evita inconsistência.
- `created_at` / `updated_at`

### 5.2 Cartão de crédito (`CreditCard`) — entidade separada da conta

É **obrigatoriamente separado** da conta financeira: a conta guarda onde o dinheiro existe; o cartão representa **uma linha de crédito** que gera **obrigações**.

- `owner` (FK User)
- `name`, `institution`
- `limit` (centavos)
- `available_limit` (derivado = `limit` − total aberto em faturas/saques; não armazenado)
- `closing_day` (dia do mês de fechamento)
- `due_day` (dia do mês de vencimento)
- `payment_account` (FK Account — conta usada para pagar a fatura)
- `status` (enum: `active`, `blocked`, `closed`)
- `created_at` / `updated_at`

**Fluxo compra → fatura → pagamento (conceito):**

```
Compra (Purchase) ──> gera lançamento na Fatura ──> Fatura fecha ──> Pagamento da fatura movimenta a conta
                                                                       (e liquida a obrigação)
```

### 5.3 Categoria (`Category`)

- `owner` (FK User) — **ou** `owner IS NULL` para categorias padrão globais (ver decisão).
- `name`
- `parent` (FK Category, self — para subcategorias)
- `kind` (enum: `expense`, `income`, `transfer` — a disciplina emocional de "não gastar em categoria incorreta")
- `is_default` (bool)
- `status` (enum: `active`, `inactive`)
- `created_at`

**Decisão — categorias padrão compartilhadas vs. copiadas:**

Categorias-padrão ("Alimentação", "Moradia", ...) serão **plantadas ("seedadas") por usuário** no momento do cadastro (via signal/`migrations` de dados ou serviço de provisionamento). Razões:

- O usuário pode **personalizar/renomear/desativar** sem afetar outros usuários (isolamento real).
- Evita o problema de categorias padrão "globais" que não podem ser editadas por ninguém sem efeito colateral.
- O custo é baixo (poucas dezenas de registros por usuário).

Alternativa considerada (rejeitada): categoria padrão global compartilhada (`owner=NULL`). Rejeitada porque quebra o isolamento e complica a regra "cada coisa tem um dono" e a personalização.

### 5.4 Transação (`Transaction`) — lançamento contábil raiz

Representa **movimentação financeira real**. É o núcleo do sistema.

- `owner` (FK User)
- `type` (enum: `income`, `expense`, `transfer`, `adjustment`)
- `amount` (centavos, **sempre > 0** em valor absoluto; o sinal vem do `type`/contabilização)
- `date` (data financeira, e.g. data da compra/competência)
- `description`
- `account` (FK Account; a conta afetada)
- `category` (FK Category, nullable — ajustes/transferências podem não ter categoria)
- `transfer` (FK Transfer — identifica a contraparte, se tipo transferência)
- `card_purchase` (FK CreditCardPurchase, nullable — se originada de compra no cartão)
- `recurrence` (FK RecurringRule, nullable — se gerada por regra)
- `external_id` (string, nullable — para importação/deduplicação)
- `source` (enum: `manual`, `imported_csv`, `imported_ofx`, `recurrence`, `system`)
- `is_reconciled` (bool) / `reconciled_at`
- `notes`
- `created_at` / `updated_at`

**Contabilização por tipo:**
- `income` / `expense` → lançamento simples, `amount` com sinal conforme convenção.
- `transfer` → dois lançamentos (ou representação via `Transfer` com duas pernas); **patrimônio total inalterado**.
- `adjustment` → correção de saldo (ex.: taxa, arredondamento manual), com `notes` obrigatório.

### 5.5 Transferência (`Transfer`)

Uma transferência entre **contas do mesmo usuário** não deve virar receita + despesa.

**Modelo:** uma entidade `Transfer` com duas referências a `Transaction` (perna de saída e perna de entrada):

- `owner`
- `from_account` (FK Account)
- `to_account` (FK Account)
- `amount`
- `date`
- `out_transaction` (FK Transaction) / `in_transaction` (FK Transaction)
- `notes`
- `created_at`

A soma líquida sobre as contas é zero; o **patrimônio total não muda**. Isso também dá trilha de auditoria (ambas as pernas visíveis).
> Alternativa considerada: usar `Transaction` com `account_from`/`account_to` no próprio registro. Rejeitada por acoplar transação a dois conceitos; preferimos o par de `Transaction` + `Transfer` para manter regularidade de cálculo de saldo por conta.

### 5.6 Compra parcelada (`InstallmentPurchase`) e parcelas (`Installment`)

**Decisão — entidades próprias (Purchase + Installments):** representar a compra como **entidade própria** relacionada às parcelas é a melhor abordagem porque permite enxergar **pago × falta × comprometimento futuro** de forma clara e alimentar projeções.

```
InstallmentPurchase (compra: 1.200 12x)
  ├── Installment #1  (100 paga)
  ├── Installment #2  (100 paga)
  ├── ...
  └── Installment #12 (100 futura)
```

- **`InstallmentPurchase`**
  - `owner`, `card` (FK CreditCard)
  - `description`
  - `total_amount` (1.200)
  - `installment_count` (12)
  - `installment_amount` (100)
  - `first_due_date` / `periodicity` (mesal por padrão)
  - `status` (enum: `ongoing`, `completed`, `cancelled`)
  - `created_at`
- **`Installment`** (uma por parcela)
  - `purchase` (FK InstallmentPurchase)
  - `number` (1..12)
  - `amount` (100)
  - `due_date`
  - `status` (enum: `pending`, `paid`, `overdue`, `skipped`)
  - `invoice` (FK CreditCardInvoice, nullable — fatura na qual foi lançado)

Quando a fatura fecha, as parcelas **do período** compõem o `total` da fatura (sem duplicar — ver 5.7). O usuário pode marcar parcelas como pagas; as pendentes alimentam **comprometimento futuro**.

Resolução do "1.200 em 12x de 100" sem resto: **o valor das parcelas pode ter centavos** e a primeira/última parcela pode absorver o arredondamento (campo `installment_amount` exato por parcela, ou ajuste na última) — decisão de implementação garantida por regra de validação (`sum(installments) == total`).

### 5.7 Fatura de cartão (`CreditCardInvoice`)

Representa o fechamento mensal do cartão e evita **dupla contabilização**.

- `owner`, `card` (FK CreditCard)
- `period_start` / `period_end` (intervalo de competência)
- `closing_date` / `due_date`
- `status` (enum: `open`, `closed`, `paid`, `overdue`)
- `amount` (total — soma das parcelas/compras do período; **derivado**, não duplicado)
- `payment_transaction` (FK Transaction, nullable — o pagamento que liquidou)
- `payment_account` (FK Account)
- `created_at`

**Regras para evitar duplicação:**
1. As compras/parcelas pertencem à fatura (via `Installment.invoice` / `InvoiceLine`), e o **`amount` da fatura é calculado** da soma delas — não armazenado independentemente.
2. O **pagamento da fatura** cria uma única `Transaction` (transferência da conta de pagamento para "quitação de cartão") e muda o status da fatura para `paid`. **Não** cria uma segunda despesa.
3. Modelamos **linhas de fatura** (`InvoiceLine`) quando precisar de histórico item a item (compra × fatura), mas a soma é o que importa para saldo.

### 5.8 Despesa recorrente / Receita recorrente (`RecurringRule`)

Regras de repetição que **não** geram milhares de registros no banco.

- `owner`
- `kind` (enum: `expense`, `income`)
- `title` (ex.: "Aluguel", "Internet", "Salário")
- `amount`
- `category` (FK Category)
- `account` (FK Account) / `card` (FK CreditCard, para gastos no cartão)
- `frequency` (enum: `weekly`, `monthly`, `yearly`, `custom`)
- `interval` (a cada N períodos)
- `start_date`
- `end_date` (nullable — indefinido)
- `day_of_month` / `weekday` (regra de geração)
- `status` (enum: `active`, `paused`, `ended`)
- `next_run_date` (campo otimizado/derivável)
- `created_at`

**Como funciona (conceitual):**
- Um **gerador/projeção** calcula as ocorrências entre duas datas **sem persistir** todas.
- O usuário pode **materializar** uma ocorrência em uma `Transaction` real (com `recurrence` FK) quando ela acontece.
- Para previsões (saldo projetado), basta iterar a regra a partir de `next_run_date` até a data-alvo.

Alternativa considerada (rejeitada): gerar N transações futuras de uma vez. Rejeitada por poluir o banco, dificultar edições e complicar projeções.

### 5.9 Orçamento (`Budget`)

- `owner`
- `category` (FK Category) — ou `None`/flag para **orçamento global**
- `kind` (enum: `category`, `global`)
- `period` (enum: `monthly`, `yearly`, `custom`)
- `limit_amount` (centavos; ex.: 800)
- `start_date` / `end_date` (nullable)
- `is_active`
- `created_at`

**Realizado** é **calculado** (# de transações de `expense` na categoria/período), não armazenado. Orçamento global soma todas as despesas do período.

### 5.10 Meta financeira (`Goal`)

- `owner`
- `name` (ex.: "Viagem")
- `target_amount` (R$ 5.000)
- `current_amount` (valor já alocado — pode ser alimentado manualmente ou por regra futura)
- `target_date` (nullable)
- `priority` (enum: `low`, `medium`, `high`)
- `status` (enum: `active`, `paused`, `achieved`, `archived`)
- `notes`
- `created_at` / `updated_at`

**Progresso** (`current/target`) é apresentado no frontend; o `current_amount` é mantido por alocação explícita (para não inventar automatização na fase inicial).

### 5.11 Dívida / compromisso financeiro (`Debt`) — decisão

**Decisão: ter uma entidade `Debt` específica e enxuta**, e **não** forçá-la a caber em outros modelos. Motivos: empréstimos/financiamentos têm características próprias (valor total, valor pago, juros, datas) que não se encaixam bem em `Account` nem em `Transaction` simples, e a clareza do domínio vale o pequeno custo.

- `owner`
- `type` (enum: `loan`, `financing`, `external_installment`, `other`)
- `name`/`description`
- `total_amount`
- `paid_amount`
- `interest_rate` (nullable, decimal — percentual; nunca usado para dinheiro)
- `start_date` / `end_date` (nullable)
- `creditor` (texto livre)
- `status` (enum: `active`, `paid_off`, `defaulted`, `archived`)
- `created_at` / `updated_at`

> Não criamos um subsistema completo de amortização (curva de juros, planilha SAC/Price) agora — isso é complexidade desnecessária para a fase atual. A entidade registra o essencial e permite evoluir, se necessário, para pagamentos associados via `Transaction`.
>
> **Nota de validade:** mantém-se **proporcionaL E simples** — não reinventaremos finanças no banco de dados; apenas os registros necessários para exibir saldos/obrigações.

---

## 6. Princípios financeiros (como os dados suportam os cálculos)

Sem implementar cálculos, definimos **como os dados estarão disponíveis**:

### 6.1 Transferência
- Duas pernas associadas a um `Transfer`. **Soma líquida = 0**; patrimônio total invariante.

### 6.2 Compra no cartão
- Gera `InstallmentPurchase`/parcelas e linhas de fatura — cria **obrigação** (`CreditCardInvoice` aberta), **não** despesa imediata de conta.

### 6.3 Pagamento de fatura
- Liquida a fatura (`status=paid`) e gera **uma** `Transaction` movimentando a conta de pagamento. Sem segunda despesa.

### 6.4 Parcelamento
- `Installment.status` permite somar: **pago** (paid), **falta** (pending/overdue), **comprometimento futuro** (pending dentro do horizonte).

### 6.5 Saldos — distinção conceitual (dados necessários)
- **Saldo atual:** `initial_balance` + Σ transações até hoje.
- **Saldo disponível:** saldo atual − compromissos já comprometidos (ex.: valor cobrar de faturas abertas).
- **Saldo comprometido:** somatório de parcelas pendentes, faturas abertas, dívidas ativas.
- **Saldo projetado:** saldo atual + ocorrências futuras de `RecurringRule` (projeção sob demanda).

Os dados para todos: `initial_balance`, transações (`date`, `amount`, `account`), `Installment.status`, `CreditCardInvoice.status`, `RecurringRule`. **Nenhum desses números é armazenado** — são servidos por funções de domínio/serviços.

---

## 7. Importação futura (CSV/OFX) — preparação

A arquitetura estará pronta via:
- `Transaction.external_id` + `Transaction.source` → identificador externo/origem e **detecção de duplicatas** (índice único por `(owner, external_id, source)` quando aplicável).
- `ExternalImport` (entidade futura) registrando: arquivo, formato, data de importação, usuário, quantidades (lidas/importadas/duplicadas/erros).
- `is_reconciled` para **conciliação manual**.
- Tudo com `owner` para isolamento.

Não implementamos nada agora; apenas garantimos os campos necessários no modelo futuro.

---

## 8. Privacidade e isolamento (crítico)

- Camada 1: **manager padrão com `owner`** para todas as entidades do domínio.
- Camada 2: **verificação de posse** nas views/serviços de escrita (403/404).
- Camada 3: `owner` sempre derivado de `request.user` (nunca de input do cliente).
- Camada 4 (futuro/PostgreSQL): RLS.
- Testes obrigatórios de **isolamento** (usuário A não vê/edita/apaga dados de B) serão escritos na implementação.

---

## 9. Auditoria — solução proporcional

Sem sistema gigantesco. Proposta:
- Campos `created_at` / `updated_at` em todas as entidades.
- Soft-delete opcional via campo `is_active`/`status` em entidades sensíveis (evita perda de histórico financeiro).
- Para rastreamento de alteração em campos críticos (conciliação, saldo, exclusão), usar o **pacote `django-simple-history`** em entidades selecionadas (Transaction, Account, CreditCard) OU revisão manual conforme necessidade. Na fase inicial, `created/updated_at` + `source` atendem à maioria.
- `Transaction.source` já registra a **origem da informação** (manual/importada/recorrência/sistema), atendendo ao requisito "origem da informação".

> Decisão: **não** adicionar auditoria AGORA (evita dependência desnecessária); o modelo deixa espaço para `django-simple-history` depois, de forma proporcional.

---

## 10. Dinheiro (nunca float)

- **Tipo:** inteiro em **centavos** (`IntegerField`) — `amount_cents`. Simples, exato, sem erro de ponto flutuante.
- **Precisão:** centavos são a unidade mínima da moeda (BRL). Trancamos a 2 casas.
- **Arredondamento:** feito de forma explícita e determinística por funções de domínio (ex.: distribuir resto de parcelamento na última parcela). Nunca `round()` em metade do caminho sem regra fixa.
- **Moeda:** cada entidade monetária tem `currency` (ISO 4217); exibição formata via locale (`BRL` → `R$ 1.234,56`). Sem conversão de moedas nesta fase.
- **Taxas de juros** (não monetárias) usam `DecimalField` (e.g. `interest_rate`), **nunca** aplicadas sobre centavos com float.

> Alternativa considerada: `DecimalField(max_digits=…, decimal_places=2)`. Funciona, porém centavos-inteiros simplificam soma/índices e evitam ambiguidade de escala entre backends. Escolhido: **centavos (int)** como canónico.

---

## 11. Datas e horários

- **Datas financeiras** (competência, vencimento, fechamento, parcela): campo `DateField` (sem hora). Ex.: compra do dia 15/03.
- **Timestamps** (created_at/updated_at/last_login): `DateTimeField` com **`USE_TZ=True`**, armazenados em UTC, exibidos no fuso do usuário (`TIME_ZONE` por sessão/setting).
- **Regra:** cálculos de saldo/relatórios usam `date` financeiro (data local civil), não timestamp UTC — evita deslocamento de fronteira de dia.
- **Recorrências/fechamento de cartão:** `day_of_month` tratados como número do dia (1–31) com regra de "último dia do mês" quando o dia não existir (ex.: fechamento dia 31 em fevereiro → cai para o último dia).
- **Fuso padrão:** `America/Sao_Paulo` (definido em `settings/base.py`). Futuro: `tz` por usuário no `Profile`.

---

## 12. Diagrama de relacionamentos

```
User (django.contrib.auth — custom)
│
├── 1─1 Profile  (preferências financeiras; criado por signal)
│
├── 1─N Account  (conta financeira)
│      └── (saldo derivado de initial_balance + Transactions)
│
├── 1─N CreditCard  (linha de crédito)
│      │
│      ├── 1─N InstallmentPurchase  (compra parcelada)
│      │       └── 1─N Installment  (parcela; status paid/pending/...)
│      │
│      └── 1─N CreditCardInvoice  (fatura)
│              └── (amount derivado das linhas/parcelas do período)
│
├── 1─N Category  (parent self → subcategorias)
├── 1─N Transaction  (lançamento raiz)
│      ├── FK Account (perna simples ou transferência)
│      ├── FK Transfer (par origem/destino)
│      ├── FK RecurringRule (quando gerada por recorrência)
│      └── FK CreditCardPurchase (quando originada de compra)
├── 1─N Transfer  (duas pernas: out/in Transaction)
├── 1─N RecurringRule  (despesas/receitas recorrentes — projeção sob demanda)
├── 1─N Budget  (limite por categoria ou global; realizado derivado)
├── 1─N Goal    (meta financeira)
└── 1─N Debt    (dívida/empréstimo/financiamento enxuto)
```

```
User
│
├── Profile
│
├── Accounts
│   └── (saldo via) Transactions
│
├── Credit Cards
│   ├── Installment Purchase
│   │   └── Installments
│   └── Invoices
│       └── (linhas/parcelas do período)
│
├── Categories
│   └── Budgets
│
├── Transactions
│   └── Transfers (par origem/destino)
│
├── Recurring Rules  (despesas/receitas recorrentes)
│
├── Goals
│
└── Debts
```

---

## 13. Cardinalidades (resumo)

| Relação | Cardinalidade |
|---|---|
| User → Profile | 1:1 |
| User → Account | 1:N |
| User → CreditCard | 1:N |
| User → Category | 1:N |
| User → Transaction | 1:N |
| User → Transfer | 1:N |
| User → RecurringRule | 1:N |
| User → Budget | 1:N |
| User → Goal | 1:N |
| User → Debt | 1:N |
| Category → Category | 1:N (self, hierarquia) |
| CreditCard → InstallmentPurchase | 1:N |
| InstallmentPurchase → Installment | 1:N |
| CreditCard → CreditCardInvoice | 1:N |
| CreditCardInvoice → Installment/InvoiceLine | 1:N |
| Transaction → Account | N:1 |
| Transaction → Transfer | N:1 (2 pernas) |
| Transaction → Category | N:1 (nullable) |
| Transaction → CreditCardPurchase | N:1 (nullable) |
| Transaction → RecurringRule | N:1 (nullable) |

---

## 14. Arquitetura de autenticação (resumo)

- `AUTH_USER_MODEL = "accounts.User"` (custom user desde o início).
- Fluxos nativos do Django; `django.contrib.auth.views`.
- `Profile` criado por signal.
- Sessões por cookie; segurança padrão do Django (CSRF, HttpOnly, Secure em prod).

---

## 15. Decisões importantes (resumo)

| # | Decisão | Justificativa |
|---|---|---|
| D1 | Multiusuário com isolamento total via `owner` | Requisito oficial; proteção no backend |
| D2 | Custom `User` desde o início | Evita retrabalho/custo de troca futura |
| D3 | `Profile` separado (1:1) por signal | Não duplica dados do User; separa responsabilidades |
| D4 | Cartão = entidade separada da conta | Representa crédito/obrigação, não saldo |
| D5 | Compra parcelada = `InstallmentPurchase` + `Installment` | Vê pago/falta/comprometimento futuro |
| D6 | Fatura com `amount` derivado; pagamento = 1 Transaction | Evita dupla contabilização |
| D7 | Transferência com duas pernas, `Transfer` separado | Não vira receita+despesa; patrimônio invariante |
| D8 | Recorrência como regra (projeção sob demanda) | Evita milhares de registros; prevê futuro |
| D9 | Categorias padrão semeadas por usuário | Isolamento + personalização |
| D10 | Dinheiro em centavos (inteiro) | Exatidão; nunca float |
| D11 | Datas financeiras `Date`; timestamps UTC | Evita problemas de timezone |
| D12 | `Debt` enxuta e própria | Clareza de domínio sem complexidade excessiva |
| D13 | Sem auditoria pesada agora; espaço para `django-simple-history` | Proporcional ao projeto |
| D14 | Acesso por manager com filtro `owner` + checagem de posse | Segurança consistente no backend |

---

## 16. Alternativas consideradas (e por que foram rejeitadas)

1. **Monousuário** → Rejeitado (requisito oficial multiusuário).
2. **Tudo no `User` da conta sem custom user** → Rejeitado (troca cara depois).
3. **Categorias padrão globais compartilhadas** → Rejeitado (quebra isolamento/personalização).
4. **Transação com `from/to` no próprio registro (sem `Transfer`)** → Rejeitado (acopla conceitos; dificulta saldo por conta uniforme).
5. **Gerar N transações futuras das recorrências** → Rejeitado (polui banco; projeção melhor sob demanda).
6. **`DecimalField` para dinheiro** → Viável, mas optou-se por centavos-int (escala consistente).
7. **Subsistema completo de amortização de dívidas** → Adiado (complexidade desnecessária agora).

---

## 17. Riscos de modelagem

| Risco | Mitigação |
|---|---|
| Dupla contabilização (cartão + fatura) | `amount` da fatura derivado; pagamento = 1 transação |
| Vazamento entre usuários | Manager com `owner` + checagem de posse + testes de isolamento |
| Erro de arredondamento em parcelas | Soma das parcelas = total; ajuste na última |
| Timezone no fechamento de cartão / recorrências | Data financeira cívica (`Date`) + regras de "último dia do mês" |
| Complexidade prematura em dívidas/previsões | Entidades enxutas; projeção sob demanda |
| `owner` esquecido em uma query | Padrão de manager central; revisão de código; testes |

---

## 18. Proposta final (próximos passos da implementação)

1. Definir `AUTH_USER_MODEL = accounts.User` + `Profile` (signal).
2. Implementar utilitário de isolamento (`OwnedManager`/mixins).
3. Modelos financeiros na ordem: Account → Category → CreditCard → Transaction/Transfer → InstallmentPurchase/Installment → CreditCardInvoice → RecurringRule → Budget → Goal → Debt.
4. Migrations + testes de isolamento e de princípios financeiros (transferência, cartão, fatura).
5. Implementar camadas de serviço para saldos/projeções quando o dashboard for construído.

---

*Documento gerado na Ordem 3 (modelagem e documentação). Nenhum model/migration/view/dashboard foi criado.*

---

## Ajustes de implementação (Ordem 4)

A implementação seguiu o contrato deste documento. Nenhuma decisão de modelagem **de fundo** mudou; apenas ajustes técnicos/consistência, registrados abaixo conforme exigido (decisão anterior → problema → nova decisão → motivo).

### A1 — `InvoiceLine` não criada agora
- **Decisão anterior:** seção 5.7 sugeria possivelmente uma `InvoiceLine` para histórico item a item.
- **Problema:** não há, nesta fase, demanda por histórico "compra × fatura" item a item; criá-la seria complexidade prematura.
- **Nova decisão:** não criar `InvoiceLine`. A relação fatura ↔ parcelas é feita por `Installment.invoice` (FK) e o valor da fatura é **derivado** (soma das parcelas do período). `InvoiceLine` poderá ser adicionada quando houver demanda concreta — exatamente o que a arquitetura previa com "quando precisar".
- **Motivo:** manter o núcleo enxuto e evitar dupla contabilização já resolvida por `Installment.invoice`.

### A2 — API de constraint do Django 6.1 (`condition=`)
- **Decisão anterior:** a arquitetura usa a semântica de `CheckConstraint`.
- **Problema:** Django 6.1 removeu o parâmetro `check=` (deprecado desde 5.1).
- **Nova decisão:** usar `models.CheckConstraint(condition=...)` em todas as constraints.
- **Motivo:** compatibilidade com o Django 6.1 instalado.

### A3 — `Installment` carrega seu próprio `owner`
- **Decisão anterior:** a seção 5.6 listava os campos da `Installment` sem `owner` explícito; a regra geral previa "proprietário quando necessário".
- **Problema:** sem `owner` próprio, a consulta de isolamento direto (`Installment.objects.for_user`) não seria possível e a regra dependeria de atravessar `purchase`/`card`.
- **Nova decisão:** `Installment` herda `OwnedModel` (tem `owner`), com validação de `owner == purchase.owner`.
- **Motivo:** consistência do padrão de isolamento D14 para todas as entidades e consultas seguras diretas.

### A4 — Reset do banco para o custom user
- **Decisão anterior:** SQLite criado na Ordem 2 com o `User` padrão do Django (migrações `auth` já aplicadas).
- **Problema:** o Django não permite trocar `AUTH_USER_MODEL` depois de o banco já ter as migrações `auth` aplicadas com o `User` padrão.
- **Nova decisão:** como `auth_user` tinha **0 linhas** (sem usuários criados) e nenhum dado dependia dele, o banco foi **resetado** (`db.sqlite3` excluído) e re-migrado do zero com `AUTH_USER_MODEL = "accounts.User"`.
- **Motivo:** introduzir o custom user corretamente desde o início (decisão D2) sem custo de migração futuro; sem perda de dados relevantes.

### A5 — Nomenclatura de valores monetários
- **Decisão anterior:** a seção 10 menciona genericamente `amount_cents`; as seções 5.x listam `amount`, `initial_balance`, `limit`, etc.
- **Nova decisão:** os campos usam os nomes das seções 5.x (`amount`, `initial_balance`, `limit`, `total_amount`, ...) com **valor em centavos** (int), conforme o próprio texto dessas seções.
- **Motivo:** coerência com os diagramas de campos da seção 5; a regra "inteiro em centavos, nunca float" é mantida.

### Verificado nesta ordem
- Isolamento por `owner` + `for_user` (testes).
- Transferência com duas pernas `type=TRANSFER` (patrimônio invariável).
- Compra no cartão sem saída imediata de dinheiro.
- Parcelamento com relação/arredondamento corretos.
- Recorrência sem materialização automática de transações.
- Dinheiro em inteiro (centavos).
- Categorias isoladas por usuário.
- Constraints de integridade (CheckConstraint) ativas no SQLite.

---

## Camada de Serviços (Ordem 5)

A Ordem 5 implementa a **camada de operações de domínio reutilizáveis**. Serviços executam
operações financeiras com **atomicidade**, **idempotência** e **isolamento por `owner`**,
independendo de `request`/`session`/templates — recebem `user` e objetos explícitos, e todo
valor monetário é **inteiro em centavos**.

### Estrutura

```
apps/finance/services/
  __init__.py
  errors.py        FinancialServiceError, ForbiddenResourceError, InvalidAmountError,
                   InvalidStateError, DuplicateOccurrenceError
  base.py          require_owned(), ensure_owned_integer_amount()
  transactions.py  record_income(), record_expense()
  transfers.py     transfer_between()
  balances.py      account_balance(), net_worth(), total_balance()
  recurrences.py   occurrence_date(), generate_occurrence()

apps/cards/services/
  __init__.py
  purchases.py     create_card_purchase()
  invoices.py      invoice_period(), determine_invoice(), get_or_create_invoice(), pay_invoice()
  reads.py         card_usage(), card_summary()
```

### Operações e regras

- **Transações** (`record_income`/`record_expense`): validam posse da conta/categoria e
  exigem `amount` inteiro positivo; retornam a `Transaction` criada.
- **Transferência** (`transfer_between`): dentro de `transaction.atomic()`, cria as **duas
  pernas** (`Transaction type=TRANSFER`) + a entidade `Transfer`, atualizando os FKs. O
  **patrimônio total é invariável**; falha na 2ª perna reverte a 1ª e o `Transfer`
  (comprovado por teste de rollback **real**, sem mock de transação).
- **Saldos** (`account_balance`/`net_worth`/`total_balance`): sempre derivados de
  `initial_balance` + Σ de transações; nunca armazenados.
- **Recorrência** (`generate_occurrence`): projeta sob demanda e é **idempotente por
  período** (`DuplicateOccurrenceError`/reutilização da ocorrência), impedindo duplicação.
- **Compra no cartão** (`create_card_purchase`): à vista (`installment_count=1`) ou
  parcelada; gera parcelas com `base = total // count` e **resto na última parcela**
  (`sum(installments) == total`); cada parcela é associada à fatura determinada pelo seu
  `due_date`; **não debita a conta** (compra cria obrigação).
- **Fatura** (`determine_invoice`/`get_or_create_invoice`): calcula `period_start/end`,
  `closing_date`, `due_date` (com virada de mês/ano); `get_or_create_invoice` é idempotente
  (chave `(card, period_start, period_end)`).
- **Pagamento de fatura** (`pay_invoice`): liquida (uma `Transaction type=EXPENSE` na conta
  de pagamento + `payment_transaction` + `status=PAID` + parcelas `PAID`). Sem dupla
  contabilização; rejeita pagamento parcial (`amount != due`), conta/fatura de outro usuário
  e pagamento repetido.
- **Leituras de cartão** (`card_usage`/`card_summary`): derivam `used`/`available` do limite
  e do total aberto; validam posse.

### Decisões de implementação (Ordem 5)

| # | Decisão | Motivo |
|---|---|---|
| S1 | Serviços não dependem de `request`/`session` | Reutilizáveis por views, testes, scripts, tasks |
| S2 | `transaction.atomic()` em operações multiobjeto (transfer, pagamento) | Invariantes garantidas mesmo em falha |
| S3 | `amount` sempre `int` positivo em centavos, validado no serviço | Nunca `float`; consistência na fronteira |
| S4 | Pagamento de fatura = 1 `EXPENSE` + `payment_transaction` | GASTO (obrigação) ≠ LIQUIDAÇÃO (movimento) |
| S5 | Parcelas mensais fecham em faturas próprias por `due_date` | Comportamento real de cartão; sem dupla contagem |
| S6 | Mesma estrutura de `apps/{finance,cards}/services/` replicável | Padrão uniforme para budgets/goals/debts |

### Validação (Ordem 5)

- `python manage.py check` → 0 issues.
- `python manage.py makemigrations --check --dry-run` → "No changes detected" (sem migração nova).
- `python manage.py test` → **71 testes OK** (30 existentes da Ordem 4 + 41 novos),
  incluindo testes de isolamento multiusuário e rollback real.

---

## Autenticação e Onboarding (Ordem 6)

A Ordem 6 entrega a fundação da experiência do usuário: autenticação completa,
onboarding e o shell da aplicação — sem dashboard financeiro real (Ordem 7).

### Autenticação

- **Exclusivamente o sistema nativo do Django** (`django.contrib.auth`) em
  `apps.accounts`. Sem pacote externo.
- **User customizado** (`accounts.User`, `AbstractUser`) já existente — mantido,
  sem alteração de model.
- **Estratégia de username:** como o `AbstractUser` exige `username`, o cadastro
  pede apenas nome/email/senha e o `username` é **derivado automaticamente do
  email** (único, sem que o usuário precise entender detalhes técnicos).
- **Login por email:** `EmailBackend` (`apps/accounts/backends.py`) autentica
  pelo email (case-insensitive), mantendo os validadores de senha do Django.
  Configurado em `AUTHENTICATION_BACKENDS`.
- **Logout via POST** (`LogoutView`) — nunca via GET (boas práticas).
- **Recuperação de senha:** fluxo nativo do `PasswordResetView` com templates
  próprios em português e `EMAIL_BACKEND=console` (sem serviço externo nesta
  ordem). Destaque: Django 6.1 redireciona a confirmação para uma URL
  `.../confirmar/<uid>/set-password/` — os testes acompanham esse fluxo.

### Cadastro (regras)

Email **obrigatório**, **válido** e **único**; senha validada pelos validadores
do Django com mensagem amigável genérica ("Confira os requisitos da senha.");
confirmação de senha conferida. Nenhum traceback/erro interno é exposto.

### Proteção e ownership

- Toda área financeira exige login: `LoginRequiredMixin` nas views da
  aplicação e no onboarding; `login_required` implícito nas views de escrita.
- Usuário não autenticado → redirecionado ao login (nunca acessa dados).
- **Ownership** reforçado pela camada de serviços (Ordem 5): toda criação de
  conta (`create_account`) define `owner=request.user`; nenhum ID vem do
  frontend para buscar dados de outro usuário.
- Novos serviços (Ordem 6): `apps/finance/services/accounts.py` →
  `create_account` (operação mínima para o onboarding; decisão documentada).

### Onboarding (estado e etapas)

- **Estado:** `Profile.onboarding_completed` (já existia no model — **sem
  alteração de model/migration**). Fonte de verdade ÚNICA o flag; **nenhum
  estado duplicado em sessão**.
- **Fluxo (4 etapas)**, em `apps/accounts/onboarding.py`:
  1. Boas-vindas ("Vamos organizar sua vida financeira.");
  2. Perfil (display_name) — usa o `Profile` existente, mínimo;
  3. **Primeira conta** — delega a regra financeira ao serviço `create_account`
     (validando saldo/ownership); nesta etapa o `onboarding_completed` é marcado;
  4. Conclusão — resumo da conta criada, acessível mesmo após conclusão.
- **Roteamento:** a raiz `/` (`apps.core.views.home`) desvia: anônimo →
  landing; autenticado sem onboarding → etapa 1; autenticado com onboarding →
  aplicação.

### Shell da aplicação (configuração visual)

- Novo app `apps.dashboard` (sem models, sem migrations): `DashboardIndexView`
  (placeholder, sem números inventados) + páginas estruturais (`/app/<section>/`)
  para Movimentações, Contas, Cartões, Planejamento, Metas, Dívidas e
  Configurações.
- Layout `templates/app/_shell.html`: sidebar (desktop) + topbar (mobile) +
  barra de navegação inferior (mobile) — **mobile-first, sem largura fixa**.
- Componentes reutilizáveis em `templates/components/`: `button`, `field`,
  `brand`, `messages`, `error_list`.
- Tailwind CSS (v4) já instalado; novas classes de componentes (`btn*`,
  `alert*`, form controls) em `static/css/input.css`.

### Erros e acessibilidade

- Templates próprios `404`, `403`, `500` (sem traceback), sessão expirada →
  redireciona ao login.
- Acessibilidade: labels associados, mensagens de erro ligadas aos campos,
  `aria-live` nas mensagens, skip link preservado, foco visível, contraste.

### Validação (Ordem 6)

- `manage.py check` → 0 issues.
- `manage.py makemigrations --check --dry-run` → "No changes detected" (sem
  migração nova — nenhum model foi alterado).
- `manage.py test` → **94 testes OK** (71 da Ordem 5 + 23 novos), incluindo
  cadastro, login/logout, recuperação de senha, onboarding, shell e
  **ISOLAMENTO REAL** (usuário A não vê/edita/cria dados de B).
- `runserver`: `/`, cadastro, login, recuperação de senha → 200; área
  protegida redireciona ao login.

---

## Dashboard Financeiro e Read Layer (Ordem 7)

### Objetivo

Dashboard Financeiro **V1 real e data-driven**: transforma dados reais do banco
em **compreensão, alertas, prioridades e decisões**. Sem mock/lorem ipsum,
sem IA/LLM — o "insight engine" é **100% determinístico** (estatística simples e
explicável), respeitando a regra de que só afirma quando há amostra suficiente.

### Fluxo (camadas obrigatórias)

```
DB → MODELS → SERVICES/QUERIES (read layer) → VIEWMODEL → TEMPLATE → TAILWIND
```

Nenhum cálculo financeiro vive em view/template. As regras duplicadas de
domínio (saldos, comprometido, fatura) **reutilizam os serviços existentes**
(`finance/services/*`, `cards/services/*`) ou são centralizadas no read layer —
nunca reimplementadas dentro do template.

- `apps/dashboard/queries.py` — read layer com dataclasses e queries agregadas
  (SQL + `TruncMonth`), todas via `for_user(user)`/`owner=user`, sem N+1.
- `apps/dashboard/viewmodel.py` — `build_dashboard(user, period, account_id,
  card_id, today)` monta o dict completo do template + formatter BRL.
- `apps/dashboard/insights.py` — motor de insights determinísticos.
- `apps/dashboard/views.py` / `urls.py` — `DashboardIndexView` (filtros GET);
  `AppPlaceholderView` mantido com `name="index"`.
- `templates/app/dashboard.html` + `templates/components/*` (design system).

### Filtros (alteram dados reais)

- `?period=7d|30d|3m|6m|12m` (default `30d`)
- `?account=<pk>` e `?card=<pk>` — restringem as métricas.
- Ownership: `account`/`card` de **outro usuário são ignorados silenciosamente**
  (não vaza dados, não quebra a página). Ver `DashboardFilter` no viewmodel.

### Definições financeiras (centavos, nunca float)

- **disponível** = soma dos saldos das contas ATIVAS.
- **comprometido** = parcelas pendentes/atrasadas de cartão (vistas em
  `committed`/`committed_by_card`).
- **disponível_após** = disponível − comprometido.
- **receitas/despesas** = soma de `Transaction` INCOME/EXPENSE (e ADJUSTMENT)
  no período.
- **Compra no cartão NÃO é despesa** até a liquidação da fatura — evita dupla
  contabilização (o pagamento da fatura aparece **uma única vez** como despesa).
- **Transferência interna não é** receita nem despesa.
- **resultado** = receitas − despesas no período.

(Fórmulas detalhadas em `docs/DASHBOARD.md`.)

### Validação (Ordem 7)

- `manage.py check` → 0 issues.
- `manage.py makemigrations --check --dry-run` → "No changes detected" (nenhum
  model alterado na Ordem 7).
- `manage.py test` → **117 testes OK** (94 anteriores + 23 novos do dashboard:
  métricas exatas, períodos, dupla contabilização, estados vazios, segurança/
  isolamento, insights, performance N+1 e render de view com conteúdo real).
- Render visual end-to-end via `runserver` + login real (dados descartados após
  verificação) confirmou: hero (disponível/comprometido/após), fluxo de caixa,
  gráfico de barras, insights, cartões/categorias/contas/faturas/parcelas/
  orçamentos/metas/dívidas/movimentações recentes.
