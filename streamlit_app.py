# =============================================================================
# CRM SYSTEM - ULTIMATE HYBRID EDITION (V4810 - FINAL STABLE)
# - FIXED: KEEP EXCEL COLUMN ORDER & NAMES
# - FIXED: SORT BY 'NO' COLUMN
# - FIXED: IMAGE DISPLAY & UPSERT
# =============================================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import re
import json
from datetime import datetime, timedelta

# --- IMPORT LIBRARY ---
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    import xlsxwriter
    import plotly.express as px
except ImportError:
    st.error("⚠️ Cần cài đặt thư viện: pip install -r requirements.txt")
    st.stop()

# =============================================================================
# 1. SETUP UI
# =============================================================================
st.set_page_config(page_title="CRM V4810 ONLINE", layout="wide", page_icon="🌈", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #f4f6f9; }
    div.stButton > button { 
        background: linear-gradient(90deg, #1CB5E0 0%, #000851 100%);
        color: white; font-weight: bold; border: none; border-radius: 8px; height: 45px;
        transition: all 0.3s; box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    div.stButton > button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    .dashboard-card {
        border-radius: 15px; padding: 20px; color: white; text-align: center; margin-bottom: 20px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3); transition: transform 0.3s;
    }
    .dashboard-card:hover { transform: scale(1.02); }
    .card-sales { background: linear-gradient(45deg, #FF416C, #FF4B2B); }
    .card-profit { background: linear-gradient(45deg, #00b09b, #96c93d); }
    .card-orders { background: linear-gradient(45deg, #8E2DE2, #4A00E0); }
    .card-value { font-size: 32px; font-weight: 800; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
    .card-title { font-size: 16px; font-weight: 600; opacity: 0.9; text-transform: uppercase; }
    .img-box { border: 2px dashed #4b6cb7; padding: 20px; text-align: center; background: white; border-radius: 10px; }
    [data-testid="stDataFrame"] { border: 2px solid #000851; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

if 'quote_data' not in st.session_state: st.session_state['quote_data'] = None

# =============================================================================
# 2. BACKEND ENGINE
# =============================================================================

class CRMBackend:
    def __init__(self):
        self.supabase = self.init_supabase()
        self.drive = self.init_drive()

    def init_supabase(self):
        try: return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        except: return None

    def init_drive(self):
        try:
            info = st.secrets["google_oauth"]
            creds = Credentials(None, refresh_token=info["refresh_token"],
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=info["client_id"], client_secret=info["client_secret"])
            return build('drive', 'v3', credentials=creds)
        except: return None

    def get_folder_id(self, name, parent_id):
        try:
            q = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            files = self.drive.files().list(q=q, fields="files(id)").execute().get('files', [])
            if files: return files[0]['id']
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
            return self.drive.files().create(body=meta, fields='id').execute().get('id')
        except: return None

    def upload_img(self, file_obj, filename):
        if not self.drive: return None
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            l1 = self.get_folder_id("PRODUCT_IMAGES", root_id)
            media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
            meta = {'name': filename, 'parents': [l1]} 
            file = self.drive.files().create(body=meta, media_body=media, fields='id').execute()
            return f"https://drive.google.com/uc?export=view&id={file.get('id')}"
        except: return None

    def upload_recursive(self, file_obj, filename, root_type, year, entity, month):
        if not self.drive: return None, "Lỗi kết nối"
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            l1 = self.get_folder_id(root_type, root_id)
            l2 = self.get_folder_id(str(year), l1)
            cln = re.sub(r'[\\/*?:"<>|]', "", str(entity).upper().strip())
            l3 = self.get_folder_id(cln, l2)
            l4 = self.get_folder_id(str(month).upper(), l3)
            media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream', resumable=True)
            meta = {'name': filename, 'parents': [l4]}
            f = self.drive.files().create(body=meta, media_body=media, fields='webViewLink').execute()
            return f.get('webViewLink'), f"{root_type}/{year}/{cln}/{month}/{filename}"
        except Exception as e: return None, str(e)

    def calc_profit(self, row):
        try:
            qty = float(row.get("Q'ty", 0))
            buy_rmb = float(row.get('Buying Price (RMB)', 0) if pd.notnull(row.get('Buying Price (RMB)')) else row.get('buying_price_rmb', 0))
            rate = float(row.get('Exchange Rate', 3600) if pd.notnull(row.get('Exchange Rate')) else row.get('exchange_rate', 3600))
            
            buy_vnd = buy_rmb * rate
            total_buy = buy_vnd * qty
            user_ap = float(row.get('AP Price (VND)', 0))
            ap_total = user_ap * qty if user_ap > 0 else total_buy * 2
            gap = 0.10 * ap_total
            total_price = ap_total + gap
            unit = total_price / qty if qty > 0 else 0
            
            costs = (total_buy + gap + (0.10 * ap_total) + (0.05 * total_price) + 
                     (0.10 * total_buy) + (0.10 * total_price) + (0.10 * total_price) + 30000)
            profit = total_price - costs + (0.40 * gap)
            pct = (profit / total_price * 100) if total_price > 0 else 0
            
            return pd.Series({
                'Buying Price (VND)': buy_vnd, 'Total Buying (VND)': total_buy,
                'AP Price (VND)': ap_total/qty if qty else 0, 'AP Total (VND)': ap_total,
                'GAP': gap, 'Total Price (VND)': total_price, 'Unit Price (VND)': unit,
                'PROFIT (VND)': profit, '% Profit': pct
            })
        except: return pd.Series({'PROFIT (VND)': 0})

    def create_docx(self, df, cust):
        doc = Document()
        section = doc.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
        doc.add_heading(f'TECHNICAL SPECS - {str(cust).upper()}', 0).alignment = 1
        cols = ['Specs', "Q'ty", 'Buying Price (VND)', 'Total Buying (VND)', 'AP Price (VND)', 'Total Price (VND)', 'PROFIT (VND)', '% Profit']
        t = doc.add_table(rows=1, cols=len(cols)); t.style = 'Table Grid'
        for i, c in enumerate(cols): t.rows[0].cells[i].text = c
        for _, r in df.iterrows():
            row = t.add_row()
            for i, c in enumerate(cols):
                v = r.get(c, 0)
                row.cells[i].text = "{:,.0f}".format(v) if isinstance(v, (int, float)) and c != "% Profit" else f"{v:.1f}%" if c == "% Profit" else str(v)
        buf = io.BytesIO(); doc.save(buf); buf.seek(0)
        return buf

be = CRMBackend()

# =============================================================================
# 3. MAIN UI
# =============================================================================

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/906/906343.png", width=80)
    st.title("CRM V4810 PRO")
    st.markdown("---")
    menu = st.radio("MENU", ["📊 DASHBOARD", "📦 KHO HÀNG", "💰 BÁO GIÁ", "📑 QUẢN LÝ PO", "🚚 TRACKING", "⚙️ MASTER DATA"])
    st.markdown("---"); st.caption("Version: V4810 Stable")

# --- DASHBOARD ---
if menu == "📊 DASHBOARD":
    st.markdown("## 📊 TỔNG QUAN")
    try:
        q = be.supabase.table("crm_shared_history").select("total_profit_vnd").execute().data
        p = be.supabase.table("db_customer_orders").select("total_value").execute().data
        prof = sum([x['total_profit_vnd'] for x in q]) if q else 0
        sale = sum([x['total_value'] for x in p]) if p else 0
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="dashboard-card card-sales"><div class="card-title">DOANH SỐ</div><div class="card-value">{sale:,.0f}</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="dashboard-card card-profit"><div class="card-title">LỢI NHUẬN</div><div class="card-value">{prof:,.0f}</div></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="dashboard-card card-orders"><div class="card-title">ĐƠN HÀNG</div><div class="card-value">{len(p) if p else 0}</div></div>', unsafe_allow_html=True)
    except: st.error("Lỗi kết nối")

# --- KHO HÀNG (IMPORT & IMAGE) ---
elif menu == "📦 KHO HÀNG":
    st.markdown("## 📦 KHO HÀNG & HÌNH ẢNH")
    
    # 1. CẤU HÌNH CỘT HIỂN THỊ CHUẨN EXCEL
    EXCEL_COLUMNS_ORDER = [
        "No", "Item code", "Item name", "Specs", "Q'ty", 
        "Buying price (RMB)", "Total buying price (RMB)", "Exchange rate", 
        "Buying price (VND)", "Total buying price (VND)", "Leadtime", 
        "Supplier", "Images", "Type", "N/U/O/C"
    ]

    # 2. MAPPING DATABASE -> EXCEL HEADER
    DB_TO_EXCEL_MAP = {
        "no": "No", "item_code": "Item code", "item_name": "Item name",
        "specs": "Specs", "qty": "Q'ty",
        "buying_price_rmb": "Buying price (RMB)",
        "total_buying_price_rmb": "Total buying price (RMB)",
        "exchange_rate": "Exchange rate",
        "buying_price_vnd": "Buying price (VND)",
        "total_buying_price_vnd": "Total buying price (VND)",
        "leadtime": "Leadtime", "supplier": "Supplier",
        "images": "Images", "type": "Type", "nuoc": "N/U/O/C"
    }

    with st.expander("📥 IMPORT TỪ EXCEL (GHI ĐÈ)", expanded=False):
        up = st.file_uploader("Upload Excel", type=['xlsx'])
        if up and st.button("Import"):
            try:
                df_imp = pd.read_excel(up)
                # Chuẩn hóa tên cột
                df_imp.columns = [str(c).replace('\n',' ').strip() for c in df_imp.columns]
                
                # Loại bỏ trùng lặp trong file Excel
                if 'Specs' in df_imp.columns:
                    df_imp['Specs'] = df_imp['Specs'].astype(str).str.strip()
                    df_imp = df_imp.drop_duplicates(subset=['Specs'], keep='last')

                recs = []
                for _, r in df_imp.iterrows():
                    recs.append({
                        "no": r.get("No"), 
                        "item_code": str(r.get("Item code","")), 
                        "item_name": str(r.get("Item name","")),
                        "specs": str(r.get("Specs","")).strip(), 
                        "qty": r.get("Q'ty"),
                        "buying_price_rmb": r.get("Buying price (RMB)"), 
                        "total_buying_price_rmb": r.get("Total buying price (RMB)"),
                        "exchange_rate": r.get("Exchange rate"), 
                        "buying_price_vnd": r.get("Buying price (VND)"),
                        "total_buying_price_vnd": r.get("Total buying price (VND)"), 
                        "leadtime": str(r.get("Leadtime","")),
                        "supplier": str(r.get("Supplier","")), 
                        "images": str(r.get("Images","")),
                        "type": str(r.get("Type","")), 
                        "nuoc": str(r.get("N/U/O/C",""))
                    })
                
                batch = 500
                valid = [x for x in recs if x['specs']]
                for i in range(0, len(valid), batch):
                    be.supabase.table("crm_purchases").upsert(valid[i:i+batch], on_conflict="specs").execute()
                st.success(f"✅ Đã cập nhật {len(valid)} dòng chuẩn Excel!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    # --- HIỂN THỊ ---
    search = st.text_input("🔍 Tìm kiếm...", placeholder="Nhập mã hàng...")
    res = be.supabase.table("crm_purchases").select("*").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        # Sắp xếp theo cột No (chuyển sang số)
        if 'no' in df.columns:
            df['no_numeric'] = pd.to_numeric(df['no'], errors='coerce')
            df = df.sort_values('no_numeric').reset_index(drop=True)
        
        # Tìm kiếm
        if search: 
            mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)
            df = df[mask].reset_index(drop=True)
        
        # Đổi tên cột & Lọc đúng cột Excel
        view_df = df.rename(columns=DB_TO_EXCEL_MAP)
        final_cols = [c for c in EXCEL_COLUMNS_ORDER if c in view_df.columns]
        view_df = view_df[final_cols]
        
        c1, c2 = st.columns([7, 3])
        with c1:
            event = st.dataframe(view_df, use_container_width=True, height=600, selection_mode="single-row", on_select="rerun", hide_index=True)
        
        with c2:
            st.markdown("### 🖼️ ẢNH SẢN PHẨM")
            if event.selection.rows:
                idx = event.selection.rows[0]
                # Truy ngược về df gốc để lấy link ảnh & id
                row = df.iloc[idx]
                st.info(f"Mã: **{row.get('specs', 'N/A')}**")
                
                img_url = row.get('images')
                if img_url and str(img_url).startswith("http"):
                    st.image(img_url, width=300)
                else:
                    st.markdown('<div class="img-box">🚫 Không có ảnh</div>', unsafe_allow_html=True)
                
                new_img = st.file_uploader("Cập nhật ảnh", type=['jpg','png'])
                if new_img and st.button("Lưu ảnh"):
                    fname = f"{re.sub(r'[^a-zA-Z0-9]', '', str(row.get('specs','')))}_{int(time.time())}.jpg"
                    link = be.upload_img(new_img, fname)
                    if link:
                        be.supabase.table("crm_purchases").update({"images": link}).eq("id", row['id']).execute()
                        st.success("Đã lưu!"); time.sleep(1); st.rerun()
            else:
                st.info("👈 Chọn dòng để xem ảnh")
    else: st.info("Chưa có dữ liệu.")

# --- BÁO GIÁ ---
elif menu == "💰 BÁO GIÁ":
    st.markdown("## 💰 BÁO GIÁ")
    t1, t2 = st.tabs(["TẠO MỚI", "TRA CỨU"])
    with t1:
        c1, c2 = st.columns([1, 2])
        cust = c1.text_input("Khách Hàng")
        rfq = c2.file_uploader("Upload RFQ", type=['xlsx','csv'])
        if rfq and cust:
            if st.session_state['quote_data'] is None:
                df = pd.read_csv(rfq) if rfq.name.endswith('.csv') else pd.read_excel(rfq)
                df.columns = [str(c).strip() for c in df.columns]
                db = be.supabase.table("crm_purchases").select("specs, buying_price_rmb, exchange_rate").execute()
                df_db = pd.DataFrame(db.data)
                
                if 'Specs' in df.columns and not df_db.empty:
                    df['Specs'] = df['Specs'].astype(str).str.strip()
                    df_db['specs'] = df_db['specs'].astype(str).str.strip()
                    m = pd.merge(df, df_db, left_on='Specs', right_on='specs', how='left')
                    m.rename(columns={'buying_price_rmb': 'Buying Price (RMB)', 'exchange_rate': 'Exchange Rate'}, inplace=True)
                    m.fillna(0, inplace=True)
                    st.session_state['quote_data'] = m
                else: st.session_state['quote_data'] = df
            
            edited = st.data_editor(st.session_state['quote_data'], num_rows="dynamic", use_container_width=True)
            if st.button("🚀 TÍNH TOÁN"):
                res = edited.apply(be.calc_profit, axis=1)
                st.session_state['quote_data'] = pd.concat([edited, res], axis=1)
                st.success("Xong!")
            
            if st.session_state['quote_data'] is not None and 'PROFIT (VND)' in st.session_state['quote_data'].columns:
                fin = st.session_state['quote_data']
                st.dataframe(fin.style.format("{:,.0f}", subset=['PROFIT (VND)']).background_gradient(subset=['PROFIT (VND)'], cmap='RdYlGn'), use_container_width=True)
                docx = be.create_docx(fin, cust)
                st.download_button("📄 Tải Specs", docx, "Specs.docx")
                if st.button("Lưu"):
                    be.supabase.table("crm_shared_history").insert({"quote_id": f"Q-{int(time.time())}", "customer_name": cust, "total_profit_vnd": fin['PROFIT (VND)'].sum()}).execute()
                    st.success("Đã lưu!")

    with t2:
        if st.button("Xem lịch sử"):
            h = be.supabase.table("crm_shared_history").select("*").execute().data
            st.dataframe(pd.DataFrame(h))

# --- PO ---
elif menu == "📑 QUẢN LÝ PO":
    st.markdown("## 📑 QUẢN LÝ PO")
    t1, t2 = st.tabs(["PO KHÁCH", "PO NCC"])
    with t1:
        f = st.file_uploader("PO Khách")
        n = st.text_input("Tên KH")
        v = st.number_input("Giá trị", step=1000.0)
        if f and n and st.button("Lưu"):
            l, p = be.upload_recursive(f, f.name, "PO_KHACH_HANG", datetime.now().year, n, datetime.now().strftime("%b"))
            if l: be.supabase.table("db_customer_orders").insert({"po_number": f"POC-{int(time.time())}", "customer_name": n, "total_value": v, "po_file_url": l, "drive_folder_url": p}).execute(); st.success("OK")
    with t2:
        f = st.file_uploader("Excel Tổng", type=['xlsx'])
        if f and st.button("Tách"):
            d = pd.read_excel(f)
            s = next((c for c in d.columns if 'supplier' in c.lower()), None)
            if s:
                for n, g in d.groupby(s):
                    with st.expander(f"NCC: {n}"):
                        st.dataframe(g)
                        if st.button(f"Lưu {n}"):
                            b = io.BytesIO(); g.to_excel(b, index=False); b.seek(0)
                            l, p = be.upload_recursive(b, f"PO_{n}.xlsx", "PO_NCC", datetime.now().year, n, datetime.now().strftime("%b"))
                            if l: st.success(f"Đã lưu {n}")

# --- TRACKING ---
elif menu == "🚚 TRACKING":
    st.markdown("## 🚚 TRACKING")
    df = pd.DataFrame(be.supabase.table("db_customer_orders").select("*").execute().data)
    if not df.empty:
        st.dataframe(df[['po_number', 'customer_name', 'status']])
        c1, c2, c3 = st.columns(3)
        sel = c1.selectbox("PO", df['po_number'])
        stt = c2.selectbox("Status", ["Shipping", "Arrived", "Delivered"])
        img = c3.file_uploader("Proof")
        if st.button("Update"):
            be.supabase.table("db_customer_orders").update({"status": stt}).eq("po_number", sel).execute()
            if img: be.upload_recursive(img, f"Proof_{sel}.jpg", "TRACKING_PROOF", 2025, "PROOF", "ALL")
            if stt == "Delivered": be.supabase.table("crm_payments").insert({"po_number": sel, "status": "Pending", "eta_payment": str(datetime.now().date())}).execute()
            st.success("Updated!")

# --- MASTER ---
elif menu == "⚙️ MASTER DATA":
    st.info("Dùng Tab KHO HÀNG để import giá.")
