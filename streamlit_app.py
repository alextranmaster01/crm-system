# -*- coding: utf-8 -*-
from __future__ import annotations
import io, re, ast, json, hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from PIL import Image
from supabase import create_client, Client as SupabaseClient
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

APP_TITLE = "SGS CRM - ONLINE (Supabase + Google Drive)"

MASTER_COLUMNS=["no","short_name","eng_name","vn_name","address_1","address_2","contact_person","director","phone","fax","tax_code","destination","payment_term"]
PURCHASE_COLUMNS=["no","item_code","item_name","specs","qty","buying_price_rmb","total_buying_price_rmb","exchange_rate","buying_price_vnd","total_buying_price_vnd","leadtime","supplier_name","image_path"]
SUPPLIER_ORDER_COLS=["no","item_code","item_name","specs","qty","price_rmb","total_rmb","exchange_rate","price_vnd","total_vnd","eta","supplier","po_number","order_date","pdf_path"]
CUSTOMER_ORDER_COLS=["no","item_code","item_name","specs","qty","unit_price","total_price","eta","customer","po_number","order_date","pdf_path","base_buying_vnd","full_cost_total"]
QUOTE_KH_COLUMNS=["no","item_code","item_name","specs","qty","buying_price_rmb","total_buying_price_rmb","exchange_rate","buying_price_vnd","total_buying_price_vnd","ap_price","ap_total_vnd","unit_price","total_price_vnd","gap","end_user_val","buyer_val","import_tax_val","vat_val","transportation","mgmt_fee","payback_val","profit_vnd","profit_pct","supplier_name","image_path","leadtime"]
TRACKING_COLS=["no","po_no","partner","status","eta","proof_image","order_type","last_update","finished"]
PAYMENT_COLS=["no","po_no","customer","invoice_no","status","due_date","paid_date"]
HISTORY_COLS=["date","quote_no","customer","item_code","item_name","specs","qty","total_revenue","total_cost","profit","supplier","status","delivery_date","po_number"]

TBL_CUSTOMERS="crm_customers"
TBL_SUPPLIERS="crm_suppliers"
TBL_PURCHASES="crm_purchases"
TBL_SALES_HISTORY="crm_sales_history"
TBL_TRACKING="crm_order_tracking"
TBL_PAYMENT="crm_payment_tracking"
TBL_PAID_HISTORY="crm_paid_history"
TBL_SUPPLIER_ORDERS="db_supplier_orders"
TBL_CUSTOMER_ORDERS="db_customer_orders"

DEFAULT_DRIVE_FOLDER="SGS_CRM_DATA"

def safe_str(v:Any)->str:
    if v is None: return ""
    s=str(v).strip()
    if s.startswith("['") and s.endswith("']"):
        try:
            a=ast.literal_eval(s)
            if isinstance(a,list) and a: return str(a[0])
        except Exception: pass
    if s.startswith("'") and s.endswith("'"): s=s[1:-1]
    return "" if s.lower()=="nan" else s

def safe_filename(s:Any)->str:
    return re.sub(r"[\\/:*?\"<>|]+","_", safe_str(s))

def to_float(v:Any)->float:
    try:
        if isinstance(v,(int,float)): return float(v)
        c=str(v).replace(",","").replace("%","").strip()
        return 0.0 if c=="" else float(c)
    except Exception:
        return 0.0

def fmt_num(x:Any)->str:
    try: return "{:,.0f}".format(float(x))
    except Exception: return "0"

def clean_key(s:Any)->str:
    if s is None: return ""
    ss=str(s)
    try:
        f=float(ss)
        if f.is_integer(): ss=str(int(f))
    except Exception: pass
    return re.sub(r"\s+","",ss).lower()

def sha1_bytes(b:bytes)->str:
    return hashlib.sha1(b).hexdigest()

def parse_formula(formula:str, buy:float, ap:float)->float:
    s=str(formula).strip().upper().replace(",","")
    try: return float(s)
    except Exception: pass
    if not s.startswith("="): return 0.0
    expr=s[1:].replace("BUYING PRICE",str(buy)).replace("BUY",str(buy)).replace("AP PRICE",str(ap)).replace("AP",str(ap))
    if any(c not in "0123456789.+-*/()" for c in expr): return 0.0
    try: return float(eval(expr))
    except Exception: return 0.0

@dataclass
class AppConfig:
    supabase_url:str
    supabase_key:str
    google_client_id:str
    google_client_secret:str
    google_refresh_token:str
    drive_root_folder:str=DEFAULT_DRIVE_FOLDER
    admin_password:str="admin"

def _get_secret(path:List[str])->str:
    cur:Any=st.secrets
    for k in path:
        if isinstance(cur,dict) and k in cur: cur=cur[k]
        else: return ""
    return str(cur)

def load_config()->Tuple[Optional[AppConfig], List[str]]:
    miss=[]
    sup_url=_get_secret(["supabase","url"]).strip().rstrip("/")
    sup_key=_get_secret(["supabase","key"]).strip()
    gid=_get_secret(["google","client_id"]).strip()
    gsec=_get_secret(["google","client_secret"]).strip()
    grt=_get_secret(["google","refresh_token"]).strip()
    drive_root=(_get_secret(["app","drive_root_folder"]) or DEFAULT_DRIVE_FOLDER).strip()
    admin_pwd=(_get_secret(["app","admin_password"]) or "admin").strip()
    if not sup_url: miss.append("supabase.url")
    if not sup_key: miss.append("supabase.key")
    if not gid: miss.append("google.client_id")
    if not gsec: miss.append("google.client_secret")
    if not grt: miss.append("google.refresh_token")
    if miss: return None, miss
    return AppConfig(sup_url,sup_key,gid,gsec,grt,drive_root,admin_pwd), []

@st.cache_resource
def get_supabase(cfg:AppConfig)->SupabaseClient:
    return create_client(cfg.supabase_url, cfg.supabase_key)

@st.cache_resource
def get_drive(cfg:AppConfig):
    creds=Credentials(token=None, refresh_token=cfg.google_refresh_token, token_uri="https://oauth2.googleapis.com/token",
                      client_id=cfg.google_client_id, client_secret=cfg.google_client_secret,
                      scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive","v3",credentials=creds, cache_discovery=False)

def drive_find_folder(svc, name:str, parent_id:Optional[str]=None)->Optional[str]:
    q=f"mimeType='application/vnd.google-apps.folder' and name='{name.replace(\"'\",\"\\\\'\")}' and trashed=false"
    if parent_id: q+=f" and '{parent_id}' in parents"
    res=svc.files().list(q=q,fields="files(id,name)").execute()
    files=res.get("files",[])
    return files[0]["id"] if files else None

def drive_ensure_folder(svc, name:str, parent_id:Optional[str]=None)->str:
    fid=drive_find_folder(svc,name,parent_id)
    if fid: return fid
    meta={"name":name,"mimeType":"application/vnd.google-apps.folder"}
    if parent_id: meta["parents"]=[parent_id]
    f=svc.files().create(body=meta,fields="id").execute()
    return f["id"]

def drive_upload_bytes(svc, folder_id:str, filename:str, content:bytes, mimetype:str)->Dict[str,str]:
    media=MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=True)
    body={"name":filename,"parents":[folder_id]}
    f=svc.files().create(body=body, media_body=media, fields="id,webViewLink").execute()
    return {"file_id":f["id"],"webViewLink":f.get("webViewLink","")}

def drive_download_bytes(svc, file_id:str)->bytes:
    req=svc.files().get_media(fileId=file_id)
    fh=io.BytesIO()
    dl=MediaIoBaseDownload(fh,req)
    done=False
    while not done:
        _,done=dl.next_chunk()
    return fh.getvalue()

def sb_fetch_df(sb:SupabaseClient, table:str, cols:List[str])->pd.DataFrame:
    try:
        res=sb.table(table).select("*").execute()
        rows=res.data or []
        df=pd.DataFrame(rows)
        if df.empty: return pd.DataFrame(columns=cols)
        for c in df.columns: df[c]=df[c].apply(safe_str)
        for c in cols:
            if c not in df.columns: df[c]=""
        return df[cols]
    except Exception as e:
        st.error(f"Supabase load error ({table}): {e}")
        return pd.DataFrame(columns=cols)

def sb_replace(sb:SupabaseClient, table:str, df:pd.DataFrame)->None:
    try:
        payload=df.to_dict(orient="records") if df is not None else []
        sb.table(table).delete().neq("id","00000000-0000-0000-0000-000000000000").execute()
        if payload: sb.table(table).insert(payload).execute()
    except Exception as e:
        st.error(f"Supabase save error ({table}): {e}")

def purchases_add_clean(df:pd.DataFrame)->pd.DataFrame:
    if df.empty:
        df["_clean_code"]=[]; df["_clean_specs"]=[]; return df
    df=df.copy()
    df["_clean_code"]=df["item_code"].apply(clean_key)
    df["_clean_specs"]=df["specs"].apply(clean_key)
    return df

def find_purchase(pur:pd.DataFrame, code_clean:str, specs_clean:str)->Optional[pd.Series]:
    if pur.empty: return None
    cand=pur[pur["_clean_code"]==code_clean]
    if cand.empty: return None
    if specs_clean:
        hit=cand[cand["_clean_specs"]==specs_clean]
        if not hit.empty: return hit.iloc[0]
        hit2=cand[cand["_clean_specs"].apply(lambda x: specs_clean in x or x in specs_clean)]
        if not hit2.empty: return hit2.iloc[0]
    return cand.iloc[0]

def recalc_quote(df:pd.DataFrame, pcts:Dict[str,float], trans_per_qty:Optional[float])->pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    out=df.copy()
    for i,r in out.iterrows():
        qty=to_float(r.get("qty"))
        buy_vnd=to_float(r.get("buying_price_vnd"))
        t_buy=qty*buy_vnd
        ap=to_float(r.get("ap_price"))
        unit=to_float(r.get("unit_price"))
        tqty = trans_per_qty if trans_per_qty is not None else to_float(r.get("transportation"))
        out.at[i,"transportation"]=fmt_num(tqty)
        ap_tot=ap*qty; total=unit*qty; gap=total-ap_tot
        tax=t_buy*pcts["tax"]; buyer=total*pcts["buy"]; vat=total*pcts["vat"]; mgmt=total*pcts["mgmt"]; end=ap_tot*pcts["end"]
        payback=gap*pcts["pay"]; trans= tqty*qty
        cost=t_buy+gap+end+buyer+tax+vat+mgmt+trans
        prof=total-cost+payback
        pct=(prof/total*100) if total else 0
        out.at[i,"total_buying_price_vnd"]=fmt_num(t_buy)
        out.at[i,"ap_total_vnd"]=fmt_num(ap_tot)
        out.at[i,"total_price_vnd"]=fmt_num(total)
        out.at[i,"gap"]=fmt_num(gap)
        out.at[i,"end_user_val"]=fmt_num(end)
        out.at[i,"buyer_val"]=fmt_num(buyer)
        out.at[i,"import_tax_val"]=fmt_num(tax)
        out.at[i,"vat_val"]=fmt_num(vat)
        out.at[i,"mgmt_fee"]=fmt_num(mgmt)
        out.at[i,"payback_val"]=fmt_num(payback)
        out.at[i,"profit_vnd"]=fmt_num(prof)
        out.at[i,"profit_pct"]=f"{pct:.2f}"
    return out

def import_purchase_excel_with_images(xlsx_bytes:bytes)->Tuple[pd.DataFrame, Dict[str,bytes]]:
    wb=load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    ws=wb.active
    img_map={}
    for img in getattr(ws,"_images",[]):
        try:
            r=img.anchor._from.row; c=img.anchor._from.col
            if c==12:
                img_map[r+1]=img._data()
        except Exception: pass
    df=pd.read_excel(io.BytesIO(xlsx_bytes), header=0, dtype=str).fillna("")
    rows=[]; imgs={}
    for i,row in df.iterrows():
        excel_row=i+2
        b=img_map.get(excel_row,b"")
        key=""
        if b:
            key=f"pending:{sha1_bytes(b)}"; imgs[key]=b
        item={
            "no":safe_str(row.iloc[0]),
            "item_code":safe_str(row.iloc[1]),
            "item_name":safe_str(row.iloc[2]),
            "specs":safe_str(row.iloc[3]),
            "qty":fmt_num(to_float(row.iloc[4])),
            "buying_price_rmb":fmt_num(to_float(row.iloc[5])),
            "total_buying_price_rmb":fmt_num(to_float(row.iloc[6])),
            "exchange_rate":fmt_num(to_float(row.iloc[7])),
            "buying_price_vnd":fmt_num(to_float(row.iloc[8])),
            "total_buying_price_vnd":fmt_num(to_float(row.iloc[9])),
            "leadtime":safe_str(row.iloc[10]),
            "supplier_name":safe_str(row.iloc[11]),
            "image_path":key
        }
        if item["item_code"]: rows.append(item)
    return pd.DataFrame(rows, columns=PURCHASE_COLUMNS), imgs

def import_rfq_excel(xlsx_bytes:bytes, purchases:pd.DataFrame)->pd.DataFrame:
    df=pd.read_excel(io.BytesIO(xlsx_bytes), header=None, dtype=str).fillna("")
    start=1 if safe_str(df.iloc[0,1]).lower() in ["code","mã hàng"] else 0
    data=[]
    for _,r in df.iloc[start:].iterrows():
        code=safe_str(r.iloc[1]); 
        if not code: continue
        it={k:"" for k in QUOTE_KH_COLUMNS}
        it.update({"no":safe_str(r.iloc[0]),"item_code":code,"item_name":safe_str(r.iloc[2]),"specs":safe_str(r.iloc[3]),"qty":fmt_num(to_float(r.iloc[4]))})
        for f in ["ap_price","unit_price","transportation","import_tax_val","vat_val","mgmt_fee","payback_val"]: it[f]="0"
        target=find_purchase(purchases, clean_key(code), clean_key(it["specs"]))
        if target is not None:
            it.update({"buying_price_rmb":safe_str(target.get("buying_price_rmb")),"exchange_rate":safe_str(target.get("exchange_rate")),
                       "buying_price_vnd":safe_str(target.get("buying_price_vnd")),"supplier_name":safe_str(target.get("supplier_name")),
                       "image_path":safe_str(target.get("image_path")),"leadtime":safe_str(target.get("leadtime"))})
        data.append(it)
    return pd.DataFrame(data, columns=QUOTE_KH_COLUMNS)

def require_admin(cfg:AppConfig)->bool:
    st.sidebar.subheader("🔐 Admin")
    pwd=st.sidebar.text_input("Admin password", type="password")
    ok=bool(pwd) and pwd==cfg.admin_password
    st.sidebar.success("Admin" if ok else "Viewer")
    return ok

def editor(df:pd.DataFrame, key:str, disabled:bool)->pd.DataFrame:
    return st.data_editor(df, key=key, disabled=disabled, use_container_width=True, num_rows="dynamic", hide_index=True)

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    cfg, missing = load_config()
    if missing:
        st.error("Thiếu Secrets. Dán vào Streamlit Cloud -> App settings -> Secrets")
        st.code("""[supabase]
url="https://YOURPROJECT.supabase.co"
key="YOUR_KEY"
[google]
client_id="..."
client_secret="..."
refresh_token="..."
[app]
drive_root_folder="SGS_CRM_DATA"
admin_password="admin"
""")
        st.warning("Thiếu: " + ", ".join(missing))
        st.stop()

    sb=get_supabase(cfg)
    drive=get_drive(cfg)
    drive_root_id=drive_ensure_folder(drive, cfg.drive_root_folder)

    is_admin=require_admin(cfg)

    customers=sb_fetch_df(sb, TBL_CUSTOMERS, MASTER_COLUMNS)
    suppliers=sb_fetch_df(sb, TBL_SUPPLIERS, MASTER_COLUMNS)
    purchases=purchases_add_clean(sb_fetch_df(sb, TBL_PURCHASES, PURCHASE_COLUMNS))
    sales=sb_fetch_df(sb, TBL_SALES_HISTORY, HISTORY_COLS)
    tracking=sb_fetch_df(sb, TBL_TRACKING, TRACKING_COLS)
    po_s=sb_fetch_df(sb, TBL_SUPPLIER_ORDERS, SUPPLIER_ORDER_COLS)
    po_c=sb_fetch_df(sb, TBL_CUSTOMER_ORDERS, CUSTOMER_ORDER_COLS)

    if "quote" not in st.session_state:
        st.session_state.quote=pd.DataFrame(columns=QUOTE_KH_COLUMNS)

    tabs=st.tabs(["📊 Tổng quan","💰 DB Giá NCC","📝 Báo giá KH","📦 PO","🚚 Tracking","🏷️ Master","⚙️ Export"])
    with tabs[0]:
        rev=po_c["total_price"].apply(to_float).sum() if not po_c.empty else 0
        profit=sales["profit"].apply(to_float).sum() if not sales.empty else 0
        cost=rev-profit
        a,b,c=st.columns(3)
        a.metric("TỔNG DOANH THU", fmt_num(rev))
        b.metric("TỔNG CHI PHÍ", fmt_num(cost))
        c.metric("LỢI NHUẬN", fmt_num(profit))

    with tabs[1]:
        st.subheader("DB Giá NCC (import Excel có ảnh)")
        up=st.file_uploader("Import Excel DB Giá", type=["xlsx"])
        if up and is_admin:
            df_new, imgs = import_purchase_excel_with_images(up.read())
            img_folder=drive_ensure_folder(drive, "product_images", drive_root_id)
            for i,r in df_new.iterrows():
                ip=safe_str(r.get("image_path"))
                if ip.startswith("pending:") and ip in imgs:
                    finfo=drive_upload_bytes(drive, img_folder, f"{ip.replace('pending:','img_')}.png", imgs[ip], "image/png")
                    df_new.at[i,"image_path"]=f"drive:{finfo['file_id']}"
            sb_replace(sb, TBL_PURCHASES, df_new)
            st.success("OK: Đã import DB giá + upload ảnh. Refresh trang.")
        kw=st.text_input("Search")
        view=purchases.copy()
        if kw:
            k=kw.lower()
            view=view[view.apply(lambda row: k in " ".join([safe_str(x) for x in row.values]).lower(), axis=1)]
        ed=editor(view[PURCHASE_COLUMNS], "pur", disabled=not is_admin)
        if is_admin and st.button("Lưu DB (Replace)"):
            sb_replace(sb, TBL_PURCHASES, ed)
            st.success("OK")
        code=st.text_input("Item code để xem ảnh")
        if code:
            row=purchases[purchases["item_code"].apply(clean_key)==clean_key(code)]
            if not row.empty:
                imgref=safe_str(row.iloc[0].get("image_path"))
                if imgref.startswith("drive:"):
                    b=drive_download_bytes(drive, imgref.split("drive:",1)[1])
                    st.image(b, caption=code)
                else:
                    st.info("Chưa có ảnh")

    with tabs[2]:
        cust=st.selectbox("Khách", [""]+customers["short_name"].tolist())
        quote_no=st.text_input("Quote No")
        c1,c2,c3,c4,c5,c6,c7=st.columns(7)
        end=c1.number_input("End(%)",0.0,0.0,100.0,0.5)
        buy=c2.number_input("Buyer(%)",0.0,0.0,100.0,0.5)
        tax=c3.number_input("Tax(%)",0.0,0.0,100.0,0.5)
        vat=c4.number_input("VAT(%)",0.0,0.0,100.0,0.5)
        pay=c5.number_input("Payback(%)",0.0,0.0,100.0,0.5)
        mgmt=c6.number_input("Mgmt(%)",0.0,0.0,100.0,0.5)
        trans=c7.number_input("Trans/Qty",0.0, step=1000.0)
        rfq=st.file_uploader("Import RFQ", type=["xlsx"])
        if rfq:
            qdf=import_rfq_excel(rfq.read(), purchases)
            pcts={"end":end/100,"buy":buy/100,"tax":tax/100,"vat":vat/100,"pay":pay/100,"mgmt":mgmt/100}
            st.session_state.quote=recalc_quote(qdf,pcts, trans if trans>0 else None)
            st.success("OK")
        apf=st.text_input("AP formula (=BUY*1.05)")
        unf=st.text_input("Unit formula (=AP*1.1)")
        A,B,C=st.columns(3)
        if A.button("Apply AP"):
            df=st.session_state.quote.copy()
            for i,r in df.iterrows():
                apv=parse_formula(apf,to_float(r.get("buying_price_vnd")),to_float(r.get("ap_price")))
                df.at[i,"ap_price"]=fmt_num(apv)
            st.session_state.quote=df
        if B.button("Apply Unit"):
            df=st.session_state.quote.copy()
            for i,r in df.iterrows():
                uv=parse_formula(unf,to_float(r.get("buying_price_vnd")),to_float(r.get("ap_price")))
                df.at[i,"unit_price"]=fmt_num(uv)
            st.session_state.quote=df
        if C.button("Recalc"):
            pcts={"end":end/100,"buy":buy/100,"tax":tax/100,"vat":vat/100,"pay":pay/100,"mgmt":mgmt/100}
            st.session_state.quote=recalc_quote(st.session_state.quote,pcts, trans if trans>0 else None)
        st.session_state.quote=editor(st.session_state.quote, "q", disabled=not is_admin)
        if is_admin and st.button("Lưu Sales History"):
            if not cust or not quote_no: st.error("Chọn khách + quote")
            else:
                now=datetime.now().strftime("%d/%m/%Y")
                rows=[]
                for _,r in st.session_state.quote.iterrows():
                    rows.append({"date":now,"quote_no":quote_no,"customer":cust,"item_code":safe_str(r.get("item_code")),
                                 "item_name":safe_str(r.get("item_name")),"specs":safe_str(r.get("specs")),"qty":safe_str(r.get("qty")),
                                 "total_revenue":safe_str(r.get("total_price_vnd")),"total_cost":safe_str(r.get("total_buying_price_vnd")),
                                 "profit":safe_str(r.get("profit_vnd")),"supplier":safe_str(r.get("supplier_name")),"status":"Báo giá",
                                 "delivery_date":"","po_number":""})
                all_hist=pd.concat([sales,pd.DataFrame(rows,columns=HISTORY_COLS)], ignore_index=True)
                sb_replace(sb, TBL_SALES_HISTORY, all_hist)
                st.success("OK")

    with tabs[3]:
        st.subheader("PO NCC")
        eds=editor(po_s, "pos", disabled=not is_admin)
        if is_admin and st.button("Lưu PO NCC"):
            sb_replace(sb, TBL_SUPPLIER_ORDERS, eds); st.success("OK")
        st.subheader("PO KH")
        edc=editor(po_c, "poc", disabled=not is_admin)
        if is_admin and st.button("Lưu PO KH"):
            sb_replace(sb, TBL_CUSTOMER_ORDERS, edc); st.success("OK")

    with tabs[4]:
        ed=editor(tracking, "trk", disabled=not is_admin)
        if is_admin and st.button("Lưu Tracking"):
            sb_replace(sb, TBL_TRACKING, ed); st.success("OK")

    with tabs[5]:
        st.subheader("Customers"); edc=editor(customers,"mc", disabled=not is_admin)
        if is_admin and st.button("Lưu Customers"): sb_replace(sb, TBL_CUSTOMERS, edc); st.success("OK")
        st.subheader("Suppliers"); eds=editor(suppliers,"ms", disabled=not is_admin)
        if is_admin and st.button("Lưu Suppliers"): sb_replace(sb, TBL_SUPPLIERS, eds); st.success("OK")

    with tabs[6]:
        out=io.BytesIO()
        if st.button("Download snapshot"):
            with pd.ExcelWriter(out, engine="openpyxl") as w:
                customers.to_excel(w,index=False,sheet_name="customers")
                suppliers.to_excel(w,index=False,sheet_name="suppliers")
                purchases[PURCHASE_COLUMNS].to_excel(w,index=False,sheet_name="purchases")
                sales.to_excel(w,index=False,sheet_name="sales_history")
                tracking.to_excel(w,index=False,sheet_name="tracking")
                po_s.to_excel(w,index=False,sheet_name="po_supplier")
                po_c.to_excel(w,index=False,sheet_name="po_customer")
            b=out.getvalue()
            st.download_button("Download", data=b, file_name=f"sgs_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if __name__=="__main__":
    main()
