"""Execute with the project environment and registered camsaq kernel. Synthetic fixtures only."""
import os,sys,tempfile,json
from pathlib import Path
import yaml, pandas as pd, nbformat
from nbclient import NotebookClient
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'notebooks/tests'))
from test_available_data import fixture_archive
base=Path(tempfile.mkdtemp(prefix='cams-notebook-validation-'))
os.environ['PYTHONPATH']=str(root/'src')
os.environ['MPLBACKEND']='Agg'
os.environ['OMP_NUM_THREADS']='1'
scenarios={
 'empty':{},
 'partial':{'pm25':pd.date_range('2017-04-01',periods=3,freq='MS')},
 'single_year':{'pm25':pd.date_range('2019-01-01',periods=12,freq='MS')},
 'gaps_and_different_variables':{
   'pm25':pd.date_range('2010-01-01',periods=12,freq='MS').append(pd.date_range('2012-01-01',periods=12,freq='MS')),
   'pm10':pd.date_range('2012-09-01',periods=3,freq='MS')},
}
results=[]
for scenario,specs in scenarios.items():
    folder=base/scenario
    folder.mkdir()
    cfg=yaml.safe_load((root/'config/config.yaml').read_text())
    cfg.update(root=str(folder),metadata_dir=str(folder),data_dir=str(folder/'data'),log_dir=str(folder/'logs'))
    if specs:
        overrides,_=fixture_archive(folder,specs)
        cfg.update({k:v for k,v in overrides.items() if k!='registry'})
    (folder/'pollutants.yaml').write_text((root/'config/pollutants.yaml').read_text())
    configpath=folder/'config.yaml'
    configpath.write_text(yaml.safe_dump(cfg))
    os.environ['CAMSAQ_CONFIG']=str(configpath)
    for path in sorted((root/'notebooks').glob('0[123]_*.ipynb')):
        nb=nbformat.read(path,as_version=4)
        nbformat.validate(nb)
        client=NotebookClient(nb,timeout=180,kernel_name='camsaq',resources={'metadata':{'path':str(root)}})
        client.execute()
        nbformat.write(nb,folder/path.name)
        results.append({'scenario':scenario,'notebook':path.name,'status':'PASS'})
        print(scenario,path.name,'PASS',flush=True)
    for path in folder.rglob('errors.json'):
        errors=json.loads(path.read_text())
        assert errors==[],(path,errors)
    if scenario in ['partial','single_year']:
        assert not list(folder.rglob('latest_anomaly.png'))
    if scenario=='gaps_and_different_variables':
        assert list(folder.rglob('latest_anomaly.png'))
        reports=[json.loads(p.read_text()) for p in folder.rglob('analysis.json')]
        assert next(r for r in reports if r['variable']=='pm25')['reference_years']==[2010,2012]
(root/'notebooks/tests/notebook_execution_results.json').write_text(json.dumps({'synthetic_only':True,'results':results},indent=2))
print('Test workspace:',base)
