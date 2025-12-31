import streamlit as st
import pandas as pd
import io
import time
import re
from openpyxl import load_workbook
from PIL import Image as PilImage

# --- KHỐI IMPORT THƯ VIỆN BACKEND (SUPABASE & DRIVE) ---
try:
    from supabase import create_client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
except ImportError:
    st.error("⚠️ Thiếu thư viện! Chạy lệnh: pip install supabase google-api-python-client google-auth-httplib2 google-auth-oauthlib openpyxl pillow pandas streamlit")
    st.stop()

# =============================================================================
# 1. SETUP UI & HELPER FUNCTIONS
# =============================================================================
st.set_page_config(page_title="SGS CRM V4810 - HYBRID", layout="wide", page_icon="🪶")
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; } 
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f6; border-radius: 4px 4px 0 0; padding: 8px 16px; font-weight: 600; font-size: 14px; } 
    .stTabs [aria-selected="true"] { background-color: #2980b9; color: white; }
    /* Tinh chỉnh hiển thị ảnh */
    div[data-testid="stImage"] { margin-top: -10px; }
    div[data-testid="stImage"] img { border-radius: 5px; border: 1px solid #ddd; }
</style>
""", unsafe_allow_html=True)

def safe_str(val): return str(val).strip() if val is not None and str(val) != 'nan' else ""
def safe_filename(s): return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))

def to_float(val):
    """Chuyển đổi chuỗi có dấu phẩy thành số thực (Float) để lưu DB"""
    try: 
        clean_val = str(val).replace(",", "").replace("%", "").strip()
        return float(clean_val) if clean_val else 0.0
    except: 
        return 0.0

def fmt_num(x):
    """Format số thành chuỗi có dấu phẩy (Chỉ dùng để hiển thị UI)"""
    try: return "{:,.0f}".format(float(x))
    except: return "0"

if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()

# =============================================================================
# 2. BACKEND CLASS (Tích hợp Logic xử lý Drive & Supabase)
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

    def upload_img(self, file_obj, filename, mime_type='image/jpeg'):
        if not self.drive: return None
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            l1 = self.get_folder_id("PRODUCT_IMAGES", root_id)
            media = MediaIoBaseUpload(file_obj, mimetype=mime_type, resumable=True)
            meta = {'name': filename, 'parents': [l1]} 
            file = self.drive.files().create(body=meta, media_body=media, fields='id').execute()
            # Trả về link thumbnail
            return f"https://drive.google.com/thumbnail?id={file.get('id')}&sz=w1000"
        except Exception as e: 
            print(f"Upload Error: {e}")
            return None

    # --- HÀM TẢI ẢNH TRỰC TIẾP TỪ DRIVE (BYPASS LINK ERROR) ---
    def get_image_bytes(self, url):
        """Tải dữ liệu binary của ảnh từ Google Drive thông qua API"""
        if not self.drive or not url or "http" not in str(url): return None
        try:
            file_id = None
            # Trích xuất ID từ các dạng link Drive phổ biến
            if "id=" in url:
                file_id = url.split("id=")[1].split("&")[0]
            elif "/d/" in url:
                file_id = url.split("/d/")[1].split("/")[0]
            elif "open?id=" in url:
                file_id = url.split("open?id=")[1].split("&")[0]
            
            if file_id:
                request = self.drive.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                return fh.getvalue() # Trả về bytes
        except Exception:
            return None

    def load_data(self, table):
        try:
            res = self.supabase.table(f"crm_{table}").select("*").execute()
            return pd.DataFrame(res.data)
        except: return pd.DataFrame()

be = CRMBackend()

# =============================================================================
# 3. MAIN APPLICATION
# =============================================================================
st.title("SGS CRM V4810 - FINAL HYBRID")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Tổng quan", "💰 Báo giá NCC (DB Giá)", "📝 Báo giá KH", "📦 Đơn đặt hàng", "🚚 Theo dõi & Thanh toán", "⚙️ Master Data"])

# TAB 1: DASHBOARD
with tab1:
    st.subheader("DASHBOARD")
    if st.button("🔄 CẬP NHẬT DATA", type="primary"): st.rerun()

# TAB 2: DATABASE GIÁ NCC
with tab2:
    st.subheader("Database Giá NCC (Hybrid Engine)")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Tự động tách ảnh & Upload)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý dữ liệu...", expanded=True)
            try:
                # 1. QUÉT ẢNH TỪ EXCEL (OPENPYXL)
                status_box.write("🖼️ Đang quét ảnh nhúng trong Excel...")
                uploaded_file.seek(0)
                
                # [QUAN TRỌNG] data_only=False để lấy được đối tượng ảnh
                wb = load_workbook(uploaded_file, data_only=False) 
                ws = wb.active
                
                image_map = {} 
                if hasattr(ws, '_images'):
                    for image in ws._images:
                        try:
                            # Lấy vị trí hàng và cột
                            row = image.anchor._from.row
                            col = image.anchor._from.col
                            
                            # [QUAN TRỌNG] Mở rộng điều kiện: Lấy ảnh từ cột 10 trở đi (Column K -> Z)
                            # Để tránh trường hợp file excel bị lệch cột
                            if col >= 10: 
                                img_bytes = io.BytesIO()
                                try:
                                    pil_img = PilImage.open(image.ref).convert('RGB')
                                    pil_img.save(img_bytes, format='JPEG')
                                except:
                                    img_bytes.write(image._data())
                                img_bytes.seek(0)
                                
                                fname = f"IMG_ROW_{row+1}_{int(time.time())}.jpg"
                                link = be.upload_img(img_bytes, fname)
                                
                                if link: 
                                    # Ưu tiên ảnh nằm ở cột 12 (M), nếu không có thì lấy ảnh cột khác cùng dòng
                                    if row not in image_map or col == 12:
                                        image_map[row] = link 
                        except Exception: pass

                status_box.write(f"✅ Đã tìm thấy và xử lý {len(image_map)} ảnh.")

                # 2. ĐỌC DỮ LIỆU TEXT (PANDAS)
                status_box.write("📖 Đang đọc dữ liệu văn bản...")
                uploaded_file.seek(0)
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                df_raw.columns = [str(c).strip() for c in df_raw.columns]

                # --- FIX LỖI 21000: LOẠI BỎ DUPLICATE 'SPECS' ---
                if 'Specs' in df_raw.columns:
                    df_raw['Specs'] = df_raw['Specs'].astype(str).str.strip()
                    rows_before = len(df_raw)
                    df_raw = df_raw.drop_duplicates(subset=['Specs'], keep='last')
                    rows_dropped = rows_before - len(df_raw)
                    if rows_dropped > 0:
                        status_box.write(f"⚠️ Đã tự động loại bỏ {rows_dropped} dòng trùng lặp mã 'Specs'.")

                data_clean = []
                prog_bar = status_box.progress(0)
                total = len(df_raw)

                for i, (idx, row) in enumerate(df_raw.iterrows()):
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    
                    code = safe_str(row.get('Item code') or row.iloc[1]) 
                    specs = safe_str(row.get('Specs') or row.iloc[3])    
                    
                    if not specs: continue 

                    final_link = ""
                    # Pandas index = Openpyxl row - 1. => Openpyxl row = Pandas index + 1
                    # Lưu ý: Openpyxl row 0-indexed trong anchor._from.row
                    if idx in image_map:  
                        final_link = image_map[idx]
                    elif (idx + 1) in image_map: # Fallback check
                        final_link = image_map[idx + 1]
                    else:
                        old_link = safe_str(row.get('Images') or row.iloc[12])
                        if "http" in old_link: final_link = old_link

                    item = {
                        "no": safe_str(row.iloc[0]), 
                        "item_code": code, 
                        "item_name": safe_str(row.iloc[2]), 
                        "specs": specs, 
                        "qty": to_float(row.iloc[4]), 
                        "buying_price_rmb": to_float(row.iloc[5]), 
                        "total_buying_price_rmb": to_float(row.iloc[6]), 
                        "exchange_rate": to_float(row.iloc[7]), 
                        "buying_price_vnd": to_float(row.iloc[8]), 
                        "total_buying_price_vnd": to_float(row.iloc[9]), 
                        "leadtime": safe_str(row.iloc[10]), 
                        "supplier": safe_str(row.iloc[11]), 
                        "images": final_link, 
                        "type": safe_str(row.iloc[13]) if len(row) > 13 else "",
                        "nuoc": safe_str(row.iloc[14]) if len(row) > 14 else ""
                    }
                    data_clean.append(item)
                
                # 3. UPSERT
                if data_clean:
                    status_box.write("💾 Đang lưu vào Database...")
                    batch_size = 100
                    for k in range(0, len(data_clean), batch_size):
                        batch = data_clean[k:k+batch_size]
                        be.supabase.table("crm_purchases").upsert(batch, on_conflict="specs").execute()
                    
                    status_box.update(label="✅ Hoàn tất Import!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
                    
            except Exception as e: 
                status_box.update(label="❌ Có lỗi xảy ra", state="error")
                st.error(f"Chi tiết lỗi: {e}")

    # --- GIAO DIỆN HIỂN THỊ (CỘT ẢNH NHỎ 9:1) ---
    col_table, col_gallery = st.columns([9, 1])
    df_pur = be.load_data("purchases")
    
    with col_table:
        search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
        
        if not df_pur.empty and 'no' in df_pur.columns:
            df_pur['no_num'] = pd.to_numeric(df_pur['no'], errors='coerce')
            df_pur = df_pur.sort_values('no_num')

        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        cfg = {
            "images": st.column_config.LinkColumn("Link Ảnh"),
            "buying_price_vnd": st.column_config.NumberColumn("Giá VND", format="%d"),
            "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Tiền", format="%d"),
            "exchange_rate": st.column_config.NumberColumn("Tỷ giá", format="%d"),
            "id": None, "created_at": None, "no_num": None
        }
        order = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "exchange_rate", "buying_price_vnd", "leadtime", "supplier"]
        
        event = st.dataframe(
            df_pur, column_config=cfg, column_order=order, 
            use_container_width=True, height=600, 
            selection_mode="single-row", on_select="rerun", hide_index=True
        )

    # --- KHUNG XEM ẢNH MINI (THU NHỎ 70%) ---
    with col_gallery:
        st.caption("📷 VIEW")
        selected_row = None
        if event.selection.rows:
            idx = event.selection.rows[0]
            selected_row = df_pur.iloc[idx]
        
        if selected_row is not None:
            img_link = selected_row.get("images", "")
            item_code = selected_row.get("item_code", "N/A")
            
            # --- LOGIC HIỂN THỊ ẢNH MƯỢT MÀ BẰNG BYTES ---
            if img_link and "http" in str(img_link):
                # Hiển thị spinner nhỏ trong lúc tải
                with st.spinner("."):
                    img_bytes = be.get_image_bytes(img_link)
                    if img_bytes:
                        # Width=100px để đảm bảo nhỏ gọn (giảm ~70% so với khổ 300px)
                        st.image(img_bytes, caption=item_code, width=100) 
                    else:
                        st.image("https://placehold.co/100x100?text=Error", width=100, caption="Lỗi tải")
            else:
                st.info("No Img")
                
            st.markdown("---")
            # Thông tin rút gọn
            st.markdown(f"<div style='font-size:10px'><b>{selected_row.get('specs','')}</b></div>", unsafe_allow_html=True)
            price_display = fmt_num(selected_row.get('buying_price_vnd', 0))
            st.markdown(f"<div style='font-size:11px; color:blue; font-weight:bold'>{price_display}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='font-size:10px; color:grey'>Chọn dòng</div>", unsafe_allow_html=True)

# TAB 3: BÁO GIÁ KH
with tab3:
    st.info("Chức năng Báo giá KH")

# TAB 4: ĐƠN HÀNG
with tab4:
    st.info("Chức năng Đơn hàng")

# TAB 5: TRACKING
with tab5:
    st.info("Chức năng Tracking")

# TAB 6: MASTER DATA
with tab6:
    st.info("Master Data")
