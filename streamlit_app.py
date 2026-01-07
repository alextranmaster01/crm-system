import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import io
import time
import json
import mimetypes
import numpy as np
import altair as alt # Thêm thư viện vẽ biểu đồ

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO
# =============================================================================
APP_VERSION = "V6032 - DASHBOARD UPGRADE & METRICS"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="💎")

# CSS UI
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 18px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 10px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    [data-testid="stDataFrame"] > div { max-height: 750px; }
    .highlight-low { background-color: #ffcccc !important; color: red !important; font-weight: bold; }
    
    /* CSS CHO CÁC NÚT BẤM: NỀN TỐI - CHỮ SÁNG */
    div.stButton > button { 
        width: 100%; 
        border-radius: 5px; 
        font-weight: bold; 
        background-color: #262730; /* Nền tối */
        color: #ffffff; /* Chữ trắng */
        border: 1px solid #4e4e4e;
    }
    div.stButton > button:hover {
        background-color: #444444;
        color: #ffffff;
        border-color: #ffffff;
    }
    
    /* STYLE CHO TOTAL VIEW */
    .total-view {
        font-size: 20px;
        font-weight: bold;
        color: #00FF00; /* Màu xanh lá nổi bật */
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
        text-align: right;
        margin-top: 10px;
        border: 1px solid #4e4e4e;
    }

    /* --- FIX: STYLE CHO DÒNG TOTAL (DÒNG CUỐI CÙNG TRONG TABLE) MÀU VÀNG --- */
    [data-testid="stDataFrame"] table tbody tr:last-child {
        background-color: #FFD700 !important; /* Màu vàng */
        color: #000000 !important; /* Chữ đen */
        font-weight: 900 !important;
    }
    [data-testid="stDataFrame"] table tbody tr:last-child td {
        color: #000000 !important;
        background-color: #FFD700 !important; /* Force nền vàng cho từng ô */
        font-weight: bold !important;
    }
    </style>""", unsafe_allow_html=True)

# LIBRARIES & CONNECTIONS
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Border, Side, Alignment, Font
except ImportError:
    st.error("⚠️ Thiếu thư viện. Vui lòng chạy lệnh: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl altair")
    st.stop()

# CONNECT SERVER
try:
    if "supabase" not in st.secrets or "google_oauth" not in st.secrets:
        st.error("⚠️ Chưa cấu hình secrets.toml. Vui lòng kiểm tra lại file secrets.")
        st.stop()

    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi Config: {e}"); st.stop()

# =============================================================================
# 2. HÀM HỖ TRỢ (UTILS)
# =============================================================================

def get_drive_service():
    try:
        cred_info = OAUTH_INFO
        creds = Credentials(None, refresh_token=cred_info["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=cred_info["client_id"], client_secret=cred_info["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

# Hàm tạo folder đệ quy
def get_or_create_folder_hierarchy(srv, path_list, parent_id):
    current_parent_id = parent_id
    for folder_name in path_list:
        q = f"'{current_parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = srv.files().list(q=q, fields="files(id)").execute().get('files', [])
        
        if results:
            current_parent_id = results[0]['id']
        else:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [current_parent_id]
            }
            folder = srv.files().create(body=file_metadata, fields='id').execute()
            current_parent_id = folder.get('id')
            try: srv.permissions().create(fileId=current_parent_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            except: pass
            
    return current_parent_id

def upload_to_drive_structured(file_obj, path_list, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, path_list, ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        return folder_link, file_id
    except Exception as e: 
        st.error(f"Lỗi upload Drive: {e}")
        return "", ""

def upload_to_drive_simple(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, [sub_folder], ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200", file_id
    except: return "", ""

def search_file_in_drive_by_name(name_contains):
    srv = get_drive_service()
    if not srv: return None, None, None
    try:
        q = f"name contains '{name_contains}' and trashed=false"
        results = srv.files().list(q=q, fields="files(id, name, parents)").execute().get('files', [])
        if results:
            return results[0]['id'], results[0]['name'], (results[0]['parents'][0] if 'parents' in results[0] else None)
        return None, None, None
    except: return None, None, None

def download_from_drive(file_id):
    srv = get_drive_service()
    if not srv: return None
    try:
        request = srv.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        
        # --- FIX QUAN TRỌNG: Đưa con trỏ về đầu file để pandas đọc được ---
        fh.seek(0) 
        return fh
    except: return None

def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def to_float(val):
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").upper()
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(nums[0]) if nums else 0.0
    except: return 0.0

def fmt_num(x): 
    try:
        if x is None: return "0"
        val = float(x)
        if val.is_integer(): return "{:,.0f}".format(val)
        else:
            s = "{:,.3f}".format(val)
            return s.rstrip('0').rstrip('.')
    except: return "0"

# --- NEW: FORMAT 2 DECIMAL PLACES (FOR QUOTE TAB) ---
def fmt_float_2(x):
    try:
        if x is None: return "0.00"
        val = float(x)
        return "{:,.2f}".format(val)
    except: return "0.00"

def clean_key(s): return safe_str(s).lower()

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime): dt_order = order_date_str
        else:
            try: dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
            except: dt_order = datetime.now()
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

def load_data(table, order_by="id", ascending=True):
    try:
        query = supabase.table(table).select("*")
        res = query.execute()
        df = pd.DataFrame(res.data)
        
        if not df.empty:
            # Drop cột 'id' nếu không cần thiết
            if table != "crm_tracking" and table != "crm_payments" and 'id' in df.columns: 
                df = df.drop(columns=['id'])
            
            # Sort bằng Pandas nếu có cột order_by
            if order_by in df.columns:
                df = df.sort_values(by=order_by, ascending=ascending)
            
        return df
    except Exception as e:
        # st.error(f"Lỗi load data {table}: {e}") # Có thể uncomment để debug
        return pd.DataFrame()

# =============================================================================
# 3. LOGIC TÍNH TOÁN CORE (UPDATED: MANUAL OVERRIDE SUPPORT & NEW PROFIT FORMULA)
# =============================================================================
def recalculate_quote_logic(df, params):
    # 1. Chuyển đổi dữ liệu sang số (Float) để tính toán
    cols_money_input = [
        "Q'ty", "Buying price(VND)", "Buying price(RMB)", "Exchange rate",
        "AP price(VND)", "Unit price(VND)", 
        "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", 
        "Transportation", "Management fee(%)", "Payback(%)"
    ]
    
    # Tạo cột nếu chưa có (để tránh lỗi) và chuyển sang số
    for c in cols_money_input:
        if c not in df.columns: df[c] = 0.0
        df[c] = df[c].apply(to_float)

    # 2. TÍNH TOÁN CÁC CỘT TOTAL & LOGIC CƠ BẢN (Luôn chạy)
    # Buying VND luôn = RMB * Rate 
    df["Buying price(VND)"] = df["Buying price(RMB)"] * df["Exchange rate"]
    
    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    
    # GAP là kết quả tính toán
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]

    # 3. TÍNH LỢI NHUẬN (PROFIT)
    # --- UPDATED FORMULA ---
    # Profit = Total price - (Total buying price VND + GAP + End user + Buyer + Import tax + VAT + Transportation + Management fee) + Payback
    
    # Lưu ý: GAP trong công thức này là giá trị GAP thô (Total - AP Total) như yêu cầu.
    
    # Cộng dồn các chi phí (bao gồm GAP)
    cost_ops = (df["Total buying price(VND)"] + 
                df["GAP"] +
                df["End user(%)"] + 
                df["Buyer(%)"] + 
                df["Import tax(%)"] + 
                df["VAT"] + 
                df["Transportation"] + 
                df["Management fee(%)"])

    # Lợi nhuận = Doanh thu - Chi phí + Payback
    df["Profit(VND)"] = df["Total price(VND)"] - cost_ops + df["Payback(%)"]
    
    # Tính % Lợi nhuận
    df["Profit_Pct_Raw"] = df.apply(lambda row: (row["Profit(VND)"] / row["Total price(VND)"] * 100) if row["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    
    # Cảnh báo
    def set_warning(row):
        if "KHÔNG KHỚP" in str(row["Cảnh báo"]): return row["Cảnh báo"]
        return "⚠️ LOW" if row["Profit_Pct_Raw"] < 10 else "✅ OK"
    df["Cảnh báo"] = df.apply(set_warning, axis=1)

    return df

# --- IMPROVED FORMULA PARSER ---
def parse_formula(formula, buying_price, ap_price):
    if not formula: return 0.0
    
    # 1. Normalize: Uppercase and Strip
    s = str(formula).strip().upper()
    
    # 2. Handle '='
    if s.startswith("="): s = s[1:]
    
    # 3. Replace Keywords (Longer first to avoid substrings issue)
    # Handle 'AP PRICE' explicitly before 'AP'
    s = s.replace("AP PRICE", str(ap_price))
    s = s.replace("BUYING PRICE", str(buying_price))
    
    # Handle shorthands
    s = s.replace("AP", str(ap_price))
    s = s.replace("BUY", str(buying_price))
    
    # 4. Cleanup Syntax
    s = s.replace(",", ".").replace("%", "/100").replace("X", "*")
    
    # 5. Filter Unsafe Characters (Only digits, dots, math ops)
    s = re.sub(r'[^0-9.+\-*/()]', '', s)
    
    try: 
        if not s: return 0.0
        return float(eval(s))
    except: return 0.0

# =============================================================================
# 4. GIAO DIỆN CHÍNH
# =============================================================================
t1, t2, t3, t4, t5, t6 = st.tabs(["📊 DASHBOARD", "📦 KHO HÀNG", "💰 BÁO GIÁ", "📑 QUẢN LÝ PO", "🚚 TRACKING", "⚙️ MASTER DATA"])

# =============================================================================
# --- TAB 1: DASHBOARD (UPDATED) ---
# =============================================================================
with t1:
    # --- 1. HEADER & ADMIN RESET ---
    c_h1, c_h2 = st.columns([3, 1])
    with c_h1:
        if st.button("🔄 REFRESH DATA"): st.cache_data.clear(); st.rerun()
    
    with c_h2:
        with st.popover("⚠️ RESET SYSTEM"):
            st.markdown("**Xóa dữ liệu giao dịch (Giữ lại Khách/NCC/Kho)**")
            adm_pass_reset = st.text_input("Mật khẩu Admin", type="password", key="pass_reset_db")
            if st.button("🔴 XÓA SẠCH LỊCH SỬ"):
                if adm_pass_reset == "admin":
                    try:
                        # Xóa các bảng Transaction (Lịch sử, PO, Tracking, Payment)
                        supabase.table("crm_shared_history").delete().neq("id", 0).execute()
                        supabase.table("db_customer_orders").delete().neq("id", 0).execute()
                        supabase.table("db_supplier_orders").delete().neq("id", 0).execute()
                        supabase.table("crm_tracking").delete().neq("id", 0).execute()
                        supabase.table("crm_payments").delete().neq("id", 0).execute()
                        
                        st.toast("✅ Đã reset toàn bộ hệ thống về trạng thái ban đầu!", icon="🗑️")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi khi xóa: {e}")
                else:
                    st.error("Sai mật khẩu!")

    # --- 2. LOAD DATA ---
    db_cust_po = load_data("db_customer_orders") # Nguồn PO Khách hàng (Doanh thu thực)
    db_hist = load_data("crm_shared_history")    # Nguồn Lịch sử (Để tính Profit & Cost theo công thức)
    db_items = load_data("crm_purchases")        # Master Data

    # --- 3. METRICS CALCULATION ---
    # Doanh thu = Tổng PO Khách Hàng
    revenue_total = db_cust_po['total_price'].apply(to_float).sum() if not db_cust_po.empty else 0
    
    # Lợi nhuận & Chi phí (Lấy từ bảng History đã tính toán kỹ)
    profit_total = 0
    cost_total = 0
    
    if not db_hist.empty:
        # Profit được lưu trực tiếp trong history
        profit_total = db_hist['profit_vnd'].apply(to_float).sum()
        # Revenue trong history (dùng để tính cost tương ứng)
        rev_hist_sum = db_hist['total_price_vnd'].apply(to_float).sum()
        # Cost = Revenue (History) - Profit
        cost_total = rev_hist_sum - profit_total
        
        # Nếu chưa có history nhưng có PO (trường hợp hiếm), cost = 0 hoặc logic khác
        # Ở đây ưu tiên hiển thị từ History để khớp công thức.
    
    # --- 4. KPI CARDS ---
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU (Total PO)</h3><h1>{fmt_num(revenue_total)}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ (Formula)</h3><h1>{fmt_num(cost_total)}</h1></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN (Est.)</h3><h1>{fmt_num(profit_total)}</h1></div>", unsafe_allow_html=True)

    st.divider()

    # --- 5. CHARTS ---
    if not db_hist.empty:
        # Pre-process Data
        db_hist['date_dt'] = pd.to_datetime(db_hist['date'], format="%Y-%m-%d", errors='coerce')
        db_hist['Month'] = db_hist['date_dt'].dt.strftime('%Y-%m')
        
        # Map Type
        type_map = {}
        if not db_items.empty:
            for r in db_items.to_dict('records'):
                type_map[clean_key(r.get('item_code'))] = safe_str(r.get('type', 'Other'))
        
        db_hist['Type'] = db_hist['item_code'].apply(lambda x: type_map.get(clean_key(x), "Other"))
        db_hist['Revenue'] = db_hist['total_price_vnd'].apply(to_float)
        
        # -----------------------------------------------------------
        # CHART 1: CỘT & TREND (DOANH SỐ THEO THÁNG & KHÁCH HÀNG)
        # -----------------------------------------------------------
        st.subheader("📈 Xu hướng Doanh số & Khách hàng")
        
        # Group Data
        chart_data = db_hist.groupby(['Month', 'customer'])['Revenue'].sum().reset_index()
        
        # Base Chart
        base = alt.Chart(chart_data).encode(x=alt.X('Month', title='Tháng'))
        
        # Bar Chart
        bar = base.mark_bar().encode(
            y=alt.Y('Revenue', title='Doanh thu (VND)'),
            color=alt.Color('customer', title='Khách hàng'),
            tooltip=['Month', 'customer', alt.Tooltip('Revenue', format=',.0f')]
        )
        
        # Text Labels for Bar (Total per month stack or per segment? 
        # Altair stack labels are tricky. We will label the total per month using the line data logic or simple text on bars)
        # Cách đơn giản nhất: Label trên từng đoạn bar
        text_bar = base.mark_text(dy=3, color='white').encode(
            y=alt.Y('Revenue', stack='zero'),
            text=alt.Text('Revenue', format='.2s') # Format gọn (vd: 10M)
        )

        # Trend Line (Total per Month)
        line_data = db_hist.groupby(['Month'])['Revenue'].sum().reset_index()
        base_line = alt.Chart(line_data).encode(x='Month')
        
        line = base_line.mark_line(color='red', point=True).encode(
            y='Revenue',
            tooltip=[alt.Tooltip('Revenue', format=',.0f', title='Tổng Trend')]
        )
        
        # Labels for Trend Line (Hiển thị tổng doanh số trên đỉnh đường line)
        text_line = base_line.mark_text(align='center', baseline='bottom', dy=-10, color='red').encode(
            y='Revenue',
            text=alt.Text('Revenue', format=',.0f')
        )
        
        st.altair_chart((bar + text_bar + line + text_line).interactive(), use_container_width=True)
        
        # -----------------------------------------------------------
        # CHART 2 & 3: PIE CHARTS (CƠ CẤU) - CÓ LABEL % VÀ GIÁ TRỊ
        # -----------------------------------------------------------
        st.divider()
        st.subheader("🍰 Cơ cấu Doanh số")
        col_pie1, col_pie2 = st.columns(2)
        
        # Helper function to create Pie Chart with Labels
        def create_pie_chart_with_labels(df_source, group_col, value_col, color_scheme="category20"):
            # 1. Aggregate
            df_agg = df_source.groupby(group_col)[value_col].sum().reset_index()
            # 2. Calculate Percentage & Label
            total_val = df_agg[value_col].sum()
            df_agg['Percent'] = (df_agg[value_col] / total_val * 100).round(1)
            # Tạo nhãn: "Name: 20% (1,000)"
            df_agg['Label'] = df_agg.apply(lambda x: f"{x['Percent']}% ({fmt_num(x[value_col])})", axis=1)
            
            base = alt.Chart(df_agg).encode(
                theta=alt.Theta(field=value_col, type="quantitative", stack=True)
            )
            
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color(field=group_col, type="nominal", scale=alt.Scale(scheme=color_scheme)),
                order=alt.Order(field=value_col, sort="descending"),
                tooltip=[group_col, alt.Tooltip(value_col, format=',.0f'), 'Percent']
            )
            
            text = base.mark_text(radius=140).encode(
                text=alt.Text("Label"),
                order=alt.Order(field=value_col, sort="descending"),
                color=alt.value("black") 
            )
            
            return (pie + text)

        with col_pie1:
            st.write("**Theo Khách Hàng**")
            chart_pie_cust = create_pie_chart_with_labels(db_hist, 'customer', 'Revenue', 'tableau10')
            st.altair_chart(chart_pie_cust, use_container_width=True)
            
        with col_pie2:
            st.write("**Theo Loại Sản Phẩm (Type)**")
            chart_pie_type = create_pie_chart_with_labels(db_hist, 'Type', 'Revenue', 'set2')
            st.altair_chart(chart_pie_type, use_container_width=True)
            
    else:
        st.info("Chưa có dữ liệu lịch sử để vẽ biểu đồ. Hãy tạo Báo Giá và Lưu Lịch Sử.")

# --- TAB 2: KHO HÀNG (UPDATED: DUPLICATE LOGIC & IMAGE FIX) ---
with t2:
    st.subheader("QUẢN LÝ KHO HÀNG (Excel Online)")
    c_imp, c_view = st.columns([1, 4])
    
    with c_imp:
        st.markdown("**📥 Import Kho Hàng**")
        st.caption("Excel cột A->O")
        st.info("No, Code, Name, Specs, Qty, BuyRMB, TotalRMB, Rate, BuyVND, TotalVND, Leadtime, Supplier, Images, Type, N/U/O/C")
        
        with st.expander("🛠️ Reset DB"):
            adm_pass = st.text_input("Pass", type="password", key="adm_inv")
            if st.button("⚠️ XÓA SẠCH"):
                if adm_pass == "admin":
                    supabase.table("crm_purchases").delete().neq("id", 0).execute()
                    st.success("Deleted!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass!")
        
        up_file = st.file_uploader("Upload Excel", type=["xlsx"], key="inv_up")
            
        if up_file and st.button("🚀 Kiểm tra & Import"):
            try:
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                
                # --- FIX: XỬ LÝ ẢNH THÔNG MINH (TRÁNH BỊ ĐÈ ẢNH) ---
                img_map = {}
                
                # 1. Lấy tất cả ảnh và dòng neo (anchor) của nó
                detected_images = []
                for image in getattr(ws, '_images', []):
                    try:
                        # anchor._from.row là 0-indexed. Dữ liệu bắt đầu từ Excel Row 2 (index 1).
                        # Code bên dưới loop df dùng i (0-indexed) + 2 để map.
                        # Tức là dòng 1 data (Excel Row 2) tương ứng key = 2.
                        r_idx = image.anchor._from.row + 1
                        
                        # Lấy tên để đặt tên file ảnh (Specs ở cột 4)
                        cell_specs = ws.cell(row=r_idx, column=4).value 
                        specs_val = safe_str(cell_specs)
                        safe_name = re.sub(r'[\\/*?:"<>|]', "", specs_val).strip()
                        if not safe_name: safe_name = f"NO_SPECS_R{r_idx}"
                        fname = f"{safe_name}.png"
                        
                        detected_images.append({'row': r_idx, 'name': fname, 'data': image._data()})
                    except: continue

                # 2. Sắp xếp ảnh theo thứ tự dòng xuất hiện
                detected_images.sort(key=lambda x: x['row'])

                # 3. Map ảnh vào dòng (Xử lý va chạm: Nếu dòng đã có ảnh, đẩy xuống dòng dưới)
                # Đây là fix cho trường hợp ảnh bị chồm lên dòng trên
                for img in detected_images:
                    r = img['row']
                    # Upload
                    buf = io.BytesIO(img['data'])
                    link, _ = upload_to_drive_simple(buf, "CRM_PRODUCT_IMAGES", img['name'])
                    
                    if r not in img_map:
                        img_map[r] = link
                    elif (r + 1) not in img_map:
                        # Nếu dòng r đã có ảnh, thử dòng r+1 (do ảnh bị lệch neo)
                        img_map[r + 1] = link
                    # Nếu cả r và r+1 đều có rồi thì đành chịu (hoặc ghi đè tùy logic, ở đây giữ cái đầu tiên)

                # --- HẾT PHẦN FIX ẢNH ---
                
                df = pd.read_excel(up_file, header=None, skiprows=1, dtype=str).fillna("")
                records = []
                prog = st.progress(0)
                cols_map = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", 
                            "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", 
                            "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]

                for i, r in df.iterrows():
                    d = {}
                    for idx, field in enumerate(cols_map):
                        if idx < len(r): d[field] = safe_str(r.iloc[idx])
                        else: d[field] = ""
                    has_data = d['item_code'] or d['item_name'] or d['specs']
                    if has_data:
                        # i là 0-indexed của dataframe. Excel header là row 1. Data bắt đầu row 2.
                        # i=0 tương ứng Excel Row 2.
                        # img_map dùng key = row index Excel (1-based)
                        if not d.get('image_path') and (i+2) in img_map: 
                            d['image_path'] = img_map[i+2]
                            
                        d['row_order'] = i + 1 
                        d['qty'] = to_float(d.get('qty', 0))
                        d['buying_price_rmb'] = to_float(d['buying_price_rmb'])
                        d['total_buying_price_rmb'] = to_float(d['total_buying_price_rmb'])
                        d['exchange_rate'] = to_float(d['exchange_rate'])
                        d['buying_price_vnd'] = to_float(d['buying_price_vnd'])
                        d['total_buying_price_vnd'] = to_float(d['total_buying_price_vnd'])
                        records.append(d)
                    prog.progress((i + 1) / len(df))
                
                if records:
                    # --- BƯỚC 1: KIỂM TRA TRÙNG LẶP (3 BIẾN: Code, Name, Specs) ---
                    df_db = load_data("crm_purchases")
                    
                    existing_sigs = set()
                    if not df_db.empty:
                        for r in df_db.to_dict('records'):
                            sig = (clean_key(r.get('item_code')), clean_key(r.get('item_name')), clean_key(r.get('specs')))
                            existing_sigs.add(sig)
                    
                    dups = []
                    non_dups = []
                    for rec in records:
                        sig = (clean_key(rec.get('item_code')), clean_key(rec.get('item_name')), clean_key(rec.get('specs')))
                        if sig in existing_sigs:
                            dups.append(rec)
                        else:
                            non_dups.append(rec)
                    
                    # Lưu vào session để xử lý
                    st.session_state.import_dups = dups
                    st.session_state.import_non_dups = non_dups
                    st.session_state.import_step = "confirm" if dups else "auto_import"
                    st.rerun()

            except Exception as e: 
                st.error(f"Lỗi đọc file: {e}")

        # --- LOGIC XỬ LÝ SAU KHI CLICK IMPORT ---
        step = st.session_state.get("import_step", None)
        
        if step == "confirm":
            st.warning(f"⚠️ Phát hiện {len(st.session_state.import_dups)} dòng dữ liệu bị TRÙNG LẶP (Giống hệt Code, Name & Specs)!")
            st.write("Dữ liệu trùng:")
            st.dataframe(pd.DataFrame(st.session_state.import_dups)[['item_code', 'item_name', 'specs']], hide_index=True)
            
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("✅ Chỉ Import dòng mới (Bỏ qua trùng)"):
                final_batch = st.session_state.import_non_dups
                st.session_state.final_import_list = final_batch
                st.session_state.import_step = "executing"
                st.rerun()
                
            if c_btn2.button("⚠️ Import TẤT CẢ (Chấp nhận trùng)"):
                final_batch = st.session_state.import_dups + st.session_state.import_non_dups
                st.session_state.final_import_list = final_batch
                st.session_state.import_step = "executing"
                st.rerun()

        elif step == "auto_import":
            st.session_state.final_import_list = st.session_state.import_non_dups
            st.session_state.import_step = "executing"
            st.rerun()

        elif step == "executing":
            final_list = st.session_state.get("final_import_list", [])
            if final_list:
                try:
                    chunk_ins = 100
                    for k in range(0, len(final_list), chunk_ins):
                        batch = final_list[k:k+chunk_ins]
                        # Xóa row_order nếu DB cũ không có (để tránh lỗi)
                        try:
                            supabase.table("crm_purchases").insert(batch).execute()
                        except Exception as e_ins:
                             if "row_order" in str(e_ins):
                                for rec in batch: 
                                    if 'row_order' in rec: del rec['row_order']
                                supabase.table("crm_purchases").insert(batch).execute()
                             else: raise e_ins
                             
                    st.success(f"✅ Đã import thành công {len(final_list)} dòng!")
                    st.session_state.import_step = None # Reset
                    st.session_state.import_dups = []
                    st.session_state.import_non_dups = []
                    time.sleep(1); st.cache_data.clear(); st.rerun()
                except Exception as e:
                    st.error(f"Lỗi Import SQL: {e}")
                    st.session_state.import_step = None # Reset on error

    with c_view:
        # Load data đã fix sort
        df_pur = load_data("crm_purchases", order_by="row_order", ascending=True) 
        cols_to_drop = ['created_at', 'row_order']
        df_pur = df_pur.drop(columns=[c for c in cols_to_drop if c in df_pur.columns], errors='ignore')

        # --- FIX: ĐỔI THỨ TỰ CỘT ĐỂ CỘT 'no' HOẶC 'No' LÊN ĐẦU ---
        current_cols = df_pur.columns.tolist()
        no_col = next((c for c in current_cols if c.lower() == 'no'), None)
        
        if no_col:
            current_cols.remove(no_col)
            current_cols.insert(0, no_col)
            df_pur = df_pur[current_cols]

        search = st.text_input("🔍 Tìm kiếm (Name, Code, Specs...)", key="search_pur")
        if not df_pur.empty:
            if search:
                mask = df_pur.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
                df_pur = df_pur[mask]
            
            cols_money = ["buying_price_vnd", "total_buying_price_vnd", "buying_price_rmb", "total_buying_price_rmb"]
            for c in cols_money:
                if c in df_pur.columns: df_pur[c] = df_pur[c].apply(fmt_num)

            st.dataframe(
                df_pur, 
                column_config={
                    "image_path": st.column_config.ImageColumn("Images"),
                    "item_code": st.column_config.TextColumn("Code", width="medium"),
                    "item_name": st.column_config.TextColumn("Name", width="medium"),
                    "specs": st.column_config.TextColumn("Specs", width="large"),
                    "buying_price_vnd": st.column_config.TextColumn("Buying (VND)"),
                    "total_buying_price_vnd": st.column_config.TextColumn("Total (VND)"),
                    "buying_price_rmb": st.column_config.TextColumn("Buying (RMB)"),
                    "total_buying_price_rmb": st.column_config.TextColumn("Total (RMB)"),
                    "qty": st.column_config.NumberColumn("Qty", format="%d"),
                }, 
                use_container_width=True, height=700, hide_index=True
            )
        else: st.info("Kho hàng trống.")
# --- TAB 3: BÁO GIÁ (FINAL FIX: ROUNDING LOGIC) ---

# 1. Hàm hỗ trợ xử lý số liệu hiển thị (Local scope)
def local_parse_money(val):
    """Chuyển chuỗi '1,000,000' thành số float"""
    try:
        if pd.isna(val) or str(val).strip() == "": return 0.0
        # Xóa dấu phẩy để parse số
        return float(str(val).replace(",", "").strip())
    except: return 0.0

def local_fmt_money(val):
    """Format VND: Luôn làm tròn về số nguyên, không có .00"""
    try:
        if pd.isna(val): return "0"
        # Làm tròn thành số nguyên (int) rồi mới format
        return "{:,.0f}".format(round(float(val)))
    except: return str(val)

def local_fmt_float(val):
    """Format RMB/USD: Giữ 2 số thập phân"""
    try:
        if pd.isna(val): return "0.00"
        return "{:,.2f}".format(float(val))
    except: return str(val)

# 2. HÀM TÍNH TOÁN LOGIC (ĐÃ THÊM LÀM TRÒN ĐỂ CHẶN VÒNG LẶP)
def recalculate_quote_logic(df, params):
    if df.empty: return df
    
    # Lấy tham số config
    p_end = params.get('end', 0) / 100.0
    p_buy = params.get('buy', 0) / 100.0
    p_tax = params.get('tax', 0) / 100.0
    p_vat = params.get('vat', 0) / 100.0
    p_mgmt = params.get('mgmt', 0) / 100.0
    p_pay = params.get('pay', 0) / 100.0
    v_trans = float(params.get('trans', 0))

    for idx, row in df.iterrows():
        try:
            # 1. Input
            qty = local_parse_money(row.get("Q'ty", 0))
            buy_vnd_unit = local_parse_money(row.get("Buying price(VND)", 0))
            ap_vnd_unit = local_parse_money(row.get("AP price(VND)", 0))
            unit_price = local_parse_money(row.get("Unit price(VND)", 0))
            buy_rmb = local_parse_money(row.get("Buying price(RMB)", 0))

            # 2. Totals cơ bản (LÀM TRÒN NGAY TẠI ĐÂY)
            # VND làm tròn về 0 số lẻ (round(x, 0))
            # RMB làm tròn về 2 số lẻ (round(x, 2))
            
            total_buy_vnd = round(buy_vnd_unit * qty, 0)
            total_buy_rmb = round(buy_rmb * qty, 2)
            ap_total = round(ap_vnd_unit * qty, 0)
            total_price = round(unit_price * qty, 0)
            
            # 3. GAP
            gap = total_price - ap_total

            # 4. Các chi phí (Cũng làm tròn VND về 0)
            val_imp_tax = round(total_buy_vnd * p_tax, 0)
            val_end = round(ap_total * p_end, 0)
            val_buyer = round(total_price * p_buy, 0)
            val_vat = round(total_price * p_vat, 0)
            val_mgmt = round(total_price * p_mgmt, 0)
            val_trans = round(v_trans, 0)
            val_payback = round(gap * p_pay, 0)

            # 5. TÍNH PROFIT
            sum_deductions = (
                total_buy_vnd + 
                gap + 
                val_end + 
                val_buyer + 
                val_imp_tax + 
                val_vat + 
                val_trans + 
                val_mgmt
            )
            
            val_profit = total_price - sum_deductions + val_payback
            val_profit = round(val_profit, 0) # Làm tròn Profit
            
            # Tính % Profit
            pct_profit = 0.0
            if total_price != 0:
                pct_profit = (val_profit / total_price) * 100

            # 6. Gán giá trị vào DataFrame
            # Lưu ý: Các cột tiền tệ đã được làm tròn ở trên, giờ chỉ cần format string
            
            df.at[idx, "Total buying price(rmb)"] = local_fmt_float(total_buy_rmb)
            df.at[idx, "Total buying price(VND)"] = local_fmt_money(total_buy_vnd)
            df.at[idx, "AP total price(VND)"] = local_fmt_money(ap_total)
            df.at[idx, "Total price(VND)"] = local_fmt_money(total_price)
            df.at[idx, "GAP"] = local_fmt_money(gap)
            
            df.at[idx, "Import tax(%)"] = local_fmt_money(val_imp_tax)
            df.at[idx, "End user(%)"] = local_fmt_money(val_end)
            df.at[idx, "Buyer(%)"] = local_fmt_money(val_buyer)
            df.at[idx, "VAT"] = local_fmt_money(val_vat)
            df.at[idx, "Management fee(%)"] = local_fmt_money(val_mgmt)
            df.at[idx, "Transportation"] = local_fmt_money(val_trans)
            df.at[idx, "Payback(%)"] = local_fmt_money(val_payback)
            
            df.at[idx, "Profit(VND)"] = local_fmt_money(val_profit)
            df.at[idx, "Profit(%)"] = f"{pct_profit:.1f}%"
            
            # Cột ẩn
            df.at[idx, "Profit_Pct_Raw"] = pct_profit

        except Exception as e:
            continue
            
    return df

with t3:
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    
    # =============================================================================
    # [ADMIN SECTION: GIỮ NGUYÊN]
    # =============================================================================
    with st.expander("🛠️ ADMIN: QUẢN LÝ LỊCH SỬ BÁO GIÁ"):
        c_adm1, c_adm2 = st.columns([3, 1])
        with c_adm1:
            st.warning("⚠️ Chức năng này sẽ xóa toàn bộ dữ liệu trong bảng Lịch sử báo giá (crm_shared_history).")
        with c_adm2:
            adm_pass_q = st.text_input("Mật khẩu Admin", type="password", key="pass_reset_quote_tab3")
            if st.button("🔴 XÓA HẾT LỊCH SỬ", key="btn_clear_hist_tab3"):
                if adm_pass_q == "admin": 
                    try:
                        supabase.table("crm_shared_history").delete().neq("id", 0).execute()
                        st.toast("✅ Đã xóa toàn bộ lịch sử báo giá!", icon="🗑️")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi khi xóa DB: {e}")
                else:
                    st.error("Sai mật khẩu Admin!")

    # ------------------ TRA CỨU LỊCH SỬ (GIỮ NGUYÊN) ------------------
    with st.expander("🔎 TRA CỨU & TRẠNG THÁI BÁO GIÁ", expanded=False):
        c_src1, c_src2 = st.columns(2)
        search_kw = c_src1.text_input("Nhập từ khóa (Tên Khách, Quote No, Code, Name, Date)", help="Tìm kiếm trong lịch sử")
        up_src = c_src2.file_uploader("Hoặc Import Excel kiểm tra", type=["xlsx"], key="src_up")
        
        if st.button("Kiểm tra trạng thái"):
            df_hist = load_data("crm_shared_history")
            df_po = load_data("db_customer_orders")
            df_items = load_data("crm_purchases") 

            item_map = {}
            if not df_items.empty:
                for r in df_items.to_dict('records'):
                    k = clean_key(r['item_code'])
                    item_map[k] = f"{safe_str(r['item_name'])} {safe_str(r['specs'])}"

            po_map = {}
            if not df_po.empty:
                for r in df_po.to_dict('records'):
                    k = f"{clean_key(r['customer'])}_{clean_key(r['item_code'])}"
                    po_map[k] = r['po_number']

            results = []
            if search_kw and not df_hist.empty:
                def check_row(row):
                    kw = search_kw.lower()
                    if kw in str(row.get('customer','')).lower(): return True
                    if kw in str(row.get('quote_no','')).lower(): return True
                    if kw in str(row.get('item_code','')).lower(): return True
                    if kw in str(row.get('date','')).lower(): return True
                    code = clean_key(row['item_code'])
                    info = item_map.get(code, "").lower()
                    if kw in info: return True
                    return False
                
                mask = df_hist.apply(check_row, axis=1)
                found = df_hist[mask]
                for _, r in found.iterrows():
                    key = f"{clean_key(r['customer'])}_{clean_key(r['item_code'])}"
                    po_found = po_map.get(key, "")
                    code_info = item_map.get(clean_key(r['item_code']), "")
                    results.append({
                        "Trạng thái": "✅ Đã báo giá", "Customer": r['customer'], "Date": r['date'],
                        "Item Code": r['item_code'], "Info": code_info, 
                        "Unit Price": fmt_float_2(r['unit_price']),
                        "Quote No": r['quote_no'], "PO No": po_found if po_found else "---"
                    })
            
            if up_src:
                try:
                    df_check = pd.read_excel(up_src, dtype=str).fillna("")
                    cols_check = {clean_key(c): c for c in df_check.columns}
                    for i, r in df_check.iterrows():
                        code = ""; name = ""; specs = ""
                        for k, col in cols_check.items():
                            if "code" in k: code = safe_str(r[col])
                            elif "name" in k: name = safe_str(r[col])
                            elif "specs" in k: specs = safe_str(r[col])
                        match = pd.DataFrame()
                        if not df_hist.empty:
                            if code: match = df_hist[df_hist['item_code'].str.contains(code, case=False, na=False)]
                        if not match.empty:
                            for _, m in match.iterrows():
                                key = f"{clean_key(m['customer'])}_{clean_key(m['item_code'])}"
                                po_found = po_map.get(key, "")
                                results.append({
                                    "Trạng thái": "✅ Đã báo giá", "Customer": m['customer'], "Date": m['date'],
                                    "Item Code": m['item_code'], "Info": item_map.get(clean_key(m['item_code']), ""),
                                    "Unit Price": fmt_float_2(m['unit_price']), "Quote No": m['quote_no'], "PO No": po_found
                                })
                        else:
                            results.append({
                                "Trạng thái": "❌ Chưa báo giá", "Item Code": code, "Customer": "---", 
                                "Date": "---", "Unit Price": "---", "Quote No": "---", "PO No": "---"
                            })
                except Exception as e: st.error(f"Lỗi file: {e}")

            if results: st.dataframe(pd.DataFrame(results), use_container_width=True)
            else: st.info("Không tìm thấy kết quả.")

    with st.expander("📂 XEM CHI TIẾT FILE LỊCH SỬ (COST & LỢI NHUẬN)", expanded=False):
        df_hist_idx = load_data("crm_shared_history", order_by="date")
        if not df_hist_idx.empty:
            df_hist_idx['display'] = df_hist_idx.apply(lambda x: f"{x['date']} | {x['customer']} | Quote: {x['quote_no']}", axis=1)
            unique_quotes = df_hist_idx['display'].unique()
            filtered_quotes = unique_quotes
            if search_kw: filtered_quotes = [q for q in unique_quotes if search_kw.lower() in q.lower()]
            sel_quote_hist = st.selectbox("Chọn báo giá cũ để xem chi tiết:", [""] + list(filtered_quotes))
            
            if sel_quote_hist:
                parts = sel_quote_hist.split(" | ")
                if len(parts) >= 3:
                    q_no = parts[2].replace("Quote: ", "").strip()
                    cust = parts[1].strip()
                    
                    if 'loaded_quote_id' not in st.session_state: st.session_state.loaded_quote_id = None
                    
                    hist_config_row = df_hist_idx[
                        (df_hist_idx['quote_no'] == q_no) & 
                        (df_hist_idx['customer'] == cust)
                    ].iloc[0] if not df_hist_idx.empty else None
                    
                    config_loaded = {}
                    
                    if hist_config_row is not None and 'config_data' in hist_config_row and hist_config_row['config_data']:
                        try:
                            config_loaded = json.loads(hist_config_row['config_data'])
                        except: pass
                    
                    if not config_loaded:
                          cfg_search_name = f"CONFIG_{q_no}_{cust}"
                          fid_cfg, _, _ = search_file_in_drive_by_name(cfg_search_name)
                          if fid_cfg:
                              fh_cfg = download_from_drive(fid_cfg)
                              if fh_cfg:
                                  try:
                                      df_cfg = pd.read_excel(fh_cfg)
                                      if not df_cfg.empty: config_loaded = df_cfg.iloc[0].to_dict()
                                  except: pass

                    if config_loaded:
                        st.info(f"📊 **CẤU HÌNH CHI PHÍ (ĐÃ LOAD):** "
                                f"End User: {config_loaded.get('end')}% | Buyer: {config_loaded.get('buy')}% | "
                                f"Tax: {config_loaded.get('tax')}% | VAT: {config_loaded.get('vat')}% | "
                                f"Payback: {config_loaded.get('pay')}% | Mgmt: {config_loaded.get('mgmt')}% | "
                                f"Trans: {fmt_num(config_loaded.get('trans'))}")
                        
                        if sel_quote_hist != st.session_state.loaded_quote_id:
                            keys_load = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
                            for k in keys_load:
                                val_str = str(config_loaded.get(k, 0))
                                st.session_state[f"pct_{k}"] = val_str
                                st.session_state[f"input_{k}"] = val_str 
                            
                            st.session_state.loaded_quote_id = sel_quote_hist
                            st.toast("✅ Đã load cấu hình thành công!", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                    else:
                        st.warning("⚠️ Báo giá này được tạo từ phiên bản cũ, chưa lưu cấu hình chi phí.")

                    search_name = f"HIST_{q_no}_{cust}"
                    fid, fname, pid = search_file_in_drive_by_name(search_name)
                    if pid:
                          folder_link = f"https://drive.google.com/drive/folders/{pid}"
                          st.markdown(f"👉 **[Mở Folder chứa file này trên Google Drive]({folder_link})**", unsafe_allow_html=True)
                    if fid and st.button(f"Tải file chi tiết: {fname}"):
                          fh = download_from_drive(fid)
                          if fh:
                              try:
                                  df_csv = pd.read_csv(fh, encoding='utf-8-sig', on_bad_lines='skip')
                                  st.success("Đã tải xong!")
                                  st.dataframe(df_csv, use_container_width=True)
                              except Exception as e: st.error(f"Lỗi đọc file CSV: {e}")
                          else: st.error("Không tải được file.")
                    elif not fid: st.warning(f"Không tìm thấy file chi tiết trên Drive (HIST_{q_no}...).")
        else: st.info("Chưa có lịch sử.")

    st.divider()
    st.subheader("TÍNH TOÁN & LÀM BÁO GIÁ")
    
    c1, c2, c3 = st.columns([2, 2, 1])
    cust_db = load_data("crm_customers")
    cust_list = cust_db["short_name"].tolist() if not cust_db.empty else []
    cust_name = c1.selectbox("Chọn Khách Hàng", [""] + cust_list)
    quote_no = c2.text_input("Số Báo Giá", key="q_no")
    
    c3.markdown('<div class="dark-btn">', unsafe_allow_html=True)
    if c3.button("🔄 Reset Quote"): 
        st.session_state.quote_df = pd.DataFrame()
        st.session_state.show_review = False 
        for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
             if f"pct_{k}" in st.session_state: del st.session_state[f"pct_{k}"]
        st.rerun()
    c3.markdown('</div>', unsafe_allow_html=True)

    with st.expander("Cấu hình chi phí (%) & Vận chuyển", expanded=True):
        cols = st.columns(7)
        keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
        params = {}
        for i, k in enumerate(keys):
            default_val = st.session_state.get(f"pct_{k}", "0")
            val = cols[i].text_input(k.upper(), value=default_val, key=f"input_{k}")
            st.session_state[f"pct_{k}"] = val
            params[k] = to_float(val)

    # MATCHING
    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        db = load_data("crm_purchases")
        if db.empty: st.error("Kho rỗng!")
        else:
            db_records = db.to_dict('records')
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            cols_found = {clean_key(c): c for c in df_rfq.columns}
            
            prog_match = st.progress(0)
            status_match = st.empty()
            total_rows = len(df_rfq)
            
            for i, r in df_rfq.iterrows():
                pct = (i + 1) / total_rows
                prog_match.progress(pct)
                status_match.text(f"Đang xử lý: {int(pct*100)}%")

                def get_val(keywords):
                    for k in keywords:
                        real_col = cols_found.get(k)
                        if real_col: return safe_str(r[real_col])
                    return ""

                code_excel = get_val(["item code", "code", "mã", "part number"])
                name_excel = get_val(["item name", "name", "tên", "description"])
                specs_excel = get_val(["specs", "quy cách", "thông số"])
                qty_raw = get_val(["q'ty", "qty", "quantity", "số lượng"])
                qty = to_float(qty_raw) if qty_raw else 1.0

                match = None
                warning_msg = ""
                
                candidates = [
                    rec for rec in db_records 
                    if clean_key(rec['item_code']) == clean_key(code_excel)
                    and clean_key(rec['item_name']) == clean_key(name_excel)
                    and clean_key(rec['specs']) == clean_key(specs_excel)
                ]

                if candidates: match = candidates[0]
                else: warning_msg = "⚠️ KHÔNG KHỚP DATA"

                if match:
                    buy_rmb = to_float(match.get('buying_price_rmb', 0))
                    buy_vnd = to_float(match.get('buying_price_vnd', 0))
                    ex_rate = to_float(match.get('exchange_rate', 0))
                    supplier = match.get('supplier_name', '')
                    image = match.get('image_path', '')
                    leadtime = match.get('leadtime', '')
                else:
                    buy_rmb = 0; buy_vnd = 0; ex_rate = 0
                    supplier = ""; image = ""; leadtime = ""

                p_tax = params['tax']/100
                v_trans = params['trans']
                val_import_tax = (buy_vnd * qty) * p_tax

                item = {
                    "Select": False, "No": i+1, "Cảnh báo": warning_msg, 
                    "Item code": code_excel, "Item name": name_excel, "Specs": specs_excel, 
                    "Q'ty": qty, 
                    "Buying price(RMB)": fmt_float_2(buy_rmb), 
                    "Total buying price(rmb)": fmt_float_2(buy_rmb * qty),
                    "Exchange rate": fmt_float_2(ex_rate), 
                    "Buying price(VND)": fmt_float_2(buy_vnd), 
                    "Total buying price(VND)": fmt_float_2(buy_vnd * qty),
                    
                    "AP price(VND)": "0", "AP total price(VND)": "0", 
                    "Unit price(VND)": "0", "Total price(VND)": "0",
                    "GAP": "0",
                    "End user(%)": "0", "Buyer(%)": "0",               
                    "Import tax(%)": fmt_float_2(val_import_tax),
                    "VAT": "0", "Transportation": fmt_num(v_trans),
                    "Management fee(%)": "0", "Payback(%)": "0",             
                    "Profit(VND)": "0", "Profit(%)": "0.0%",
                    "Supplier": supplier, "Image": image, "Leadtime": leadtime
                }
                res.append(item)
            
            prog_match.progress(100)
            status_match.text("Done! Hoàn tất Matching.")
            time.sleep(1)
            status_match.empty()

            st.session_state.quote_df = pd.DataFrame(res)
    
    # --- FORMULA BUTTONS (ONE CLICK FIX) ---
    c_form1, c_form2 = st.columns(2)
    with c_form1:
        ap_f = st.text_input("Formula AP (vd: =BUY*1.1)", key="f_ap")
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("Apply AP Price"):
            if not st.session_state.quote_df.empty:
                for idx, row in st.session_state.quote_df.iterrows():
                    buy = to_float(row["Buying price(VND)"])
                    ap = to_float(row["AP price(VND)"])
                    new_ap = parse_formula(ap_f, buy, ap)
                    st.session_state.quote_df.at[idx, "AP price(VND)"] = fmt_float_2(new_ap)
                st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)
                st.rerun() 
        st.markdown('</div>', unsafe_allow_html=True)
    with c_form2:
        unit_f = st.text_input("Formula Unit (vd: =AP*1.2)", key="f_unit")
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("Apply Unit Price"):
            if not st.session_state.quote_df.empty:
                for idx, row in st.session_state.quote_df.iterrows():
                    buy = to_float(row["Buying price(VND)"])
                    ap = to_float(row["AP price(VND)"])
                    new_unit = parse_formula(unit_f, buy, ap)
                    st.session_state.quote_df.at[idx, "Unit price(VND)"] = fmt_float_2(new_unit)
                st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)
                st.rerun() 
        st.markdown('</div>', unsafe_allow_html=True)
    
    if not st.session_state.quote_df.empty:
        if "Select" not in st.session_state.quote_df.columns:
            st.session_state.quote_df.insert(0, "Select", False)

        st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)

        cols_order = ["Select", "No", "Cảnh báo"] + [c for c in st.session_state.quote_df.columns if c not in ["Select", "No", "Cảnh báo"]]
        st.session_state.quote_df = st.session_state.quote_df[cols_order]

        cols_to_hide = ["Image", "Profit_Pct_Raw"]
        df_show = st.session_state.quote_df.drop(columns=[c for c in cols_to_hide if c in st.session_state.quote_df.columns], errors='ignore')

        # CHUẨN BỊ DỮ LIỆU HIỂN THỊ: CHUYỂN SỐ THÀNH TEXT
        df_display = df_show.copy()
        
        # Danh sách cột tiền VND (dùng format_money)
        editable_money_cols = [
            "Buying price(VND)", "Total buying price(VND)",
            "AP price(VND)", "AP total price(VND)", "Unit price(VND)", "Total price(VND)",
            "GAP", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT",
            "Transportation", "Management fee(%)", "Payback(%)", "Profit(VND)"
        ]
        
        # Danh sách cột tiền RMB (dùng format_float)
        editable_rmb_cols = ["Buying price(RMB)", "Total buying price(rmb)"]

        # Format Display
        for c in editable_money_cols:
            if c in df_display.columns:
                df_display[c] = df_display[c].apply(local_fmt_money)
        
        for c in editable_rmb_cols:
            if c in df_display.columns:
                df_display[c] = df_display[c].apply(local_fmt_float)
        
        if "Exchange rate" in df_display.columns:
            df_display["Exchange rate"] = df_display["Exchange rate"].apply(local_fmt_float)

        # TÍNH TỔNG (TOTAL ROW)
        cols_to_sum = ["Q'ty", "Total buying price(rmb)"] + editable_money_cols
        total_row = {"Select": False, "No": "TOTAL", "Cảnh báo": "", "Item code": "", "Item name": "", "Specs": "", "Q'ty": 0}
        
        for c in cols_to_sum:
            if c in st.session_state.quote_df.columns:
                total_val = st.session_state.quote_df[c].apply(to_float).sum()
                if c == "Q'ty": total_row[c] = total_val
                elif c in editable_rmb_cols: total_row[c] = local_fmt_float(total_val)
                else: total_row[c] = local_fmt_money(total_val) 
        
        t_profit = to_float(str(total_row.get("Profit(VND)", "0")).replace(",",""))
        t_price = to_float(str(total_row.get("Total price(VND)", "0")).replace(",",""))
        t_pct = (t_profit / t_price * 100) if t_price > 0 else 0
        total_row["Profit(%)"] = f"{t_pct:.1f}%"
        
        df_display = pd.concat([df_display, pd.DataFrame([total_row])], ignore_index=True)

        # RENDER BẢNG
        edited_df = st.data_editor(
            df_display,
            column_config={
                "Select": st.column_config.CheckboxColumn("✅", width="small"),
                "Cảnh báo": st.column_config.TextColumn("Cảnh báo", width="small", disabled=True),
                "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d", width="small"),
                "Item code": st.column_config.TextColumn("Item code", width="medium"),
                "Item name": st.column_config.TextColumn("Item name", width="medium"),
                "Specs": st.column_config.TextColumn("Specs", width="medium"),
                "Exchange rate": st.column_config.TextColumn("Rate", width="small"),
                
                **{c: st.column_config.TextColumn(c, width="small") for c in editable_money_cols},
                **{c: st.column_config.TextColumn(c, width="small") for c in editable_rmb_cols}
            },
            use_container_width=True, height=600, key="main_editor",
            hide_index=True 
        )
        
        # ĐỒNG BỘ DỮ LIỆU NGƯỢC (TYPE-SAFE)
        df_data_only = edited_df[edited_df["No"] != "TOTAL"]
        data_changed = False
        
        if len(df_data_only) == len(st.session_state.quote_df):
            for idx, row in df_data_only.iterrows():
                 # 1. Sync Q'ty
                 if "Q'ty" in st.session_state.quote_df.columns:
                     old_qty = local_parse_money(st.session_state.quote_df.at[idx, "Q'ty"])
                     new_qty = local_parse_money(row.get("Q'ty", 0))
                     if abs(old_qty - new_qty) > 0.001:
                         st.session_state.quote_df.at[idx, "Q'ty"] = new_qty
                         data_changed = True

                 # 2. Sync Text
                 for c in ["Item name", "Specs"]:
                     if c in st.session_state.quote_df.columns:
                         old_val = str(st.session_state.quote_df.at[idx, c]).strip()
                         new_val = str(row.get(c, "")).strip()
                         if old_val != new_val:
                             st.session_state.quote_df.at[idx, c] = new_val
                             data_changed = True

                 # 3. Sync Exchange rate
                 if "Exchange rate" in st.session_state.quote_df.columns:
                     val_str = row["Exchange rate"]
                     val_float = local_parse_money(val_str)
                     old_float = to_float(st.session_state.quote_df.at[idx, "Exchange rate"])
                     if abs(val_float - old_float) > 0.001:
                         st.session_state.quote_df.at[idx, "Exchange rate"] = val_float
                         data_changed = True

                 # 4. Sync Tiền tệ (VND integer, RMB decimal)
                 all_money_cols = editable_money_cols + editable_rmb_cols
                 for c in all_money_cols:
                     if c in st.session_state.quote_df.columns:
                         val_str = row[c]
                         val_float = local_parse_money(val_str) 
                         old_float = to_float(st.session_state.quote_df.at[idx, c])
                         
                         threshold = 0.01 if c in editable_rmb_cols else 1.0
                         
                         if abs(val_float - old_float) > threshold: 
                             st.session_state.quote_df.at[idx, c] = val_float
                             data_changed = True
        
        if data_changed:
            st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)
            st.rerun()

        # --- QUICK TOOLBAR LOGIC ---
        selected_rows = df_data_only[df_data_only["Select"] == True]
        if not selected_rows.empty:
            st.info(f"Đang chọn {len(selected_rows)} dòng.")
            tb_col1, tb_col2, tb_col3, tb_col4 = st.columns(4)
            with tb_col1:
                if st.button("🗑️ DELETE"):
                    indices_to_drop = selected_rows.index
                    st.session_state.quote_df = st.session_state.quote_df.drop(indices_to_drop).reset_index(drop=True)
                    st.session_state.quote_df["No"] = st.session_state.quote_df.index + 1
                    st.rerun()
            with tb_col2:
                csv = selected_rows.to_csv(index=False).encode('utf-8')
                st.download_button(label="⬇️ DOWNLOAD", data=csv, file_name="selected_items.csv", mime="text/csv")
            with tb_col3:
                if st.button("⛶ FULL SCREEN"): st.toast("Chế độ toàn màn hình đã được kích hoạt (Giả lập)", icon="🖥️")
            with tb_col4:
                if st.button("👁️ HIDE"):
                      for idx in selected_rows.index: st.session_state.quote_df.at[idx, "Select"] = False
                      st.rerun()

        # --- VIEW TOTAL PRICE ---
        total_q = st.session_state.quote_df["Total price(VND)"].apply(to_float).sum()
        st.markdown(f'<div class="total-view">💰 TỔNG GIÁ TRỊ BÁO GIÁ (TOTAL VIEW): {local_fmt_money(total_q)} VND</div>', unsafe_allow_html=True)

        # --- GLOBAL CONFIG BUTTON ---
        st.markdown("---")
        c_tool1, c_tool2 = st.columns([1, 3])
        with c_tool1:
            if st.button("⚡ ÁP DỤNG GLOBAL CONFIG", help="Tính lại toàn bộ các cột Tax, VAT, Fee..."):
                if not st.session_state.quote_df.empty:
                    st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)
                    st.toast("✅ Đã áp dụng Global Config!", icon="⚡")
                    st.rerun()

        st.divider()
        c_rev, c_sv = st.columns([1, 1])
        with c_rev:
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("🔍 REVIEW BÁO GIÁ"): st.session_state.show_review = True
            st.markdown('</div>', unsafe_allow_html=True)
        
        if st.session_state.get('show_review', False):
            st.write("### 📋 BẢNG REVIEW")
            cols_review = ["No", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Leadtime"]
            valid_cols = [c for c in cols_review if c in st.session_state.quote_df.columns]
            
            df_review = st.session_state.quote_df[valid_cols].copy()
            total_qty = df_review["Q'ty"].apply(to_float).sum() if "Q'ty" in df_review.columns else 0
            total_unit = df_review["Unit price(VND)"].apply(to_float).sum() if "Unit price(VND)" in df_review.columns else 0
            total_price = df_review["Total price(VND)"].apply(to_float).sum() if "Total price(VND)" in df_review.columns else 0

            # Format text review
            if "Unit price(VND)" in df_review.columns: df_review["Unit price(VND)"] = df_review["Unit price(VND)"].apply(local_fmt_money)
            if "Total price(VND)" in df_review.columns: df_review["Total price(VND)"] = df_review["Total price(VND)"].apply(local_fmt_money)
            
            total_review = {
                "No": "TOTAL", "Item code": "", "Item name": "", "Specs": "", "Leadtime": "",
                "Q'ty": total_qty,
                "Unit price(VND)": local_fmt_money(total_unit),
                "Total price(VND)": local_fmt_money(total_price)
            }
            df_review = pd.concat([df_review, pd.DataFrame([total_review])], ignore_index=True)
            st.dataframe(df_review, use_container_width=True, hide_index=True)
            st.markdown(f'<div class="total-view">💰 TỔNG CỘNG: {local_fmt_money(total_q)} VND</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("📤 XUẤT BÁO GIÁ (Excel)"):
                if not cust_name: st.error("Chưa chọn khách hàng!")
                else:
                    try:
                        df_tmpl = load_data("crm_templates")
                        match_tmpl = df_tmpl[df_tmpl['template_name'].astype(str).str.contains("AAA-QUOTATION", case=False, na=False)]
                        if match_tmpl.empty: st.error("Không tìm thấy template 'AAA-QUOTATION'!")
                        else:
                            tmpl_id = match_tmpl.iloc[0]['file_id']
                            fh = download_from_drive(tmpl_id)
                            if not fh: st.error("Lỗi tải template!")
                            else:
                                wb = load_workbook(fh); ws = wb.active
                                start_row = 11
                                first_leadtime = st.session_state.quote_df.iloc[0]['Leadtime'] if not st.session_state.quote_df.empty else ""
                                ws['H8'] = safe_str(first_leadtime)
                                for idx, row in st.session_state.quote_df.iterrows():
                                    r = start_row + idx
                                    ws[f'A{r}'] = row['No']
                                    ws[f'C{r}'] = row['Item code']
                                    ws[f'D{r}'] = row['Item name']
                                    ws[f'E{r}'] = row['Specs']
                                    ws[f'F{r}'] = to_float(row["Q'ty"])
                                    ws[f'G{r}'] = to_float(row["Unit price(VND)"])
                                    ws[f'H{r}'] = to_float(row["Total price(VND)"])
                                out = io.BytesIO(); wb.save(out); out.seek(0)
                                curr_year = datetime.now().strftime("%Y")
                                curr_month = datetime.now().strftime("%b").upper()
                                fname = f"QUOTE_{quote_no}_{cust_name}_{int(time.time())}.xlsx"
                                path_list = ["QUOTATION_HISTORY", cust_name, curr_year, curr_month]
                                lnk, _ = upload_to_drive_structured(out, path_list, fname)
                                st.success(f"✅ Đã xuất báo giá: {fname}")
                                st.info("ℹ️ File đã lưu trên Drive (KHÔNG GHI VÀO DASHBOARD).")
                                st.markdown(f"📂 [Mở Folder]({lnk})", unsafe_allow_html=True)
                                st.download_button(label="📥 Tải File Về Máy", data=out, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception as e: st.error(f"Lỗi xuất Excel: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        with c_sv:
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("💾 LƯU LỊCH SỬ (QUAN TRỌNG)"):
                if cust_name:
                    clean_params = {}
                    for k, v in params.items():
                        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): clean_params[k] = 0.0
                        else: clean_params[k] = v
                    config_json = json.dumps(clean_params) 
                    
                    recs = []
                    for r in st.session_state.quote_df.to_dict('records'):
                        val_qty = to_float(r["Q'ty"])
                        val_unit = to_float(r["Unit price(VND)"])
                        val_total = to_float(r["Total price(VND)"])
                        val_profit = to_float(r["Profit(VND)"])
                        
                        if np.isnan(val_qty) or np.isinf(val_qty): val_qty = 0.0
                        if np.isnan(val_unit) or np.isinf(val_unit): val_unit = 0.0
                        if np.isnan(val_total) or np.isinf(val_total): val_total = 0.0
                        if np.isnan(val_profit) or np.isinf(val_profit): val_profit = 0.0

                        recs.append({
                            "history_id": f"{cust_name}_{int(time.time())}", "date": datetime.now().strftime("%Y-%m-%d"),
                            "quote_no": quote_no, "customer": cust_name,
                            "item_code": r["Item code"], "qty": val_qty,
                            "unit_price": val_unit,
                            "total_price_vnd": val_total,
                            "profit_vnd": val_profit,
                            "config_data": config_json 
                        })
                    
                    # [RESTORED]: GHI LẠI VÀO DB ĐỂ TRA CỨU
                    try:
                        try:
                            supabase.table("crm_shared_history").insert(recs).execute()
                        except Exception as e:
                            if "config_data" in str(e) or "PGRST204" in str(e):
                                 recs_fallback = [{k: v for k, v in r.items() if k != 'config_data'} for r in recs]
                                 supabase.table("crm_shared_history").insert(recs_fallback).execute()
                            else: raise e
                    except Exception as e:
                        st.error(f"Lỗi lưu DB: {e}")
                        st.stop()

                    try:
                        csv_buffer = io.BytesIO()
                        st.session_state.quote_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                        csv_buffer.seek(0)
                        csv_name = f"HIST_{quote_no}_{cust_name}_{int(time.time())}.csv"
                        curr_year = datetime.now().strftime("%Y")
                        curr_month = datetime.now().strftime("%b").upper()
                        path_list_hist = ["QUOTATION_HISTORY", cust_name, curr_year, curr_month]
                        lnk, _ = upload_to_drive_structured(csv_buffer, path_list_hist, csv_name)
                        
                        df_cfg = pd.DataFrame([clean_params])
                        cfg_buffer = io.BytesIO()
                        df_cfg.to_excel(cfg_buffer, index=False)
                        cfg_buffer.seek(0)
                        cfg_name = f"CONFIG_{quote_no}_{cust_name}_{int(time.time())}.xlsx"
                        upload_to_drive_structured(cfg_buffer, path_list_hist, cfg_name)
                        
                        st.success("✅ Đã lưu thành công (DB & Drive)!")
                        st.markdown(f"📂 [Folder Lịch Sử]({lnk})", unsafe_allow_html=True)
                    except Exception as e: st.error(f"Lỗi lưu Drive: {e}")
                else: st.error("Chọn khách!")
            st.markdown('</div>', unsafe_allow_html=True)
# =============================================================================
# --- TAB 4: QUẢN LÝ PO (NEW LOGIC) ---
# =============================================================================
with t4:
    # -------------------------------------------------------------------------
    # 1. TRA CỨU ĐƠN HÀNG (BLACKBOX - GIỮ NGUYÊN)
    # -------------------------------------------------------------------------
    st.markdown("### 🔎 TRA CỨU ĐƠN HÀNG (PO)")
    search_po = st.text_input("Nhập số PO, Mã hàng, Tên hàng, Khách, NCC...", key="search_po_tab")
    if search_po:
        df_po_cust = load_data("db_customer_orders")
        df_po_supp = load_data("db_supplier_orders")
        if not df_po_cust.empty:
            mask_c = df_po_cust.astype(str).apply(lambda x: x.str.contains(search_po, case=False, na=False)).any(axis=1)
            st.dataframe(df_po_cust[mask_c], use_container_width=True)
        if not df_po_supp.empty:
            mask_s = df_po_supp.astype(str).apply(lambda x: x.str.contains(search_po, case=False, na=False)).any(axis=1)
            st.dataframe(df_po_supp[mask_s], use_container_width=True)

    st.divider()

    # -------------------------------------------------------------------------
    # 2. QUẢN LÝ PO KHÁCH HÀNG (LUỒNG CHÍNH)
    # -------------------------------------------------------------------------
    st.subheader("📋 PO KHÁCH HÀNG")
    
    # Khởi tạo Session State cho Dataframe chính
    if 'po_main_df' not in st.session_state: st.session_state.po_main_df = pd.DataFrame()

    # Input Form
    c_in1, c_in2, c_in3 = st.columns([1, 1, 1])
    po_no_input = c_in1.text_input("Số PO Khách Hàng", key="po_no_main")
    
    cust_db = load_data("crm_customers")
    cust_list = cust_db["short_name"].tolist() if not cust_db.empty else []
    cust_name = c_in2.selectbox("Chọn Khách Hàng", [""] + cust_list, key="cust_name_po")
    
    po_file = c_in3.file_uploader("Upload File PO (Excel)", type=["xlsx"], key="po_up_main")

    # Nút Load Dữ Liệu
    if st.button("🔄 Tải dữ liệu & Tính toán"):
        if not po_file: st.error("Chưa upload file PO!")
        elif not cust_name: st.error("Chưa chọn khách hàng!")
        else:
            try:
                # Load Excel PO
                df_up = pd.read_excel(po_file, header=None, skiprows=1, dtype=str).fillna("")
                
                # Load Master Data để lấy giá gốc
                db_items = load_data("crm_purchases")
                item_map = {clean_key(r['item_code']): r for r in db_items.to_dict('records')}
                
                recs = []
                # Giả định Excel PO có cột theo thứ tự hoặc logic tìm kiếm tương đối
                # Ta sẽ loop và map dữ liệu
                for i, r in df_up.iterrows():
                    # Map Excel Columns (Cần khớp với file thực tế, ở đây lấy logic tương đối an toàn)
                    # Giả sử col 1 là Code, col 4 là Qty, Col 5 là Unit Price (nếu có)
                    code = safe_str(r.iloc[1]) 
                    if not code: continue # Bỏ qua dòng ko có code
                    
                    qty = to_float(r.iloc[4])
                    
                    # Lookup Info từ Master Data
                    match = item_map.get(clean_key(code))
                    
                    # Init Defaults
                    buy_rmb = 0.0; rate = 0.0; buy_vnd = 0.0; supplier = ""; leadtime = "0"
                    specs = safe_str(r.iloc[3])
                    name = safe_str(r.iloc[2])

                    if match:
                        buy_rmb = to_float(match.get('buying_price_rmb', 0))
                        rate = to_float(match.get('exchange_rate', 0))
                        buy_vnd = to_float(match.get('buying_price_vnd', 0))
                        supplier = match.get('supplier_name', '')
                        leadtime = match.get('leadtime', '0')
                        if not specs: specs = match.get('specs', '')
                        if not name: name = match.get('item_name', '')
                    
                    # Unit Price from Excel PO (Giá khách đặt)
                    unit_price_raw = to_float(r.iloc[5]) if len(r) > 5 else 0.0
                    
                    # Tạo dòng dữ liệu đầy đủ các cột yêu cầu
                    item = {
                        "No": safe_str(r.iloc[0]) if safe_str(r.iloc[0]) else (i+1), 
                        "Item code": code, 
                        "Item name": name, 
                        "Specs": specs, 
                        "Q'ty": qty,
                        
                        "Buying price(RMB)": buy_rmb,
                        "Total buying price(RMB)": buy_rmb * qty,
                        "Exchange rate": rate,
                        "Buying price(VND)": buy_vnd,
                        "Total buying price(VND)": buy_vnd * qty,
                        
                        "AP price(VND)": 0.0, # Mặc định 0
                        "AP total price(VND)": 0.0, # Mặc định 0
                        
                        "Unit price(VND)": unit_price_raw,
                        "Total price(VND)": unit_price_raw * qty,
                        
                        "GAP": 0.0, # Sẽ tính lại
                        
                        # Default Configs (User can edit later in table)
                        "End user(%)": 0.0, "Buyer(%)": 0.0, "Import tax(%)": 0.0,
                        "VAT": 0.0, "Transportation": 0.0, "Management fee(%)": 0.0, "Payback(%)": 0.0,
                        
                        "Profit(VND)": 0.0, "Profit(%)": "0%",
                        
                        "Supplier": supplier, "Leadtime": leadtime # Các cột ẩn hoặc phụ trợ
                    }
                    recs.append(item)
                
                if recs:
                    st.session_state.po_main_df = pd.DataFrame(recs)
                    # Tính toán lại lần đầu (Tính GAP, Profit...)
                    # Sử dụng hàm có sẵn recalculate_quote_logic (Blackbox)
                    params_dummy = {} 
                    st.session_state.po_main_df = recalculate_quote_logic(st.session_state.po_main_df, params_dummy)
                    st.success(f"✅ Đã tải {len(recs)} dòng dữ liệu!")
                else: st.warning("Không đọc được dữ liệu nào từ file.")

            except Exception as e: st.error(f"Lỗi đọc file: {e}")

    # --- MAIN TABLE EDITOR ---
    if not st.session_state.po_main_df.empty:
        # Tính toán Real-time để đảm bảo số liệu đúng trước khi hiển thị
        params_dummy = {}
        st.session_state.po_main_df = recalculate_quote_logic(st.session_state.po_main_df, params_dummy)
        
        st.write("📝 **Chi tiết Đơn Hàng (Chỉnh sửa trực tiếp Chi phí/Thuế tại đây):**")
        
        # Sắp xếp cột theo yêu cầu
        cols_order_req = [
            "No", "Item code", "Item name", "Specs", "Q'ty", 
            "Buying price(RMB)", "Total buying price(RMB)", "Exchange rate",
            "Buying price(VND)", "Total buying price(VND)", 
            "AP price(VND)", "AP total price(VND)", 
            "Unit price(VND)", "Total price(VND)", 
            "GAP", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", 
            "Transportation", "Management fee(%)", "Payback(%)", 
            "Profit(VND)", "Profit(%)"
        ]
        # Lọc những cột có trong DF
        cols_display = [c for c in cols_order_req if c in st.session_state.po_main_df.columns]
        
        edited_po = st.data_editor(
            st.session_state.po_main_df[cols_display],
            column_config={
                "Buying price(RMB)": st.column_config.NumberColumn(format="%.2f"),
                "Total buying price(RMB)": st.column_config.NumberColumn(format="%.2f"),
                "Buying price(VND)": st.column_config.NumberColumn(format="%d"),
                "Total buying price(VND)": st.column_config.NumberColumn(format="%d"),
                "Unit price(VND)": st.column_config.NumberColumn(format="%d"),
                "Total price(VND)": st.column_config.NumberColumn(format="%d"),
                "GAP": st.column_config.NumberColumn(format="%d"),
                "End user(%)": st.column_config.NumberColumn(format="%d"),
                "Buyer(%)": st.column_config.NumberColumn(format="%d"),
                "Import tax(%)": st.column_config.NumberColumn(format="%d"),
                "VAT": st.column_config.NumberColumn(format="%d"),
                "Transportation": st.column_config.NumberColumn(format="%d"),
                "Management fee(%)": st.column_config.NumberColumn(format="%d"),
                "Payback(%)": st.column_config.NumberColumn(format="%d"),
                "Profit(VND)": st.column_config.NumberColumn(format="%d"),
            },
            use_container_width=True, height=400, key="editor_po_main", hide_index=True
        )
        
        # Sync changes back to session_state (Update các cột đã sửa)
        # Vì data_editor chỉ trả về subset cột, cần merge lại vào main df
        if not edited_po.equals(st.session_state.po_main_df[cols_display]):
            for idx, row in edited_po.iterrows():
                for c in cols_display:
                    st.session_state.po_main_df.at[idx, c] = row[c]
            st.rerun()

        st.divider()
        
        # --- 3 ACTION SECTIONS ---
        
        # 1. REVIEW & ĐẶT HÀNG NCC
        with st.expander("📦 Review và đặt hàng nhà cung cấp (Đặt NCC)", expanded=False):
            # Columns NCC View
            cols_ncc = ["No", "Item code", "Item name", "Specs", "Q'ty", 
                        "Buying price(RMB)", "Total buying price(RMB)", "Exchange rate", 
                        "Buying price(VND)", "Total buying price(VND)", "Supplier"]
            
            # Đảm bảo có cột Supplier trong main df (ẩn ở view trên nhưng cần ở đây)
            df_ncc_view = st.session_state.po_main_df.copy()
            if "Supplier" not in df_ncc_view.columns: df_ncc_view["Supplier"] = ""
            df_ncc_view = df_ncc_view[cols_ncc]
            
            # Total Row Logic
            total_row_ncc = {"No": "TOTAL", "Item code": "", "Item name": "", "Specs": "", "Supplier": ""}
            sum_cols_ncc = ["Q'ty", "Buying price(RMB)", "Total buying price(RMB)", "Buying price(VND)", "Total buying price(VND)"]
            
            for c in sum_cols_ncc:
                total_row_ncc[c] = df_ncc_view[c].apply(to_float).sum()
                
            # Formatting & Display
            df_ncc_fmt = df_ncc_view.copy()
            # Format rows
            for c in ["Buying price(RMB)", "Total buying price(RMB)"]:
                df_ncc_fmt[c] = df_ncc_fmt[c].apply(fmt_float_2)
            for c in ["Buying price(VND)", "Total buying price(VND)"]:
                df_ncc_fmt[c] = df_ncc_fmt[c].apply(fmt_num)
            df_ncc_fmt["Q'ty"] = df_ncc_fmt["Q'ty"].apply(fmt_num)

            # Format Total Row
            total_row_fmt = total_row_ncc.copy()
            total_row_fmt["Buying price(RMB)"] = fmt_float_2(total_row_ncc["Buying price(RMB)"])
            total_row_fmt["Total buying price(RMB)"] = fmt_float_2(total_row_ncc["Total buying price(RMB)"])
            total_row_fmt["Buying price(VND)"] = fmt_num(total_row_ncc["Buying price(VND)"])
            total_row_fmt["Total buying price(VND)"] = fmt_num(total_row_ncc["Total buying price(VND)"])
            total_row_fmt["Q'ty"] = fmt_num(total_row_ncc["Q'ty"])
            
            # Append Total
            df_ncc_fmt = pd.concat([df_ncc_fmt, pd.DataFrame([total_row_fmt])], ignore_index=True)
            
            st.dataframe(df_ncc_fmt, use_container_width=True, hide_index=True)
            
            if st.button("🚀 Đặt hàng NCC"):
                if not po_no_input: st.error("Thiếu số PO Khách Hàng!")
                else:
                    grouped = st.session_state.po_main_df.groupby("Supplier")
                    curr_year = datetime.now().strftime("%Y")
                    curr_month = datetime.now().strftime("%m")
                    
                    count_files = 0
                    for supp, group in grouped:
                        supp_name = clean_key(supp).upper() if supp else "UNKNOWN"
                        
                        # Generate Excel PO NCC
                        wb = Workbook(); ws = wb.active; ws.title = "PO NCC"
                        ws.append(cols_ncc) # Header
                        for r in group[cols_ncc].to_dict('records'):
                            ws.append(list(r.values()))
                        
                        # Footer Total
                        ws.append(["TOTAL", "", "", "", group["Q'ty"].sum(), "", group["Total buying price(RMB)"].sum(), "", "", group["Total buying price(VND)"].sum(), ""])

                        out = io.BytesIO(); wb.save(out); out.seek(0)
                        
                        # File Name: PO-HS...-SUPPLIER
                        fname = f"{po_no_input}-{supp_name}.xlsx"
                        
                        # Path: PO_NCC/{Year}/{Supplier}/{Month}/
                        path_list = ["PO_NCC", curr_year, supp_name, curr_month]
                        
                        lnk, _ = upload_to_drive_structured(out, path_list, fname)
                        
                        # Tracking Insert
                        # Calculate ETA based on first item leadtime
                        lt_val = group.iloc[0]["Leadtime"] if "Leadtime" in group.columns else 0
                        eta = calc_eta(datetime.now(), lt_val)
                        
                        track_rec = {
                            "po_no": f"{po_no_input}-{supp_name}",
                            "partner": supp_name,
                            "status": "Ordered",
                            "order_type": "NCC",
                            "last_update": datetime.now().strftime("%d/%m/%Y"),
                            "eta": eta
                        }
                        supabase.table("crm_tracking").insert([track_rec]).execute()
                        count_files += 1
                        
                    st.success(f"✅ Đã tạo {count_files} đơn hàng NCC (Tách file) và lưu Drive!")

        # 2. REVIEW PO KHÁCH HÀNG & LƯU
        with st.expander("👤 Review PO khách hàng và lưu PO", expanded=False):
            # Columns Customer View
            cols_kh = ["No", "Item code", "Item name", "Specs", "Q'ty", 
                       "Unit price(VND)", "Total price(VND)", "Leadtime"]
            
            df_kh_view = st.session_state.po_main_df[cols_kh].copy()
            df_kh_view["Customer"] = cust_name # Add Customer column
            
            # Total Row Logic
            total_row_kh = {"No": "TOTAL", "Item code": "", "Item name": "", "Specs": "", "Customer": "", "Leadtime": ""}
            sum_cols_kh = ["Q'ty", "Unit price(VND)", "Total price(VND)"]
            for c in sum_cols_kh:
                total_row_kh[c] = df_kh_view[c].apply(to_float).sum()
                
            # Formatting
            df_kh_fmt = df_kh_view.copy()
            for c in ["Unit price(VND)", "Total price(VND)"]:
                df_kh_fmt[c] = df_kh_fmt[c].apply(fmt_num)
            df_kh_fmt["Q'ty"] = df_kh_fmt["Q'ty"].apply(fmt_num)
                
            total_row_kh_fmt = total_row_kh.copy()
            total_row_kh_fmt["Unit price(VND)"] = fmt_num(total_row_kh["Unit price(VND)"])
            total_row_kh_fmt["Total price(VND)"] = fmt_num(total_row_kh["Total price(VND)"])
            total_row_kh_fmt["Q'ty"] = fmt_num(total_row_kh["Q'ty"])
            
            # Append Total
            df_kh_fmt = pd.concat([df_kh_fmt, pd.DataFrame([total_row_kh_fmt])], ignore_index=True)
            
            st.dataframe(df_kh_fmt, use_container_width=True, hide_index=True)
            
            if st.button("💾 Lưu PO Khách Hàng"):
                if not po_no_input: st.error("Thiếu số PO!")
                else:
                    # 1. Insert DB (Doanh thu -> db_customer_orders)
                    db_recs = []
                    eta_final = ""
                    for r in st.session_state.po_main_df.to_dict('records'):
                        eta_item = calc_eta(datetime.now(), r.get("Leadtime", 0))
                        eta_final = eta_item # Take last or first
                        db_recs.append({
                            "po_number": po_no_input, "customer": cust_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                            "item_code": r["Item code"], "item_name": r["Item name"], "specs": r["Specs"],
                            "qty": to_float(r["Q'ty"]), "unit_price": to_float(r["Unit price(VND)"]),
                            "total_price": to_float(r["Total price(VND)"]), "eta": eta_item
                        })
                    supabase.table("db_customer_orders").insert(db_recs).execute()
                    
                    # 2. Upload Drive
                    # Path: PO_KHACH_HANG/{Year}/{Customer}/{Month}/
                    curr_year = datetime.now().strftime("%Y")
                    curr_month = datetime.now().strftime("%m")
                    path_list = ["PO_KHACH_HANG", curr_year, cust_name, curr_month]
                    
                    # Create Excel File PO Customer
                    wb = Workbook(); ws = wb.active; ws.title = "PO CUSTOMER"
                    ws.append(cols_kh + ["Customer"])
                    for r in df_kh_view.to_dict('records'):
                        ws.append(list(r.values()))
                    # Total Row Excel
                    ws.append(["TOTAL", "", "", "", df_kh_view["Q'ty"].sum(), df_kh_view["Unit price(VND)"].sum(), df_kh_view["Total price(VND)"].sum(), "", ""])
                    
                    out = io.BytesIO(); wb.save(out); out.seek(0)
                    fname = f"{po_no_input}.xlsx"
                    lnk, _ = upload_to_drive_structured(out, path_list, fname)
                    
                    # 3. Tracking (crm_tracking -> Waiting, KH)
                    track_rec = {
                        "po_no": po_no_input, "partner": cust_name, "status": "Waiting",
                        "order_type": "KH", "last_update": datetime.now().strftime("%d/%m/%Y"),
                        "eta": eta_final
                    }
                    supabase.table("crm_tracking").insert([track_rec]).execute()
                    
                    st.success("✅ Đã lưu PO Khách Hàng (Tracking + Doanh thu Dashboard + Drive)!")
                    st.markdown(f"📂 [Link File Drive]({lnk})")

        # 3. REVIEW CHI PHÍ & LƯU
        with st.expander("💰 Review chi phí và lưu chi phí", expanded=False):
            # Columns Cost View
            cols_cost = ["No", "Item code", "Item name", "Specs", "Q'ty", 
                         "Buying price(RMB)", "Total buying price(RMB)", "Exchange rate",
                         "Buying price(VND)", "Total buying price(VND)", 
                         "GAP", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", 
                         "Transportation", "Management fee(%)", "Profit(%)"]
            
            df_cost_view = st.session_state.po_main_df[cols_cost].copy()
            
            # Total Row Logic
            total_row_cost = {"No": "TOTAL", "Item code": "", "Item name": "", "Specs": "", "Profit(%)": ""}
            sum_cols_cost = ["Q'ty", "Buying price(VND)", "Total buying price(VND)", "GAP", 
                             "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", 
                             "Transportation", "Management fee(%)"]
            
            for c in sum_cols_cost:
                total_row_cost[c] = df_cost_view[c].apply(to_float).sum()
                
            # Formatting
            df_cost_fmt = df_cost_view.copy()
            for c in sum_cols_cost:
                df_cost_fmt[c] = df_cost_fmt[c].apply(fmt_num)
            # RMB columns format
            df_cost_fmt["Buying price(RMB)"] = df_cost_fmt["Buying price(RMB)"].apply(fmt_float_2)
            df_cost_fmt["Total buying price(RMB)"] = df_cost_fmt["Total buying price(RMB)"].apply(fmt_float_2)

            total_row_cost_fmt = total_row_cost.copy()
            for c in sum_cols_cost:
                total_row_cost_fmt[c] = fmt_num(total_row_cost[c])
            # Handle RMB fields in Total row explicitly if needed, but they are not in sum_cols_cost list for Total display per request?
            # Request says: "total của các cột: q’ty, Buying price(VND),Total buying price(VND),GAP,End user(%),Buyer(%),Import tax(%),VAT, Transportation,Management fee(%)"
            # So RMB totals are NOT requested here.
                
            # Append Total
            df_cost_fmt = pd.concat([df_cost_fmt, pd.DataFrame([total_row_cost_fmt])], ignore_index=True)
            
            st.dataframe(df_cost_fmt, use_container_width=True, hide_index=True)
            
            if st.button("💾 Lưu Chi Phí (Link Dashboard)"):
                if not po_no_input: st.error("Thiếu số PO!")
                else:
                    # 1. Upload Drive
                    # Path: CHI PHI/{Year}/{Customer}/{Month}/
                    curr_year = datetime.now().strftime("%Y")
                    curr_month = datetime.now().strftime("%m")
                    path_list = ["CHI PHI", curr_year, cust_name, curr_month]
                    
                    wb = Workbook(); ws = wb.active; ws.title = "COST"
                    ws.append(cols_cost)
                    for r in df_cost_view.to_dict('records'):
                        ws.append(list(r.values()))
                    
                    # Total Row Excel
                    vals = ["TOTAL", "", "", ""]
                    vals.append(df_cost_view["Q'ty"].apply(to_float).sum())
                    vals.append("") # Buy RMB
                    vals.append("") # Total Buy RMB
                    vals.append("") # Rate
                    vals.append(df_cost_view["Buying price(VND)"].apply(to_float).sum())
                    vals.append(df_cost_view["Total buying price(VND)"].apply(to_float).sum())
                    vals.append(df_cost_view["GAP"].apply(to_float).sum())
                    vals.append(df_cost_view["End user(%)"].apply(to_float).sum())
                    vals.append(df_cost_view["Buyer(%)"].apply(to_float).sum())
                    vals.append(df_cost_view["Import tax(%)"].apply(to_float).sum())
                    vals.append(df_cost_view["VAT"].apply(to_float).sum())
                    vals.append(df_cost_view["Transportation"].apply(to_float).sum())
                    vals.append(df_cost_view["Management fee(%)"].apply(to_float).sum())
                    vals.append("") # Profit %
                    ws.append(vals)
                    
                    out = io.BytesIO(); wb.save(out); out.seek(0)
                    fname = f"{po_no_input}.xlsx"
                    lnk, _ = upload_to_drive_structured(out, path_list, fname)
                    
                    # 2. Insert to DB for Dashboard Cost Calculation (crm_shared_history)
                    # Logic Dashboard: Cost = Revenue - Profit. 
                    # Do đó, cần lưu Profit vào crm_shared_history để dashboard tính toán đúng.
                    recs_hist = []
                    for r in st.session_state.po_main_df.to_dict('records'):
                         recs_hist.append({
                            "history_id": f"PO_{po_no_input}_{int(time.time())}_{r['Item code']}", 
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "quote_no": po_no_input, # Dùng PO No thay Quote No
                            "customer": cust_name,
                            "item_code": r["Item code"], 
                            "qty": to_float(r["Q'ty"]),
                            "unit_price": to_float(r["Unit price(VND)"]),
                            "total_price_vnd": to_float(r["Total price(VND)"]),
                            "profit_vnd": to_float(r["Profit(VND)"]),
                            "config_data": "{}" # Placeholder
                        })
                    try:
                        # Lưu ý: Cần fallback nếu bảng crm_shared_history có ràng buộc unique
                        # Ở đây insert mới
                        supabase.table("crm_shared_history").insert(recs_hist).execute()
                        st.success("✅ Đã lưu Chi phí & Lợi nhuận (Dashboard đã được cập nhật)!")
                        st.markdown(f"📂 [Link File Chi Phí]({lnk})")
                    except Exception as e: st.error(f"Lỗi lưu DB History: {e}")
# --- TAB 5: TRACKING, PAYMENTS, HISTORY ---
with t5:
    t5_1, t5_2, t5_3 = st.tabs(["📦 THEO DÕI ĐƠN HÀNG", "💸 THANH TOÁN", "📜 LỊCH SỬ"])
    
    # ---------------- TAB 5.1: ĐƠN HÀNG (ACTIVE) ----------------
    with t5_1:
        st.subheader("5.1: THEO DÕI ĐƠN HÀNG (ACTIVE)")
        if st.button("🔄 Refresh Orders"): st.cache_data.clear(); st.rerun()
        
        with st.expander("🔐 Admin: Reset Orders (Xóa hết dữ liệu Tracking)"):
            adm_tr = st.text_input("Pass Admin", type="password", key="pass_tr")
            if st.button("⚠️ XÓA HẾT TRACKING"):
                if adm_tr == "admin":
                    supabase.table("crm_tracking").delete().neq("id", 0).execute()
                    st.success("Deleted All Tracking!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass!")

        # Load data
        df_track = load_data("crm_tracking", order_by="id")
        
        # Filter Active Orders (Exclude History conditions)
        # History Logic: (NCC + Arrived + Proof) OR (KH + Delivered + Proof)
        if not df_track.empty:
            def is_history(row):
                has_proof = pd.notna(row['proof_image']) and str(row['proof_image']) != ''
                cond_ncc = (row['order_type'] == 'NCC' and row['status'] == 'Arrived' and has_proof)
                cond_kh = (row['order_type'] == 'KH' and row['status'] == 'Delivered' and has_proof)
                return cond_ncc or cond_kh

            mask_active = ~df_track.apply(is_history, axis=1)
            df_active = df_track[mask_active].copy()
        else:
            df_active = pd.DataFrame()

        if not df_active.empty:
            c_up, c_list = st.columns([1, 2])
            
            # --- FORM CẬP NHẬT ---
            with c_up:
                st.markdown("#### 📝 Cập nhật trạng thái")
                po_list = df_active['po_no'].unique()
                sel_po = st.selectbox("Chọn PO", po_list, key="tr_po_active")
                curr_row = df_active[df_active['po_no'] == sel_po].iloc[0]
                
                new_status = st.selectbox("Trạng thái mới", 
                                          ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"], 
                                          index=["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"].index(curr_row['status']) if curr_row['status'] in ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"] else 0,
                                          key="tr_st_active")
                
                proof_img = st.file_uploader("Upload Ảnh Proof (Bắt buộc để hoàn thành)", type=['png', 'jpg'], key="tr_img_active")
                
                if st.button("💾 Cập nhật"):
                    upd_data = {"status": new_status, "last_update": datetime.now().strftime("%d/%m/%Y")}
                    if proof_img:
                        lnk, _ = upload_to_drive_simple(proof_img, "CRM_PROOF", f"PRF_{sel_po}_{int(time.time())}.png")
                        upd_data["proof_image"] = lnk
                    
                    supabase.table("crm_tracking").update(upd_data).eq("po_no", sel_po).execute()
                    
                    # --- TRIGGER LOGIC: AUTOMATIC INSERT TO PAYMENTS ---
                    if new_status == "Delivered" and curr_row['order_type'] == 'KH':
                        try:
                            # Check payment exists
                            pay_check = supabase.table("crm_payments").select("*").eq("po_no", sel_po).execute()
                            if not pay_check.data:
                                eta_pay = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
                                pay_rec = {
                                    "po_no": sel_po, 
                                    "partner": curr_row['partner'],
                                    "payment_status": "Đợi xuất hóa đơn",
                                    "eta_payment": eta_pay,
                                    "invoice_no": ""
                                }
                                supabase.table("crm_payments").insert([pay_rec]).execute()
                                st.toast("✅ Đã tự động tạo lịch thanh toán!", icon="💸")
                        except Exception as e:
                            st.warning(f"Không thể tạo lịch thanh toán tự động. Lỗi: {e}")

                    st.success("Đã cập nhật!"); time.sleep(1); st.rerun()

                st.divider()
                # --- DELETE ROW FUNCTION ---
                st.markdown("#### 🗑️ Xóa đơn hàng")
                po_to_del = st.selectbox("Chọn PO để xóa", [""] + list(po_list), key="del_po_active")
                if po_to_del and st.button("Xóa PO này"):
                    supabase.table("crm_tracking").delete().eq("po_no", po_to_del).execute()
                    st.warning(f"Đã xóa {po_to_del}"); time.sleep(1); st.rerun()

            # --- DISPLAY LIST ---
            with c_list:
                st.markdown("#### 📋 Danh sách đang hoạt động")
                st.dataframe(
                    df_active, 
                    column_config={
                        "proof_image": st.column_config.ImageColumn("Proof"), 
                        "status": st.column_config.TextColumn("Status"),
                        "po_no": "PO No.", "partner": "Partner", "eta": "ETA"
                    }, 
                    use_container_width=True, hide_index=True
                )
        else: st.info("Không có đơn hàng nào đang hoạt động.")

    # ---------------- TAB 5.2: THANH TOÁN ----------------
    with t5_2:
        st.subheader("5.2: QUẢN LÝ THANH TOÁN (PAYMENTS)")
        if st.button("🔄 Refresh Payments"): st.cache_data.clear(); st.rerun()
        
        with st.expander("🔐 Admin: Reset Payments"):
            adm_pay = st.text_input("Pass Admin", type="password", key="pass_pay")
            if st.button("⚠️ XÓA HẾT PAYMENTS"):
                if adm_pay == "admin":
                    supabase.table("crm_payments").delete().neq("id", 0).execute()
                    st.success("Deleted All Payments!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass!")

        df_pay = load_data("crm_payments", order_by="id")
        
        if not df_pay.empty:
            c_p_up, c_p_list = st.columns([1, 2])
            
            with c_p_up:
                st.markdown("#### 📝 Cập nhật thanh toán")
                # Filter rows not fully paid? Assuming we show all here to manage
                p_po_list = df_pay['po_no'].unique()
                sel_p_po = st.selectbox("Chọn PO Thanh toán", p_po_list, key="pay_po_sel")
                curr_p_row = df_pay[df_pay['po_no'] == sel_p_po].iloc[0]
                
                inv_no = st.text_input("Số Hóa Đơn (Invoice No)", value=safe_str(curr_p_row.get('invoice_no', '')))
                
                curr_status = safe_str(curr_p_row.get('payment_status', 'Đợi xuất hóa đơn'))
                status_opts = ["Đợi xuất hóa đơn", "Đợi thanh toán", "Đã nhận thanh toán"]
                idx_st = status_opts.index(curr_status) if curr_status in status_opts else 0
                new_p_status = st.selectbox("Trạng thái", status_opts, index=idx_st, key="pay_st_sel")
                
                if st.button("💾 Lưu Thanh Toán"):
                    upd_p = {"invoice_no": inv_no, "payment_status": new_p_status}
                    # TRIGGER: Update payment date if paid
                    if new_p_status == "Đã nhận thanh toán":
                        upd_p["payment_date"] = datetime.now().strftime("%d/%m/%Y")
                    
                    supabase.table("crm_payments").update(upd_p).eq("po_no", sel_p_po).execute()
                    st.success("Updated Payment!"); time.sleep(1); st.rerun()
                
                st.divider()
                # --- DELETE PAYMENT ROW ---
                st.markdown("#### 🗑️ Xóa dòng thanh toán")
                if st.button("Xóa dòng này"):
                    supabase.table("crm_payments").delete().eq("po_no", sel_p_po).execute()
                    st.warning("Deleted!"); time.sleep(1); st.rerun()

            with c_p_list:
                st.markdown("#### 💰 Danh sách cần thanh toán")
                st.dataframe(
                    df_pay,
                    column_config={
                        "po_no": "PO No.", "partner": "Khách hàng",
                        "payment_status": "Trạng thái", "eta_payment": "Hạn TT",
                        "invoice_no": "Invoice", "payment_date": "Ngày TT"
                    },
                    use_container_width=True, hide_index=True
                )
        else: st.info("Chưa có dữ liệu thanh toán. (Dữ liệu sẽ tự động qua đây khi đơn Khách Hàng chuyển trạng thái Delivered)")

    # ---------------- TAB 5.3: LỊCH SỬ ----------------
    with t5_3:
        st.subheader("5.3: LỊCH SỬ ĐƠN HÀNG (HISTORY)")
        if st.button("🔄 Refresh History"): st.cache_data.clear(); st.rerun()
        
        # Re-load tracking to get history
        df_track_h = load_data("crm_tracking", order_by="id")
        
        if not df_track_h.empty:
            def is_history_check(row):
                has_proof = pd.notna(row['proof_image']) and str(row['proof_image']) != ''
                cond_ncc = (row['order_type'] == 'NCC' and row['status'] == 'Arrived' and has_proof)
                cond_kh = (row['order_type'] == 'KH' and row['status'] == 'Delivered' and has_proof)
                return cond_ncc or cond_kh
            
            mask_hist = df_track_h.apply(is_history_check, axis=1)
            df_history = df_track_h[mask_hist].copy()
            
            if not df_history.empty:
                st.dataframe(
                    df_history,
                    column_config={
                        "proof_image": st.column_config.ImageColumn("Proof"), 
                        "status": st.column_config.TextColumn("Status"),
                        "po_no": "PO No.", "partner": "Partner", "eta": "ETA"
                    },
                    use_container_width=True, hide_index=True
                )
                
                with st.expander("🗑️ Xóa Lịch Sử"):
                    h_po_list = df_history['po_no'].unique()
                    po_del_h = st.selectbox("Chọn PO Lịch sử để xóa", h_po_list, key="del_hist_sel")
                    if st.button("Xóa Vĩnh Viễn PO Lịch Sử"):
                        supabase.table("crm_tracking").delete().eq("po_no", po_del_h).execute()
                        st.warning("Deleted!"); time.sleep(1); st.rerun()
            else:
                st.info("Chưa có đơn hàng nào hoàn tất quy trình (Có Proof + Đúng trạng thái đích).")
        else:
            st.info("No Data.")

# --- TAB 6: MASTER DATA (RESTORED ALGORITHM V6025) ---
with t6:
    tc, ts, tt = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    
    # --- CUSTOMERS (ALGORITHM: DELETE ALL -> INSERT CHUNKS, NORMALIZED COLUMNS) ---
    with tc:
        st.markdown("### 1. QUẢN LÝ KHÁCH HÀNG")
        df_c = load_data("crm_customers", order_by="id")
        st.dataframe(df_c, use_container_width=True, hide_index=True)
        
        st.write("---")
        st.write("📥 **Import Dữ Liệu Mới (Ghi đè toàn bộ)**")
        st.caption("Excel Headers: Short Name, Eng Name, VN Name, Address 1, Tax Code... (Hệ thống tự động chuẩn hóa)")
        up_c = st.file_uploader("Upload Excel Khách Hàng", type=["xlsx"], key="up_cust_master")
        
        if up_c and st.button("🚀 CẬP NHẬT KHÁCH HÀNG (V6025 Algorithm)"):
            try:
                # 1. Read Excel
                df = pd.read_excel(up_c, dtype=str).fillna("")
                
                # 2. Normalize Columns (Logic V6025 Safe Import)
                # Chuyển tên cột về dạng lowercase và thay khoảng trắng bằng gạch dưới để khớp với DB
                # Ví dụ: "Short Name" -> "short_name", "Address 1" -> "address_1"
                df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
                
                data = df.to_dict('records')
                
                if data:
                    # 3. Clear Data
                    supabase.table("crm_customers").delete().neq("id", 0).execute()
                    
                    # 4. Insert Data (Chunking)
                    chunk_size = 100
                    for k in range(0, len(data), chunk_size):
                        batch = data[k:k+chunk_size]
                        # Remove 'id' if exists to let DB auto-inc
                        for b in batch:
                            if 'id' in b: del b['id']
                        supabase.table("crm_customers").insert(batch).execute()
                        
                    st.success(f"✅ Đã import thành công {len(data)} khách hàng!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("File rỗng!")
            except Exception as e:
                st.error(f"Lỗi Import: {e}")

    # --- SUPPLIERS (ALGORITHM: DELETE ALL -> INSERT CHUNKS) ---
    with ts:
        st.markdown("### 2. QUẢN LÝ NHÀ CUNG CẤP")
        df_s = load_data("crm_suppliers", order_by="id")
        st.dataframe(df_s, use_container_width=True, hide_index=True)
        
        st.write("---")
        st.write("📥 **Import Dữ Liệu Mới (Ghi đè toàn bộ)**")
        up_s = st.file_uploader("Upload Excel Nhà Cung Cấp", type=["xlsx"], key="up_supp_master")
        
        if up_s and st.button("🚀 CẬP NHẬT NHÀ CUNG CẤP (V6025 Algorithm)"):
            try:
                # 1. Read Excel
                df = pd.read_excel(up_s, dtype=str).fillna("")
                
                # 2. Normalize Columns
                df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
                
                data = df.to_dict('records')
                
                if data:
                    # 3. Clear Data
                    supabase.table("crm_suppliers").delete().neq("id", 0).execute()
                    
                    # 4. Insert Data (Chunking)
                    chunk_size = 100
                    for k in range(0, len(data), chunk_size):
                        batch = data[k:k+chunk_size]
                        for b in batch:
                            if 'id' in b: del b['id']
                        supabase.table("crm_suppliers").insert(batch).execute()
                        
                    st.success(f"✅ Đã import thành công {len(data)} nhà cung cấp!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("File rỗng!")
            except Exception as e:
                st.error(f"Lỗi Import: {e}")

    # --- TEMPLATE ---
    with tt:
        st.write("Upload Template Excel (Quotation)")
        up_t = st.file_uploader("File Template (.xlsx)", type=["xlsx"])
        t_name = st.text_input("Tên Template (Nhập chính xác: AAA-QUOTATION)")
        if up_t and t_name and st.button("Lưu Template"):
            lnk, fid = upload_to_drive_simple(up_t, "CRM_TEMPLATES", f"TMP_{t_name}.xlsx")
            if fid: 
                supabase.table("crm_templates").insert([{"template_name": t_name, "file_id": fid, "last_updated": datetime.now().strftime("%d/%m/%Y")}]).execute()
                st.success("OK"); st.rerun()
        st.dataframe(load_data("crm_templates"))
