create extension if not exists "pgcrypto";

create table if not exists public.crm_customers (
  id uuid primary key default gen_random_uuid(),
  no text, short_name text, eng_name text, vn_name text,
  address_1 text, address_2 text, contact_person text, director text,
  phone text, fax text, tax_code text, destination text, payment_term text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_suppliers (
  id uuid primary key default gen_random_uuid(),
  no text, short_name text, eng_name text, vn_name text,
  address_1 text, address_2 text, contact_person text, director text,
  phone text, fax text, tax_code text, destination text, payment_term text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_purchases (
  id uuid primary key default gen_random_uuid(),
  no text, item_code text, item_name text, specs text, qty text,
  buying_price_rmb text, total_buying_price_rmb text, exchange_rate text,
  buying_price_vnd text, total_buying_price_vnd text,
  leadtime text, supplier_name text, image_path text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_sales_history (
  id uuid primary key default gen_random_uuid(),
  date text, quote_no text, customer text, item_code text, item_name text, specs text, qty text,
  total_revenue text, total_cost text, profit text, supplier text,
  status text, delivery_date text, po_number text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_order_tracking (
  id uuid primary key default gen_random_uuid(),
  no text, po_no text, partner text, status text, eta text,
  proof_image text, order_type text, last_update text, finished text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_payment_tracking (
  id uuid primary key default gen_random_uuid(),
  no text, po_no text, customer text, invoice_no text, status text, due_date text, paid_date text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.crm_paid_history (
  id uuid primary key default gen_random_uuid(),
  no text, po_no text, customer text, invoice_no text, status text, due_date text, paid_date text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.db_supplier_orders (
  id uuid primary key default gen_random_uuid(),
  no text, item_code text, item_name text, specs text, qty text,
  price_rmb text, total_rmb text, exchange_rate text, price_vnd text, total_vnd text,
  eta text, supplier text, po_number text, order_date text, pdf_path text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table if not exists public.db_customer_orders (
  id uuid primary key default gen_random_uuid(),
  no text, item_code text, item_name text, specs text, qty text,
  unit_price text, total_price text, eta text, customer text,
  po_number text, order_date text, pdf_path text, base_buying_vnd text, full_cost_total text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create index if not exists idx_purchases_item_code on public.crm_purchases (item_code);
create index if not exists idx_sales_quote_no on public.crm_sales_history (quote_no);
create index if not exists idx_sales_item_code on public.crm_sales_history (item_code);
create index if not exists idx_po_cust_po_number on public.db_customer_orders (po_number);
create index if not exists idx_po_supp_po_number on public.db_supplier_orders (po_number);
