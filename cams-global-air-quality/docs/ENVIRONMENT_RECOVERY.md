# Diagnóstico e recuperação da última etapa

A retomada solicitada pelo usuário preservou código, catálogo, manifesto e logs.
Algumas execuções iniciais reportavam todas as asserções aprovadas, mas terminavam
com SIGABRT/erro de desalocação. Isso **não foi contado como sucesso integral**.

Foram comparados grupos de testes, instalações isoladas e backends. A hipótese
inicial de associação exclusiva ao Parquet não se confirmou: trocar seu backend
não resolveu. O teste integrado com análise e mapas era o elemento que distinguia
execuções completas anormais de execuções normais. Não se atribui uma causa
interna específica ao código C sem investigação adicional do upstream.

A correção de arquitetura isolou Cartopy/PROJ em processo de renderização, sem
compartilhar bibliotecas nativas de projeção com o processamento do arquivo.
O processo recebe arrays NumPy sem pickle; calcula limites explícitos de células;
fecha a figura; o controlador verifica retorno zero antes de publicar o PNG.
Falha ou timeout do worker é erro visível, nunca um gráfico marcado como válido.

Também foi identificada uma incompatibilidade concreta entre xarray 2026.9 e
Zarr 2 nessa instalação (`zarr_format` repassado para API incompatível). A entrega
fixa uma família compatível de versões e fornece `requirements-lock.txt`.
NetCDF4/HDF5 usa `h5netcdf`; o leitor independente `netCDF4` confirma o formato.
Parquet usa `fastparquet`, com round-trip testado. Essas alternativas não alteram
as unidades nem a definição científica dos produtos.

A suíte final está em `reports/pytest-final.txt`: **61 testes aprovados**, sem
avisos nessa execução, com **exit code 0** observado pelo executor. Os testes
incluem renderização Cartopy real em worker, codecs GRIB/NetCDF, Zarr, Parquet,
manifesto e operações incrementais. Os dados de teste são sintéticos.

Uma tentativa de kernel Jupyter encontrou restrições de sockets do ambiente.
Os três notebooks foram validados estruturalmente; as células de inventário
foram executadas diretamente em Python. Os notebooks que exigem dados CAMS reais
ficam sem outputs científicos, pois a autenticação ADS ainda não foi fornecida.
