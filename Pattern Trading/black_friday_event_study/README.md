# Black Friday Event Study — MVP

This project tests whether US-listed companies exposed to e-commerce/retail,
payments, and logistics show recurring abnormal stock returns around Black Friday.

## Research hypothesis

Companies with high exposure to US e-commerce, payments, and parcel delivery
generate positive abnormal returns during the 20 trading days preceding Black
Friday, followed by weaker or reversing returns after the event.

## Method

For every company and Black Friday year from 2010 through 2025:

1. Download adjusted daily prices.
2. Estimate a market model against SPY from trading day -250 to -61.
3. Calculate abnormal returns from day -60 to +30.
4. Calculate cumulative abnormal returns for fixed windows.
5. Aggregate first by exposure group and year.
6. Test recurrence, positive-year rate, and statistical significance.
7. Apply Benjamini-Hochberg false-discovery-rate correction.
8. Compare discovery years (2010–2018) with validation years (2019–2025).

## Setup in VS Code

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_pipeline.py
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py
```

## Main outputs

- `output/group_summary.csv`
- `output/group_year_cars.csv`
- `output/company_summary.csv`
- `output/group_curve.csv`
- `output/split_results.csv`
- `event_study.db`

## Suggested Power BI pages

### 1. Executive overview

- Cards: mean CAR, positive-year rate, number of event years
- Matrix: exposure group × event window
- Slicers: exposure group, ticker, event year, window

### 2. Event curve

Use `group_curve.csv`:

- X-axis: `relative_day`
- Y-axis: `mean_cumulative_abnormal_return`
- Legend: `exposure_group`
- Add a vertical reference line at day 0

### 3. Recurrence

Use `group_year_cars.csv`:

- X-axis: `event_year`
- Y-axis: `mean_group_car`
- Small multiples or legend: `exposure_group`
- Slicer: `window`

### 4. Company exploration

Use `company_summary.csv`:

- Scatter X: `positive_year_rate`
- Scatter Y: `mean_car`
- Size: `n_years`
- Details: `ticker`
- Legend: `exposure_group`

## Important limitations

This starter uses yfinance, which is suitable for prototyping and educational
research but is not a survivorship-bias-free institutional dataset. The manually
curated company list contains current companies and therefore cannot support a
strong historical investment claim by itself.

After validating the pipeline, replace the price/universe layer with a source
that includes delisted securities and point-in-time index membership, such as
CRSP/Compustat through WRDS or another licensed institutional source.

## Next development steps

1. Review missing ticker-years in `data/processed/diagnostics.csv`.
2. Freeze the MVP rules before examining alternative windows.
3. Add Fama-French factors as an alternative expected-return model.
4. Replace manual exposure groups with measurable features:
   - Q4 revenue concentration
   - US revenue share
   - online-sales exposure
   - transaction-volume exposure
5. Expand to a point-in-time company universe.
6. Run walk-forward validation and transaction-cost simulations.
