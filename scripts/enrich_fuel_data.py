import os
import pgeocode
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
RAW_CSV_PATH = os.path.join(DATA_DIR, 'fuel-prices-for-be-assessment.csv')
OUTPUT_CSV_PATH = os.path.join(DATA_DIR, 'fuel_stations_geocoded.csv')

def enrich_fuel_dataset():
    if not os.path.exists(RAW_CSV_PATH):
        raise FileNotFoundError(f"Source file not found at: {RAW_CSV_PATH}")

    print(f"Reading raw dataset from: {RAW_CSV_PATH}")
    fuel_df = pd.read_csv(RAW_CSV_PATH)
    print(f"Loaded {len(fuel_df)} records.")

    # دانلود و لود دیتابیس شهرهای آمریکا از طریق pgeocode
    print("Loading US geographical index...")
    nomi = pgeocode.Nominatim('us')
    
    # استخراج دیتای کامل تمام شهرهای آمریکا
    geo_df = nomi._data_frame.copy()
    
    # آماده‌سازی ستون‌های کلیدی جهت اتصال (Join)
    geo_df['city_clean'] = geo_df['place_name'].astype(str).str.strip().str.upper()
    geo_df['state_clean'] = geo_df['state_code'].astype(str).str.strip().str.upper()
    
    # میانگین‌گیری مختصات برای شهرهایی با چندین زیپ‌کد
    city_coords = geo_df.groupby(['city_clean', 'state_clean'])[['latitude', 'longitude']].mean().reset_index()

    fuel_df['city_clean'] = fuel_df['City'].astype(str).str.strip().str.upper()
    fuel_df['state_clean'] = fuel_df['State'].astype(str).str.strip().str.upper()

    # اتصال داده‌ها
    merged = pd.merge(fuel_df, city_coords, on=['city_clean', 'state_clean'], how='left')

    matched_count = merged['latitude'].notnull().sum()
    total_count = len(merged)
    print(f"Matched coordinates for {matched_count} / {total_count} stations ({matched_count/total_count*100:.2f}%).")

    # حذف رکوردهای بدون مختصات و مرتب‌سازی
    geocoded_df = merged.dropna(subset=['latitude', 'longitude']).copy()

    columns_to_keep = [
        'OPIS Truckstop ID', 'Truckstop Name', 'Address', 
        'City', 'State', 'Rack ID', 'Retail Price', 'latitude', 'longitude'
    ]
    geocoded_df[columns_to_keep].to_csv(OUTPUT_CSV_PATH, index=False)
    print(f"Enriched dataset successfully created at: {OUTPUT_CSV_PATH}")

if __name__ == '__main__':
    enrich_fuel_dataset()
