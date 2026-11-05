EXE = "faturam.exe"
TITULO_APP = r".*Faturamento.*"
# Salux e PowerBuilder (DataWindow): so o backend win32 enxerga a tela
BACKEND = "win32"
CLASSE_ABAS = "PBTabControl32_100"
# Posicao das abas relativa ao controle de abas (x, y)
POS_ABA_ITENS = (22, 13)
POS_ABA_ORIGEM = (132, 13)
# Botao de consulta (informar/executar) na barra de ferramentas FNFIXEDBAR, relativo ao controle (x, y)
POS_BOTAO_CONSULTA = (102, 14)
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

# Portal Salux (login e acesso aos modulos). O faturam.exe e filho do portal.
PORTAL_EXE = r"C:\Salux\Módulos - PRODUÇÃO\Portal\portal.exe"
# Posicoes (x, y) relativas aos DataWindows do portal: menu da esquerda e area dos azulejos
PORTAL_MENU_FATURAMENTO = (95, 106)
PORTAL_TILE_FATURAMENTO = (120, 57)

# Cliente-servidor. Valores PADRAO: o servidor guarda bind/porta/token em servidor_config.json
# (token gerado na primeira execucao) e o cliente em cliente_config.json (tela de configuracao).
SERVIDOR_BIND = "0.0.0.0"          # escuta na rede interna (use 127.0.0.1 para so a propria maquina)
SERVIDOR_HOST = "10.10.10.249"     # endereco padrao que o cliente tenta (IP da maquina do servidor)
SERVIDOR_PORTA = 8765
