# Operação e manutenção

Este roteiro principal trata da **EAC4**. Para CH4 CAMS73, consulte a seção
própria abaixo: são outro produto, outro manifesto e outros comandos.

## Sequência recomendada

1. Configurar venv, credencial e aceite de licença; executar testes.
2. `camsaq inventory` e `camsaq plan --kind monthly` ao vivo.
3. `camsaq smoke ... --pollutants pm25` e `... --pollutants co`.
4. Examinar `metadata/downloads.sqlite` e o QC dos pilotos, inclusive nível/unidade.
5. `camsaq download-monthly`; `camsaq validate`; `camsaq inventory`.
6. `camsaq consolidate` se necessário. A aquisição completa já tenta consolidar.
7. `camsaq analyze --baseline-start ... --baseline-end ...`.
8. Atualizações subsequentes: `python -m cams_air_quality update`.

Se você possui os três snapshots JSON de uma consulta anterior, pode lê-los
sem rede. O diretório `evidence/` deste checkout está vazio; os testes criam
fixtures sintéticas temporárias e não usam esses comandos:

```bash
camsaq inventory --offline-evidence evidence
camsaq plan --kind subdaily --offline-evidence evidence
```

Essa opção só existe em comandos de leitura/planejamento; downloads sempre
revalidam o catálogo. Nunca altere manualmente um final de série só para fazer
um pedido passar. Novos campos/formats não reconhecidos exigem revisar o adaptador.

## Erros e recuperação

- API key ausente: configurar arquivo do SDK, sem compartilhar chave.
- HTTP 401/403: verificar conta, token, URL ADS e termos. Não repetir milhares de pedidos.
- HTTP 429/5xx ou conexão interrompida: backoff exponencial com jitter e tentativas limitadas.
- Deadline de job: ID permanece no SQLite; rode o mesmo comando depois.
- Arquivo truncado: `.part` permanece e o Range tenta continuar.
- QC FAIL: payload isolado com sufixo `.corrupt-*`; consultar `qc_json`.
- Arquivo bom mas derivado ausente: `camsaq process`, sem nova recuperação ADS.
- Checksum do derivado mudou: reconstrução a partir do original verificado.
- Pouco disco: mude `data_dir` **antes** de construir o arquivo ou use lotes
  limitados. Transferir um arquivo já existente exige também reconciliar caminhos
  absolutos do manifesto e revalidar checksums.

Não apague `metadata/` ao retomar: nele ficam IDs de jobs, estados e catálogo.
Faça backup de SQLite e dos originais em consistência com o filesystem. Para
backup do banco em uso, use a API de backup SQLite; não copie apenas o arquivo
principal ignorando WAL. Pare o pipeline ao mover todo o arquivo.

## Agendamento opcional no Ubuntu

A CLI faz atualização incremental quando executada; esta entrega não instala
serviços na máquina do usuário. Depois dos pilotos, um cron local pode chamar:

```cron
# Todo dia 5 do mês às 06h locais da máquina, exemplo editável.
0 6 5 * * cd /caminho/cams-global-air-quality && /usr/bin/flock -n metadata/update.lock .venv/bin/python -m cams_air_quality update >> logs/scheduler.log 2>&1
```

A periodicidade deve ser compatível com a publicação do produto; não há ganho em
consultar incessantemente. O lock evita duas atualizações agendadas simultâneas.

## Recursos e benchmark

`plan` calcula n_variáveis × n_tempos × n_lat × n_lon × 4 bytes, sem assumir uma
razão universal de compressão. O orçamento de quatro cópias representa original,
intermediário, processado e temporário; reservas para gerações antigas, backups,
ZIP e filesystem são adicionais. A estimativa para bbox é global, conservadora.

Depois de uma amostra real, meça `filesize`, elapsed e pico de RAM de 1 mês por
tipo vertical. Extrapole com intervalo, não uma promessa de tempo total. Filas ADS
podem dominar o tempo e dados em fita podem ser mais lentos. Não exceda quatro
workers sem reprojetar explicitamente política de serviço e integração.

A criação de Zarr anual reescreve apenas o ano alterado e mantém gerações antigas.
Planeje limpeza manual após validar backups; o pipeline não apaga dados bons.
O comando `camsaq clean` descrito abaixo executa exclusões somente com `--yes`.
NetCDF bruto convertido do ZIP permanece no cache `interim/unpacked` para
reutilização. Alterar chunks ou versão do código pode gerar novos derivados.

Logs incluem timestamps UTC no conteúdo JSON, dataset, variável, ano/mês, request,
status, bytes, elapsed, erro sanitizado e tentativa. Não incluem token nem URL
assinada. `metadata/qc-report.json` é produzido por `camsaq validate`.

## Operação do metano CAMS73

Na pasta do pacote, com o ambiente ativo, consulte primeiro o catálogo e o
orçamento de disco. Escolha **import** se já tem o NetCDF ou **download** se vai
solicitar o arquivo ao ADS:

```bash
camsaq ch4 plan --start 2024-09 --version v25r1
camsaq ch4 import --file ../exemplo_ch4/cams73_latest_ch4_conc_first_guess_dm_202409.nc
# Ou, com token e licença ADS configurados:
camsaq ch4 download --start 2024-09 --version v25r1
```

A importação valida, copia, processa e indexa; o download também. Comece com um
mês. O arquivo de exemplo é local e não acompanha o clone do GitHub.

`camsaq ch4 validate` repete QC e checksum dos originais registrados;
`camsaq ch4 process` reconstrói derivados quando necessário;
`camsaq ch4 consolidate --version v25r1` publica o índice Zarr. O manifesto fica
em `metadata/ghg_inversion/downloads.sqlite`, separado do EAC4. A análise exige
um nível: `camsaq ch4 analyze --level 1 --version v25r1`. A versão é a **release
efetiva** encontrada no NetCDF, mesmo quando o arquivo de entrada tinha `latest`
no nome. Não programe o mesmo mês pelos caminhos importação e download sem
revisar duplicidade de lotes. Consulte o [passo a passo](../../GUIA_COMPLETO.md#24-metano-ch4-passo-a-passo).

### Análise por período

```bash
camsaq ch4 analyze --level 1 --start 2023-01 --end 2023-04 \
  --maps monthly,period,std --scale shared
camsaq ch4 analyze --level 1 --start 2022-01 --end 2023-12 \
  --baseline-start 2022-01 --baseline-end 2023-12 \
  --maps annual,climatology,anomaly
```

`--maps annual` publica apenas anos com 12 meses diários completos. Referência
e anomalia exigem ao menos dois anos completos. Veja cobertura e omissões em
`analysis.json`; não interprete um ano parcial como média anual.

## Limpeza explícita

`camsaq clean` **não apaga nada sem `--yes`**. Faça primeiro uma prévia:

```bash
camsaq clean --scope reports --scope tmp
camsaq clean --scope processed --product ch4 --json
camsaq clean --scope zarr-stale --yes
```

`--scope all` inclui relatórios gerados conhecidos, temporários, logs, catálogo,
cache, intermediários e processados; **não** inclui brutos ou manifestos.
`--scope everything --yes` inclui também brutos e manifestos. `--product ch4`
ou `eac4` filtra `raw`, `processed` e `manifest`; os outros escopos são comuns.
`--scope all` e `everything` não podem ser combinados com outro escopo.

Os escopos individuais são `reports`, `interim`, `processed`, `raw`, `manifest`,
`zarr-stale`, `tmp`, `logs`, `catalog` e `cache`. `reports` preserva Markdown e
arquivos rastreados pelo Git. `zarr-stale` confere o índice e conserva a geração
ativa; um caminho ativo ausente bloqueia a limpeza daquele produto. Locks ativos
bloqueiam remoções de dados, salvo escolha explícita `--force`; locks detidos
continuam protegidos no escopo `tmp`.

Ao limpar `processed` com bruto íntegro, o manifesto retorna a `validated` e
`camsaq ch4 process` reconstrói o derivado CH4. Ao limpar bruto e derivado, a
linha passa a `cleaned` e `validate` a omite. Se só o bruto foi apagado mas o
derivado continua íntegro, a análise segue possível e `validate` informa
`raw_missing_processed_intact`. O escopo `manifest` cria
`downloads.sqlite.bak-<data UTC>` por padrão; `--no-manifest-backup` desativa
essa proteção. Guarde backups fora da máquina antes de uma limpeza ampla.
