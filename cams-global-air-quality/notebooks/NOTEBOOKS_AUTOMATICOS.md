# Notebooks CAMS com descoberta automática de cobertura

Os notebooks **01–03** usam somente partições mensais EAC4, por meio de
`available_data.py`. Os notebooks **04–06** usam somente partições diárias CH4
CAMS73, por meio de `available_ch4.py`. Eles não juntam produtos, não baixam
arquivos e não escrevem nos manifestos.

## Preparar o ambiente

Na raiz de `cams-global-air-quality`, instale o projeto com o extra `notebooks`
descrito no README. Reinicie o kernel se algum notebook já estiver aberto.
Escolha o ambiente Python
em que `cams_air_quality` está instalado e execute todas as células em ordem.
O kernel indicado nos arquivos é `camsaq`:

```bash
python -m ipykernel install --user --name camsaq --display-name 'Python (CAMS Air Quality)'
```

1. `01_inventory.ipynb`: arquivos elegíveis, checksum, meses, lacunas, anos completos.
2. `02_global_climatology.ipynb`: séries espaciais, ciclo mensal, médias anuais,
   referência multianual quando possível, anomalias e mapas automáticos.
3. `03_timeseries_example.ipynb`: ponto mais próximo e recorte regional opcional,
   CSV e metadados, com a cobertura própria de cada variável.
4. `04_ch4_inventory.ipynb`: meses CH4, checksums, níveis, lacunas e anos completos.
5. `05_ch4_timeseries.ipynb`: médias diárias, mensais e anuais, ponto, referência e
   anomalias quando a cobertura permite.
6. `06_ch4_maps.ipynb`: mapas mensais, anuais, do período, referência, anomalias
   e desvio padrão; motivos para omissões em `map_manifest.json`.

## Como os notebooks EAC4 descobrem dados

O manifesto `metadata/downloads.sqlite` é aberto somente para leitura. Selecionam-se
registros EAC4 mensais do mesmo dataset, área e formato da configuração; o arquivo
processado deve existir e seu SHA-256 deve conferir. O timestamp é conferido contra
o mês registrado. Os campos são abertos com xarray/Dask, por variável, sem exigir
que PM2.5 e O3 tenham os mesmos anos. `VARIABLES=None` descobre todas as variáveis
processadas elegíveis, mesmo que o subconjunto ativo de download seja menor.
A configuração continua definindo o escopo geográfico e o produto.

Não se misturam EAC4, EGG4, operacional, níveis diferentes, grades diferentes ou
unidades diferentes. Arquivos órfãos não são incorporados apenas pelo nome.
Arquivos originais ainda não processados aparecem no inventário, mas não entram
nas análises. Rode `camsaq validate` e `camsaq process --kind monthly` para prepará-los.
Nenhum dos notebooks exige `consolidate`; a consolidação Zarr permanece disponível
para os demais comandos do projeto. Bancos contendo somente Zarr, sem as partições
NetCDF e o manifesto correspondentes, precisam restaurar esses componentes antes
 de usar estes notebooks. Caminhos absolutos antigos no manifesto precisam ser
migrados pelo pipeline, sem editar checksums para forçar aceitação.

## Regras científicas dos notebooks EAC4

- A análise é mensal; não agrega silenciosamente dados subdiários.
- A varredura de qualidade percorre os chunks e guarda apenas uma fração finita
  por mês. Não materializa décadas inteiras do globo em RAM.
- Para médias espaciais, só entram meses com todas as células do domínio finitas.
  A política conserva o domínio espacial entre meses; um mês parcialmente ausente
  é reportado e excluído. Não há interpolação temporal ou espacial.
- Lacunas de calendário aparecem no inventário e como NaN nas séries CSV.
- Média anual exige janeiro a dezembro utilizáveis, ponderados por dias do mês.
- Ciclo mensal descritivo usa os meses existentes, com contagem explícita por mês.
- Referência para anomalias usa todos os anos completos se houver pelo menos dois.
  Pode usar anos não consecutivos, listados em `analysis.json`. Dois anos permitem
  uma referência empírica, mas não representam automaticamente uma normal
  climatológica de 30 anos. Não há análise inferencial de tendência neste pacote.
- Um único ano ou meses isolados geram gráficos descritivos; não produzem anomalias
  triviais em relação ao próprio ano. Médias anuais só aparecem se houver ano completo.
- O mês do mapa é o último válido; o ano do mapa anual é o último completo.
- A média de todo o período usa dias dos meses válidos. Se houver lacunas sazonais,
  ela pode não representar o clima do intervalo completo; a cobertura acompanha o produto.
- A referência muda quando entram anos novos. Saídas são separadas por execução,
  com datas UTC, checksums e lista de arquivos. Para comparar estudos publicados,
  use a mesma referência explícita e arquive os relatórios; não compare anomalias
  de referências diferentes como se fossem equivalentes.
- Médias espaciais são ponderadas por área dos centros de grade, não por população.
  Quando `cfg.area` for regional, o produto também será regional.
- A extração pontual tem QC próprio: preserva o ponto quando finito mesmo que outra
  célula do globo esteja ausente. A distância e a célula efetiva estão nos metadados.
- Conversões de unidade não são feitas pelos notebooks. Os gases preservam kg/kg.

Saídas: `reports/automatic_notebooks/<notebook>/<execução UTC>/`.
Consulte `file_inventory.csv`, `coverage.json`, `monthly_quality.csv`,
`analysis.json`, arquivos `.metadata.json` e `errors.json`.
Um notebook pode finalizar tendo erros de uma variável: confira `Falhas: 0`
e `errors.json`; exceções são exibidas e as outras variáveis continuam.

## Recortes e mapas EAC4

Em 02 e 03, `BBOX=None` usa o domínio disponível. Para um recorte:

```python
BBOX = [-20, -55, -26, -40]  # norte, oeste, sul, leste
```

Em 03, edite apenas `LAT` e `LON` para outro ponto. Não há ano fixo.
Mapas exigem pelo menos dois centros de grade em cada eixo. Bboxes que cruzam o
antimeridiano suportam séries regionais, mas os mapas são omitidos com mensagem,
pois o renderizador atual exige uma grade contígua após ordenar longitudes.
As linhas de costa ficam desabilitadas por padrão para evitar downloads extras.

## Teste inicial de um ano

O exemplo usa 2003 apenas para limitar downloads de teste. Os notebooks não contêm
esse ano fixado. No ambiente correto, na raiz do projeto:

```bash
camsaq inventory --start 2003-01 --end 2003-12
camsaq smoke --kind monthly --start 2003-01 --end 2003-01 --pollutants pm25
camsaq smoke --kind monthly --start 2003-01 --end 2003-01 --pollutants co
camsaq download-monthly --start 2003-01 --end 2003-12
camsaq validate
camsaq process --kind monthly
```

Execute os notebooks 01, 02 e 03. Se já houver outros anos locais, eles também
serão analisados: o download de teste não apaga nem esconde a cobertura existente.
`validate` e `process` não têm filtro de ano nessa versão e abrangem o manifesto.
O segundo piloto, apenas com CO, verifica o ramo de gases em nível de modelo.
`smoke` executa somente a primeira variável da seleção; listar PM2.5 e CO no
mesmo comando não testaria as duas.
O projeto requer pilotos válidos antes dos lotes maiores; siga qualquer indicação
da CLI quanto ao formato e escopo do piloto. Credenciais ficam fora do Git.
Repita `download-monthly` com o mesmo intervalo para exercitar a retomada; arquivos
já íntegros devem ser aproveitados pelo pipeline.

## Executar por linha de comando

No ambiente em que o projeto está instalado, disponibilize `nbconvert` e registre
o kernel acima. Se necessário: `python -m pip install 'nbconvert>=7,<8'`.
Depois, na raiz do projeto:

```bash
mkdir -p reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/01_inventory.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/02_global_climatology.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/03_timeseries_example.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/04_ch4_inventory.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/05_ch4_timeseries.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
jupyter nbconvert --to notebook --execute notebooks/06_ch4_maps.ipynb --ExecutePreprocessor.kernel_name=camsaq --ExecutePreprocessor.timeout=3600 --output-dir=reports/executed_notebooks
```

O tempo necessário depende da quantidade de dados: aumentar o timeout não aumenta
memória. Em máquinas com pouca memória, processe uma variável de cada vez nos
notebooks EAC4.
Configuração alternativa: `export CAMSAQ_CONFIG=/caminho/absoluto/config.yaml`.
Essa variável seleciona a configuração, sem expor qualquer token.

## Dependências e reprodutibilidade do ambiente

As dependências científicas e o extra `notebooks` já estão declarados em
`pyproject.toml`. Instale o projeto como descrito no README; esta ampliação
não acrescenta bibliotecas. Os comandos `jupyter nbconvert` acima exigem que
esse executável esteja disponível no ambiente. O harness de teste usa `nbclient`,
que já faz parte do extra `notebooks`.

Para registrar um ambiente verificado, execute na própria máquina:

```bash
mkdir -p environment-snapshots
python -m pip freeze > environment-snapshots/python-freeze.txt
python --version > environment-snapshots/python-version.txt
```

O freeze registra as versões Python instaladas, mas pode incluir caminhos locais
e não substitui a documentação de bibliotecas nativas. Revise os arquivos antes
de publicá-los.

## Validação desta atualização

Testes pequenos e sintéticos em `notebooks/tests/test_available_data.py`:

```bash
python -m pytest -q notebooks/tests/test_available_data.py
```

A execução integral de 01–06 pode ser repetida com bases sintéticas temporárias:

```bash
python notebooks/execute_notebooks.py
```

O harness inclui CH4 de dois anos completos e bloqueia pedidos de rede nos
notebooks CH4. Ele gera produtos em um diretório temporário e imprime o resumo;
não usa `data/`, `metadata/` ou `reports/` reais. Esses testes não comprovam
credenciais ADS, downloads reais ou desempenho com décadas de dados.

## Como usar os notebooks CH4

Primeiro prepare os meses com `camsaq ch4 download` ou `camsaq ch4 import`,
seguido de `camsaq ch4 process` se necessário. Os notebooks não fazem essa etapa.
Em cada notebook CH4, ajuste no topo `LEVEL`, `START`, `END`, `BASELINE_START`,
`BASELINE_END` e `BBOX`; no 05 e 06 também pode ajustar `LAT` e `LON`.
`START`/`END` são meses `YYYY-MM`; `BBOX` é `[norte, oeste, sul, leste]`.
`None` usa toda a cobertura local da release configurada. Um nível é uma camada
do modelo, não uma altitude fixa nem uma estação.

O inventário 04 grava `inventory.csv`, `coverage.json`, `analysis.json` e
`errors.json`. O notebook 05 grava séries CSV com `.metadata.json` e os gráficos
disponíveis. O 06 chama as mesmas funções da análise CLI e grava `analysis.json`,
`map_manifest.json` e mapas. As saídas ficam em
`reports/automatic_notebooks/<NOTEBOOK>/<RUN_ID>/` para não misturar execuções.
Se não houver partição processada e íntegra, o notebook explica qual comando
prepará-la; `errors.json` fica vazio quando não ocorreu erro de execução.

Mês completo significa todos os dias, uma vez cada. Ano completo exige os 12
meses. Referência e anomalia exigem ao menos dois anos completos; com cobertura
menor, os produtos dependentes são omitidos e o motivo é registrado. `BBOX`
afeta média espacial e mapas; a série pontual usa a célula mais próxima de
`LAT`/`LON`, inclusive fora desse recorte. Não há interpolação nem tendência
inferencial. Consulte [o relatório CH4](../docs/CH4_CAM73.md) para a definição
das escalas e da referência.
