# CAMS Global Air Quality Historical Database

Projeto Python para consultar, baixar, validar, organizar e analisar dados da reanálise atmosférica CAMS EAC4. O código principal está em [`cams-global-air-quality/`](cams-global-air-quality/).

**Estado atual:** o pipeline e os notebooks foram testados localmente com dados sintéticos. O download autenticado de dados CAMS ainda depende de uma chave da API ADS; os resultados de teste não representam observações ou reanálise real. Consulte o [relatório da primeira fase](cams-global-air-quality/reports/PHASE1_REPORT.md) e a [validação do complemento](VALIDACAO.md).

## Começar

Requer Python 3.11 ou 3.12. Depois de clonar o repositório:

```bash
cd cams/cams-global-air-quality
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,notebooks]'
pytest -q
camsaq --help
```

Para obter dados reais, configure sua própria chave ADS conforme o [guia do pacote](cams-global-air-quality/README.md#autenticação-ads--apenas-na-sua-máquina). A chave deve ficar fora do repositório.

## Documentação

- [Guia completo de uso](GUIA_COMPLETO.md)
- [Teste com um ano](GUIA_TESTE_UM_ANO.md)
- [Documentação técnica, configuração, código e testes](cams-global-air-quality/)
- [Relatório da primeira fase](CAMS_Relatorio_Primeira_Fase.md)

Os dados baixados, bancos locais, logs e arquivos temporários de análise ficam fora do controle de versão. O diretório `reports/` do pacote contém registros de validação e exemplos; interprete cada resultado conforme a proveniência descrita nos relatórios.
