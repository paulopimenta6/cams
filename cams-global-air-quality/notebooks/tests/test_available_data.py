"""Small synthetic data only; no ADS requests."""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from available_data import annual, coverage, digest, inventory, open_variable, reference


def cube(dates, name='pm25'):
    return xr.DataArray(np.ones((len(dates), 3, 4)), dims=('time','latitude','longitude'),
        coords={'time':dates, 'latitude':[-30.,0.,30.], 'longitude':[0.,90.,180.,270.]},
        name=name, attrs={'units':'ug m-3'})


def test_partial():
    a=cube(pd.date_range('2011-05-01', periods=3, freq='MS'))
    valid,r,q=coverage(a)
    assert r['complete_years']==[] and r['months_usable']==3
    assert reference(valid,r['reference_years']) is None


def test_single_year():
    a=cube(pd.date_range('1999-01-01', periods=12, freq='MS'))
    valid,r,q=coverage(a)
    assert r['complete_years']==[1999] and r['reference_years']==[]
    assert annual(valid,[1999]).sizes['time']==1


def test_nonconsecutive_reference_and_weighting():
    dates=pd.date_range('2010-01-01',periods=12,freq='MS').append(pd.date_range('2012-01-01',periods=12,freq='MS'))
    a=cube(dates)
    a[12:]=3
    valid,r,q=coverage(a)
    assert r['reference_years']==[2010,2012] and len(r['missing_months'])==12
    np.testing.assert_allclose(reference(valid,r['reference_years']),2)
    part=cube(pd.date_range('2012-01-01',periods=12,freq='MS'))
    part[1]=2
    np.testing.assert_allclose(annual(part,[2012]),1+29/366)


def test_invalid_fields_excluded():
    a=cube(pd.date_range('2011-01-01',periods=12,freq='MS'))
    a[0,0,0]=np.nan
    a[1,0,0]=np.inf
    valid,r,q=coverage(a)
    assert r['months_usable']==10 and r['complete_years']==[]
    assert r['invalid_months']==['2011-01','2011-02']


@pytest.mark.parametrize('dates', [['2011-01-01','2011-01-01'],['2011-01-15'],['2011-02-01','2011-01-01']])
def test_invalid_time_rejected(dates):
    with pytest.raises(ValueError): coverage(cube(pd.to_datetime(dates)))


def fixture_archive(tmp_path, specs):
    cfg={'metadata_dir':str(tmp_path), 'data_format':'grib', 'area':None,
         'sources':{'EAC4':{'monthly':'test-eac4'}}, 'netcdf_engine':'h5netcdf',
         'chunks':{'time':1,'latitude':3,'longitude':4}, 'registry':{}}
    rows=[]
    for variable,dates in specs.items():
        for date in dates:
            path=tmp_path/f'{variable}-{date:%Y-%m}.nc'
            cube([date],variable).to_dataset().to_netcdf(path,engine='h5netcdf')
            rows.append({'key':path.stem,'variable':variable,'year':date.year,'month':date.month,
                'dataset':'test-eac4','temporal_resolution':'monthly','status':'processed',
                'processed_path':str(path),'processed_checksum':digest(path),
                'api_request':json.dumps({'data_format':'grib'}),'level_type':'surface','level':None})
    with sqlite3.connect(tmp_path/'downloads.sqlite') as c:
        pd.DataFrame(rows).to_sql('downloads',c,index=False)
    return cfg,rows


def test_different_variable_coverage(tmp_path):
    cfg,rows=fixture_archive(tmp_path,{'pm25':pd.date_range('2019-01-01',periods=12,freq='MS'),
                                     'o3':pd.date_range('2022-01-01',periods=3,freq='MS')})
    accepted,report=inventory(cfg)
    assert len(accepted)==15
    for name,n in [('pm25',12),('o3',3)]:
        with open_variable(accepted,name,cfg) as a: assert a.sizes['time']==n


def test_missing_corrupt_and_duplicate(tmp_path):
    cfg,rows=fixture_archive(tmp_path,{'pm25':pd.date_range('2019-01-01',periods=3,freq='MS')})
    Path(rows[0]['processed_path']).unlink()
    Path(rows[1]['processed_path']).write_bytes(b'broken')
    accepted,report=inventory(cfg)
    assert len(accepted)==1
    assert set(report.status)=={'ready','checksum_failed','processed_file_missing'}
    with sqlite3.connect(tmp_path/'downloads.sqlite') as c:
        pd.DataFrame([rows[-1]]).to_sql('downloads',c,index=False,if_exists='append')
    accepted,report=inventory(cfg)
    assert accepted==[] and 'ambiguous_variable' in set(report.status)


def test_missing_manifest(tmp_path):
    accepted,report=inventory({'metadata_dir':str(tmp_path)})
    assert not accepted and report.iloc[0]['status']=='manifest_absent'
    assert not (tmp_path/'downloads.sqlite').exists()


def test_mismatched_timestamp(tmp_path):
    cfg,rows=fixture_archive(tmp_path,{'pm25':pd.date_range('2019-01-01',periods=1,freq='MS')})
    rows[0]['month']=2
    with pytest.raises(ValueError,match='timestamps'):
        with open_variable(rows,'pm25',cfg): pass
