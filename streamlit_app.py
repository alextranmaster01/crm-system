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

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO
# =============================================================================
APP_VERSION = "V6023 - FINAL FIX CONFIG & FORMULA"
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
    st.error("⚠️ Thiếu thư viện. Vui lòng chạy lệnh: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl")
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
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], client_secret=OAUTH_INFO["client_secret"])
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
        
        # --- FIX LỖI IMPORT PGRST204: KHÔNG SORT ROW_ORDER NẾU CỘT KHÔNG TỒN TẠI ---
        # Thay vì sort cứng bằng Supabase, ta sẽ tải về rồi sort bằng Pandas cho an toàn.
        # Hoặc dùng try-except để fallback. Ở đây chọn cách đơn giản: tải hết về rồi sort.
        res = query.execute()
        df = pd.DataFrame(res.data)
        
        if not df.empty:
            # Drop cột 'id' nếu không cần thiết
            if table != "crm_tracking" and 'id' in df.columns: 
                df = df.drop(columns=['id'])
            
            # Sort bằng Pandas nếu có cột order_by
            if order_by in df.columns:
                df = df.sort_values(by=order_by, ascending=ascending)
            
        return df
    except Exception as e:
        # st.error(f"Lỗi load data {table}: {e}") # Có thể uncomment để debug
        return pd.DataFrame()

# =============================================================================
# 3. LOGIC TÍNH TOÁN CORE
# =============================================================================
def recalculate_quote_logic(df, params):
    cols_to_num = ["Q'ty", "Buying price(VND)", "Buying price(RMB)", "AP price(VND)", "Unit price(VND)"]
    for c in cols_to_num:
        if c in df.columns: df[c] = df[c].apply(to_float)
    
    pend = params['end']/100; pbuy = params['buy']/100
    ptax = params['tax']/100; pvat = params['vat']/100
    ppay = params['pay']/100; pmgmt = params['mgmt']/100
    val_trans = params['trans']

    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]

    df["End user(%)"] = df["AP total price(VND)"] * pend
    df["Buyer(%)"] = df["Total price(VND)"] * pbuy
    df["Import tax(%)"] = df["Total buying price(VND)"] * ptax
    df["VAT"] = df["Total price(VND)"] * pvat
    df["Management fee(%)"] = df["Total price(VND)"] * pmgmt
    df["Payback(%)"] = df["GAP"] * ppay
    df["Transportation"] = val_trans 

    gap_positive = df["GAP"].apply(lambda x: x * 0.6 if x > 0 else 0)
    cost_ops = gap_positive + df["End user(%)"] + df["Buyer(%)"] + df["Import tax(%)"] + df["VAT"] + df["Management fee(%)"] + df["Transportation"]
    
    df["Profit(VND)"] = df["Total price(VND)"] - df["Total buying price(VND)"] - cost_ops + df["Payback(%)"]
    df["Profit_Pct_Raw"] = df.apply(lambda row: (row["Profit(VND)"] / row["Total price(VND)"] * 100) if row["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    
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

# --- TAB 1: DASHBOARD ---
with t1:
    if st.button("🔄 REFRESH DATA"): st.cache_data.clear(); st.rerun()
    db_cust = load_data("db_customer_orders")
    db_supp = load_data("db_supplier_orders")
    rev = db_cust['total_price'].apply(to_float).sum() if not db_cust.empty else 0
    cost = db_supp['total_vnd'].apply(to_float).sum() if not db_supp.empty else 0
    profit = rev - cost 
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ NCC</h3><h1>{fmt_num(cost)}</h1></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN GỘP</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: KHO HÀNG ---
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
            
        if up_file and st.button("🚀 Import"):
            try:
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                img_map = {}
                for image in getattr(ws, '_images', []):
                    row = image.anchor._from.row + 1
                    buf = io.BytesIO(image._data())
                    cell_specs = ws.cell(row=row, column=4).value 
                    specs_val = safe_str(cell_specs)
                    safe_name = re.sub(r'[\\/*?:"<>|]', "", specs_val).strip()
                    if not safe_name: safe_name = f"NO_SPECS_R{row}"
                    fname = f"{safe_name}.png"
                    link, _ = upload_to_drive_simple(buf, "CRM_PRODUCT_IMAGES", fname)
                    img_map[row] = link
                
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
                        if not d.get('image_path') and (i+2) in img_map: d['image_path'] = img_map[i+2]
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
                    chunk_ins = 100
                    codes = [b['item_code'] for b in records if b['item_code']]
                    if codes: supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                    
                    # --- FIX: THỬ INSERT BÌNH THƯỜNG TRƯỚC ---
                    try:
                        for k in range(0, len(records), chunk_ins):
                            batch = records[k:k+chunk_ins]
                            supabase.table("crm_purchases").insert(batch).execute()
                    except Exception as e_ins:
                         # NẾU LỖI DO CỘT row_order KHÔNG TỒN TẠI, XÓA NÓ ĐI VÀ INSERT LẠI
                        if "row_order" in str(e_ins):
                            st.warning("⚠️ Database cũ chưa có cột row_order. Đang tự động bỏ qua cột này để insert...")
                            for rec in records:
                                if 'row_order' in rec: del rec['row_order']
                            
                            for k in range(0, len(records), chunk_ins):
                                batch = records[k:k+chunk_ins]
                                supabase.table("crm_purchases").insert(batch).execute()
                        else:
                            raise e_ins

                    st.success(f"✅ Đã import {len(records)} dòng (đúng thứ tự Excel)!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")

    with c_view:
        # Load data đã fix sort
        df_pur = load_data("crm_purchases", order_by="row_order", ascending=True) 
        cols_to_drop = ['created_at', 'row_order']
        df_pur = df_pur.drop(columns=[c for c in cols_to_drop if c in df_pur.columns], errors='ignore')

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

# --- TAB 3: BÁO GIÁ ---
with t3:
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    
    # ------------------ TRA CỨU LỊCH SỬ ------------------
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
                    
                    # --- HOTFIX: FORCE RELOAD CONFIG FROM EXCEL FALLBACK OR DB ---
                    # Check if new quote selected to force RERUN
                    if 'loaded_quote_id' not in st.session_state: st.session_state.loaded_quote_id = None
                    
                    hist_config_row = df_hist_idx[
                        (df_hist_idx['quote_no'] == q_no) & 
                        (df_hist_idx['customer'] == cust)
                    ].iloc[0] if not df_hist_idx.empty else None
                    
                    config_loaded = {}
                    
                    # 1. Try DB
                    if hist_config_row is not None and 'config_data' in hist_config_row and hist_config_row['config_data']:
                        try:
                            config_loaded = json.loads(hist_config_row['config_data'])
                        except: pass
                    
                    # 2. If DB empty, Try Drive (Fallback)
                    if not config_loaded:
                          cfg_search_name = f"CONFIG_{q_no}_{cust}"
                          fid_cfg, _, _ = search_file_in_drive_by_name(cfg_search_name)
                          if fid_cfg:
                              fh_cfg = download_from_drive(fid_cfg)
                              if fh_cfg:
                                  try:
                                      df_cfg = pd.read_excel(fh_cfg)
                                      if not df_cfg.empty:
                                          config_loaded = df_cfg.iloc[0].to_dict()
                                  except: pass

                    # 3. Apply Config
                    if config_loaded:
                        st.info(f"📊 **CẤU HÌNH CHI PHÍ (ĐÃ LOAD):** "
                                f"End User: {config_loaded.get('end')}% | Buyer: {config_loaded.get('buy')}% | "
                                f"Tax: {config_loaded.get('tax')}% | VAT: {config_loaded.get('vat')}% | "
                                f"Payback: {config_loaded.get('pay')}% | Mgmt: {config_loaded.get('mgmt')}% | "
                                f"Trans: {fmt_num(config_loaded.get('trans'))}")
                        
                        # Trigger RERUN if switching quotes to update widgets
                        if sel_quote_hist != st.session_state.loaded_quote_id:
                            keys_load = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
                            for k in keys_load:
                                val_str = str(config_loaded.get(k, 0))
                                st.session_state[f"pct_{k}"] = val_str
                                st.session_state[f"input_{k}"] = val_str # Force Widget Key
                            
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
            # --- WIDGET INPUT ---
            # Quan trọng: key=f"input_{k}" để khớp với logic load lịch sử
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
            
            for i, r in df_rfq.iterrows():
                def get_val(keywords):
                    for k in keywords:
                        real_col = cols_found.get(k)
                        if real_col: return safe_str(r[real_col])
                    return ""

                # 1. LẤY DỮ LIỆU TỪ EXCEL (SOURCE OF TRUTH)
                code_excel = get_val(["item code", "code", "mã", "part number"])
                name_excel = get_val(["item name", "name", "tên", "description"])
                specs_excel = get_val(["specs", "quy cách", "thông số"])
                qty_raw = get_val(["q'ty", "qty", "quantity", "số lượng"])
                qty = to_float(qty_raw) if qty_raw else 1.0

                # 2. MATCHING LOGIC (Khớp 3 thông số: Code, Name, Specs)
                match = None
                warning_msg = ""
                
                candidates = [
                    rec for rec in db_records 
                    if clean_key(rec['item_code']) == clean_key(code_excel)
                    and clean_key(rec['item_name']) == clean_key(name_excel)
                    and clean_key(rec['specs']) == clean_key(specs_excel)
                ]

                if candidates:
                    match = candidates[0]
                else:
                    warning_msg = "⚠️ KHÔNG KHỚP DATA"

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

                item = {
                    "No": i+1, "Cảnh báo": warning_msg, 
                    "Item code": code_excel, "Item name": name_excel, "Specs": specs_excel, "Q'ty": qty, 
                    "Buying price(RMB)": fmt_float_2(buy_rmb), "Total buying price(rmb)": fmt_float_2(buy_rmb * qty),
                    "Exchange rate": fmt_float_2(ex_rate), "Buying price(VND)": fmt_float_2(buy_vnd), "Total buying price(VND)": fmt_float_2(buy_vnd * qty),
                    "AP price(VND)": "0.00", "AP total price(VND)": "0.00", "Unit price(VND)": "0.00", "Total price(VND)": "0.00",
                    "GAP": "0.00", "End user(%)": "0.00", "Buyer(%)": "0.00", "Import tax(%)": "0.00", "VAT": "0.00", "Transportation": "0.00",
                    "Management fee(%)": "0.00", "Payback(%)": "0.00", "Profit(VND)": "0.00", "Profit(%)": "0.0%",
                    "Supplier": supplier, "Image": image, "Leadtime": leadtime
                }
                res.append(item)
            
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
        # REAL-TIME CALCULATION BEFORE DISPLAY (Fixes Transportation lag)
        st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)

        cols_order = ["Cảnh báo", "No"] + [c for c in st.session_state.quote_df.columns if c not in ["Cảnh báo", "No"]]
        st.session_state.quote_df = st.session_state.quote_df[cols_order]

        cols_to_hide = ["Image", "Profit_Pct_Raw"]
        df_show = st.session_state.quote_df.drop(columns=[c for c in cols_to_hide if c in st.session_state.quote_df.columns], errors='ignore')

        # --- ADD TOTAL ROW LOGIC ---
        df_display = df_show.copy()
        
        # Calculate sums for relevant columns
        cols_to_sum = ["Buying price(RMB)", "Total buying price(rmb)", "Buying price(VND)", 
                       "Total buying price(VND)", "AP price(VND)", "AP total price(VND)", 
                       "Unit price(VND)", "Total price(VND)", "GAP", "End user(%)", "Buyer(%)", 
                       "Import tax(%)", "VAT", "Transportation", "Management fee(%)", "Payback(%)", "Profit(VND)"]
        
        total_row = {"No": "TOTAL", "Cảnh báo": "", "Item code": "", "Item name": "", "Specs": "", "Q'ty": 0}
        for c in cols_to_sum:
            if c in df_display.columns:
                total_val = df_display[c].apply(to_float).sum()
                total_row[c] = fmt_float_2(total_val)
        
        # Append Total Row to dataframe for display
        df_display = pd.concat([df_display, pd.DataFrame([total_row])], ignore_index=True)

        edited_df = st.data_editor(
            df_display,
            column_config={
                "Buying price(RMB)": st.column_config.TextColumn("Buying(RMB)", disabled=True),
                "Buying price(VND)": st.column_config.TextColumn("Buying(VND)", disabled=True),
                "Cảnh báo": st.column_config.TextColumn("Cảnh báo", width="small", disabled=True),
                "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d"),
            },
            use_container_width=True, height=600, key="main_editor",
            hide_index=True 
        )
        
        # Sync edits back (Exclude Total Row)
        df_data_only = edited_df[edited_df["No"] != "TOTAL"]
        # Update main dataframe with edited values (mapped back)
        for idx, row in df_data_only.iterrows():
             if idx < len(st.session_state.quote_df):
                 for c in df_data_only.columns:
                     if c in st.session_state.quote_df.columns:
                         st.session_state.quote_df.at[idx, c] = row[c]
        
        # --- VIEW TOTAL PRICE (FEATURE ADDED) ---
        total_q = st.session_state.quote_df["Total price(VND)"].apply(to_float).sum()
        st.markdown(f'<div class="total-view">💰 TỔNG GIÁ TRỊ BÁO GIÁ (TOTAL VIEW): {fmt_float_2(total_q)} VND</div>', unsafe_allow_html=True)

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
            st.dataframe(st.session_state.quote_df[valid_cols], use_container_width=True, hide_index=True)
            
            # Show Total in Review as well
            st.markdown(f'<div class="total-view">💰 TỔNG CỘNG: {fmt_float_2(total_q)} VND</div>', unsafe_allow_html=True)
            
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
                                start_row = 10
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
                                st.markdown(f"📂 [Mở Folder]({lnk})", unsafe_allow_html=True)
                                st.download_button(label="📥 Tải File Về Máy", data=out, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception as e: st.error(f"Lỗi xuất Excel: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        with c_sv:
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("💾 LƯU LỊCH SỬ (QUAN TRỌNG ĐỂ LÀM PO)"):
                if cust_name:
                    # 1. CLEAN PARAMS BEFORE JSON DUMP (AVOID NaN IN CONFIG)
                    clean_params = {}
                    for k, v in params.items():
                        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)): clean_params[k] = 0.0
                        else: clean_params[k] = v
                    config_json = json.dumps(clean_params) 
                    
                    recs = []
                    for r in st.session_state.quote_df.to_dict('records'):
                        # --- FIX: DATA CLEANING (NaN -> 0.0) ---
                        val_qty = to_float(r["Q'ty"])
                        val_unit = to_float(r["Unit price(VND)"])
                        val_total = to_float(r["Total price(VND)"])
                        val_profit = to_float(r["Profit(VND)"])
                        
                        # Ensure no NaNs exist (Supabase API Error fix)
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
                    
                    try:
                        # --- TRY INSERT WITH config_data ---
                        supabase.table("crm_shared_history").insert(recs).execute()
                    except Exception as e:
                        # --- FALLBACK IF DB SCHEMA IS MISSING 'config_data' COLUMN ---
                        if "config_data" in str(e) or "PGRST204" in str(e):
                             # Remove 'config_data' key and retry insert
                             recs_fallback = [{k: v for k, v in r.items() if k != 'config_data'} for r in recs]
                             try:
                                 supabase.table("crm_shared_history").insert(recs_fallback).execute()
                                 st.warning("⚠️ Đã lưu thành công (Chế độ tương thích: Bỏ qua cấu hình chi phí do Database cũ).")
                             except Exception as e2:
                                 st.error(f"Lỗi Fatal sau khi retry: {e2}")
                                 st.stop()
                        else:
                             st.error(f"Lỗi lưu Supabase: {e}")
                             st.stop()

                    # Save CSV Backup
                    try:
                        csv_buffer = io.BytesIO()
                        st.session_state.quote_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                        csv_buffer.seek(0)
                        csv_name = f"HIST_{quote_no}_{cust_name}_{int(time.time())}.csv"
                        curr_year = datetime.now().strftime("%Y")
                        curr_month = datetime.now().strftime("%b").upper()
                        path_list_hist = ["QUOTATION_HISTORY", cust_name, curr_year, curr_month]
                        lnk, _ = upload_to_drive_structured(csv_buffer, path_list_hist, csv_name)
                        
                        # --- NEW FEATURE: SAVE CONFIG FILE SEPARATELY TO DRIVE ---
                        # Creates an Excel file with the percentage configuration
                        df_cfg = pd.DataFrame([clean_params])
                        cfg_buffer = io.BytesIO()
                        df_cfg.to_excel(cfg_buffer, index=False)
                        cfg_buffer.seek(0)
                        cfg_name = f"CONFIG_{quote_no}_{cust_name}_{int(time.time())}.xlsx"
                        upload_to_drive_structured(cfg_buffer, path_list_hist, cfg_name)
                        
                        st.success("✅ Đã lưu lịch sử DB & CSV (Kèm file cấu hình % riêng)!")
                        st.markdown(f"📂 [Folder Lịch Sử]({lnk})", unsafe_allow_html=True)
                    except Exception as e: st.error(f"Lỗi lưu Drive: {e}")
                else: st.error("Chọn khách!")
            st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 4: PO & ĐẶT HÀNG ---
with t4:
    if 'show_ncc_upload' not in st.session_state: st.session_state.show_ncc_upload = False
    if 'show_cust_upload' not in st.session_state: st.session_state.show_cust_upload = False
    if 'po_ncc_df' not in st.session_state: st.session_state.po_ncc_df = pd.DataFrame()
    if 'po_cust_df' not in st.session_state: st.session_state.po_cust_df = pd.DataFrame()
    
    st.markdown("### 🔎 TRA CỨU ĐƠN HÀNG (PO)")
    search_po = st.text_input("Nhập số PO, Mã hàng, Tên hàng, Khách, NCC...", key="search_po_tab")
    if search_po:
        df_po_cust = load_data("db_customer_orders")
        df_po_supp = load_data("db_supplier_orders")
        res_cust = pd.DataFrame()
        if not df_po_cust.empty:
            mask_c = df_po_cust.astype(str).apply(lambda x: x.str.contains(search_po, case=False, na=False)).any(axis=1)
            res_cust = df_po_cust[mask_c]
            if not res_cust.empty:
                st.info(f"Tìm thấy {len(res_cust)} dòng trong PO Khách Hàng")
                st.dataframe(res_cust, use_container_width=True)
        res_supp = pd.DataFrame()
        if not df_po_supp.empty:
            mask_s = df_po_supp.astype(str).apply(lambda x: x.str.contains(search_po, case=False, na=False)).any(axis=1)
            res_supp = df_po_supp[mask_s]
            if not res_supp.empty:
                st.info(f"Tìm thấy {len(res_supp)} dòng trong PO Nhà Cung Cấp")
                st.dataframe(res_supp, use_container_width=True)
        if res_cust.empty and res_supp.empty: st.warning("Không tìm thấy kết quả nào.")

    st.divider()
    c_ncc, c_kh = st.columns(2)
    with c_ncc:
        st.subheader("1. ĐẶT HÀNG NHÀ CUNG CẤP")
        with st.expander("🔐 Admin: Reset Đếm Đơn NCC"):
            adm_po_ncc = st.text_input("Pass Admin NCC", type="password")
            if st.button("Reset Đếm Đơn NCC"):
                if adm_po_ncc == "admin":
                    supabase.table("db_supplier_orders").delete().neq("id", 0).execute()
                    st.success("Đã reset bộ đếm PO NCC!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass")

        if st.button("➕ TẠO MỚI (Đặt NCC)"):
            st.session_state.po_ncc_df = pd.DataFrame()
            st.session_state.show_ncc_upload = True 
            st.rerun()

        if st.session_state.show_ncc_upload:
            po_s_no = st.text_input("Số PO NCC", key="po_s_input")
            up_s = st.file_uploader("Upload File Items (Excel)", key="ups")
            if up_s and st.button("Load Items NCC"):
                df_up = pd.read_excel(up_s, dtype=str).fillna("")
                db = load_data("crm_purchases")
                lookup = {clean_key(r['item_code']): r for r in db.to_dict('records')}
                recs = []
                for i, r in df_up.iterrows():
                    code_raw = safe_str(r.iloc[1])
                    qty_val = to_float(r.iloc[4])
                    no_val = safe_str(r.iloc[0]) 
                    match = lookup.get(clean_key(code_raw))
                    if match:
                        name = match['item_name']; specs = match['specs']; supplier = match['supplier_name']
                        buy_rmb = to_float(match['buying_price_rmb']); rate = to_float(match['exchange_rate'])
                        buy_vnd = to_float(match['buying_price_vnd']); leadtime = match['leadtime']
                    else:
                        name = safe_str(r.iloc[2]); specs = safe_str(r.iloc[3]); supplier = "Unknown"
                        buy_rmb = 0; rate = 0; buy_vnd = 0; leadtime = "0"
                    eta = calc_eta(datetime.now(), leadtime)
                    recs.append({
                        "No": no_val, "Item code": code_raw, "Item name": name, "Specs": specs, "Q'ty": qty_val,
                        "Buying price(RMB)": fmt_num(buy_rmb), "Total buying price(RMB)": fmt_num(buy_rmb * qty_val),
                        "Exchange rate": fmt_num(rate),
                        "Buying price(VND)": fmt_num(buy_vnd), "Total buying price(VND)": fmt_num(buy_vnd * qty_val),
                        "Supplier": supplier, "ETA": eta
                    })
                st.session_state.po_ncc_df = pd.DataFrame(recs)
            
            if not st.session_state.po_ncc_df.empty:
                st.dataframe(st.session_state.po_ncc_df, use_container_width=True, hide_index=True)
                if st.button("💾 XÁC NHẬN ĐẶT HÀNG NCC"):
                    if not po_s_no: st.error("Thiếu số PO")
                    else:
                        grouped = st.session_state.po_ncc_df.groupby("Supplier")
                        created_files = []
                        for supp_name, group in grouped:
                            if not supp_name: supp_name = "Unknown"
                            db_recs = []
                            for r in group.to_dict('records'):
                                db_recs.append({
                                    "po_number": po_s_no, "supplier": supp_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                                    "item_code": r["Item code"], "item_name": r["Item name"], "specs": r["Specs"],
                                    "qty": to_float(r["Q'ty"]), "total_vnd": to_float(r["Total buying price(VND)"]),
                                    "eta": r["ETA"]
                                })
                            supabase.table("db_supplier_orders").insert(db_recs).execute()
                            track_rec = {
                                "po_no": f"{po_s_no}_{supp_name}", "partner": supp_name, "status": "Ordered", "order_type": "NCC",
                                "last_update": datetime.now().strftime("%d/%m/%Y"), 
                                "eta": group.iloc[0]["ETA"]
                            }
                            supabase.table("crm_tracking").insert([track_rec]).execute()
                            wb = Workbook(); ws = wb.active; ws.title = "PO"
                            headers = ["No", "Item code", "Item name", "Specs", "Q'ty", "Buying(RMB)", "Total(RMB)", "Rate", "Buying(VND)", "Total(VND)", "Supplier", "ETA"]
                            ws.append(headers)
                            for r in group.to_dict('records'):
                                ws.append([r["No"], r["Item code"], r["Item name"], r["Specs"], r["Q'ty"], 
                                             r["Buying price(RMB)"], r["Total buying price(RMB)"], r["Exchange rate"],
                                             r["Buying price(VND)"], r["Total buying price(VND)"], r["Supplier"], r["ETA"]])
                            out = io.BytesIO(); wb.save(out); out.seek(0)
                            curr_year = datetime.now().strftime("%Y")
                            curr_month = datetime.now().strftime("%b").upper()
                            file_name = f"PO_{po_s_no}_{supp_name}.xlsx"
                            path_list = ["PO_NCC", curr_year, supp_name, curr_month]
                            lnk, _ = upload_to_drive_structured(out, path_list, file_name)
                            created_files.append((file_name, lnk, out)) 
                        st.success(f"✅ Đã tạo {len(created_files)} PO cho các NCC!")
                        for fname, lnk, buffer in created_files:
                            c_d1, c_d2 = st.columns([2,1])
                            c_d1.markdown(f"📂 **[Mở Folder: {fname}]({lnk})**", unsafe_allow_html=True)
                            c_d2.download_button(label=f"📥 Tải {fname}", data=buffer, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_{fname}")

    with c_kh:
        st.subheader("2. PO KHÁCH HÀNG")
        with st.expander("🔐 Admin: Reset Đếm Đơn Khách"):
            adm_po_cust = st.text_input("Pass Admin Cust", type="password")
            if st.button("Reset Đếm Đơn Khách"):
                if adm_po_cust == "admin":
                    supabase.table("db_customer_orders").delete().neq("id", 0).execute()
                    st.success("Đã reset bộ đếm PO Khách!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass")

        if st.button("➕ TẠO MỚI (PO Khách)"):
            st.session_state.po_cust_df = pd.DataFrame()
            st.session_state.show_cust_upload = True
            st.rerun()

        if st.session_state.show_cust_upload:
            po_c_no = st.text_input("Số PO Khách", key="po_c_input")
            custs = load_data("crm_customers")
            c_name = st.selectbox("Chọn Khách", [""] + custs['short_name'].tolist() if not custs.empty else [], key="sel_cust_po")
            uploaded_files = st.file_uploader("Upload File PO Khách (Excel/PDF)", type=['xlsx', 'pdf'], accept_multiple_files=True, key="upc")
            if uploaded_files and st.button("Load PO Khách"):
                if not c_name: st.error("Vui lòng chọn khách trước để lấy giá!")
                else:
                    excel_files = [f for f in uploaded_files if f.name.endswith('.xlsx')]
                    if excel_files:
                        all_recs = []
                        hist = load_data("crm_shared_history") 
                        cust_hist = hist[hist['customer'] == c_name].sort_values(by='date', ascending=False)
                        price_lookup = {}
                        for _, h in cust_hist.iterrows():
                            c_code = clean_key(h['item_code'])
                            if c_code not in price_lookup: price_lookup[c_code] = to_float(h['unit_price'])
                        db_items = load_data("crm_purchases")
                        lt_lookup = {clean_key(r['item_code']): r['leadtime'] for r in db_items.to_dict('records')}
                        for f in excel_files:
                            try:
                                df_up = pd.read_excel(f, header=None, skiprows=1, dtype=str).fillna("")
                                for i, r in df_up.iterrows():
                                    no_val = safe_str(r.iloc[0]) 
                                    code = safe_str(r.iloc[1])
                                    qty = to_float(r.iloc[4])
                                    unit_price = price_lookup.get(clean_key(code), 0)
                                    total = unit_price * qty
                                    leadtime = lt_lookup.get(clean_key(code), "0")
                                    eta = calc_eta(datetime.now(), leadtime)
                                    if code:
                                         all_recs.append({
                                             "No.": no_val, "Item code": code, "Item name": safe_str(r.iloc[2]),
                                             "Specs": safe_str(r.iloc[3]), "Q'ty": qty,
                                             "Unit price(VND)": fmt_num(unit_price), "Total price(VND)": fmt_num(total),
                                             "Customer": c_name, "ETA": eta, "Source File": f.name
                                         })
                            except: pass
                        st.session_state.po_cust_df = pd.DataFrame(all_recs)
                    else: st.info("Chỉ load data từ Excel. PDF sẽ được lưu khi bấm 'Lưu PO'.")

            if not st.session_state.po_cust_df.empty:
                st.dataframe(st.session_state.po_cust_df, use_container_width=True, hide_index=True)
                if st.button("💾 LƯU PO KHÁCH HÀNG"):
                    if not po_c_no: st.error("Thiếu số PO")
                    else:
                        db_recs = []
                        for r in st.session_state.po_cust_df.to_dict('records'):
                            db_recs.append({
                                "po_number": po_c_no, "customer": c_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                                "item_code": r["Item code"], "item_name": r["Item name"], "specs": r["Specs"],
                                "qty": to_float(r["Q'ty"]), "unit_price": to_float(r["Unit price(VND)"]),
                                "total_price": to_float(r["Total price(VND)"]), "eta": r["ETA"]
                            })
                        supabase.table("db_customer_orders").insert(db_recs).execute()
                        track_rec = {
                            "po_no": po_c_no, "partner": c_name, "status": "Waiting", "order_type": "KH",
                            "last_update": datetime.now().strftime("%d/%m/%Y"),
                            "eta": st.session_state.po_cust_df.iloc[0]["ETA"]
                        }
                        supabase.table("crm_tracking").insert([track_rec]).execute()
                        curr_year = datetime.now().strftime("%Y")
                        curr_month = datetime.now().strftime("%b").upper()
                        path_list = ["PO_KHACH_HANG", curr_year, c_name, curr_month]
                        saved_links = []
                        if uploaded_files:
                            for upf in uploaded_files:
                                upf.seek(0)
                                f_name = f"{po_c_no}_{upf.name}"
                                lnk, _ = upload_to_drive_structured(upf, path_list, f_name)
                                saved_links.append(lnk)
                        st.success("✅ Lưu PO Khách thành công! Đã link sang Tracking.")
                        if saved_links:
                             st.markdown(f"📂 **[Mở Folder PO Khách: {c_name}/{curr_month}]({saved_links[0]})**", unsafe_allow_html=True)

# --- TAB 5: TRACKING ---
with t5:
    st.subheader("THEO DÕI ĐƠN HÀNG (TRACKING)")
    if st.button("🔄 Refresh Tracking"): st.cache_data.clear(); st.rerun()
    df_track = load_data("crm_tracking", order_by="id")
    if not df_track.empty:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("#### Cập nhật trạng thái / Ảnh")
            po_list = df_track['po_no'].unique()
            sel_po = st.selectbox("Chọn PO", po_list, key="tr_po")
            new_status = st.selectbox("Trạng thái mới", ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"], key="tr_st")
            proof_img = st.file_uploader("Upload Ảnh Proof", type=['png', 'jpg'], key="tr_img")
            if st.button("Cập nhật Tracking"):
                upd_data = {"status": new_status, "last_update": datetime.now().strftime("%d/%m/%Y")}
                if proof_img:
                    lnk, _ = upload_to_drive_simple(proof_img, "CRM_PROOF", f"PRF_{sel_po}_{int(time.time())}.png")
                    upd_data["proof_image"] = lnk
                supabase.table("crm_tracking").update(upd_data).eq("po_no", sel_po).execute()
                st.success("Updated!"); time.sleep(1); st.rerun()
        with c2:
            st.markdown("#### Danh sách đơn hàng")
            st.dataframe(
                df_track, 
                column_config={
                    "proof_image": st.column_config.ImageColumn("Proof"), 
                    "status": st.column_config.TextColumn("Status"),
                    "po_no": "PO No.", "partner": "Partner", "eta": "ETA"
                }, 
                use_container_width=True, hide_index=True
            )
    else: st.info("Chưa có dữ liệu Tracking. Hãy tạo PO ở Tab 4.")

# --- TAB 6: MASTER DATA ---
with t6:
    tc, ts, tt = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    with tc:
        df = load_data("crm_customers"); st.data_editor(df, num_rows="dynamic", use_container_width=True)
        up = st.file_uploader("Import KH", key="uck")
        if up and st.button("Import KH"):
            d = pd.read_excel(up, dtype=str).fillna("")
            recs = []
            for i,r in d.iterrows(): recs.append({"short_name": safe_str(r.iloc[0]), "full_name": safe_str(r.iloc[1]), "address": safe_str(r.iloc[2])})
            supabase.table("crm_customers").insert(recs).execute(); st.rerun()
    with ts:
        df = load_data("crm_suppliers"); st.data_editor(df, num_rows="dynamic", use_container_width=True)
        up = st.file_uploader("Import NCC", key="usn")
        if up and st.button("Import NCC"):
            d = pd.read_excel(up, dtype=str).fillna("")
            recs = []
            for i,r in d.iterrows(): recs.append({"short_name": safe_str(r.iloc[0]), "full_name": safe_str(r.iloc[1]), "address": safe_str(r.iloc[2])})
            supabase.table("crm_suppliers").insert(recs).execute(); st.rerun()
    with tt:
        st.write("Upload Template Excel")
        up_t = st.file_uploader("File Template (.xlsx)", type=["xlsx"])
        t_name = st.text_input("Tên Template (Nhập: AAA-QUOTATION)")
        if up_t and t_name and st.button("Lưu Template"):
            lnk, fid = upload_to_drive_simple(up_t, "CRM_TEMPLATES", f"TMP_{t_name}.xlsx")
            if fid: supabase.table("crm_templates").insert([{"template_name": t_name, "file_id": fid, "last_updated": datetime.now().strftime("%d/%m/%Y")}]).execute(); st.success("OK"); st.rerun()
        st.dataframe(load_data("crm_templates"))
