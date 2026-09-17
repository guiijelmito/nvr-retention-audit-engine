import logging

# Credenciais de acesso padrão para os NVRs da rede
USUARIO = "admin"
SENHA = "sua_senha_segura_aqui"

# Mapeamento de unidades escolares e seus respectivos endereços IP para teste
ESCOLAS_TESTE = {
    "E.M. Exemplo 01 (NVR1)": "192.168.1.100",
    "E.M. Exemplo 02 (NVR2)": "192.168.1.101"
}

# Configuração padronizada do logger corporativo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S"
)
logger = logging.getLogger("NVR_Audit_Portfolio")