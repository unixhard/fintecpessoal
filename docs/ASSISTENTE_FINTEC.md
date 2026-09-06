# Assistente Fintec — Assistente Conversacional de Lançamentos

Módulo que permite registrar receitas e despesas por linguagem natural, com
interface de chat integrada ao shell do FINTECPESSOAL. A interpretação é 100%
**determinística** (regex + normalização + dicionários de palavras-chave) — **não
usa API externa, LLM ou qualquer modelo de IA** nesta versão.

## Arquitetura (fluxo)

```
Chat (frontend) -> POST /app/finance/assistente/interpretar/
                -> services/chat.py::interpret  -> services/chat_parser.py (parser puro)
                -> RASCUNHO (retornado, NADA salvo)

Usuário revisa/ajusta -> POST /app/finance/assistente/confirmar/
                -> services/chat.py::confirm (re-valida TUDO no servidor)
                -> services existentes (record_income / record_expense /
                   create_card_purchase) -> Models existentes
```

O princípio central da diretiva é respeitado: o Assistente é apenas uma **nova
interface de entrada** para o mesmo domínio financeiro. A mesma movimentação
criada manualmente ou pelo Assistente produz exatamente os mesmos efeitos.

## Arquivos criados

| Arquivo | Papel |
| --- | --- |
| `apps/finance/services/chat_parser.py` | Parser puro (sem banco/request): valores, tipo, categoria, descrição, data |
| `apps/finance/services/chat.py` | Orquestração: `interpret` (rascunho) + `confirm` (persistência + idempotência) |
| `static/js/chat.js` | UX do chat (envio, typing, rascunho editável, confirmação) |
| `apps/finance/tests_chat.py` | Testes do parser, endpoints, segurança e cartão |

## Arquivos modificados

| Arquivo | Mudança |
| --- | --- |
| `apps/finance/views.py` | `ChatParseView` + `ChatConfirmView` (endpoints JSON) |
| `apps/finance/urls.py` | Rotas `assistente/interpretar/` e `assistente/confirmar/` |
| `templates/app/_shell.html` | CTA "Nova Transação" com menu duplo + FAB mobile + modal do chat |
| `static/css/tailwind.css` | Build (`npm run tailwind:build`) |

## Como funciona o parser

1. **Normalização** — lowercase, acentos removidos para comparação, espaços
   limpos, limite de 500 caracteres.
2. **Valor** — sempre `decimal.Decimal` (nunca float). Aceita `58`, `58,50`,
   `58.50`, `1.500`, `1.500,50`, `R$ 1.500,50`, `1500 reais`, `1 conto` (convenção
   brasileira). Rejeita zero, negativos, não-numéricos e valores absurdos.
3. **Tipo** — conjuntos independentes de verbos de despesa/receita. **Nunca**
   assume `se não for receita = despesa`; sem intenção clara → `type_ambiguous`.
4. **Categoria** — dicionário genérico (Alimentação, Transporte, Lazer, Moradia,
   Saúde, Renda) -> resolvido para uma `Category` **real e ativa** do usuário
   (via `for_user`). Nunca cria categoria; se nada bater, deixa para seleção.
5. **Descrição** — remove apenas verbos/conectores no início/fim e o token de
   valor. Preserva preposições internas (`mercado do bairro` fica intacto).
6. **Data** — hoje por padrão (timezone do projeto); reconhece `hoje`/`ontem`.

## Fluxo preview → confirmação

- **Interpretar**: retorna rascunho `{type, amount, description, category_id,
  category_label, date}` + listas **mínimas** de contas/cartões/categorias
  (id, nome, tipo). Nenhuma escrita.
- **Confirmar**: o backend **não confia** nos dados do frontend — re-aplica o
  parser na mensagem original, re-valida cada campo editado, valida ownership de
  conta/cartão/categoria e grava **somente via services existentes**.

## Regras de conta x cartão

- **Receita** → somente conta ativa. Cartão de crédito é **rejeitado** como
  destino.
- **Despesa em conta** → `record_expense` (débito normal).
- **Despesa em cartão** → `create_card_purchase` (compra à vista, 1 parcela);
  NÃO debita a conta; impacta fatura/limite exatamente como o fluxo manual.

## Idempotência

- Frontend: botão "Confirmar" desabilitado após o primeiro clique.
- Backend: chave em cache (hash da solicitação) por 120s — duplo clique, Enter
  repetido, refresh ou retry não geram lançamentos duplicados. Bônus: testes
  limpam o cache a cada `setUp`.

## Segurança

- Todos os endpoints exigem login, respeitam CSRF (sem `csrf_exempt`).
- `request.user` é sempre a fonte de propriedade — nunca `user_id` do cliente.
- Toda busca de conta/cartão/categoria usa `for_user`; objetos de outro usuário
  viram "não encontrado".

## Limitações atuais

- Só interpreta **uma** movimentação por mensagem.
- Data: apenas `hoje`/`ontem` (sem parser temporal complexo).
- Cartão: compra sempre à vista (1 parcela).
- Sem suporte a transferências entre contas nesta fase.

## Como ampliar o dicionário

- Categorias: adicionar palavras-chave em `CATEGORY_KEYWORDS` em
  `chat_parser.py`.
- Tipo: adicionar verbos em `_EXPENSE_VERBS` / `_INCOME_VERBS`.
- Valor: ajustar `_VALUE_TOKEN` / `_raw_to_cents` se novos formatos forem
  necessários (a convenção brasileira já está coberta).
