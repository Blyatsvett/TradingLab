python -c "
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/prices.db')

df = pd.read_sql('SELECT date, ticker, close FROM prices_enriched', conn)

conn.close()

df['date'] = pd.to_datetime(df['date'])

df = df.sort_values(['ticker', 'date'])

df['ret'] = df.groupby('ticker')['close'].pct_change()

print(df['ret'].describe())
"