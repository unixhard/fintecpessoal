"""Semeia o catálogo global de estabelecimentos brasileiros (Ordem 18 — FASE 4).

Cobre ~250 merchants com aliases reais de extratos bancários (Nubank, Itaú,
Bradesco, Santander, etc.) para maximizar a acertividade da classificação
automática na importação.

Idempotente e não destrutivo: só cria o que não existe.
"""

from django.core.management.base import BaseCommand

from ...models import Merchant, MerchantAlias

# ---------------------------------------------------------------------------
# Catálogo: nome do merchant, categoria-pai da taxonomia (Category.Name),
# e aliases tal como aparecem em extratos bancários brasileiros.
#
# Os aliases seguem o padrão real de cada banco:
#   Nubank  : "MERCADO EXTRA" / "UBER TRIP" / "IFOOD*PEDIDO123"
#   Itaú    : "ITAU UNIBANCO" / "COMPRA 09/03 MERCADO"
#   Bradesco: "PAG*ABC123 MERCADO" / "DEBITO AUTOMATICO ENEL"
#   Santander: "SANTANDER" / "TED SALARIO"
#   Inter   : "IO*UBER" / "IO*IFOOD"
#   C6      : "C6S*NETFLIX"
# ---------------------------------------------------------------------------

_CATALOG = [
    # =========================================================================
    # ALIMENTAÇÃO — Supermercado
    # =========================================================================
    {"name": "Pão de Açúcar", "default_category_name": "Supermercado", "aliases": [
        ("PAO DE ACUCAR", 0.98), ("PAC", 0.90), ("GRUPO PAO DE ACUCAR", 0.95),
        ("GPA", 0.90), ("COMERCIO", 0.85), ("CASA SANTA MARIA", 0.90),
    ]},
    {"name": "Carrefour", "default_category_name": "Supermercado", "aliases": [
        ("CARREFOUR", 0.98), ("CARREFOUR BRASIL", 0.95), ("ATACADAO CARREFOUR", 0.95),
        ("ATACADAO", 0.92), ("ATAcadão", 0.92),
    ]},
    {"name": "Extra", "default_category_name": "Supermercado", "aliases": [
        ("EXTRA", 0.92), ("EXTRA HIPERMERCADO", 0.95), ("EXTRA COMPRE BEM", 0.95),
    ]},
    {"name": "Assaí Atacadista", "default_category_name": "Supermercado", "aliases": [
        ("ASSAI", 0.98), ("ASSAI ATACADISTA", 0.95),
    ]},
    {"name": "Sam's Club", "default_category_name": "Supermercado", "aliases": [
        ("SAMS CLUB", 0.98), ("SAMS", 0.90), ("SAM S CLUB", 0.95),
    ]},
    {"name": "Gransol", "default_category_name": "Supermercado", "aliases": [
        ("GRANSOL", 0.98), ("GRANSOL SUPERMERCADO", 0.95),
    ]},
    {"name": "Zaffari", "default_category_name": "Supermercado", "aliases": [
        ("ZAFFARI", 0.98), ("BORRACHARIA ZAFFARI", 0.95),
    ]},
    {"name": "Prezunic", "default_category_name": "Supermercado", "aliases": [
        ("PREZUNIC", 0.98),
    ]},
    {"name": "Savegnago", "default_category_name": "Supermercado", "aliases": [
        ("SAVEGNAGO", 0.98), ("HIPERMECADO SAVEGNAGO", 0.95),
    ]},
    {"name": "Stokados", "default_category_name": "Supermercado", "aliases": [
        ("STOKADOS", 0.98),
    ]},
    {"name": "Lobão", "default_category_name": "Supermercado", "aliases": [
        ("LOBAO", 0.98), ("LOBAO SUPERMERCADO", 0.95),
    ]},
    {"name": "Rede Expressa", "default_category_name": "Supermercado", "aliases": [
        ("REDE EXPRESSA", 0.98), ("EXPRESSA", 0.88),
    ]},
    {"name": "Bom Preço", "default_category_name": "Supermercado", "aliases": [
        ("BOM PRECO", 0.92), ("BOM PRECOS", 0.92),
    ]},
    {"name": "Sorveteria", "default_category_name": "Supermercado", "aliases": [
        ("SORVETERIA", 0.88),
    ]},
    {"name": "Frigorífico", "default_category_name": "Supermercado", "aliases": [
        ("FRIGORIFICO", 0.88), ("FRIGORIFICO", 0.88),
    ]},
    {"name": "Mercearia", "default_category_name": "Supermercado", "aliases": [
        ("MERCERIA", 0.88), ("MERCEARIA", 0.88),
    ]},

    # =========================================================================
    # ALIMENTAÇÃO — Restaurante / Fast-food
    # =========================================================================
    {"name": "McDonald's", "default_category_name": "Restaurante", "aliases": [
        ("MCDONALDS", 0.98), ("MC DONALDS", 0.95), ("MCD", 0.88),
        ("MCDONALD*S", 0.90),
    ]},
    {"name": "Burger King", "default_category_name": "Restaurante", "aliases": [
        ("BURGER KING", 0.98), ("BK", 0.85), ("BURGERKING", 0.95),
    ]},
    {"name": "Subway", "default_category_name": "Restaurante", "aliases": [
        ("SUBWAY", 0.98),
    ]},
    {"name": "Bob's", "default_category_name": "Restaurante", "aliases": [
        ("BOBS", 0.95), ("BOB S", 0.92),
    ]},
    {"name": "Habib's", "default_category_name": "Restaurante", "aliases": [
        ("HABIBS", 0.98), ("HABIB S", 0.95),
    ]},
    {"name": "Outback", "default_category_name": "Restaurante", "aliases": [
        ("OUTBACK", 0.98), ("OUTBACK STEAKHOUSE", 0.95),
    ]},
    {"name": "Giraffas", "default_category_name": "Restaurante", "aliases": [
        ("GIRAFFAS", 0.98),
    ]},
    {"name": "China in Box", "default_category_name": "Restaurante", "aliases": [
        ("CHINA IN BOX", 0.98), ("CHINA IN BOX", 0.95),
    ]},
    {"name": "Spoleto", "default_category_name": "Restaurante", "aliases": [
        ("SPOLETO", 0.98),
    ]},
    {"name": "Vivenda do Camarão", "default_category_name": "Restaurante", "aliases": [
        ("VIVENDA DO CAMARAO", 0.98), ("VIVENDA", 0.88),
    ]},
    {"name": "Outback", "default_category_name": "Restaurante", "aliases": [
        ("OUTBACK", 0.98),
    ]},
    {"name": "Divino Fogão", "default_category_name": "Restaurante", "aliases": [
        ("DIVINO FOGAO", 0.98), ("DIVINO FOGAO", 0.95),
    ]},
    {"name": "Coco Bambu", "default_category_name": "Restaurante", "aliases": [
        ("COCO BAMBU", 0.98),
    ]},
    {"name": "Madero", "default_category_name": "Restaurante", "aliases": [
        ("MADERO", 0.98),
    ]},
    {"name": "Fábrica de Hambúrguer", "default_category_name": "Restaurante", "aliases": [
        ("FABRICA DE HAMBURGUER", 0.95), ("FABRICA", 0.80),
    ]},
    {"name": "Restaurante Universitário", "default_category_name": "Restaurante", "aliases": [
        ("RESTAURANTE UNIVERSITARIO", 0.95), ("RU", 0.78),
    ]},
    {"name": "Padaria Real", "default_category_name": "Padaria", "aliases": [
        ("PADARIA REAL", 0.95),
    ]},
    {"name": "Casa do Pão", "default_category_name": "Padaria", "aliases": [
        ("CASA DO PAO", 0.95), ("CASA DO PAO DE QUEIJO", 0.95),
    ]},
    {"name": "Casa Amarela", "default_category_name": "Padaria", "aliases": [
        ("CASA AMARELA", 0.95),
    ]},
    {"name": "Paris", "default_category_name": "Padaria", "aliases": [
        ("PADARIA PARIS", 0.95), ("PARIS", 0.82),
    ]},

    # =========================================================================
    # ALIMENTAÇÃO — Cafeteria
    # =========================================================================
    {"name": "Starbucks", "default_category_name": "Cafeteria", "aliases": [
        ("STARBUCKS", 0.98), ("STARBUCKS COFFEE", 0.95),
    ]},
    {"name": "Café do Ponto", "default_category_name": "Cafeteria", "aliases": [
        ("CAFE DO PONTO", 0.95),
    ]},
    {"name": "Coffee Tea", "default_category_name": "Cafeteria", "aliases": [
        ("COFFEE TEA", 0.95),
    ]},
    {"name": "3 Corações", "default_category_name": "Cafeteria", "aliases": [
        ("3 CORACOES", 0.95), ("TRES CORACOES", 0.95),
    ]},
    {"name": "Nespresso", "default_category_name": "Cafeteria", "aliases": [
        ("NESPRESSO", 0.98),
    ]},

    # =========================================================================
    # ALIMENTAÇÃO — Delivery / Delivery de comida
    # =========================================================================
    {"name": "Rappi", "default_category_name": "Delivery", "aliases": [
        ("RAPPI", 0.98), ("RAP10", 0.95),
    ]},
    {"name": "99Food", "default_category_name": "Delivery", "aliases": [
        ("99FOOD", 0.98), ("99 FOOD", 0.95),
    ]},
    {"name": "Uber Eats", "default_category_name": "Delivery", "aliases": [
        ("UBER EATS", 0.98), ("UBEREATS", 0.95),
    ]},
    {"name": "Pedidos Ya", "default_category_name": "Delivery", "aliases": [
        ("PEDIDOS YA", 0.98), ("PEDIDOSYA", 0.95),
    ]},

    # =========================================================================
    # TRANSPORTE — Aplicativos
    # =========================================================================
    {"name": "Uber", "default_category_name": "Aplicativos", "aliases": [
        ("UBER", 0.98), ("UBER *TRIP", 0.98), ("UBER TRIP", 0.95),
        ("UBER TECNOLOGIA", 0.95), ("UBER DO BRASIL", 0.95),
    ]},
    {"name": "99", "default_category_name": "Aplicativos", "aliases": [
        ("99TAXI", 0.95), ("99 TAXI", 0.95), ("99 POP", 0.95),
        ("99 RECARGAS", 0.88), ("99CONTA", 0.88),
    ]},
    {"name": "inDrive", "default_category_name": "Aplicativos", "aliases": [
        ("INDRIVE", 0.95), ("IN DRIVE", 0.92),
    ]},
    {"name": "Cabify", "default_category_name": "Aplicativos", "aliases": [
        ("CABIFY", 0.98),
    ]},
    {"name": "DiDi", "default_category_name": "Aplicativos", "aliases": [
        ("DIDI", 0.92), ("DIDI CHUXING", 0.95),
    ]},
    {"name": "BlaBlaCar", "default_category_name": "Aplicativos", "aliases": [
        ("BLABLACAR", 0.98), ("BLA BLA CAR", 0.95),
    ]},

    # =========================================================================
    # TRANSPORTE — Combustível
    # =========================================================================
    {"name": "Shell", "default_category_name": "Combustível", "aliases": [
        ("SHELL", 0.98), ("SHELL BRASIL", 0.95), ("SHELL V-POWER", 0.95),
    ]},
    {"name": "Ipiranga", "default_category_name": "Combustível", "aliases": [
        ("IPIRANGA", 0.98),
    ]},
    {"name": "Raízen", "default_category_name": "Combustível", "aliases": [
        ("RAIZEN", 0.98),
    ]},
    {"name": "Petrobras", "default_category_name": "Combustível", "aliases": [
        ("PETROBRAS", 0.95), ("BR", 0.82), ("POSTO BR", 0.90),
    ]},
    {"name": "Texaco", "default_category_name": "Combustível", "aliases": [
        ("TEXACO", 0.98),
    ]},
    {"name": "Ale", "default_category_name": "Combustível", "aliases": [
        ("ALE", 0.85), ("ALE COMBUSTIVEIS", 0.92),
    ]},
    {"name": "Rede Bandeirantes", "default_category_name": "Combustível", "aliases": [
        ("REDE BANDEIRANTES", 0.95),
    ]},
    {"name": "Mobil", "default_category_name": "Combustível", "aliases": [
        ("MOBIL", 0.95), ("MOBIL LUBRIFICANTES", 0.92),
    ]},
    {"name": "Lubrax", "default_category_name": "Combustível", "aliases": [
        ("LUBRAX", 0.95),
    ]},
    {"name": "Ultrapar", "default_category_name": "Combustível", "aliases": [
        ("ULTRAPAR", 0.95), ("ULTRAPAR COMBUSTIVEIS", 0.92),
    ]},

    # =========================================================================
    # TRANSPORTE — Transporte público
    # =========================================================================
    {"name": "Metrô", "default_category_name": "Transporte público", "aliases": [
        ("METRO", 0.95), ("METROPOLITANO", 0.95), ("METRO SP", 0.95),
    ]},
    {"name": "CPTM", "default_category_name": "Transporte público", "aliases": [
        ("CPTM", 0.98),
    ]},
    {"name": "Bilhete Único", "default_category_name": "Transporte público", "aliases": [
        ("BILHETE UNICO", 0.98),
    ]},
    {"name": "MOB", "default_category_name": "Transporte público", "aliases": [
        ("MOB", 0.88),
    ]},
    {"name": "Ônibus Municipal", "default_category_name": "Transporte público", "aliases": [
        ("ONIBUS", 0.88), ("TRANSPORTE MUNICIPAL", 0.88),
    ]},

    # =========================================================================
    # TRANSPORTE — Pedágio
    # =========================================================================
    {"name": "Sem Parar", "default_category_name": "Pedágio", "aliases": [
        ("SEM PARAR", 0.98), ("SEMPARAR", 0.95),
    ]},
    {"name": "Via Quatro", "default_category_name": "Pedágio", "aliases": [
        ("VIA QUATRO", 0.95), ("VIAQUATRO", 0.92),
    ]},
    {"name": "Via Brasil", "default_category_name": "Pedágio", "aliases": [
        ("VIA BRASIL", 0.92),
    ]},
    {"name": "Renovias", "default_category_name": "Pedágio", "aliases": [
        ("RENOVIAS", 0.95),
    ]},

    # =========================================================================
    # TRANSPORTE — Estacionamento
    # =========================================================================
    {"name": "Zona Azul", "default_category_name": "Estacionamento", "aliases": [
        ("ZONA AZUL", 0.95),
    ]},
    {"name": "Estapar", "default_category_name": "Estacionamento", "aliases": [
        ("ESTAPAR", 0.95),
    ]},
    {"name": "Guinchos Etc", "default_category_name": "Estacionamento", "aliases": [
        ("GUINCHOS ETC", 0.95),
    ]},
    {"name": "Conscar", "default_category_name": "Estacionamento", "aliases": [
        ("CONSCAR", 0.95),
    ]},

    # =========================================================================
    # MORADIA — Energia elétrica
    # =========================================================================
    {"name": "Enel", "default_category_name": "Energia elétrica", "aliases": [
        ("ENEL", 0.98), ("ENEL DISTRIBUICAO", 0.95),
    ]},
    {"name": "CPFL", "default_category_name": "Energia elétrica", "aliases": [
        ("CPFL", 0.98), ("CPFL ENERGIA", 0.95),
    ]},
    {"name": "Eletropaulo", "default_category_name": "Energia elétrica", "aliases": [
        ("ELETROPAULO", 0.98),
    ]},
    {"name": "Celesc", "default_category_name": "Energia elétrica", "aliases": [
        ("CELESC", 0.98),
    ]},
    {"name": "Celpa", "default_category_name": "Energia elétrica", "aliases": [
        ("CELPA", 0.98),
    ]},
    {"name": "Cosern", "default_category_name": "Energia elétrica", "aliases": [
        ("COSERN", 0.98),
    ]},
    {"name": "Ampla", "default_category_name": "Energia elétrica", "aliases": [
        ("AMPLA", 0.92),
    ]},
    {"name": "Elektro", "default_category_name": "Energia elétrica", "aliases": [
        ("ELEKTRO", 0.95), ("ELEKTRO ENERGIA", 0.92),
    ]},
    {"name": "Companhia Elétrica", "default_category_name": "Energia elétrica", "aliases": [
        ("COMPANHIA ELETRICA", 0.95), ("COMPANHIA ELETRICA CONTA LUZ", 0.95),
    ]},

    # =========================================================================
    # MORADIA — Água e esgoto
    # =========================================================================
    {"name": "Sabesp", "default_category_name": "Água e esgoto", "aliases": [
        ("SABESP", 0.98),
    ]},
    {"name": "Copasa", "default_category_name": "Água e esgoto", "aliases": [
        ("COPASA", 0.98),
    ]},
    {"name": "CEDAE", "default_category_name": "Água e esgoto", "aliases": [
        ("CEDAE", 0.98),
    ]},
    {"name": "Sanepar", "default_category_name": "Água e esgoto", "aliases": [
        ("SANEPAR", 0.98),
    ]},
    {"name": "CAESA", "default_category_name": "Água e esgoto", "aliases": [
        ("CAESA", 0.95),
    ]},
    {"name": "AMESA", "default_category_name": "Água e esgoto", "aliases": [
        ("AMESA", 0.95),
    ]},

    # =========================================================================
    # MORADIA — Internet / Telefone
    # =========================================================================
    {"name": "Vivo", "default_category_name": "Internet", "aliases": [
        ("VIVO", 0.92), ("VIVO FIBRA", 0.95), ("VIVO TELECOM", 0.95),
    ]},
    {"name": "Claro", "default_category_name": "Internet", "aliases": [
        ("CLARO", 0.90), ("CLARO TELECOM", 0.95), ("CLARO S.A.", 0.95),
    ]},
    {"name": "Tim", "default_category_name": "Internet", "aliases": [
        ("TIM", 0.85), ("TIM BRASIL", 0.95), ("TIM SA", 0.95),
    ]},
    {"name": "Oi", "default_category_name": "Internet", "aliases": [
        ("OI", 0.80), ("OI VELOX", 0.92), ("OI S.A.", 0.92),
    ]},
    {"name": "NET", "default_category_name": "Internet", "aliases": [
        ("NET", 0.82), ("NET CLARO", 0.95), ("NET SERVICOS", 0.95),
    ]},
    {"name": "Oi Fibra", "default_category_name": "Internet", "aliases": [
        ("OI FIBRA", 0.95),
    ]},
    {"name": "Starlink", "default_category_name": "Internet", "aliases": [
        ("STARLINK", 0.98),
    ]},
    {"name": "Wondernet", "default_category_name": "Internet", "aliases": [
        ("WONDERNET", 0.95),
    ]},
    {"name": "Flash Net", "default_category_name": "Internet", "aliases": [
        ("FLASH NET", 0.95), ("FLASHNET", 0.92),
    ]},
    {"name": "TOTVS", "default_category_name": "Internet", "aliases": [
        ("TOTVS", 0.88),
    ]},
    {"name": "Brasilnet", "default_category_name": "Internet", "aliases": [
        ("BRASILNET", 0.95),
    ]},
    {"name": "Algar Telecom", "default_category_name": "Internet", "aliases": [
        ("ALGAR TELECOM", 0.95),
    ]},
    {"name": "Provedor Telecom", "default_category_name": "Internet", "aliases": [
        ("PROVEDOR TELECOM", 0.95), ("PROVEDOR TELECOM INTERNET FIBRA", 0.95),
    ]},

    # =========================================================================
    # MORADIA — Gás
    # =========================================================================
    {"name": "Liquigás", "default_category_name": "Gás", "aliases": [
        ("LIQUIGAS", 0.98),
    ]},
    {"name": "Ultragaz", "default_category_name": "Gás", "aliases": [
        ("ULTRAGAZ", 0.98),
    ]},
    {"name": "Nacional Gás", "default_category_name": "Gás", "aliases": [
        ("NACIONAL GAS", 0.95),
    ]},
    {"name": "Consigaz", "default_category_name": "Gás", "aliases": [
        ("CONSIGAZ", 0.98),
    ]},
    {"name": "Vivo Gas", "default_category_name": "Gás", "aliases": [
        ("VIVO GAS", 0.95),
    ]},

    # =========================================================================
    # SAÚDE — Farmácia
    # =========================================================================
    {"name": "Droga Raia", "default_category_name": "Farmácia", "aliases": [
        ("DROGA RAIA", 0.98), ("DROGARAIA", 0.95),
    ]},
    {"name": "Drogasil", "default_category_name": "Farmácia", "aliases": [
        ("DROGASIL", 0.98), ("DROGA SIL", 0.92),
    ]},
    {"name": "Droga Brasil", "default_category_name": "Farmácia", "aliases": [
        ("DROGA BRASIL", 0.95),
    ]},
    {"name": "Pacheco", "default_category_name": "Farmácia", "aliases": [
        ("PACHECO", 0.98),
    ]},
    {"name": "Ultrafarma", "default_category_name": "Farmácia", "aliases": [
        ("ULTRAFARMA", 0.98),
    ]},
    {"name": "Farmácia Sempre", "default_category_name": "Farmácia", "aliases": [
        ("FARMACIA SEMPRE", 0.95),
    ]},
    {"name": "Clique Farma", "default_category_name": "Farmácia", "aliases": [
        ("CLIQUE FARMA", 0.95),
    ]},
    {"name": "Drogaria São Paulo", "default_category_name": "Farmácia", "aliases": [
        ("DROGARIA SAO PAULO", 0.95),
    ]},
    {"name": "Drogaria Venancio", "default_category_name": "Farmácia", "aliases": [
        ("DROGARIA VENANCIO", 0.95),
    ]},
    {"name": "Farmais", "default_category_name": "Farmácia", "aliases": [
        ("FARMAIS", 0.95),
    ]},
    {"name": "Fachini", "default_category_name": "Farmácia", "aliases": [
        ("FACHINI", 0.95),
    ]},
    {"name": "Farmácias É Reais", "default_category_name": "Farmácia", "aliases": [
        ("FARMACIAS E REAIS", 0.95),
    ]},
    {"name": "Santé", "default_category_name": "Farmácia", "aliases": [
        ("SANTE", 0.95),
    ]},
    {"name": "Drogafacil", "default_category_name": "Farmácia", "aliases": [
        ("DROGAFACIL", 0.95),
    ]},

    # =========================================================================
    # SAÚDE — Plano de saúde
    # =========================================================================
    {"name": "Unimed", "default_category_name": "Plano de saúde", "aliases": [
        ("UNIMED", 0.98),
    ]},
    {"name": "Amil", "default_category_name": "Plano de saúde", "aliases": [
        ("AMIL", 0.98), ("AMIL SA", 0.95),
    ]},
    {"name": "SulAmérica", "default_category_name": "Plano de saúde", "aliases": [
        ("SULAMERICA", 0.98), ("SUL AMERICA", 0.95),
    ]},
    {"name": "São Francisco", "default_category_name": "Plano de saúde", "aliases": [
        ("SAO FRANCISCO", 0.92),
    ]},
    {"name": "NotreDame Intermédica", "default_category_name": "Plano de saúde", "aliases": [
        ("NOTREDAME INTERMEDICA", 0.95), ("NOTRE DAME", 0.92),
    ]},
    {"name": "Bradesco Saúde", "default_category_name": "Plano de saúde", "aliases": [
        ("BRADESCO SAUDE", 0.95), ("BRADESCO SAUDE LTDA", 0.92),
    ]},
    {"name": "Omint", "default_category_name": "Plano de saúde", "aliases": [
        ("OMINT", 0.98),
    ]},
    {"name": "Medial", "default_category_name": "Plano de saúde", "aliases": [
        ("MEDIAL", 0.95),
    ]},
    {"name": "Capesaúde", "default_category_name": "Plano de saúde", "aliases": [
        ("CAPESAUDE", 0.95),
    ]},

    # =========================================================================
    # SAÚDE — Consultas / Exames
    # =========================================================================
    {"name": "Laboratório Fleury", "default_category_name": "Exames", "aliases": [
        ("FLEURY", 0.95),
    ]},
    {"name": "DASA", "default_category_name": "Exames", "aliases": [
        ("DASA", 0.92), ("DASA DIAGNOSTICOS", 0.95),
    ]},
    {"name": "Hcor", "default_category_name": "Exames", "aliases": [
        ("HCOR", 0.95),
    ]},
    {"name": "Fleury", "default_category_name": "Exames", "aliases": [
        ("FLEURY", 0.95),
    ]},
    {"name": "Dr. Consulta", "default_category_name": "Consultas", "aliases": [
        ("DR CONSULTA", 0.95),
    ]},
    {"name": "Doctoralia", "default_category_name": "Consultas", "aliases": [
        ("DOCTORALIA", 0.95),
    ]},

    # =========================================================================
    # SAÚDE — Academia
    # =========================================================================
    {"name": "Smart Fit", "default_category_name": "Academia", "aliases": [
        ("SMART FIT", 0.98), ("SMARTFIT", 0.95),
    ]},
    {"name": "Bio Ritmo", "default_category_name": "Academia", "aliases": [
        ("BIO RITMO", 0.98), ("BIORITMO", 0.95),
    ]},
    {"name": "Bluefit", "default_category_name": "Academia", "aliases": [
        ("BLUEFIT", 0.98),
    ]},
    {"name": "Bodytech", "default_category_name": "Academia", "aliases": [
        ("BODYTECH", 0.98),
    ]},
    {"name": "Total Pass", "default_category_name": "Academia", "aliases": [
        ("TOTAL PASS", 0.95),
    ]},
    {"name": "Gym Pass", "default_category_name": "Academia", "aliases": [
        ("GYM PASS", 0.95), ("GYMPASS", 0.95),
    ]},
    {"name": "Selfit", "default_category_name": "Academia", "aliases": [
        ("SELFIT", 0.95),
    ]},
    {"name": "Óculos", "default_category_name": "Academia", "aliases": [
        ("OCULOS", 0.85),
    ]},
    {"name": "Academia", "default_category_name": "Academia", "aliases": [
        ("ACADEMIA", 0.88),
    ]},

    # =========================================================================
    # SAÚDE — Dentista
    # =========================================================================
    {"name": "Odontoprev", "default_category_name": "Dentista", "aliases": [
        ("ODONTOPREV", 0.98),
    ]},
    {"name": "Clínica Sorriso", "default_category_name": "Dentista", "aliases": [
        ("CLINICA SORRISO", 0.95),
    ]},
    {"name": "Dental", "default_category_name": "Dentista", "aliases": [
        ("DENTAL", 0.85),
    ]},
    {"name": "Ortodont", "default_category_name": "Dentista", "aliases": [
        ("ORTODONT", 0.88),
    ]},

    # =========================================================================
    # SAÚDE — Terapias
    # =========================================================================
    {"name": "Psicologia", "default_category_name": "Terapias", "aliases": [
        ("PSICOLOGIA", 0.88), ("PSICOTERAPIA", 0.88),
    ]},
    {"name": "Fisioterapia", "default_category_name": "Terapias", "aliases": [
        ("FISIOTERAPIA", 0.92),
    ]},
    {"name": "Nutricionista", "default_category_name": "Terapias", "aliases": [
        ("NUTRICIONISTA", 0.92),
    ]},

    # =========================================================================
    # COMPRAS PESSOAIS — Vestuário
    # =========================================================================
    {"name": "Renner", "default_category_name": "Vestuário", "aliases": [
        ("RENNER", 0.98),
    ]},
    {"name": "C&A", "default_category_name": "Vestuário", "aliases": [
        ("CEA", 0.95), ("C E A", 0.92), ("C&A", 0.95),
    ]},
    {"name": "Marisa", "default_category_name": "Vestuário", "aliases": [
        ("MARISA", 0.92),
    ]},
    {"name": "Riachuelo", "default_category_name": "Vestuário", "aliases": [
        ("RIACHUELO", 0.98),
    ]},
    {"name": "Zara", "default_category_name": "Vestuário", "aliases": [
        ("ZARA", 0.95), ("ZARA HOME", 0.95),
    ]},
    {"name": "H&M", "default_category_name": "Vestuário", "aliases": [
        ("H M", 0.92), ("H AND M", 0.92),
    ]},
    {"name": "Nike", "default_category_name": "Vestuário", "aliases": [
        ("NIKE", 0.98), ("NIKE BRASIL", 0.95),
    ]},
    {"name": "Adidas", "default_category_name": "Vestuário", "aliases": [
        ("ADIDAS", 0.98),
    ]},
    {"name": "Puma", "default_category_name": "Vestuário", "aliases": [
        ("PUMA", 0.95),
    ]},
    {"name": "Calçados Dassin", "default_category_name": "Vestuário", "aliases": [
        ("DASSIN", 0.95),
    ]},
    {"name": "Osklen", "default_category_name": "Vestuário", "aliases": [
        ("OSKLEN", 0.95),
    ]},
    {"name": "Farm", "default_category_name": "Vestuário", "aliases": [
        ("FARM", 0.82),
    ]},
    {"name": "Lacoste", "default_category_name": "Vestuário", "aliases": [
        ("LACOSTE", 0.95),
    ]},
    {"name": "Colcci", "default_category_name": "Vestuário", "aliases": [
        ("COLCCI", 0.95),
    ]},
    {"name": "Forum", "default_category_name": "Vestuário", "aliases": [
        ("FORUM", 0.82),
    ]},
    {"name": "Le Lis Blanc", "default_category_name": "Vestuário", "aliases": [
        ("LE LIS BLANC", 0.95),
    ]},
    {"name": "Arezzo", "default_category_name": "Calçados", "aliases": [
        ("AREZZO", 0.98),
    ]},
    {"name": "Schutz", "default_category_name": "Calçados", "aliases": [
        ("SCHUTZ", 0.95),
    ]},
    {"name": "Vans", "default_category_name": "Calçados", "aliases": [
        ("VANS", 0.95),
    ]},
    {"name": "Converse", "default_category_name": "Calçados", "aliases": [
        ("CONVERSE", 0.98),
    ]},
    {"name": "Dafiti", "default_category_name": "Vestuário", "aliases": [
        ("DAFITI", 0.95),
    ]},
    {"name": "Netshoes", "default_category_name": "Vestuário", "aliases": [
        ("NETSHOES", 0.95),
    ]},
    {"name": "Centauro", "default_category_name": "Vestuário", "aliases": [
        ("CENTAURO", 0.95),
    ]},
    {"name": "Roupas", "default_category_name": "Vestuário", "aliases": [
        ("ROUPAS", 0.80),
    ]},

    # =========================================================================
    # COMPRAS PESSOAIS — Beleza e cuidados
    # =========================================================================
    {"name": "Natura", "default_category_name": "Beleza e cuidados", "aliases": [
        ("NATURA", 0.92),
    ]},
    {"name": "O Boticário", "default_category_name": "Beleza e cuidados", "aliases": [
        ("O BOTICARIO", 0.98), ("BOTICARIO", 0.95),
    ]},
    {"name": "Avon", "default_category_name": "Beleza e cuidados", "aliases": [
        ("AVON", 0.95),
    ]},
    {"name": "Riachuelo Beleza", "default_category_name": "Beleza e cuidados", "aliases": [
        ("RIACHUELO BELEZA", 0.95),
    ]},
    {"name": "Droga Raia Beleza", "default_category_name": "Beleza e cuidados", "aliases": [
        ("DROGA RAIA BELEZA", 0.95),
    ]},
    {"name": "Renner Beauty", "default_category_name": "Beleza e cuidados", "aliases": [
        ("RENNER BEAUTY", 0.95),
    ]},
    {"name": "Sephora", "default_category_name": "Beleza e cuidados", "aliases": [
        ("SEPHORA", 0.98),
    ]},
    {"name": "Rouge", "default_category_name": "Beleza e cuidados", "aliases": [
        ("ROUGE", 0.85),
    ]},
    {"name": "Barbearia", "default_category_name": "Beleza e cuidados", "aliases": [
        ("BARBEARIA", 0.88),
    ]},
    {"name": "Salão de beleza", "default_category_name": "Beleza e cuidados", "aliases": [
        ("SALAO DE BELEZA", 0.88), ("SALAO", 0.80),
    ]},

    # =========================================================================
    # CASA — Eletrodomésticos / Móveis
    # =========================================================================
    {"name": "Casas Bahia", "default_category_name": "Eletrodomésticos", "aliases": [
        ("CASAS BAHIA", 0.98), ("CASASBAHIA", 0.95),
    ]},
    {"name": "Magazine Luiza", "default_category_name": "Eletrodomésticos", "aliases": [
        ("MAGAZINE LUIZA", 0.98), ("MAGALU", 0.92), ("MAGAZ LUIZA", 0.95),
    ]},
    {"name": "Ponto", "default_category_name": "Eletrodomésticos", "aliases": [
        ("PONTO", 0.82), ("PONTO FRIO", 0.92),
    ]},
    {"name": "Americanas", "default_category_name": "Eletrodomésticos", "aliases": [
        ("AMERICANAS", 0.92),
    ]},
    {"name": "Leroy Merlin", "default_category_name": "Decoração", "aliases": [
        ("LEROY MERLIN", 0.98),
    ]},
    {"name": "C&C", "default_category_name": "Eletrodomésticos", "aliases": [
        ("C&C", 0.88),
    ]},
    {"name": "Tok&Stok", "default_category_name": "Decoração", "aliases": [
        ("TOK STOK", 0.95),
    ]},
    {"name": "Livraria Cultura", "default_category_name": "Eletrodomésticos", "aliases": [
        ("LIVRARIA CULTURA", 0.95),
    ]},
    {"name": "Wall Mart", "default_category_name": "Eletrodomésticos", "aliases": [
        ("WALL MART", 0.92),
    ]},
    {"name": "Loja de Móveis", "default_category_name": "Eletrodomésticos", "aliases": [
        ("MOVEIS", 0.80), ("LOJA DE MOVEIS", 0.85),
    ]},
    {"name": "Eletro Shopping", "default_category_name": "Eletrodomésticos", "aliases": [
        ("ELETRO SHOPPING", 0.95),
    ]},
    {"name": "Lojas Colombo", "default_category_name": "Eletrodomésticos", "aliases": [
        ("LOJAS COLOMBO", 0.95),
    ]},
    {"name": "Lenoxx", "default_category_name": "Eletrodomésticos", "aliases": [
        ("LENOXX", 0.95),
    ]},
    {"name": "Fast Shop", "default_category_name": "Eletrodomésticos", "aliases": [
        ("FAST SHOP", 0.95),
    ]},

    # =========================================================================
    # CASA — Limpeza
    # =========================================================================
    {"name": "Limpeza", "default_category_name": "Limpeza", "aliases": [
        ("LIMPEZA", 0.80),
    ]},

    # =========================================================================
    # TECNOLOGIA — Celular / Software
    # =========================================================================
    {"name": "Apple", "default_category_name": "Software", "aliases": [
        ("APPLE", 0.92), ("APPLE.COM", 0.98), ("APPLE STORE", 0.95),
        ("APPLE.COM/BILL", 0.98),
    ]},
    {"name": "Samsung", "default_category_name": "Acessórios", "aliases": [
        ("SAMSUNG", 0.95), ("SAMSUNG STORE", 0.95),
    ]},
    {"name": "Microsoft", "default_category_name": "Software", "aliases": [
        ("MICROSOFT", 0.95), ("MICROSOFT STORE", 0.98),
    ]},
    {"name": "Google", "default_category_name": "Software", "aliases": [
        ("GOOGLE", 0.92), ("GOOGLE STORE", 0.95),
    ]},
    {"name": "Adobe", "default_category_name": "Software", "aliases": [
        ("ADOBE", 0.98),
    ]},
    {"name": "Zoom", "default_category_name": "Software", "aliases": [
        ("ZOOM", 0.92),
    ]},
    {"name": "Slack", "default_category_name": "Software", "aliases": [
        ("SLACK", 0.95),
    ]},
    {"name": "GitHub", "default_category_name": "Software", "aliases": [
        ("GITHUB", 0.98),
    ]},
    {"name": "Dropbox", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("DROPBOX", 0.98),
    ]},
    {"name": "Google Drive", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("GOOGLE DRIVE", 0.95),
    ]},
    {"name": "iCloud", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("ICLOUD", 0.98),
    ]},
    {"name": "Notion", "default_category_name": "Software", "aliases": [
        ("NOTION", 0.95),
    ]},
    {"name": "Canva", "default_category_name": "Software", "aliases": [
        ("CANVA", 0.98),
    ]},
    {"name": "Figma", "default_category_name": "Software", "aliases": [
        ("FIGMA", 0.98),
    ]},
    {"name": "1Password", "default_category_name": "Software", "aliases": [
        ("1PASSWORD", 0.98),
    ]},

    # =========================================================================
    # ENTRETENIMENTO — Streaming de vídeo
    # =========================================================================
    {"name": "Netflix", "default_category_name": "Streaming de vídeo", "aliases": [
        ("NETFLIX", 0.98), ("NETFLIX.COM", 0.98),
    ]},
    {"name": "Disney+", "default_category_name": "Streaming de vídeo", "aliases": [
        ("DISNEY", 0.95), ("DISNEY PLUS", 0.95), ("DISNEY+", 0.95),
    ]},
    {"name": "Amazon Prime Video", "default_category_name": "Streaming de vídeo", "aliases": [
        ("AMAZON PRIME", 0.95), ("PRIME VIDEO", 0.95), ("PRIME VIDEO AMZN", 0.95),
    ]},
    {"name": "HBO Max", "default_category_name": "Streaming de vídeo", "aliases": [
        ("HBO", 0.92), ("HBO MAX", 0.95),
    ]},
    {"name": "Globoplay", "default_category_name": "Streaming de vídeo", "aliases": [
        ("GLOBOPLAY", 0.98),
    ]},
    {"name": "Paramount+", "default_category_name": "Streaming de vídeo", "aliases": [
        ("PARAMOUNT", 0.95), ("PARAMOUNT PLUS", 0.95),
    ]},
    {"name": "Apple TV+", "default_category_name": "Streaming de vídeo", "aliases": [
        ("APPLE TV", 0.95),
    ]},
    {"name": "YouTube Premium", "default_category_name": "Streaming de vídeo", "aliases": [
        ("YOUTUBE", 0.90), ("YOUTUBE PREMIUM", 0.95),
    ]},
    {"name": "UOL Play", "default_category_name": "Streaming de vídeo", "aliases": [
        ("UOL PLAY", 0.95),
    ]},

    # =========================================================================
    # ENTRETENIMENTO — Streaming de música
    # =========================================================================
    {"name": "Spotify", "default_category_name": "Streaming de música", "aliases": [
        ("SPOTIFY", 0.98),
    ]},
    {"name": "Apple Music", "default_category_name": "Streaming de música", "aliases": [
        ("APPLE MUSIC", 0.95),
    ]},
    {"name": "Deezer", "default_category_name": "Streaming de música", "aliases": [
        ("DEEZER", 0.98),
    ]},
    {"name": "YouTube Music", "default_category_name": "Streaming de música", "aliases": [
        ("YOUTUBE MUSIC", 0.95),
    ]},
    {"name": "Tidal", "default_category_name": "Streaming de música", "aliases": [
        ("TIDAL", 0.95),
    ]},

    # =========================================================================
    # ENTRETENIMENTO — Jogos
    # =========================================================================
    {"name": "Steam", "default_category_name": "Jogos", "aliases": [
        ("STEAM", 0.95), ("STEAMGAMES", 0.95),
    ]},
    {"name": "PlayStation Store", "default_category_name": "Jogos", "aliases": [
        ("PLAYSTATION", 0.95), ("PS STORE", 0.95),
    ]},
    {"name": "Xbox Game Pass", "default_category_name": "Jogos", "aliases": [
        ("XBOX", 0.95), ("XBOX GAME PASS", 0.95),
    ]},
    {"name": "Nintendo", "default_category_name": "Jogos", "aliases": [
        ("NINTENDO", 0.95),
    ]},
    {"name": "Epic Games", "default_category_name": "Jogos", "aliases": [
        ("EPIC GAMES", 0.98),
    ]},
    {"name": "Riot Games", "default_category_name": "Jogos", "aliases": [
        ("RIOT GAMES", 0.95),
    ]},

    # =========================================================================
    # ENTRETENIMENTO — Cinema
    # =========================================================================
    {"name": "Cinemark", "default_category_name": "Cinema", "aliases": [
        ("CINEMARK", 0.98),
    ]},
    {"name": "Cinépolis", "default_category_name": "Cinema", "aliases": [
        ("CINEPOLIS", 0.98),
    ]},
    {"name": "Kinoplex", "default_category_name": "Cinema", "aliases": [
        ("KINOPLEX", 0.98),
    ]},
    {"name": "Cinema Severiano Ribeiro", "default_category_name": "Cinema", "aliases": [
        ("CINEMA SEVERIANO", 0.95), ("CINEMA SEVERIANO RIBEIRO", 0.95),
    ]},

    # =========================================================================
    # ASSINATURAS — Software / Serviços
    # =========================================================================
    {"name": "Alura", "default_category_name": "Educação", "aliases": [
        ("ALURA", 0.98),
    ]},
    {"name": "Udemy", "default_category_name": "Educação", "aliases": [
        ("UDEMY", 0.98),
    ]},
    {"name": "Coursera", "default_category_name": "Educação", "aliases": [
        ("COURSERA", 0.98),
    ]},
    {"name": "Descomplica", "default_category_name": "Educação", "aliases": [
        ("DESCOMPLICA", 0.98),
    ]},
    {"name": "Domestika", "default_category_name": "Educação", "aliases": [
        ("DOMESTIKA", 0.98),
    ]},
    {"name": "Platzi", "default_category_name": "Educação", "aliases": [
        ("PLATZI", 0.98),
    ]},
    {"name": "YouTube", "default_category_name": "Streaming de vídeo", "aliases": [
        ("YOUTUBE", 0.88),
    ]},
    {"name": "ChatGPT", "default_category_name": "Software", "aliases": [
        ("CHATGPT", 0.98), ("OPENAI", 0.95),
    ]},
    {"name": "Midjourney", "default_category_name": "Software", "aliases": [
        ("MIDJOURNEY", 0.98),
    ]},
    {"name": "Notion", "default_category_name": "Software", "aliases": [
        ("NOTION LABS", 0.95),
    ]},
    {"name": "Grammarly", "default_category_name": "Software", "aliases": [
        ("GRAMMARLY", 0.98),
    ]},
    {"name": "Vercel", "default_category_name": "Software", "aliases": [
        ("VERCEL", 0.95),
    ]},
    {"name": "DigitalOcean", "default_category_name": "Software", "aliases": [
        ("DIGITALOCEAN", 0.98),
    ]},
    {"name": "AWS", "default_category_name": "Software", "aliases": [
        ("AWS", 0.90), ("AMAZON WEB SERVICES", 0.95),
    ]},
    {"name": "Cloudflare", "default_category_name": "Software", "aliases": [
        ("CLOUDFLARE", 0.98),
    ]},
    {"name": "Heroku", "default_category_name": "Software", "aliases": [
        ("HEROKU", 0.95),
    ]},
    {"name": "Netlify", "default_category_name": "Software", "aliases": [
        ("NETLIFY", 0.95),
    ]},

    # =========================================================================
    # PETS
    # =========================================================================
    {"name": "Petz", "default_category_name": "Pet shop", "aliases": [
        ("PETZ", 0.98), ("PETZ BRASIL", 0.95),
    ]},
    {"name": "Cobasi", "default_category_name": "Pet shop", "aliases": [
        ("COBASI", 0.98),
    ]},
    {"name": "PetLove", "default_category_name": "Pet shop", "aliases": [
        ("PETLOVE", 0.98), ("PET LOVE", 0.95),
    ]},
    {"name": "Cansei de Ser Pet", "default_category_name": "Pet shop", "aliases": [
        ("CSSP", 0.95), ("CANSEI DE SER PET", 0.95),
    ]},
    {"name": "Vet", "default_category_name": "Veterinário", "aliases": [
        ("VETERINARIO", 0.88), ("VETERINARIA", 0.88),
    ]},
    {"name": "Ração", "default_category_name": "Ração", "aliases": [
        ("RACAO", 0.85),
    ]},

    # =========================================================================
    # VIAGENS
    # =========================================================================
    {"name": "Decolar", "default_category_name": "Passagens", "aliases": [
        ("DECOLAR", 0.98),
    ]},
    {"name": "Booking", "default_category_name": "Hospedagem", "aliases": [
        ("BOOKING", 0.95), ("BOOKING.COM", 0.98),
    ]},
    {"name": "Airbnb", "default_category_name": "Hospedagem", "aliases": [
        ("AIRBNB", 0.98),
    ]},
    {"name": "CVC", "default_category_name": "Passagens", "aliases": [
        ("CVC", 0.92), ("CVC BRASIL", 0.95),
    ]},
    {"name": "LATAM", "default_category_name": "Passagens", "aliases": [
        ("LATAM", 0.95), ("LATAM AIRLINES", 0.95),
    ]},
    {"name": "GOL", "default_category_name": "Passagens", "aliases": [
        ("GOL", 0.88), ("GOL LINHAS AEREAS", 0.95),
    ]},
    {"name": "Azul", "default_category_name": "Passagens", "aliases": [
        ("AZUL", 0.85), ("AZUL LINHAS AEREAS", 0.95),
    ]},
    {"name": "MaxMilhas", "default_category_name": "Passagens", "aliases": [
        ("MAXMILHAS", 0.98),
    ]},
    {"name": "123milhas", "default_category_name": "Passagens", "aliases": [
        ("123MILHAS", 0.98),
    ]},
    {"name": "Hurb", "default_category_name": "Hospedagem", "aliases": [
        ("HURB", 0.98),
    ]},
    {"name": "TripAdvisor", "default_category_name": "Hospedagem", "aliases": [
        ("TRIPADVISOR", 0.98),
    ]},
    {"name": "Trivago", "default_category_name": "Hospedagem", "aliases": [
        ("TRIVAGO", 0.98),
    ]},

    # =========================================================================
    # E-COMMERCE
    # =========================================================================
    {"name": "Mercado Livre", "default_category_name": "Outros", "aliases": [
        ("MERCADO LIVRE", 0.95), ("MERCADOLIVRE", 0.95), ("MERCADO PAGO", 0.92),
        ("MERCADOPAGO", 0.92),
    ]},
    {"name": "Shopee", "default_category_name": "Outros", "aliases": [
        ("SHOPEE", 0.98),
    ]},
    {"name": "AliExpress", "default_category_name": "Outros", "aliases": [
        ("ALIEXPRESS", 0.98),
    ]},
    {"name": "Amazon", "default_category_name": "Outros", "aliases": [
        ("AMAZON", 0.92), ("AMAZON BR", 0.95), ("AMZN", 0.90),
    ]},
    {"name": "OLX", "default_category_name": "Outros", "aliases": [
        ("OLX", 0.95),
    ]},
    {"name": "Kwai", "default_category_name": "Outros", "aliases": [
        ("KWAI", 0.95),
    ]},
    {"name": "Shein", "default_category_name": "Outros", "aliases": [
        ("SHEIN", 0.98),
    ]},
    {"name": "Temu", "default_category_name": "Outros", "aliases": [
        ("TEMU", 0.98),
    ]},
    {"name": "Magazine Luiza", "default_category_name": "Outros", "aliases": [
        ("MAGALU", 0.88),
    ]},
    {"name": "Americanas", "default_category_name": "Outros", "aliases": [
        ("AMERICANAS.COM", 0.95),
    ]},
    {"name": "Submarino", "default_category_name": "Outros", "aliases": [
        ("SUBMARINO", 0.95),
    ]},
    {"name": "Nova Idea", "default_category_name": "Outros", "aliases": [
        ("NOVA IDEA", 0.95),
    ]},
    {"name": "Kabum", "default_category_name": "Outros", "aliases": [
        ("KABUM", 0.98),
    ]},
    {"name": "Terabyte", "default_category_name": "Outros", "aliases": [
        ("TERABYTE", 0.95),
    ]},
    {"name": "Pichau", "default_category_name": "Outros", "aliases": [
        ("PICHAU", 0.95),
    ]},
    {"name": "PCDiga", "default_category_name": "Outros", "aliases": [
        ("PCDIGA", 0.95),
    ]},

    # =========================================================================
    # FINANÇAS — Bancos / Financeiras
    # =========================================================================
    {"name": "Nubank", "default_category_name": "Tarifas bancárias", "aliases": [
        ("NUBANK", 0.95), ("NU PAGAMENTOS", 0.95), ("NUFINANCE", 0.92),
    ]},
    {"name": "Inter", "default_category_name": "Tarifas bancárias", "aliases": [
        ("INTER", 0.88), ("BANCO INTER", 0.95),
    ]},
    {"name": "C6 Bank", "default_category_name": "Tarifas bancárias", "aliases": [
        ("C6 BANK", 0.95), ("C6S*", 0.92),
    ]},
    {"name": "Bradesco", "default_category_name": "Tarifas bancárias", "aliases": [
        ("BRADESCO", 0.95), ("BRADESCO BANCO", 0.95),
    ]},
    {"name": "Itaú", "default_category_name": "Tarifas bancárias", "aliases": [
        ("ITAU", 0.92), ("ITAU UNIBANCO", 0.95), ("ITAUPU", 0.92),
    ]},
    {"name": "Banco do Brasil", "default_category_name": "Tarifas bancárias", "aliases": [
        ("BANCO DO BRASIL", 0.98), ("BB", 0.80),
    ]},
    {"name": "Santander", "default_category_name": "Tarifas bancárias", "aliases": [
        ("SANTANDER", 0.95),
    ]},
    {"name": "Caixa", "default_category_name": "Tarifas bancárias", "aliases": [
        ("CAIXA", 0.88), ("CAIXA ECONOMICA", 0.95),
    ]},
    {"name": "BTG Pactual", "default_category_name": "Tarifas bancárias", "aliases": [
        ("BTG", 0.92), ("BTG PACTUAL", 0.95),
    ]},
    {"name": "XP Investimentos", "default_category_name": "Tarifas bancárias", "aliases": [
        ("XP", 0.88), ("XP INVESTIMENTOS", 0.95),
    ]},
    {"name": "Stone", "default_category_name": "Tarifas bancárias", "aliases": [
        ("STONE", 0.85), ("STONE PAGAMENTOS", 0.92),
    ]},
    {"name": "PagSeguro", "default_category_name": "Tarifas bancárias", "aliases": [
        ("PAGSEGURO", 0.95), ("PAG*SEGURO", 0.92),
    ]},
    {"name": "Mercado Pago", "default_category_name": "Tarifas bancárias", "aliases": [
        ("MERCADOPAGO", 0.92),
    ]},
    {"name": "PicPay", "default_category_name": "Tarifas bancárias", "aliases": [
        ("PICPAY", 0.98),
    ]},
    {"name": "Will Bank", "default_category_name": "Tarifas bancárias", "aliases": [
        ("WILL BANK", 0.95),
    ]},
    {"name": "Rendimento", "default_category_name": "Retorno de aplicações", "aliases": [
        ("RENDA", 0.80),
    ]},

    # =========================================================================
    # IMPOSTOS
    # =========================================================================
    {"name": "Receita Federal", "default_category_name": "Federais", "aliases": [
        ("RECEITA FEDERAL", 0.98), ("PGTO RFB", 0.95),
    ]},
    {"name": "SEFAZ", "default_category_name": "Estaduais", "aliases": [
        ("SEFAZ", 0.95),
    ]},
    {"name": "Prefeitura", "default_category_name": "Municipais", "aliases": [
        ("PREFEITURA", 0.92),
    ]},
    {"name": "Detran", "default_category_name": "Impostos e documentação", "aliases": [
        ("DETRAN", 0.98),
    ]},
    {"name": "IPTU", "default_category_name": "IPTU", "aliases": [
        ("IPTU", 0.98),
    ]},
    {"name": "IPVA", "default_category_name": "IPVA", "aliases": [
        ("IPVA", 0.98),
    ]},

    # =========================================================================
    # RENDIMENTOS / SALÁRIO
    # =========================================================================
    {"name": "Pix Recebido", "default_category_name": "Recebimento de PIX", "aliases": [
        ("PIX RECEBIDO", 0.95), ("PIX CREDITO", 0.95),
    ]},
    {"name": "TED", "default_category_name": "Salário", "aliases": [
        ("TED", 0.85),
    ]},
    {"name": "DOC", "default_category_name": "Salário", "aliases": [
        ("DOC", 0.82),
    ]},
    {"name": "Nubank Recebimento", "default_category_name": "Salário", "aliases": [
        ("NUBANK RECEBIMENTO", 0.92),
    ]},
    {"name": "Transferência Recebida", "default_category_name": "Salário", "aliases": [
        ("TRANSFERENCIA RECEBIDA", 0.92),
    ]},

    # =========================================================================
    # ASSINATURAS / Clubes
    # =========================================================================
    {"name": "Amazon Prime", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("AMZN PRIME", 0.95), ("AMAZON PRIME", 0.95),
    ]},
    {"name": "YouTube Premium", "default_category_name": "Streaming de vídeo", "aliases": [
        ("YOUTUBE.COM", 0.92), ("YT PREMIUM", 0.95),
    ]},
    {"name": "Google One", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("GOOGLE ONE", 0.98),
    ]},
    {"name": "iCloud+", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("ICLOUD", 0.95),
    ]},
    {"name": "Dropbox", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("DROPBOX.COM", 0.98),
    ]},
    {"name": "Evernote", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("EVERNOTE", 0.98),
    ]},
    {"name": "OneDrive", "default_category_name": "Armazenamento em nuvem", "aliases": [
        ("ONEDRIVE", 0.98),
    ]},

    # =========================================================================
    # SEGURANÇA / Seguros
    # =========================================================================
    {"name": "Porto Seguro", "default_category_name": "Automóvel", "aliases": [
        ("PORTO SEGURO", 0.98),
    ]},
    {"name": "Bradesco Seguros", "default_category_name": "Vida", "aliases": [
        ("BRADESCO SEGUROS", 0.95),
    ]},
    {"name": "SulAmérica Seguros", "default_category_name": "Vida", "aliases": [
        ("SULAMERICA SEGUROS", 0.95),
    ]},
    {"name": "Allianz", "default_category_name": "Vida", "aliases": [
        ("ALLIANZ", 0.95),
    ]},
    {"name": "AZUL Seguros", "default_category_name": "Vida", "aliases": [
        ("AZUL SEGUROS", 0.95),
    ]},
    {"name": "Boston", "default_category_name": "Vida", "aliases": [
        ("BOSTON", 0.85),
    ]},

    # =========================================================================
    # TRANSPORTE para o trabalho / Manutenção de veículo
    # =========================================================================
    {"name": "Wash", "default_category_name": "Manutenção", "aliases": [
        ("WASH", 0.85),
    ]},
    {"name": "Autopeças", "default_category_name": "Manutenção", "aliases": [
        ("AUTOPECAS", 0.88), ("AUTO PECAS", 0.88),
    ]},
    {"name": "Oficina", "default_category_name": "Manutenção", "aliases": [
        ("OFICINA", 0.88),
    ]},
    {"name": "Mecânica", "default_category_name": "Manutenção", "aliases": [
        ("MECANICA", 0.88),
    ]},

    # =========================================================================
    # ESTACIONAMENTO (adicional)
    # =========================================================================
    {"name": "Parque Estacionamento", "default_category_name": "Estacionamento", "aliases": [
        ("PARQUE ESTACIONAMENTO", 0.92),
    ]},
    {"name": "Seta Park", "default_category_name": "Estacionamento", "aliases": [
        ("SETA PARK", 0.95),
    ]},
    {"name": "Fast Park", "default_category_name": "Estacionamento", "aliases": [
        ("FAST PARK", 0.95),
    ]},

    # =========================================================================
    # CASA — Utilidades / Ferramentas
    # =========================================================================
    {"name": "Sodexo", "default_category_name": "Utilidades", "aliases": [
        ("SODEXO", 0.95),
    ]},
    {"name": "Alelo", "default_category_name": "Utilidades", "aliases": [
        ("ALELO", 0.92),
    ]},
    {"name": "VR", "default_category_name": "Utilidades", "aliases": [
        ("VR ALIMENTACAO", 0.92),
    ]},
    {"name": "Flash", "default_category_name": "Utilidades", "aliases": [
        ("FLASH", 0.82),
    ]},

    # =========================================================================
    # LIVROS / MÍDIA
    # =========================================================================
    {"name": "Amazon Kindle", "default_category_name": "Livros", "aliases": [
        ("KINDLE", 0.95), ("AMAZON KINDLE", 0.95),
    ]},
    {"name": "Saraiva", "default_category_name": "Livros", "aliases": [
        ("SARAIVA", 0.95),
    ]},
    {"name": "Livraria Leitura", "default_category_name": "Livros", "aliases": [
        ("LIVRARIA LEITURA", 0.95),
    ]},
    {"name": "Livraria Cultura", "default_category_name": "Livros", "aliases": [
        ("CULTURA", 0.82),
    ]},
    {"name": "Publishdrive", "default_category_name": "Livros", "aliases": [
        ("PUBLISHDRIVE", 0.95),
    ]},

    # =========================================================================
    # FESTAS / PRESENTES
    # =========================================================================
    {"name": "Magalu Presentes", "default_category_name": "Presentes", "aliases": [
        ("MAGALU PRESENTES", 0.95),
    ]},
    {"name": "Centauro Presentes", "default_category_name": "Presentes", "aliases": [
        ("CENTAURO PRESENTES", 0.95),
    ]},

    # =========================================================================
    # MANUTENÇÃO RESIDENCIAL
    # =========================================================================
    {"name": "Roux", "default_category_name": "Manutenção residencial", "aliases": [
        ("ROUX", 0.85),
    ]},
    {"name": "Construção Civil", "default_category_name": "Manutenção residencial", "aliases": [
        ("CONSTRUCAO CIVIL", 0.85),
    ]},
    {"name": "Eletricista", "default_category_name": "Manutenção residencial", "aliases": [
        ("ELETRICISTA", 0.85),
    ]},
    {"name": "Hidráulica", "default_category_name": "Manutenção residencial", "aliases": [
        ("HIDRAULICA", 0.85),
    ]},
    {"name": "Pintura", "default_category_name": "Manutenção residencial", "aliases": [
        ("PINTURA", 0.85),
    ]},

    # =========================================================================
    # MOBÍLIA
    # =========================================================================
    {"name": "Tok&Stok", "default_category_name": "Mobília", "aliases": [
        ("TOK STOK", 0.92),
    ]},
    {"name": "Ortobom", "default_category_name": "Mobília", "aliases": [
        ("ORTOBOM", 0.95),
    ]},
    {"name": "Liz", "default_category_name": "Mobília", "aliases": [
        ("LIZ", 0.82),
    ]},
    {"name": "Madesa", "default_category_name": "Mobília", "aliases": [
        ("MADESA", 0.92),
    ]},
    {"name": "Berlanda", "default_category_name": "Mobília", "aliases": [
        ("BERLANDA", 0.92),
    ]},
]


class Command(BaseCommand):
    help = "Semeia o catálogo global de estabelecimentos brasileiros."

    def handle(self, *args, **options):
        created_merchants = 0
        created_aliases = 0
        for item in _CATALOG:
            merchant, m_created = Merchant.objects.get_or_create(
                owner=None,
                name=item["name"],
                defaults={
                    "source": Merchant.Source.CATALOG,
                    "default_category_name": item["default_category_name"],
                    "is_default": True,
                },
            )
            if m_created:
                created_merchants += 1
            for alias, conf in item["aliases"]:
                _, a_created = MerchantAlias.objects.get_or_create(
                    owner=None,
                    alias=alias,
                    defaults={
                        "merchant": merchant,
                        "source": MerchantAlias.Source.CATALOG,
                        "confidence": conf,
                    },
                )
                if a_created:
                    created_aliases += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo expandido: {created_merchants} merchants e "
                f"{created_aliases} aliases criados (idempotente)."
            )
        )
