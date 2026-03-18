from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
import pandas as pd
import time

# ------------------ SETUP ------------------

options = Options()
options.add_argument("--start-maximized")

driver = webdriver.Firefox(
    service=Service(GeckoDriverManager().install()),
    options=options
)

base_url = "https://www.chittorgarh.com/ipo/ipo_list.asp?year="
years = ["2026", "2025", "2024", "2023"]

all_data = []

# ------------------ SCRAPING ------------------

for year in years:
    try:
        driver.get(base_url + year)
        time.sleep(5)

        table = driver.find_element(By.ID, "report_table")
        rows = table.find_elements(By.TAG_NAME, "tr")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")

            if len(cols) < 8:
                continue

            try:
                link_element = cols[0].find_element(By.TAG_NAME, "a")
                company_name = link_element.text.replace("IPO", "").strip()
                company_link = link_element.get_attribute("href")
            except:
                continue

            ipo_open = cols[1].text
            ipo_close = cols[2].text
            listing_date = cols[3].text
            issue_price = cols[4].text
            issue_size = cols[5].text
            exchange = cols[6].text
            lead_manager = cols[7].text

            # ----------- OPEN DETAIL PAGE -----------

            description = None

            try:
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])

                driver.get(company_link)
                time.sleep(3)

                paragraphs = driver.find_elements(By.TAG_NAME, "p")
                if paragraphs:
                    description = paragraphs[0].text

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            except:
                driver.switch_to.window(driver.window_handles[0])

            # ----------- STORE DATA -----------

            all_data.append({
                "company_name": company_name,
                "ipo_open_date": ipo_open,
                "ipo_close_date": ipo_close,
                "listing_date": listing_date,
                "issue_price_range": issue_price,
                "issue_size_crore": issue_size,
                "exchange": exchange,
                "lead_manager": lead_manager,
                "ipo_year": year,
                "company_description": description,
                "company_link": company_link
            })

        print(f"✅ Done year {year}")

    except Exception as e:
        print(f"❌ Error in year {year}: {e}")

driver.quit()

print("Total records:", len(all_data))

# ------------------ DATAFRAME ------------------

df = pd.DataFrame(all_data)

# ------------------ CLEANING ------------------

# Convert dates and format cleanly (FIXES ######## ISSUE)
for col in ["ipo_open_date", "ipo_close_date", "listing_date"]:
    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime('%Y-%m-%d')

# Split price range
df[["price_min", "price_max"]] = df["issue_price_range"].str.split("to", expand=True)
df["price_min"] = pd.to_numeric(df["price_min"], errors="coerce")
df["price_max"] = pd.to_numeric(df["price_max"], errors="coerce")

# Average price
df["issue_price_avg"] = (df["price_min"] + df["price_max"]) / 2

# Clean issue size
df["issue_size_crore"] = df["issue_size_crore"].str.replace(",", "", regex=False)
df["issue_size_crore"] = pd.to_numeric(df["issue_size_crore"], errors="coerce")

# Convert back to datetime for calculations
df["ipo_open_date"] = pd.to_datetime(df["ipo_open_date"])
df["ipo_close_date"] = pd.to_datetime(df["ipo_close_date"])
df["listing_date"] = pd.to_datetime(df["listing_date"])

# Derived features
df["subscription_days"] = (df["ipo_close_date"] - df["ipo_open_date"]).dt.days
df["listing_delay_days"] = (df["listing_date"] - df["ipo_close_date"]).dt.days

# Convert again to string for Excel clarity
for col in ["ipo_open_date", "ipo_close_date", "listing_date"]:
    df[col] = df[col].dt.strftime('%Y-%m-%d')

# Remove duplicates
df = df.drop_duplicates()

# ------------------ SAVE ------------------

from openpyxl import load_workbook

file_name = "ipo_full_dataset.xlsx"

# Save first
df.to_excel(file_name, index=False)

# Open and format
wb = load_workbook(file_name)
ws = wb.active

# Auto-adjust column width
for col in ws.columns:
    max_length = 0
    col_letter = col[0].column_letter

    for cell in col:
        try:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        except:
            pass

    ws.column_dimensions[col_letter].width = max_length + 2

# Save again
wb.save(file_name)

print("✅ Excel formatted properly (no more ########)")