# PAUTA PARA CONVERSAR COM IA SOBRE MONETIZAÇÃO

> **Use este documento como contexto.** Copie e cole no chat com a IA (GPT/Claude etc.)
> e faça as perguntas do final (ou peça uma estratégia completa).

---

## 1. O que é o produto

O **FINTECPESSOAL** é uma aplicação web de **controle e inteligência financeira
pessoal**, 100% funcional e **já no ar** em `https://fintecpessoal.onrender.com`.

É multiusuário (cada conta é isolada), com os módulos abaixo já implementados e
testados (319 testes automatizados).

### Funcionalidades existentes (todas funcionando):
- Contas financeiras (corrente, poupança, carteira, digital, investimento) e
  categorias com hierarquia (pai/subcategoria).
- Transações: receitas, despesas, transferências (2 pernas) e ajustes — valores
  sempre em **centavos (inteiros)** para evitar erros de ponto flutuante.
- **Cartões de crédito**: compras parceladas, parcelas, faturas (valor derivado
  das parcelas, evitando dupla contabilização), pagamento de fatura.
- **Orçamentos**: por categoria ou global, com alerta de atenção/estouro.
- **Metas**: com aportes, progresso, ritmo mensal necessário, projeção de término.
- **Dívidas**: tipos, taxa, pagamentos (geram transação contábil real), status.
- **Lembretes/agenda**: timeline de vencimentos (faturas, recorrências, dívidas).
- **Comprovantes**: anexos, tipos, controle/aviso de garantia.
- **Relatórios**: consolidado, exportação CSV, impressão/PDF.
- **Dashboard**: liquidez, fluxo de caixa, gastos por categoria, evolução mensal,
  resumos de cartões/metas/orçamentos/dívidas e **insights/alertas automáticos**
  (sem IA): risco de liquidez, gasto acima do padrão, cartão perto do limite,
  orçamento estourado, etc.
- **Recorrências** (semanal/mensal/anual) com projeção sob demanda.
- **Autenticação completa**: cadastro, login, recuperação de senha por email,
  onboarding em 4 etapas.

## 2. Inteligência Artificial (Gemini) — o diferencial

A IA é a principal diferenciação e funciona como **feature flag opcional**
(sem chave, o app funciona normal):

1. **Leitura automática de comprovantes**: o usuário envia um PDF/imagem e a IA
   extrai estabelecimento, valor, data e **categoria sugerida**, preenchendo o
   formulário automaticamente.
2. **Sugestão de categoria** ao lançar uma movimentação (digita a descrição e a
   IA sugere onde classificar).
3. **Relatório "auditor de bolso"**: relatório de análise completo em Markdown com
   visão geral, nota de saúde financeira (0–10), alertas e cuidados, sugestões de
   melhoria, plano para aumentar patrimônio e **3 ações concretas**. Limitado a
   **1 geração a cada 3 dias** (cooldown) por usuário.

### Custos atuais de infraestrutura:
- **Render (free)** — hospeda o app 24/7.
- **Supabase (Postgres free)** — banco de dados (~500MB).
- **Gemini (free tier)** — as chamadas de IA são leves e cabem no plano gratuito.

**Ou seja, hoje o produto roda com custo de infra ≈ R$ 0.**

## 3. Público-alvo presumido
- Pessoas físicas que querem organizar as finanças pessoais (equivalente local a
  apps como Organizze, Mobills, GuiaBolso, YNAB, Nubank insights).
- Perfil: brasileiro, usa banco digital + cartão de crédito, não usa planilha.

## 4. O que quero que a IA me ajude a decidir

### (a) Modelo de monetização
Qual o melhor caminho? Entre as opções, qual se encaixa mais para este produto
e qual o raciocínio:
- **Assinatura (SaaS pago)** — freemium ou pago integral; qual preço sugerido
  para o mercado brasileiro (R$) e quais tiers/limites.
- **Perguntas de frequência:** preço por usuário/mês, anual com desconto, trial.
- Alternativas: pagamento único, doações, patrocínio, open-core, licenciar como
  White-label para bancos/cooperativas, vender como serviço de consultoria
  financeira.

### (b) Estratégia Freemium (se assinatura)
Quais funcionalidades devem ficar **gratuitas** (magnet de atração) e quais
devem ser **pagas** (valor percebido)? Sugira uma divisão clara usando a lista
de funcionalidades deste documento. A IA parece o candidato natural ao "muro do
premium" — concorda? Como limitar a IA no free vs. pago de forma justa?

### (c) Público e posicionamento
Para quem priorizar primeiro? Como segmentar (ex.: assalariados com parcelas,
freelancers, famílias)? Qual a proposta de valor/mensagem principal (ex.:
"seu auditor financeiro de bolso")?

### (d) Próximas funcionalidades com maior retorno
Baseado no produto atual, quais são as funcionalidades de maior impacto para
converter/atrair pagantes (ex.: integração bancária via Open Finance, multi-moeda,
metas de investimento, relatórios fiscais/IR, versão família/dupla)?

### (e) Infra e custos ao escalar
Quais custos surgem ao passar de 5 usuários para 50/500 (plano pago do Render,
banco, limite de IA, armazenamento de arquivos) e como precificar levando isso
em conta? O limite de IA tem custo direto — como calibrar o cooldown/limite por
plano para o custo ficar sustentável?

### (f) Passos de execução para validar
Um plano pragmático em ordem: (1) validar demanda com X usuários reais; (2)
escolher e implementar cobrança (Stripe vs. PIX/Boleto manual no BR — qual
recomenda?); (3) piloto pago; (4) métricas a acompanhar (conversão, churn,
custo por usuário).

## 5. Contexto técnico relevante para a IA
- Django 6.1 · Python 3.12 · PostgreSQL (Supabase) · IA Gemini · frontend com
  Tailwind, visual "neumorfismo moderno".
- Já tem multiusuário, isolamento de dados, testes automatizados e deploy
  contínuo (Render + GitHub).
- Valores em centavos (inteiros). IA por feature flag. Sem dependências pesadas.
- Capacidade atual indicada para **até ~5 usuários** sem nenhum custo; escala
  exige plano pago do Render e, possivelmente, limites maiores de IA.

---

## Perguntas rápidas para começar o papo (copie e envie junto)

> "Analise o produto FINTECPESSOAL (controle e inteligência financeira pessoal
> multiusuário, com IA via Gemini, já no ar e com custo de infra ≈ 0). Quero
> monetizar no Brasil. Responda:
> 1. Qual modelo de monetização você recomenda e por quê?
> 2. Proponha um plano Freemium: o que fica grátis e o que fica pago (usando
>    funcionalidades de contas, cartões, metas, orçamentos, dívidas, relatórios,
>    comprovantes, dashboard e IA)?
> 3. Qual preço sugerido em R$/mês (e se anual com desconto) para o público
>    brasileiro?
> 4. Como precificar e limitar o uso da IA no free vs. pago para o custo ficar
>    sustentável?
> 5. Quais próximas 3 funcionalidades teriam maior impacto em conversão?
> 6. Como validar a demanda antes de investir em cobrança?
> 7. Qual gateway de pagamento recomenda para o Brasil (Stripe vs. alternativas
>    PIX/boleto) para um SaaS pequeno começando?"

---

*Gerado em 02/09/2026. Enviar este documento + a pergunta do final a qualquer IA.*
