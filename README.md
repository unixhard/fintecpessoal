# FINTECPESSOAL

Controle e inteligência financeira pessoal — simples, local, confiável e sem custo.

> Status: **plataforma financeira operacional completa** (core financeiro multiusuário + isolamento + camada de serviços + cadastro/login/onboarding + shell + dashboard data-driven + CRUD de contas/categorias/lançamentos/transferências/recorrências + cartões/compras parceladas/faturas com pagamento + **orçamentos, metas e dívidas com regras de negócio**).

## Objetivo

Aplicação local, gratuita, de **controle e inteligência financeira pessoal** com aparência de fintech profissional. Funciona 100% local, sem APIs pagas e sem LLM. Esta fase entrega o **núcleo do domínio financeiro** (models, migrações, isolamento multiusuário, regras de integridade e camada de serviços) **e a experiência do usuário** (cadastro, login, recuperação de senha, onboarding, shell da aplicação) **mais o dashboard financeiro data-driven** na Ordem 7 (métricas reais, filtros por período/conta/cartão, insights determinísticos sem IA e design system mobile-first) **e o produto financeiro completo** na Ordem 9 (orçamentos, metas e dívidas com CRUD operacional, regras de negócio nos services e isolamento por usuário).

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Django 6.1 (Python 3.12) |
| Banco | SQLite (migração futura para PostgreSQL é só configuração) |
| Frontend | Tailwind CSS 4 (build real via CLI) + HTML semântico |
| Containers de ambiente | `venv` (Python) + `node_modules` (assets) |

Sem React, Next.js, Vue ou Bootstrap. Sem APIs externas. Sem LLM.

## Requisitos do ambiente

- Python 3.12+ (3.12.7 usado)
- Node.js 22+ (para o build do Tailwind)

## Como configurar o ambiente

```bash
# 1. Criar e ativar o ambiente virtual
python -m venv .venv
.venv\Scripts\activate

# 2. Instalar dependências Python
pip install -r requirements.txt

# 3. Instalar dependências de frontend (Tailwind CLI)
npm install

# 4. Configurar variáveis de ambiente
copy .env.example .env
#   (gere uma SECRET_KEY e ajuste, se quiser)

# 5. Aplicar migrações do banco
python manage.py migrate
```

## Como executar

```bash
.venv\Scripts\activate

# Gerar/build do CSS do Tailwind (uma vez ou a cada mudança de template)
npm run tailwind:build

# Em modo observação (para desenvolvimento, regenera ao salvar)
npm run tailwind:watch

# Iniciar servidor de desenvolvimento
python manage.py runserver
```

Abra <http://127.0.0.1:8000/> — deve carregar a landing page. Cadastre-se em
`/contas/cadastro/`, faça login e passe pelo onboarding para acessar a área
autenticada em `/app/`. Health check em <http://127.0.0.1:8000/health/>.

## Como rodar os testes

```bash
.venv\Scripts\activate
python manage.py test
```

O ambiente `test` usa banco em memória (ver `config/settings/test.py`).

## Estrutura de diretórios

```
C:\fintecpessoal\
├── .env / .env.example   # variáveis de ambiente
├── .gitignore
├── manage.py
├── package.json          # scripts e dependências do front (Tailwind)
├── requirements.txt
├── config/               # projeto Django
│   ├── settings/         # base / development / production / test
│   ├── asgi.py
│   ├── urls.py
│   └── wsgi.py
├── apps/                 # apps modulares (um por domínio)
│   ├── core/             # home/roteamento, health check, utilidades globais (OwnedModel)
│   ├── accounts/         # User customizado + Profile + autenticação + onboarding
│   ├── dashboard/        # Dashboard financeiro (read layer, viewmodel, insights, view)
│   ├── finance/          # Account, Category, Transaction, Transfer, RecurringRule
│   ├── cards/            # CreditCard, InstallmentPurchase/Installment, Invoice
│   ├── budgets/          # Budget (por categoria / global)
│   ├── goals/            # Goal
│   └── debts/            # Debt
├── templates/            # templates globais (ex.: base.html)
│   ├── components/       # botões, campos, marca, alertas (reutilizáveis)
│   ├── accounts/         # login, cadastro, recuperação de senha, onboarding
│   └── app/              # shell + dashboard/placeholder da área autenticada
├── static/               # arquivos estáticos
│   ├── css/input.css     # fonte do design system (Tailwind v4)
│   └── css/tailwind.css  # CSS gerado (não editar à mão)
├── media/                # uploads futuros
├── tests/                # testes de integração (futuro)
└── docs/
    └── REQUISITOS.md     # requisitos do produto/design
```

## Como compilar/usar o Tailwind

Este projeto usa **Tailwind CSS v4** com a CLI oficial. O fluxo não usa cópia manual de CSS:

1. O design system vive em `static/css/input.css` (tokens em `@theme`, componentes em `@layer`).
2. O Tailwind **escaneia** `templates/` e `apps/**/templates/` (diretivas `@source`) e gera apenas o CSS usado.
3. O CSS final é salvo em `static/css/tailwind.css` e carregado pelo `templates/base.html`.
4. O arquivo gerado é ignorado pelo git (`.gitignore`) e regenerado por `npm run tailwind:build`.

Scripts (em `package.json`):

- `npm run tailwind:build` — gera CSS minificado de produção.
- `npm run tailwind:watch` — regenera em loop para desenvolvimento.

## Documentação do projeto

- `docs/REQUISITOS.md` — requisitos do produto e identidade visual.
- `docs/ARQUITETURA_DOMINIO.md` — **modelagem do domínio financeiro multiusuário** (entidades, relacionamentos, decisões, alternativas e riscos) + seção "Dashboard Financeiro e Read Layer (Ordem 7)". Consulte antes de implementar qualquer model financeiro.
- `docs/DASHBOARD.md` — **métricas, fórmulas, períodos, estados vazios e regras de insights do dashboard** (referência para o cálculo de cada número).
- `docs/OPERACAO_FINANCEIRA.md` — camada de serviços da app finance (contas, transações, transferências, recorrências).
- `docs/ORCAMENTOS.md` — **orçamentos** (regras, services, cálculos de consumo/situação, rotas, testes).
- `docs/METAS.md` — **metas financeiras** (regras, contribuição/marcadores, projeção, rotas, testes).
- `docs/DIVIDAS.md` — **dívidas** (regras, pagamento como despesa, transições de status, rotas, testes).

## Decisões arquiteturais relevantes

- **Estrutura `config/` + `apps/` separados**: o projeto (settings/urls/wsgi/asgi) vive em `config/`; a lógica de negócio vive em `apps/` modulares, um app por domínio. Isso evita um app monolítico e facilita adicionar módulos futuros (importadores, IA) sem acoplar.
- **Settings divididos por ambiente** (`config/settings/`): `base`, `development`, `production`, `test`. O ambiente ativo é escolhido pela variável `DJANGO_ENV` (padrão: `development`) no `config/settings/__init__.py`.
- **SQLite primeiro, PostgreSQL depois**: o banco fica isolado em `config/settings/base.py`; a migração futura é apenas trocar a configuração de `DATABASES` (usando o ORM do Django, sem código acoplado ao SQLite).
- **Segredos no `.env`**: `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS` são lidos de variáveis de ambiente através de `python-dotenv`. O `.env` real é ignorado pelo git; o `.env.example` documenta as variáveis.
- **`SECRET_KEY` fora do código**: o valor real vive apenas no `.env` (não versionado).
- **Design system em design tokens**: as cores, tipografia, raios e sombras estão centralizadas no `@theme` do `input.css`, prontas para dark mode futuro e para definir componentes consistentes.
