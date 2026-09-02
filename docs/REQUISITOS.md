# Requisitos do Projeto — FINTECPESSOAL

Documento de requisitos oficiais do projeto **FINTECPESSOAL** (controle e inteligência financeira pessoal).

> Última atualização: ver histórico de commits / datar ao adicionar novas seções.
> Aviso: este documento registra decisões de produto e design. Nada aqui substitui a análise técnica detalhada em questão de tempo de implementação.

---

## 1. Objetivo do produto

Aplicação local, gratuita, de **controle e inteligência financeira pessoal**, com cara de produto fintech profissional, simples e confiável. Funciona inicialmente 100% **local**, **custo zero**, sem dependência de APIs pagas e sem LLM.

## 2. Stack / base técnica

- **Django** (backend);
- **Python**;
- Banco **SQLite** inicialmente (com possibilidade futura de **PostgreSQL**);
- Sem LLM inicialmente;
- Sem APIs externas inicialmente;
- Arquitetura **modular**;
- Código simples e de fácil manutenção;
- Possibilidade futura de importar **CSV/OFX**;
- Possibilidade futura de adicionar **IA como módulo opcional**.

---

## 3. Frontend

- Django;
- **Tailwind CSS**;
- **HTML semântico**;
- **JavaScript apenas quando necessário**;
- Arquitetura de **componentes reutilizáveis**;
- Layout **responsivo**;
- Abordagem **mobile-first**.

**Restrição:** NÃO adicionar React, Next.js ou outro framework frontend neste momento.

---

## 4. Direção visual

Queremos um produto com **aparência de fintech grande e profissional**.

A referência de experiência é a simplicidade, clareza e qualidade percebida de aplicativos financeiros modernos, incluindo o **Nubank como referência de UX**.

> **IMPORTANTE:** Não copiar identidade visual, logotipo, componentes proprietários, textos ou layout específico do Nubank. Queremos apenas a mesma **sensação** de:

- produto financeiro premium;
- simplicidade;
- confiança;
- clareza;
- excelente hierarquia visual;
- interface moderna;
- navegação extremamente intuitiva;
- números financeiros visualmente importantes;
- poucos elementos desnecessários;
- excelente experiência mobile e desktop.

## 5. Princípio de design

O FINTECPESSOAL **não deve parecer uma planilha bonita** — deve parecer um **produto financeiro profissional**.

A interface deve priorizar responder:

1. Quanto dinheiro tenho?
2. Quanto posso realmente gastar?
3. O que vai acontecer nos próximos dias?
4. Estou gastando demais em alguma coisa?
5. Quais problemas financeiros foram encontrados?
6. Quais decisões devo tomar?
7. Minhas metas estão evoluindo?

O dashboard deverá, futuramente, **transformar dados em decisões**, e não apenas exibir gráficos.

### Exemplos conceituais de tomada de decisão

> "Você está gastando 18% acima do seu padrão."

> "Esta compra compromete sua meta."

> "Você pode comprar isso sem comprometer suas despesas."

> "Se mantiver este comportamento, sua reserva chegará a R$ X em 12 meses."

> "Encontramos R$ X em possíveis desperdícios."

> **Nota:** Essas funcionalidades serão implementadas em etapas posteriores.

---

## 6. Restrições atuais

- NÃO implementar funcionalidades ainda;
- NÃO criar o dashboard ainda;
- NÃO alterar a arquitetura existente sem necessidade;
- Registrar estas diretrizes na documentação/planejamento do projeto.

---

## 7. Diretrizes do diagnóstico inicial (ambiente)

Informações do diagnóstico do ambiente (não repetir diagnóstico):

| Ferramenta | Versão |
|---|---|
| Windows | 10 Pro, build 19045 (AMD64) |
| Python | 3.12.7 |
| pip | 24.2 |
| Git | 2.55.0.windows.3 |
| venv | Disponível |
| SQLite | 3.45.3 |
| Django | 6.1 |
| Node.js | v22.13.1 / npm 10.9.2 (opcional) |

### Recomendações registradas
- Criar **venv** dentro do projeto (`.venv`) para isolamento;
- Iniciar repositório **Git** e configurar identidade;
- Usar **requirements.txt**;
- Definir **`.gitignore`** (`.venv/`, `db.sqlite3`, `__pycache__/`);
- Manter Django recente (6.x), compatível com Python 3.12.

### Arquitetura inicial sugerida (proposta, sujeita a confirmação)

```
C:\fintecpessoal\
├── .gitignore
├── requirements.txt
├── README.md
├── .venv/
├── manage.py
├── config/                  (projeto: settings/urls/wsgi/asgi)
└── apps/                    (negócio modular por domínio)
    ├── core/
    ├── accounts/
    ├── contas/              (futuro)
    ├── transacoes/          (futuro)
    ├── orcamento/           (futuro)
    └── relatorios/          (futuro)
```

> Arquitetura modular por domínio; futuros apps `importadores` (CSV/OFX) e `ia` (opcional) encaixam-se como módulos separados.

### Decisão arquitetural implementada (Ordem 2)

- Projeto Django em `config/` com **settings divididos por ambiente**: `config/settings/` com `base`, `development`, `production`, `test`. Ambiente ativo definido por `DJANGO_ENV` (padrão `development`), no `config/settings/__init__.py`.
- Negócio isolado em `apps/` modulares (`apps.core`, `apps.accounts`). Apps de terceiros seriam adicionados antes de `LOCAL_APPS`.
- SQLite em `config/settings/base.py`; futura migração para PostgreSQL via configuração do ORM, sem acoplar código.
- Segredos (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`) via `.env` (python-dotenv); `.env` não versionado.
- Frontend com **Tailwind CSS v4** (CLI oficial, build real), design tokens em `static/css/input.css` (`@theme`), CSS gerado em `static/css/tailwind.css` (ignorado pelo git, regenerado por `npm run tailwind:build`/`:watch`).
- Template base estrutural em `templates/base.html` (HTML5, responsivo, acessível, pronto para navegação).

### Modelagem do domínio financeiro (Ordem 3)

Requisito oficial de **multiusuário** e modelagem conceitual completa do domínio financeiro registrados em:
📄 [`ARQUITETURA_DOMINIO.md`](./ARQUITETURA_DOMINIO.md)

Inclui: entidades (Account, CreditCard, Category, Transaction, Transfer, InstallmentPurchase/Installment, CreditCardInvoice, RecurringRule, Budget, Goal, Debt), isolamento por usuário, princípios financeiros, cartão→fatura→pagamento, dinheiro em centavos, datas/timezone, importação futura (CSV/OFX), auditoria e riscos. **Sem models/migrations implementados ainda.**


