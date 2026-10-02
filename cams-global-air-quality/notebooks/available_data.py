"""Coverage-aware monthly EAC4 notebook utilities. No downloads or manifest writes."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import dask
import numpy as np
import pandas as pd
import xarray as xr

from cams_air_quality.extraction import area_mean, extract_point, save_table, subset_bbox
from cams_air_quality.maps import plot_map


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inventory(cfg, variables=None):
    """Only current, checksum-verified processed monthly partitions for this scope."""
    manifest = Path(cfg['metadata_dir']) / 'downloads.sqlite'
    if not manifest.is_file():
        return [], pd.DataFrame([{'status': 'manifest_absent', 'file': str(manifest)}])
    with sqlite3.connect(manifest.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute('SELECT * FROM downloads')]
    accepted, report = [], []
    for row in rows:
        if row['temporal_resolution'] != 'monthly':
            continue
        if row['dataset'] != cfg['sources']['EAC4']['monthly']:
            continue
        if variables is not None and row['variable'] not in variables:
            continue
        request = json.loads(row['api_request'])
        if request.get('area') != cfg.get('area'):
            continue
        if request.get('data_format') != cfg['data_format']:
            continue
        state = row['status']
        path = Path(row['processed_path']) if row.get('processed_path') else None
        spec = cfg.get('registry', {}).get(row['variable'], {})
        if spec and (row['level_type'] != spec['level_type'] or row['level'] != spec['level']):
            state = 'incompatible_level'
        elif state == 'processed':
            if path is None or not path.is_file():
                state = 'processed_file_missing'
            elif not row.get('processed_checksum') or digest(path) != row['processed_checksum']:
                state = 'checksum_failed'
            else:
                state = 'ready'
                accepted.append(row)
        report.append({'variable': row['variable'], 'year': row['year'], 'month': row['month'],
                       'status': state, 'file': str(path) if path else '', 'key': row['key']})
    duplicates = pd.DataFrame(accepted)
    if not duplicates.empty:
        bad = set(duplicates.loc[duplicates.duplicated(['variable', 'year', 'month'], keep=False), 'variable'])
        # Ambiguous generations block that variable instead of silently selecting a file.
        accepted = [r for r in accepted if r['variable'] not in bad]
        for entry in report:
            if entry['variable'] in bad and entry['status'] == 'ready':
                entry['status'] = 'ambiguous_variable'
    return accepted, pd.DataFrame(report)


@contextmanager
def open_variable(rows, variable, cfg):
    selected = sorted((r for r in rows if r['variable'] == variable), key=lambda r: (r['year'], r['month']))
    if not selected:
        raise ValueError(f'No verified processed files for {variable}')
    lookup = {str(Path(r['processed_path']).resolve()): r for r in selected}
    signatures = set()

    def prepare(ds):
        row = lookup[str(Path(ds.encoding['source']).resolve())]
        a = ds[variable]
        t = pd.DatetimeIndex(a.time.values)
        expected = pd.Timestamp(year=row['year'], month=row['month'], day=1)
        if len(t) != 1 or t[0] != expected:
            raise ValueError(f'{variable}: file timestamps differ from manifest: {row["processed_path"]}')
        if set(a.dims) != {'time', 'latitude', 'longitude'}:
            raise ValueError(f'{variable}: expected time, latitude, longitude')
        if not a.attrs.get('units'):
            raise ValueError(f'{variable}: missing units')
        signatures.add((a.attrs['units'], a.attrs.get('source_level_type'), a.attrs.get('source_level')))
        return a.to_dataset()

    ds = xr.open_mfdataset(list(lookup), engine=cfg['netcdf_engine'], chunks=cfg['chunks'],
                          combine='by_coords', preprocess=prepare, parallel=False,
                          data_vars='minimal', coords='minimal', compat='equals', join='exact',
                          combine_attrs='drop_conflicts')
    try:
        if len(signatures) != 1:
            raise ValueError(f'{variable}: units or vertical level differ between partitions')
        a = ds[variable].sortby('time')
        if pd.DatetimeIndex(a.time.values).has_duplicates:
            raise ValueError(f'{variable}: duplicate timestamps')
        yield a
    finally:
        ds.close()


def coverage(a):
    """Scan chunks, retaining only a small vector; require a fixed, fully finite spatial domain."""
    if set(a.dims) != {'time', 'latitude', 'longitude'} or not a.sizes['time']:
        raise ValueError('Expected nonempty monthly spatial data')
    t = pd.DatetimeIndex(a.time.values)
    if t.has_duplicates or not t.is_monotonic_increasing or not t.equals(t.to_period('M').start_time):
        raise ValueError('Time must be unique, sorted, month-start timestamps')
    with dask.config.set(scheduler='synchronous'):
        finite = np.isfinite(a).mean(['latitude', 'longitude']).compute().values
    quality = pd.DataFrame({'date': t, 'finite_fraction': finite, 'usable': finite == 1.0})
    valid = t[finite == 1.0]
    expected = pd.date_range(t[0], t[-1], freq='MS')
    years = [int(y) for y in sorted(set(valid.year)) if sum(valid.year == y) == 12]
    report = {
        'first_observed': str(t[0].date()), 'last_observed': str(t[-1].date()),
        'months_observed': len(t), 'months_usable': len(valid),
        'months_expected_between_endpoints': len(expected),
        'missing_months': [str(p) for p in expected.difference(t).to_period('M')],
        'invalid_months': [str(p) for p in t[finite != 1.0].to_period('M')],
        'complete_years': years, 'reference_years': years if len(years) >= 2 else [],
        'units': a.attrs.get('units'),
        'helper_sha256': digest(__file__),
        'qc_policy': 'All grid cells finite in each included month; no spatial imputation',
        'reference_policy': 'All available complete calendar years; may be nonconsecutive',
        'climatology_status': 'empirical_multiyear_reference' if len(years) >= 2 else 'monthly_cycle_only',
    }
    return a.sel(time=valid), report, quality


def annual(a, years):
    result = []
    for year in years:
        part = a.sel(time=str(year))
        if part.sizes['time'] != 12:
            raise ValueError('Annual mean requires 12 valid months')
        result.append(part.weighted(part.time.dt.days_in_month).mean('time', keep_attrs=True)
                      .expand_dims(time=[pd.Timestamp(year=year, month=1, day=1)]))
    return xr.concat(result, dim='time') if result else None


def reference(a, years):
    if len(years) < 2:
        return None
    selected = a.sel(time=a.time.dt.year.isin(years))
    result = selected.groupby('time.month').mean('time', skipna=False, keep_attrs=True)
    result.attrs.update(reference_years=json.dumps(years),
                        reference_method='equal weights between complete years within each month')
    return result


def export_series(a, path, metadata):
    # Insert NaN rows for absent dates so plots/CSV never bridge a temporal gap silently.
    dates = pd.DatetimeIndex(a.time.values)
    a = a.reindex(time=pd.date_range(dates.min(), dates.max(), freq='MS'))
    frame = a.to_dataframe(name=a.name or 'value').reset_index()
    frame.attrs = metadata
    save_table(frame, path)
    return a


def analyze(variable, rows, cfg, output, bbox=None, maps=True):
    import matplotlib.pyplot as plt
    out = Path(output) / variable
    out.mkdir(parents=True, exist_ok=True)
    with open_variable(rows, variable, cfg) as a:
        if bbox is not None:
            a = subset_bbox(a, *bbox)
        valid, report, quality = coverage(a)
        report.update(source='EAC4', variable=variable, bbox=bbox, configured_area=cfg.get('area'),
                      created_at=datetime.now(timezone.utc).isoformat(),
                      files=[{k: r.get(k) for k in ('processed_path', 'processed_checksum', 'filepath',
                                                    'checksum', 'api_request')} for r in rows if r['variable'] == variable])
        quality.to_csv(out / 'monthly_quality.csv', index=False)
        (out / 'analysis.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if not valid.sizes['time']:
            print(variable, ': no month with complete finite spatial coverage; see monthly_quality.csv')
            return report
        with dask.config.set(scheduler='synchronous'):
            series = area_mean(valid).compute()
            period_mean = valid.weighted(valid.time.dt.days_in_month).mean('time', keep_attrs=True).compute()
        label = 'média espacial ponderada por área'
        plotted = export_series(series, out / 'spatial_mean.csv', report)
        fig, ax = plt.subplots(figsize=(10, 4))
        plotted.plot(ax=ax, marker='o')
        ax.set_title(f'{variable}: {label} — meses disponíveis')
        fig.savefig(out / 'timeseries.png', dpi=130, bbox_inches='tight')
        plt.close(fig)
        cycle = series.groupby('time.month').mean('time', keep_attrs=True)
        counts = series.groupby('time.month').count('time')
        cycle.to_dataframe(name='mean').join(counts.to_dataframe(name='n_months')).to_csv(out / 'monthly_cycle.csv')
        fig, ax = plt.subplots(figsize=(9, 4))
        cycle.reindex(month=range(1, 13)).plot(ax=ax, marker='o')
        ax.set_title(f'{variable}: ciclo mensal descritivo (contagens no CSV)')
        ax.set_xticks(range(1, 13))
        fig.savefig(out / 'monthly_cycle.png', dpi=130, bbox_inches='tight')
        plt.close(fig)
        yearly = annual(series, report['complete_years'])
        if yearly is not None:
            frame = yearly.to_dataframe(name=variable).reset_index()
            frame.attrs = report
            save_table(frame, out / 'annual_mean.csv')
        clim = reference(valid, report['reference_years'])
        if clim is not None:
            ref_series = reference(series, report['reference_years'])
            save_table(ref_series.to_dataframe(name=variable).reset_index(), out / 'reference_cycle.csv')
            anomaly = series.groupby('time.month') - ref_series
            anomaly.name = variable
            anomaly.attrs = {**series.attrs, 'reference_years': json.dumps(report['reference_years'])}
            export_series(anomaly, out / 'monthly_anomalies.csv', report)
            ann_anomaly = annual(anomaly, report['complete_years'])
            frame = ann_anomaly.to_dataframe(name=variable).reset_index()
            frame.attrs = report
            save_table(frame, out / 'annual_anomalies.csv')
        if maps:
            latest = pd.Timestamp(valid.time.values[-1])
            # Regional masks crossing the antimeridian need a different map seam; fail visibly.
            if bbox is not None and bbox[1] > bbox[3]:
                print('Mapas omitidos: bbox cruza antimeridiano; séries regionais foram calculadas.')
            else:
                plot_map(valid.isel(time=-1), out / f'month_{latest:%Y-%m}.png', title=f'{variable}: {latest:%Y-%m}')
                plot_map(period_mean, out / 'available_period_mean.png', title=f'{variable}: média dos meses disponíveis')
                if report['complete_years']:
                    year = report['complete_years'][-1]
                    plot_map(annual(valid.sel(time=str(year)), [year]).isel(time=0), out / f'annual_{year}.png',
                             title=f'{variable}: média anual {year}')
                if clim is not None:
                    plot_map(clim.sel(month=latest.month), out / 'reference_month.png',
                             title=f'{variable}: referência mês {latest.month}; anos {report["reference_years"]}')
                    difference = valid.isel(time=-1) - clim.sel(month=latest.month)
                    difference.attrs = dict(valid.attrs)
                    plot_map(difference, out / 'latest_anomaly.png',
                             title=f'{variable}: anomalia {latest:%Y-%m}', anomaly=True)
        return report


def point_and_region(variable, rows, cfg, output, lat, lon, bbox=None):
    out = Path(output) / variable
    out.mkdir(parents=True, exist_ok=True)
    with open_variable(rows, variable, cfg) as a:
        point = extract_point(a, lat, lon)
        with dask.config.set(scheduler='synchronous'):
            point = point.compute()
        point = point.where(np.isfinite(point))
        point.name = variable
        export_series(point, out / 'nearest_cell.csv', {**point.attrs, 'source': 'EAC4',
            'files': [r['processed_path'] for r in rows if r['variable'] == variable]})
        if bbox is not None:
            region = subset_bbox(a, *bbox)
            good, info, qc = coverage(region)
            qc.to_csv(out / 'region_quality.csv', index=False)
            if good.sizes['time']:
                with dask.config.set(scheduler='synchronous'):
                    series = area_mean(good).compute()
                export_series(series, out / 'region_mean.csv', {**info, 'bbox': bbox, 'source': 'EAC4'})
        return point
