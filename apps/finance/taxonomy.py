"""Base semântica (taxonomia) do FINTECPESSOAL — Ordem 18, FASE 3.

Define o conjunto INICIAL de categorias/subcategorias padrão (semeadas por
usuário), usando o campo ``Category.parent`` como hierarquia (NÃO criamos um
modelo de Subcategoria separado).

Princípios (Ordem 18 §8 / FASE 2 ajustes):
- Otimizada para IMPORTAÇÃO + CLASSIFICAÇÃO + ANÁLISE, não para cadastro manual.
- NÃO existem categorias "Netflix", "Uber", "Spotify", "iFood" — esses serão
  estabelecimentos reconhecidos pelo Merchant (FASE 4).
- Categorias e subcategorias analiticamente úteis; isolação por usuário.
- A árvore é a "base semântica" que a classificação reutiliza depois.
- ``kind``: expense | income. Transferências possuem categorias próprias.

Estrutura: lista de (kind, categoria, [subcategorias]).
"""

from .models import Category

# Categorias/subcategorias padrão de DESPESA (EXPENSE).
_EXPENSE_TREE = [
    ("Moradia", [
        "Aluguel", "Condomínio", "Água e esgoto", "Energia elétrica", "Gás",
        "IPTU", "Manutenção residencial", "Mobília", "Outros",
    ]),
    ("Alimentação", [
        "Supermercado", "Feira", "Padaria", "Açougue", "Hortifrúti",
        "Restaurante", "Delivery", "Refeições no trabalho", "Cafeteria", "Outros",
    ]),
    ("Transporte", [
        "Aplicativos", "Combustível", "Transporte público", "Estacionamento",
        "Pedágio", "Manutenção", "Seguro veicular", "IPVA", "Impostos e documentação",
        "Outros",
    ]),
    ("Saúde", [
        "Farmácia", "Consultas", "Exames", "Plano de saúde", "Dentista",
        "Terapias", "Academia", "Outros",
    ]),
    ("Educação", [
        "Mensalidade", "Cursos", "Material", "Livros", "Cursos online", "Outros",
    ]),
    ("Trabalho", [
        "Equipamentos", "Uniforme", "Transporte para o trabalho", "Outros",
    ]),
    ("Entretenimento", [
        "Streaming de vídeo", "Streaming de música", "Jogos", "Cinema",
        "Shows e eventos", "Livros e mídia", "Outros",
    ]),
    ("Assinaturas", [
        "Streaming de vídeo", "Streaming de música", "Software", "Armazenamento em nuvem",
        "Educação", "Clubes", "Outros",
    ]),
    ("Tecnologia", [
        "Celular", "Internet", "Computadores", "Acessórios", "Software",
        "Armazenamento em nuvem", "Outros",
    ]),
    ("Compras pessoais", [
        "Vestuário", "Calçados", "Acessórios", "Beleza e cuidados", "Presentes",
        "Outros",
    ]),
    ("Casa", [
        "Eletrodomésticos", "Limpeza", "Utilidades", "Decoração", "Ferramentas",
        "Outros",
    ]),
    ("Família", [
        "Dependentes", "Presentes", "Festas", "Outros",
    ]),
    ("Pets", [
        "Ração", "Veterinário", "Pet shop", "Outros",
    ]),
    ("Viagens", [
        "Passagens", "Hospedagem", "Transporte local", "Alimentação",
        "Seguro viagem", "Lazer", "Outros",
    ]),
    ("Finanças", [
        "Tarifas bancárias", "Juros", "Encargos", "Impostos financeiros",
        "Transferência para cartão", "Outros",
    ]),
    ("Transferências", ["Envio de PIX", "Outros"]),
    ("Impostos", [
        "Federais", "Estaduais", "Municipais", "Outros",
    ]),
    ("Seguros", [
        "Vida", "Residência", "Automóvel", "Saúde", "Celular", "Outros",
    ]),
    ("Doações", [
        "Instituições", "Pessoas", "Outros",
    ]),
    ("Outros", [
        "Diversos",
    ]),
]

# Categorias/subcategorias padrão de RECEITA (INCOME).
_INCOME_TREE = [
    ("Rendimentos", [
        "Salário", "Benefícios", "Reembolso", "Outros",
    ]),
    ("Renda extra", [
        "Freelancer", "Vendas", "Serviços", "Outros",
    ]),
    ("Investimentos", [
        "Retorno de aplicações", "Dividendos", "Outros",
    ]),
    ("Transferências", ["Recebimento de PIX", "Outros"]),
]

# Árvore combinada para facilitar a iteração e testes.
DEFAULT_TREE = [
    (Category.Kind.EXPENSE, name, children) for name, children in _EXPENSE_TREE
] + [
    (Category.Kind.INCOME, name, children) for name, children in _INCOME_TREE
]


def default_kinds():
    """Conjunto de kinds usados na taxonomia padrão."""
    return {kind for kind, _, _ in DEFAULT_TREE}
