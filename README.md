# CAMS: dados atmosféricos para estudar e analisar

Este projeto em Python consulta o portal **ADS/Copernicus**, baixa arquivos,
confere sua integridade e gera dados prontos para séries temporais, estatísticas
e mapas. Há dois fluxos independentes:

| Fluxo | O que contém | Situação local |
|---|---|---|
| **EAC4** | PM2.5, PM10, CO, NO₂, SO₂ e O₃; dados mensais ou a cada três horas | Código e testes verificados; a obtenção de dados reais requer uma conta ADS com licença aceita |
| **CAMS73 CH4** | Metano da inversão de gases de efeito estufa; médias diárias em 34 níveis | O arquivo real de setembro de 2024 foi importado, validado, processado e analisado |

Esses produtos têm grades, níveis e unidades diferentes. O programa os mantém
separados. Um valor de uma célula do modelo não é uma medição feita em uma estação
ou na casa de alguém.

## Comece por aqui

O ambiente verificado é Linux com Python **3.11 ou 3.12**. No terminal, a partir
da pasta `cams/` que você clonou ou recebeu, entre na pasta que contém
`pyproject.toml`:

```bash
cd cams-global-air-quality
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,notebooks]'
python -m pytest -q
camsaq --help
```

Se a versão mostrada por `python3 --version` não for 3.11 ou 3.12, use um
executável compatível, como `python3.11`, ao criar o ambiente. Nas próximas
sessões, entre novamente nessa pasta e execute `source .venv/bin/activate`.

### Se você já tem o arquivo de CH4 deste estudo

O arquivo grande em `exemplo_ch4/` é local e não acompanha o clone do GitHub.
Quando ele estiver nessa pasta, execute a partir de `cams-global-air-quality/`:

```bash
camsaq ch4 import --file ../exemplo_ch4/cams73_latest_ch4_conc_first_guess_dm_202409.nc
camsaq ch4 analyze --version v25r1 --level 1 --output reports/ch4_inversion
```

O primeiro comando verifica, arquiva, processa e indexa o arquivo. O segundo
produz séries, mapas e `analysis.json`. **Nível 1** é a camada mais baixa desse
produto, mas não representa uma altura fixa. Veja o [guia de execução](GUIA_COMPLETO.md#24-metano-ch4-passo-a-passo)
e o [relatório do arquivo](cams-global-air-quality/docs/CH4_CAM73.md).

### Se você quer baixar dados pelo ADS

Crie uma conta ADS, aceite os termos do produto desejado e configure seu token
fora do repositório, conforme a [seção de credenciais](GUIA_COMPLETO.md#5-configuração-da-chave-ads).
Planeje **antes** de iniciar pedidos que possam consumir tempo e disco:

```bash
camsaq ch4 plan --start 2024-09 --version v25r1
camsaq inventory --start 2003-01 --end 2003-12
camsaq plan --kind monthly --start 2003-01 --end 2003-12
```

`plan` e `inventory` consultam o catálogo, mas não baixam os campos. A
[primeira execução EAC4](GUIA_COMPLETO.md#7-primeiro-teste-somente-um-ano) e o
[download CH4](GUIA_COMPLETO.md#24-metano-ch4-passo-a-passo) estão descritos no
guia, com opções para retomar e conferir resultados.

## Documentação

- [Guia completo: instalação, execução e interpretação](GUIA_COMPLETO.md)
- [Referência de todas as funções Python](cams-global-air-quality/docs/REFERENCIA_FUNCOES.md)
- [Teste EAC4 com um ano](GUIA_TESTE_UM_ANO.md)
- [Metano CAMS73: origem, conteúdo e pedido ADS](cams-global-air-quality/docs/CH4_CAM73.md)
- [Dicionário dos arquivos e metadados](cams-global-air-quality/docs/DATA_DICTIONARY.md)
- [Validação da primeira fase](VALIDACAO.md)

Originais, derivados, bancos locais, logs e credenciais não entram no Git. Os
testes automatizados usam dados sintéticos; a análise de CH4 mencionada acima
usa o arquivo real disponível neste ambiente.
