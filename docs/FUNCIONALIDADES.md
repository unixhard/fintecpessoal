# FINTECPESSOAL — Documentação Completa de Funcionalidades

> **Produto:** Controle e inteligência financeira pessoal (web, multiusuário)
> **Status:** Em produção — `https://fintecpessoal.onrender.com`
> **Stack:** Django 6.1 · PostgreSQL (Supabase) · IA Gemini (feature flag) · Tailwind
> **Custo de infra (hoje):** US$ 0 — Render free + Supabase free + Gemini free tier

---

## 1. Visão Geral

O FINTECPESSOAL é um sistema web de **finanças pessoais** que permite ao usuário
registrar e acompanhar sua vida financeira completa (contas, cartões, metas,
orçamentos, dívidas) e receber **inteligência artificial** (Gemini) para
automatizar tarefas e gerar relatórios de análise.

É **multiusuário**: cada conta é isolada (nunca um usuário vê dados de outro).
Arquitetura com forte ênfase em:
- **Valores monetários sempre em inteiros (centavos)** — evita erros de ponto flutuante.
- **Isolamento por usuário** em todas as entidades (ownership).
- **IA opcional por feature flag** — sem chave, o sistema continua 100% funcional.
- **Sem dependências externas desnecessárias** (IA via `urllib` da stdlib, Markdown renderizado internamente).

---

## 2. Módulos e Funcionalidades por Área

### 2.1 Contas e Autenticação (`accounts`)

| Funcionalidade | Descrição |
|---|---|
| **Cadastro** | Criar conta com nome, email e senha (username derivado do email). |
| **Login** | Autenticação por email + senha. |
| **Logout** | Saída segura (POST). |
| **Recuperação de senha** | Fluxo completo por email (4 telas: solicitar → confirmar → nova senha → concluído). |
| **Perfil** | Nome de exibição, moeda padrão. |
| **Onboarding (4 etapas)** | Boas-vindas → nome/moeda → primeira conta financeira → conclusão. Redireciona usuários que já finalizaram direto ao dashboard. |

**Entidades:** `User`, `Profile` (display_name, preferred_currency, default_account,
preferences JSON, onboarding_completed).

---

### 2.2 Núcleo Financeiro (`finance`)

É o razão (ledger) principal do sistema.

| Funcionalidade | Descrição |
|---|---|
| **Contas financeiras** | Tipos: corrente, poupança, carteira/papel, digital, investimento, outros. Com saldo inicial, instituição, status (ativa/arquivada/encerrada). |
| **Categorias** | Classificação de despesas/receitas/transferências com **hierarquia pai/subcategoria**. Categorias padrão semeadas por usuário. |
| **Transações** | Receita, despesa, **transferência** (2 pernas, patrimônio invariável) e **ajuste** (exige observação). Valores em centavos. |
| **Transferências** | Entre contas do mesmo usuário, sem afetar patrimônio total. |
| **Recorrências** | Regras de repetição (semanal/mensal/anual/personalizada) que **projetam** ocorrências sob demanda, sem gerar milhares de registros. |

**Entidades:** `Account`, `Category`, `Transaction`, `Transfer`, `RecurringRule`.

---

### 2.3 Cartões de Crédito (`cards`)

| Funcionalidade | Descrição |
|---|---|
| **Cartões** | Cadastro de cartões (limite, dia de fechamento e vencimento, conta de pagamento). |
| **Compras parceladas** | Registro de compras em N parcelas; parcelas geradas automaticamente. |
| **Parcelas** | Status: pendente/paga/atrasada/pulada. Última parcela absorve diferença de arredondamento. |
| **Faturas** | Valor da fatura **derivado** das parcelas do período (evita dupla contabilização). Status: aberta/fechada/paga/atrasada. |

**Entidades:** `CreditCard`, `InstallmentPurchase`, `Installment`, `CreditCardInvoice`.

---

### 2.4 Orçamentos (`budgets`)

| Funcionalidade | Descrição |
|---|---|
| **Criar orçamento** | Por categoria ou global; período mensal/anual/personalizado; limite em R$. |
| **Acompanhar** | Progresso calculado em tempo real (planejado, realizado, restante, %). |
| **Situação** | `saudável` (<80%), `atenção` (≥80%), `estourado` (≥100%). |
| **Ativar/inativar** | Toggle rápido. |

**Entidades:** `Budget`. Orçamento por categoria inclui subcategorias no cálculo.

---

### 2.5 Metas (`goals`)

| Funcionalidade | Descrição |
|---|---|
| **Criar meta** | Nome, valor objetivo, data objetivo, prioridade, observações. |
| **Aportes** | Registrar contribuições; ao atingir o objetivo a meta vira **Alcançada** automaticamente. |
| **Acompanhar** | Progresso, restante, %, ritmo mensal necessário, projeção de conclusão, prazo vencido. |
| **Gerenciar status** | Ativa/Pausada/Alcançada/Arquivada; reativar e arquivar. |

**Entidades:** `Goal`.

---

### 2.6 Dívidas (`debts`)

| Funcionalidade | Descrição |
|---|---|
| **Criar dívida** | Nome, tipo (empréstimo/financiamento/parcelamento externo/outros), taxa de juros, credor, datas. |
| **Pagamentos** | Registrar pagamento (conta, valor, data) — gera **transação de despesa real** (rastreabilidade contábil). |
| **Status** | Ativa/Quitada/Inadimplente/Arquivada. Impede pagamento acima do saldo. |
| **Acompanhar** | Pago, restante, percentual. |

**Entidades:** `Debt`.

---

### 2.7 Lembretes / Agenda (`reminders`)

| Funcionalidade | Descrição |
|---|---|
| **Timeline consolidada** | Eventos próximos: faturas de cartão + recorrências + fim de dívidas ativas. |
| **Filtro** | Horizontes: 7/15/30/60 dias. |
| **Urgência** | Classificação: atrasado, hoje, em breve (≤3d), próximo. |

Entidade de leitura (sem modelos próprios). App de agregação.

---

### 2.8 Relatórios e IA (`reports`)

| Funcionalidade | Descrição |
|---|---|
| **Relatório consolidado** | Fluxo de caixa, gastos por categoria e evolução mensal (períodos 7d/30d/3m/6m/12m). |
| **Exportação CSV** | Movimentações do período (abre no Excel). |
| **Impressão/PDF** | Relatório limpo para salvar/imprimir em PDF pelo navegador. |
| **Relatório por IA ("auditor de bolso")** | Relatório completo em Markdown com: visão geral, saúde financeira (nota 0–10), alertas, sugestões, plano para aumentar patrimônio e **3 ações concretas**. |
| **Cooldown IA** | 1 geração a cada **3 dias** por usuário. |
| **Fallback** | Se a IA estiver indisponível, mostra relatório local determinístico **sem consumir o cooldown**. |

**Entidade:** `AIReport` (summary, content Markdown, via_ai, generated_at).

---

### 2.9 Comprovantes (`comprovantes`)

| Funcionalidade | Descrição |
|---|---|
| **Registrar comprovante** | Título, tipo, arquivo anexado, data de expiração de garantia, observações. |
| **Tipos** | Comprovante/recibo, nota fiscal, garantia, recibo de saúde/IR, outros. |
| **Garantia** | Alerta quando a garantia expira (janela de 60 dias). |
| **Download** | Baixar o arquivo anexado. |
| **IA "Preencher com IA"** | Analisa o arquivo (PDF/JPG/PNG/TXT, até 2MB) e **extrai automaticamente**: estabelecimento, valor, data e categoria sugerida, preenchendo o formulário. |

**Entidade:** `Comprovante` (slug único, title, kind, file, warranty_expiry).

---

### 2.10 Dashboard e Insights (`dashboard`)

| Funcionalidade | Descrição |
|---|---|
| **Filtros** | Período (7d/30d/3m/6m/12m), conta, cartão. |
| **Cards de liquidez** | Saldo disponível, comprometido em cartões, disponível após compromissos. |
| **Fluxo de caixa** | Receitas, despesas, resultado, transferências do período. |
| **Gastos por categoria** | Com variação vs. período anterior. |
| **Evolução mensal** | Gráfico de tendência (receitas vs. despesas). |
| **Resumos** | Cartões, próximas faturas, parcelas pendentes, eventos futuros, orçamentos, metas, dívidas, contas, transações recentes. |
| **Insights determinísticos** | Alertas automáticos **sem IA**: risco de liquidez, fatura próxima sem saldo, gasto acima do padrão, despesa excepcional, concentração de gastos, cartão perto do limite, orçamento estourado, meta com prazo vencido. Classificados por severidade (crítico/atenção/info). |
| **Checklist de primeiros passos** | Guia para cadastrar conta, movimentação, cartão, meta, orçamento. |
| **Card do relatório IA** | Atalho para o relatório de análise IA na home. |

Entidade de leitura (agrega todos os outros módulos).

---

### 2.11 Público (`core`)

| Funcionalidade | Descrição |
|---|---|
| **Landing page** | Página inicial pública para visitantes anônimos. |
| **Health check** | `/health/` para monitoramento de disponibilidade. |
| **Redirecionamento** | Anônimo → landing; autenticado sem onboarding → onboarding; com onboarding → dashboard. |

---

## 3. Inteligência Artificial (Gemini) — Resumo

A IA é **opcional** e segue o princípio de *feature flag*: sem `GEMINI_API_KEY`,
tudo funciona normalmente no fluxo manual.

| Recurso IA | O que faz | Entrada enviada |
|---|---|---|
| **Leitura de comprovante** | Extrai estabelecimento, valor, data e categoria de um arquivo. | A imagem/arquivo (DPI mínimo). |
| **Sugestão de categoria** | Sugere a categoria de um lançamento. | Descrição + tipo. |
| **Relatório "auditor de bolso"** | Relatório de análise com notas, alertas, sugestões e plano. | Indicadores numéricos agregados (sem dados de terceiros). |

**Limites:** relatório IA = 1 a cada 3 dias; colet desta natureza é leve no plano
gratuito do Gemini.

---

## 4. Infraestrutura e Segurança (atual)

| Item | Configuração |
|---|---|
| **Aplicação** | Render (Web Service free, Gunicorn, 1 worker). |
| **Banco de dados** | PostgreSQL via Supabase (free tier, ~500MB). |
| **Arquivos estáticos** | WhiteNoise + `collectstatic` (CSS compilado versionado). |
| **Variáveis de ambiente** | `SECRET_KEY`, `DEBUG=false`, `ALLOWED_HOSTS`, `DATABASE_URL`, `GEMINI_API_KEY` (opcional). |
| **Multiusuário** | Isolamento por `owner` em todas as entidades (OwnedModel). |
| **Valores em centavos** | Inteiros — sem erro de float. |
| **Senha** | Hash seguro do Django; fluxo de reset por email. |
| **HTTPS** | Término TLS no Render. |

---

## 5. Diferenciais (o que o torna interessante)

1. **IA integrada ao app financeiro** — não é só cadastro; a IA *automatiza* o lançamento e *analisa* a saúde financeira.
2. **Arquitetura multiusuário segura** com custo de infra **zero**.
3. **Razoável amplitude de módulos** (contas, cartões, parcelas, faturas, orçamentos, metas, dívidas, lembretes, comprovantes, relatórios, dashboard, insights).
4. **Insights sem depender da IA** — valor entregue mesmo sem chave.

---

*Documentação gerada em 02/09/2026.*
