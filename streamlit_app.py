import streamlit as st
import pandas as pd
import io
import time
import re
from datetime import datetime
from openpyxl import load_workbook
from PIL import Image as PilImage

# --- KHỐI IMPORT THƯ VIỆN BACKEND (SUPABASE & DRIVE) ---
try:
    from supabase import create_client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
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
    /* Giảm kích thước padding của block ảnh */
    div[data-testid="stImage"] { margin-top: -20px; }
</style>
""", unsafe_allow_html=True)

def safe_str(val): return str(val).strip() if val is not None and str(val) != 'nan' else ""
def safe_filename(s): return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))
def to_float(val):
    try: return float(str(val).replace(",", "").replace("%", "").strip())
    except: return 0.0
def fmt_num(x):
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
            # Trả về link thumbnail để hiển thị nhanh
            return f"https://drive.google.com/thumbnail?id={file.get('id')}&sz=w1000"
        except Exception as e: 
            print(f"Upload Error: {e}")
            return None

    def load_data(self, table):
        try:
            res = self.supabase.table(f"crm_{table}").select("*").execute()
            return pd.DataFrame(res.data)
        except: return pd.DataFrame()

    def save_data(self, table, df):
        # Hàm save data cho edit trực tiếp (logic cũ)
        pass 

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
    # (Có thể thêm các card thống kê ở đây nếu cần)

# TAB 2: DATABASE GIÁ NCC (UPDATED LOGIC)
with tab2:
    st.subheader("Database Giá NCC (Hybrid Engine)")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        # LOGIC IMPORT MỚI: QUÉT ẢNH EMBEDDED + GHI ĐÈ
        uploaded_file = st.file_uploader("📥 Import Excel (Tự động tách ảnh & Upload)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý dữ liệu...", expanded=True)
            try:
                # 1. QUÉT ẢNH TỪ EXCEL (OPENPYXL)
                status_box.write("🖼️ Đang quét ảnh nhúng trong Excel...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=True)
                ws = wb.active
                
                image_map = {} # Mapping: Row Index -> Drive Link
                
                # Quét tất cả ảnh trong sheet
                if hasattr(ws, '_images'):
                    for image in ws._images:
                        try:
                            # Lấy tọa độ hàng (0-indexed)
                            row = image.anchor._from.row
                            col = image.anchor._from.col
                            
                            # Chỉ lấy ảnh ở cột M (Cột 12 - 0-indexed)
                            if col == 12: 
                                img_bytes = io.BytesIO()
                                try:
                                    pil_img = PilImage.open(image.ref).convert('RGB')
                                    pil_img.save(img_bytes, format='JPEG')
                                except:
                                    img_bytes.write(image._data())
                                
                                img_bytes.seek(0)
                                # Tạo tên file unique
                                fname = f"IMG_ROW_{row+1}_{int(time.time())}.jpg"
                                
                                # Upload lên Drive ngay lập tức
                                link = be.upload_img(img_bytes, fname)
                                if link:
                                    image_map[row] = link # Lưu link vào map theo row index
                        except Exception as e:
                            print(f"Lỗi ảnh tại row {row}: {e}")

                status_box.write(f"✅ Đã tách và upload {len(image_map)} ảnh thành công!")

                # 2. ĐỌC DỮ LIỆU TEXT (PANDAS)
                status_box.write("📖 Đang đọc dữ liệu văn bản...")
                uploaded_file.seek(0)
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                # Chuẩn hóa tên cột để tránh lỗi
                df_raw.columns = [str(c).strip() for c in df_raw.columns]

                data_clean = []
                prog_bar = status_box.progress(0)
                total = len(df_raw)

                for i, (idx, row) in enumerate(df_raw.iterrows()):
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    
                    # Logic Mapping cột Excel -> Database
                    # Giả định cột theo thứ tự file mẫu của bạn
                    code = safe_str(row.get('Item code') or row.iloc[1]) # Cột B
                    specs = safe_str(row.get('Specs') or row.iloc[3])    # Cột D
                    
                    if not specs: continue # Bắt buộc phải có specs để làm khóa chính

                    # Xử lý Link ảnh: Ưu tiên ảnh vừa tách -> Link trong Excel -> Rỗng
                    final_link = ""
                    # Pandas index idx tương ứng với Openpyxl row idx + 1 (header)
                    if (idx + 1) in image_map:
                        final_link = image_map[idx + 1]
                    else:
                        old_link = safe_str(row.get('Images') or row.iloc[12])
                        if "http" in old_link: final_link = old_link

                    item = {
                        "no": safe_str(row.iloc[0]), 
                        "item_code": code, 
                        "item_name": safe_str(row.iloc[2]), 
                        "specs": specs, 
                        "qty": fmt_num(to_float(row.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(row.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(row.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(row.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(row.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(row.iloc[9])), 
                        "leadtime": safe_str(row.iloc[10]), 
                        "supplier": safe_str(row.iloc[11]), # Lưu ý tên cột trong DB là 'supplier'
                        "images": final_link, # Tên cột trong DB là 'images'
                        "type": safe_str(row.iloc[13]) if len(row) > 13 else "",
                        "nuoc": safe_str(row.iloc[14]) if len(row) > 14 else ""
                    }
                    data_clean.append(item)
                
                # 3. UPSERT VÀO SUPABASE (GHI ĐÈ DỰA TRÊN 'SPECS')
                if data_clean:
                    status_box.write("💾 Đang lưu vào Database...")
                    # Chia nhỏ batch để gửi tránh lỗi request quá lớn
                    batch_size = 100
                    for k in range(0, len(data_clean), batch_size):
                        batch = data_clean[k:k+batch_size]
                        be.supabase.table("crm_purchases").upsert(batch, on_conflict="specs").execute()
                    
                    status_box.update(label="✅ Hoàn tất Import!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
                    
            except Exception as e: 
                status_box.update(label="❌ Có lỗi xảy ra", state="error")
                st.error(f"Chi tiết lỗi: {e}")

    # --- GIAO DIỆN HIỂN THỊ (ĐÃ TỐI ƯU KÍCH THƯỚC ẢNH) ---
    # Thay đổi tỷ lệ cột: 8.5 phần Bảng - 1.5 phần Ảnh (Giảm kích thước cột ảnh)
    col_table, col_gallery = st.columns([8.5, 1.5])
    
    # Load data từ DB (bảng crm_purchases)
    df_pur = be.load_data("purchases")
    
    # Xử lý hiển thị bảng
    with col_table:
        search = st.text_input("🔍 Tìm kiếm (Mã/Tên/Thông số)...", key="search_pur")
        
        # Sắp xếp theo cột No (chuyển về số để sort đúng)
        if not df_pur.empty and 'no' in df_pur.columns:
            df_pur['no_num'] = pd.to_numeric(df_pur['no'], errors='coerce')
            df_pur = df_pur.sort_values('no_num')

        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        # Config cột cho đẹp
        cfg = {
            "images": st.column_config.LinkColumn("Link Ảnh"),
            "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Tiền", format="%d"),
            "id": None, "created_at": None, "no_num": None # Ẩn cột kỹ thuật
        }
        # Thứ tự cột hiển thị
        order = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "exchange_rate", "buying_price_vnd", "leadtime", "supplier"]
        
        # Bảng dữ liệu chính
        event = st.dataframe(
            df_pur, column_config=cfg, column_order=order, 
            use_container_width=True, height=600, 
            selection_mode="single-row", on_select="rerun", hide_index=True
        )

    # --- KHUNG XEM ẢNH MINI (GIẢM 70% KÍCH THƯỚC) ---
    with col_gallery:
        st.caption("📷 PREVIEW") # Dùng caption cho nhỏ
        
        selected_row = None
        if event.selection.rows:
            idx = event.selection.rows[0]
            selected_row = df_pur.iloc[idx]
        
        if selected_row is not None:
            img_link = selected_row.get("images", "")
            item_code = selected_row.get("item_code", "N/A")
            
            # Hiển thị ảnh với width nhỏ (130px) -> Giảm khoảng 70% so với full width cũ
            if img_link and "http" in str(img_link):
                st.image(img_link, caption=item_code, width=130) 
            else:
                st.info("No Img")
                
            st.markdown("---")
            # Hiển thị thông tin tóm tắt dạng nhỏ
            st.markdown(f"<div style='font-size:12px'><b>Specs:</b> {selected_row.get('specs','')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:12px; color:blue'><b>Giá:</b> {fmt_num(selected_row.get('buying_price_vnd',0))}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='font-size:11px; color:grey'>Chọn 1 dòng để xem</div>", unsafe_allow_html=True)

# TAB 3: BÁO GIÁ KH
with tab3:
    st.info("Chức năng Báo giá KH (Giữ nguyên logic cũ hoặc phát triển thêm)")

# TAB 4: ĐƠN HÀNG
with tab4:
    st.info("Chức năng Đơn hàng (Giữ nguyên logic cũ)")

# TAB 5: TRACKING
with tab5:
    st.info("Chức năng Tracking (Giữ nguyên logic cũ)")

# TAB 6: MASTER DATA
with tab6:
    st.info("Master Data")
