# TAB 2: DB GIÁ NCC
with tab2:
    st.subheader("Database Giá NCC")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                status_box.write("🖼️ Quét ảnh...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=False); ws = wb.active
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        image_map[img.anchor._from.row + 1] = img._data()
                
                status_box.write("📖 Đọc dữ liệu...")
                uploaded_file.seek(0)
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                data_clean = []
                prog_bar = status_box.progress(0); total = len(df_raw)
                
                for i, row in df_raw.iterrows():
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    excel_row_idx = i + 2
                    def get(c): return safe_str(row.get(c, ""))
                    code = safe_str(row.iloc[1])
                    if not code: continue

                    final_link = ""
                    if excel_row_idx in image_map:
                        status_box.write(f"☁️ Up ảnh: {code}...")
                        link = backend.upload_to_drive(io.BytesIO(image_map[excel_row_idx]), f"{safe_filename(code)}.png", "images")
                        if link: final_link = link
                    else:
                        old = safe_str(row.iloc[12]) if len(row) > 12 else ""
                        if "http" in old: final_link = old

                    item = {
                        "no": safe_str(row.iloc[0]), "item_code": code, "item_name": safe_str(row.iloc[2]), 
                        "specs": safe_str(row.iloc[3]), "qty": fmt_num(to_float(row.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(row.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(row.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(row.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(row.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(row.iloc[9])), 
                        "leadtime": safe_str(row.iloc[10]), "supplier_name": safe_str(row.iloc[11]), 
                        "image_path": final_link,
                        "_clean_code": clean_lookup_key(code), "_clean_specs": clean_lookup_key(safe_str(row.iloc[3])), "_clean_name": clean_lookup_key(safe_str(row.iloc[2]))
                    }
                    data_clean.append(item)
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label="✅ Hoàn tất!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    # CHIA CỘT: 80% BẢNG - 20% ẢNH
    col_table, col_gallery = st.columns([7, 3])
    df_pur = backend.load_data("purchases")
    
    with col_table:
        search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        cfg = {
            "image_path": st.column_config.LinkColumn("Link Ảnh"), # Chỉ hiện link text, ko hiện ảnh nhỏ để tránh lỗi
            "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Mua", format="%d"),
            "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
        }
        order = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name"]
        
        edited_pur = st.data_editor(
            df_pur, column_config=cfg, column_order=order, 
            use_container_width=True, height=600, key="ed_pur", num_rows="dynamic"
        )
        if st.button("💾 Lưu thay đổi"): backend.save_data("purchases", edited_pur)

    # KHUNG XEM ẢNH TRỰC TIẾP (DÙNG SELECTBOX CHO CHẮC ĂN)
    with col_gallery:
        st.info("📷 KHUNG XEM ẢNH")
        if not df_pur.empty:
            # Tạo list mã hàng để chọn
            item_list = df_pur["item_code"].unique().tolist()
            selected_code = st.selectbox("👉 Chọn mã hàng để xem ảnh:", item_list)
            
            if selected_code:
                row = df_pur[df_pur["item_code"] == selected_code].iloc[0]
                img_link = row.get("image_path", "")
                
                st.markdown(f"**{row['item_name']}**")
                
                if img_link and "http" in str(img_link):
                    with st.spinner("Đang tải ảnh từ Drive..."):
                        # GỌI HÀM BACKEND ĐỂ TẢI DỮ LIỆU ẢNH THẬT
                        img_bytes = backend.get_image_bytes(img_link)
                        if img_bytes:
                            st.image(img_bytes, caption=f"Mã: {selected_code}", use_container_width=True)
                        else:
                            st.error("Không tải được ảnh (File có thể bị xóa hoặc lỗi quyền).")
                else:
                    st.warning("Sản phẩm này chưa có link ảnh.")
                
                st.write("---")
                st.write(f"**Thông số:** {row['specs']}")
                st.write(f"**Giá:** {row['buying_price_vnd']}")
                st.write(f"**NCC:** {row['supplier_name']}")
