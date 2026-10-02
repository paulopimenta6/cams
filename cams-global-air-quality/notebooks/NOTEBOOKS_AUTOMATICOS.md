# Notebooks CAMS com descoberta automática de cobertura

## Instalação da atualização

Este pacote contém os três notebooks refeitos e o módulo compartilhado
`notebooks/available_data.py`. Copie os quatro arquivos juntos. Não há alteração
nos arquivos CAMS, credenciais, manifesto ou configuração do downloader.
A implementação foi conferida contra `processing.py` do repositório
paulopimenta6/cams (SHA do arquivo 87a3b01627e0b5f455f07ee7268dacf5452e62d4).

Na raiz do projeto, faça uma cópia de segurança antes de extrair o ZIP:

```bash
cp -a notebooks "notebooks.backup.$(date +%Y%m%d-%H%M%S)"
unzip /caminho/para/CAMS_Notebooks_Automaticos.zip -d .
```

Reinicie o kernel se algum notebook já estiver aberto. Escolha o ambiente Python
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

## O que é descoberto

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

## Regras científicas

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

## Recortes e mapas

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
camsaq smoke --kind monthly --start 2003-01 --end 2003-01 --pollutants pm25 co
camsaq download-monthly --start 2003-01 --end 2003-12
camsaq validate
camsaq process --kind monthly
```

Execute os notebooks 01, 02 e 03. Se já houver outros anos locais, eles também
serão analisados: o download de teste não apaga nem esconde a cobertura existente.
`validate` e `process` não têm filtro de ano nessa versão e abrangem o manifesto.
A variável CO do piloto verifica o ramo de gases em nível de modelo.
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
```

O tempo necessário depende da quantidade de dados: aumentar o timeout não aumenta
memória. Na Jetson, processe uma variável de cada vez (já é o padrão deste código).
Configuração alternativa: `export CAMSAQ_CONFIG=/caminho/absoluto/config.yaml`.
Essa variável seleciona a configuração, sem expor qualquer token.

## Dependências e reprodutibilidade do ambiente

Mantenha no `pyproject.toml`, em dependencies:

```toml
"zarr>=2.18.7,<3",
"numcodecs>=0.12,<0.16",
```

Nos extras de notebooks, mantenha JupyterLab, nbclient, ipykernel e Jinja2;
acrescente `nbconvert>=7,<8` se quiser os comandos de execução acima.
Cartopy 0.24 e ecCodes nativo da Jetson também precisam ser documentados no Conda.
O pacote PyPI `eccodes` (interface Python) não é a mesma distribuição que
`eccodes` do Conda (biblioteca nativa). Não substitua a versão da interface pela
versão nativa só porque os nomes coincidem.

Para registrar seu ambiente que passou nos 61 testes, execute na própria Jetson:

```bash
mkdir -p environment-snapshots
conda list --explicit > environment-snapshots/jetson-conda-explicit.txt
python -m pip freeze > environment-snapshots/jetson-python-freeze.txt
python -m eccodes selfcheck > environment-snapshots/jetson-eccodes.txt
```

O arquivo Conda explícito registra builds nativos e é específico da plataforma;
o freeze Python não substitui esse arquivo. Não restaure cegamente todo o freeze
com pip sobre bibliotecas Conda: ele lista também distribuições fornecidas pelo
Conda e caminhos de instalação editável. Revise caminhos locais antes de versionar.
Esses snapshots devem ser gerados na sua máquina: não é possível reconstruir
exatamente seu ambiente a partir de alguns números de versão no chat.

## Validação desta atualização

Testes pequenos e sintéticos em `notebooks/tests/test_available_data.py`:

```bash
python -m pytest -q notebooks/tests/test_available_data.py
```

A execução integral dos notebooks foi exercitada com bases sintéticas, incluindo
base vazia, meses isolados, um ano completo e dois anos não consecutivos com
coberturas diferentes por variável. O resumo está em
`notebooks/tests/notebook_execution_results.json`. Esses testes não comprovam
credenciais ADS, downloads reais ou desempenho com décadas de dados na Jetson.
