# Validação do complemento — 30/09/2026

- Esquema do notebook validado com nbformat; sete células de código compiladas.
- As sete células foram executadas sequencialmente em Python com dados
  **sintéticos**, identificados como teste de software, cobrindo janeiro–dezembro
  de 2003, seis variáveis e a grade 241 × 480. Não são observações CAMS.
- A execução usou as funções existentes de abertura Zarr, estatísticas, recorte,
  extração, exportação e renderização Cartopy em subprocesso.
- PASS: 72 registros QC, seis séries globais, cinco mapas (11 PNG ao todo),
  séries regionais, CSV/Parquet com 12 registros para São Paulo e relatório JSON.
- PASS: remoção de dezembro provocou erro explícito antes das análises.
- O processo finalizou com código 0. Os dados sintéticos e seus produtos foram
  temporários e não fazem parte deste pacote.
- O comando nbconvert foi conferido na documentação oficial. Não foi iniciada
  uma sessão de kernel Jupyter neste ambiente; o teste executou as células
  diretamente em Python. A execução integral via nbconvert deverá ser feita
  no Linux com o kernel camsaq configurado.
- Nenhum download CAMS foi iniciado e os arquivos do computador do usuário
  não foram acessados. O PASS acima não certifica o arquivo científico real.

Ambiente principal do teste: Python 3.12, NumPy 1.26.4, xarray 2025.3.1,
Dask 2025.3.1 e Zarr 2.18.7. Notebook fonte entregue sem saídas sintéticas.

O pacote acrescenta um notebook e documentação; não modifica os módulos do
pipeline, o arquivo de configuração, os notebooks anteriores nem o manifesto.
