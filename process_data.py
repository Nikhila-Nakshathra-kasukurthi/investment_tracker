import pandas as pd
import yfinance as yf
from datetime import datetime

# Load CSV
df = pd.read_csv("ipo_data.csv")

# ------------------ CLEANING ------------------

# Clean column names
df.columns = [col.replace("\n▲\n▼", "").strip() for col in df.columns]

# Drop unnecessary column
df = df.drop(columns=["Compare"], errors="ignore")

# Remove empty rows
df = df.dropna(how="all")

# Clean company names
df["Company"] = df["Company"].str.replace("IPO", "").str.strip()

# Convert Listing Date to datetime
df["Listing Date"] = pd.to_datetime(df["Listing Date"], errors="coerce")

# ------------------ FUNCTION ------------------

def get_index_data(date):
    if pd.isna(date):
        return [None, None, None, None]

    # Skip future dates
    if date > pd.Timestamp(datetime.today()):
        return [None, None, None, None]

    start = date.strftime("%Y-%m-%d")
    end = (date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        nifty = yf.Ticker("^NSEI").history(start=start, end=end)
        sensex = yf.Ticker("^BSESN").history(start=start, end=end)

        return [
            nifty["Open"].iloc[0] if not nifty.empty else None,
            nifty["Close"].iloc[0] if not nifty.empty else None,
            sensex["Open"].iloc[0] if not sensex.empty else None,
            sensex["Close"].iloc[0] if not sensex.empty else None,
        ]
    except:
        return [None, None, None, None]

# ------------------ APPLY ------------------

def safe_index_data(date):
    try:
        result = get_index_data(date)
        if len(result) == 4:
            return pd.Series(result)
        else:
            return pd.Series([None, None, None, None])
    except:
        return pd.Series([None, None, None, None])


index_data = df["Listing Date"].apply(get_index_data)

# Convert list of lists into DataFrame
index_df = pd.DataFrame(index_data.tolist(), columns=[
    "Nifty Open", "Nifty Close", "Sensex Open", "Sensex Close"
])

# Merge with original dataframe
df = pd.concat([df, index_df], axis=1)

# ------------------ SAVE ------------------

df.to_csv("ipo_enriched.csv", index=False)

# ------------------ OUTPUT ------------------

print(df.head())
print("\n✅ Enriched data saved as ipo_enriched.csv")