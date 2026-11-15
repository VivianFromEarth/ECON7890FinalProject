import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

# -----------------------------------------------------------------------------
# 0. Page Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="HK Cafe Selection & Rent Pressure Analysis System",
    page_icon="☕",
    layout="wide"
)

st.title("☕ Hong Kong Specialty Cafe Selection & District Rent Analysis System")
st.caption("Empowering F&B entrepreneurs to evaluate district potential, analyze competitor density, and discover commercial leasing opportunities.")

# -----------------------------------------------------------------------------
# 1. Helper Functions: Data Loading & File Timestamp Checking
# -----------------------------------------------------------------------------
def get_file_last_modified_time(file_path):
    """Get the last modified timestamp of a data file formatted as a readable string."""
    if os.path.exists(file_path):
        timestamp = os.path.getmtime(file_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return "Never (File not found)"

@st.cache_data
def load_openrice_shops():
    """Load real cafe data from OpenRice scraper output (data/shops.csv)"""
    csv_path = "data/shops.csv"
    if os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

@st.cache_data
def load_real_rental_data():
    """Load real commercial rental listings from 28Hse scraper output (data/rent_listings_clean.csv)"""
    csv_path = "data/rent_listings_clean.csv"
    if os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def get_business_districts():
    """Get available business districts matching the scrapers"""
    return ["Sheung Wan", "Sai Ying Pun", "Causeway Bay", "Tsim Sha Tsui", "Sham Shui Po"]

# -----------------------------------------------------------------------------
# 2. Sidebar: Control Panel & Live Data Sync Management
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🎛️ Filter & Search Control Panel")
    
    # --- Form: Filter & Search ---
    with st.form(key="search_form"):
        st.subheader("📍 1. District Selection")
        selected_district = st.selectbox(
            "Select Target District:",
            options=get_business_districts()
        )

        st.divider()

        st.subheader("🏪 2. Rental Property Filters")
        price_range = st.slider(
            "Monthly Rent Range (HKD):", 
            min_value=1000, 
            max_value=100000, 
            value=(10000, 60000), 
            step=1000
        )
        min_size = st.number_input("Minimum Area (sq.ft.):", min_value=50, max_value=2000, value=300, step=50)

        st.divider()

        st.subheader("🔍 3. Keyword Search")
        search_keyword = st.text_input(
            "Enter keyword (street/building/cafe name):", 
            placeholder="e.g., Queen's Road..."
        )
        
        submit_search = st.form_submit_button("Search", use_container_width=True)

    st.markdown("---")
    
    # --- Data Source Live Update & Timestamp Section ---
    st.header("🔄 Live Data Sync Center")
    
    # 1. OpenRice Data Update Control
    st.subheader("☕ OpenRice Shops Data")
    openrice_time = get_file_last_modified_time("data/shops.csv")
    st.caption(f"🕒 Last Updated: {openrice_time}")
    
    if st.button("🔄 Click to Run OpenRice Scraper", use_container_width=True):
        with st.spinner("Scraping live OpenRice cafes & reviews... Please wait, this may take a moment."):
            try:
                from src.scrape_openrice import main as run_openrice_scraper
                run_openrice_scraper()
                load_openrice_shops.clear()
                st.success("OpenRice data updated successfully!")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"OpenRice update failed: {e}")
                
    st.info("💡 **Note**: Large data volume. Frequent updates are not recommended.")

    st.markdown("###")

    # 2. 28Hse Rental Data Update Control
    st.subheader("🏢 28Hse Rental Listings")
    rental_time = get_file_last_modified_time("data/rent_listings_clean.csv")
    st.caption(f"🕒 Last Updated: {rental_time}")
    
    if st.button("🔄 Click to Run 28Hse Scraper", use_container_width=True):
        with st.spinner("Scraping live commercial lease listings from 28Hse... Please wait."):
            try:
                from src.scrape_28hse import main as run_28hse_scraper
                run_28hse_scraper()
                load_real_rental_data.clear()
                st.success("28Hse rental listings updated successfully!")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"28Hse update failed: {e}")
                
    st.info("💡 **Tip**: Property listings change frequently. Click to refresh live leasing info.")

# -----------------------------------------------------------------------------
# 3. Main Dashboard Layout & Data Integration
# -----------------------------------------------------------------------------
shops_df = load_openrice_shops()
rentals_df = load_real_rental_data()

if submit_search:
    st.success(f"Filters applied successfully for [{selected_district}]!")

st.header(f"📍 Currently Analyzed District: {selected_district}")
if search_keyword:
    st.info(f"Active search keyword: **{search_keyword}**")


total_cafes = 0
avg_price_mid = None
has_real_price = False

if not shops_df.empty and "district_en" in shops_df.columns:
    district_shops = shops_df[shops_df["district_en"] == selected_district]
    total_cafes = len(district_shops)
    if total_cafes > 0 and "price_mid_hkd" in district_shops.columns:
        valid_prices = pd.to_numeric(district_shops["price_mid_hkd"], errors="coerce").dropna()
        if not valid_prices.empty:
            avg_price_mid = valid_prices.mean()
            has_real_price = True
else:
    district_shops = pd.DataFrame()

display_avg_spend = avg_price_mid if has_real_price else None

avg_sqft_rent_val = None
has_real_rent = False

if not rentals_df.empty and "district" in rentals_df.columns:
    district_rentals = rentals_df[rentals_df["district"] == selected_district]
    if not district_rentals.empty and "rent_psf" in district_rentals.columns:
        valid_psf = pd.to_numeric(district_rentals["rent_psf"], errors="coerce").dropna()
        if not valid_psf.empty:
            avg_sqft_rent_val = valid_psf.mean()
            has_real_rent = True
else:
    district_rentals = pd.DataFrame()

display_avg_rent = avg_sqft_rent_val if has_real_rent else None

if has_real_price and has_real_rent and display_avg_spend is not None and display_avg_spend > 0:
    est_monthly_rent = display_avg_rent * 400
    est_monthly_rev = display_avg_spend * 120 * 30
    rent_to_rev_ratio = est_monthly_rent / est_monthly_rev
    rpi_score = min(10.0, max(1.0, round((rent_to_rev_ratio / 0.35) * 10.0, 1)))
    rpi_label = "Medium-High" if rpi_score > 7.0 else "Moderate"
    rpi_color = "inverse" if rpi_score > 7.0 else "normal"
else:
    rpi_score = None
    rpi_label = "No Data"
    rpi_color = "off"

# --- Module 1: Core Economic & Business Metrics ---
st.subheader("📊 Core Business Metrics Overview")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Avg. Spend / Customer",
        f"HKD ${display_avg_spend:.1f}" if display_avg_spend is not None else "None",
        help="Calculated from OpenRice shops.csv" if has_real_price else "No data available. Run OpenRice scraper."
    )
with col2:
    st.metric(
        "Avg. Rent / Sq.Ft.",
        f"HKD ${display_avg_rent:.1f}" if display_avg_rent is not None else "None",
        help="Calculated from 28Hse rent_listings_clean.csv" if has_real_rent else "No data available. Run 28Hse scraper."
    )
with col3:
    st.metric(
        "Rent Pressure Index",
        f"{rpi_score:.1f} / 10" if rpi_score is not None else "None",
        delta=rpi_label if rpi_score is not None else None,
        delta_color=rpi_color
    )
with col4:
    st.metric(
        "Specialty Cafes in District",
        f"{total_cafes} shops" if total_cafes > 0 else "None"
    )

st.divider()

# --- Module 2: Existing Competitor Cafes in District (OpenRice Data) ---
st.subheader("☕ Existing Specialty Cafes in District (OpenRice Overview)")
if not district_shops.empty:
    display_cafes = district_shops[[
        "name", "street_clean", "price_band", "score_overall", "n_review", "detail_url"
    ]].copy()
    display_cafes.columns = ["Cafe Name", "Street", "Price Band", "OpenRice Score", "Total Reviews", "OpenRice Link"]
    
    st.dataframe(
        display_cafes.head(10),
        use_container_width=True,
        hide_index=True,
        column_config={
            "OpenRice Link": st.column_config.LinkColumn(
                "OpenRice URL",
                display_text="🔗 View on OpenRice",
                help="Click to open cafe page on OpenRice"
            ),
            "OpenRice Score": st.column_config.NumberColumn("Score", format="%.1f")
        }
    )
    st.caption(f"Showing top cafes out of {total_cafes} total specialty coffee shops found in {selected_district}.")
else:
    st.warning(f"No OpenRice cafe data found for [{selected_district}]. Click the **'Click to Run OpenRice Scraper'** button in the sidebar to fetch live data.")

st.divider()

# --- Module 3: Filterable Real Rental Listings Table with Clickable Links (28Hse Data) ---
st.subheader("🏢 Available Rental Properties in District (Powered by 28Hse Scraper)")

if not district_rentals.empty:
    # Apply sidebar slider & number input filters
    filtered_rentals = district_rentals[
        (district_rentals["rent_monthly"] >= price_range[0]) &
        (district_rentals["rent_monthly"] <= price_range[1]) &
        (district_rentals["area_sqft_gross"] >= min_size)
    ]
    
    # Filter by search keyword if provided
    if search_keyword:
        filtered_rentals = filtered_rentals[
            filtered_rentals["title"].str.contains(search_keyword, case=False, na=False) |
            filtered_rentals["building"].str.contains(search_keyword, case=False, na=False)
        ]
    
    if not filtered_rentals.empty:
        display_rentals = filtered_rentals[[
            "title", "building", "area_sqft_gross", "rent_monthly", "rent_psf", "url"
        ]].copy()
        
        display_rentals.columns = [
            "Listing Title", "Building / Mall", "Area (sq.ft.)", 
            "Monthly Rent (HKD)", "Rent/sq.ft. (HKD)", "Listing Link"
        ]
        
        st.dataframe(
            display_rentals,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Listing Link": st.column_config.LinkColumn(
                    "Property Listing URL",
                    display_text="🔗 View on 28Hse",
                    help="Click to open the live 28Hse property page"
                ),
                "Monthly Rent (HKD)": st.column_config.NumberColumn(
                    "Monthly Rent (HKD)",
                    format="HK$ %d"
                ),
                "Rent/sq.ft. (HKD)": st.column_config.NumberColumn(
                    "Rent/sq.ft. (HKD)",
                    format="HK$ %.1f"
                ),
                "Area (sq.ft.)": st.column_config.NumberColumn(
                    "Area (sq.ft.)",
                    format="%d sq.ft."
                )
            }
        )
        st.caption(f"Found {len(display_rentals)} matching rental properties in {selected_district}.")
    else:
        st.info(f"No rental properties found in [{selected_district}] matching your current price range or search keywords.")
else:
    st.warning(f"⚠️ No rental properties found for [{selected_district}]. Click the **'🔄 Click to Run 28Hse Scraper'** button in the sidebar to fetch live leasing data.")