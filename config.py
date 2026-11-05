EXE = "faturam.exe"
TITULO_APP = r".*Faturamento.*"
# Salux e PowerBuilder (DataWindow): so o backend win32 enxerga a tela
BACKEND = "win32"
CLASSE_ABAS = "PBTabControl32_100"
# Posicao das abas relativa ao controle de abas (x, y)
POS_ABA_ITENS = (22, 13)
POS_ABA_ORIGEM = (132, 13)
# Coluna CBOS na aba Origem: largura (px) do editor da celula (a grade pode estar rolada)
CBOS_LARGURA = 39

# Pasta dos logs em texto (relativa a esta pasta)
PASTA_LOGS = "logs"

# Avisos do Salux cujo texto tem uma destas palavras sao ERRO CRITICO (parar tudo):
# queda de banco/rede/internet, erro de DataWindow etc. Ajuste conforme novos casos.
PALAVRAS_CRITICAS = (
    "conex", "rede", "internet", "servidor", "banco de dados", "database",
    "sql", "datawindow", "dberror", "timeout", "time-out", "sess", "desconect",
    "falha grave", "erro fatal", "perdida", "perdido",
)
