import io
import gc
import os
import hashlib
import zipfile
import warnings
import pandas as pd
from typing import List
from datetime import datetime
from jose import JWTError, jwt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from pydantic import BaseModel

import config
from services import deals, docuseal, inventory, sales
from services.supabase_client import (
    get_user_role_id,
    list_bucket,
    signed_url,
    upload_to_bucket,
    supabase_admin,
)

warnings.filterwarnings('ignore')

app = FastAPI(title="EVOne Internal System API")

# ==========================================
# 1. Base Configuration
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Auth failed")


# Role definitions — single source of truth for RBAC across backend + frontend.
# role_id 1 = Admin     : full access everywhere
# role_id 2 = Finance   : billing page only
# role_id 3 = Read Only : read access to all pages (no destructive actions)
# role_id 4 = Technical : Document Signing (full) + Document Center (read-only)
ROLE_INFO: dict[int, dict] = {
    1: {"name": "Admin",     "allowed_paths": ["*"]},
    2: {"name": "Finance",   "allowed_paths": ["/"]},
    3: {"name": "Read Only", "allowed_paths": ["*"]},
    4: {"name": "Technical", "allowed_paths": ["/e-sign", "/documents"]},
}


def _get_role_id(user_payload: dict) -> int:
    return get_user_role_id(user_payload.get("sub")) or 3


def check_is_admin(user_payload: dict) -> bool:
    return _get_role_id(user_payload) == 1


def check_can_sign(user_payload: dict) -> bool:
    """Admin and Technical may perform destructive signing operations."""
    return _get_role_id(user_payload) in (1, 4)


# ==========================================
# 2. Page & Config Routes
# ==========================================
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/")
async def serve_billing(request: Request):
    return templates.TemplateResponse(request=request, name="billing.html")


@app.get("/e-sign")
async def serve_signing(request: Request):
    return templates.TemplateResponse(request=request, name="signing.html")


@app.get("/activity")
async def serve_activity(request: Request):
    return templates.TemplateResponse(request=request, name="activity.html")


@app.get("/documents")
async def serve_documents(request: Request):
    return templates.TemplateResponse(request=request, name="files.html")


@app.get("/analytics")
async def serve_analytics(request: Request):
    return templates.TemplateResponse(request=request, name="analytics.html")


@app.get("/customers")
async def serve_customers(request: Request):
    return templates.TemplateResponse(request=request, name="customers.html")


@app.get("/config")
async def get_config():
    return {
        "supabase_url": config.SUPABASE_URL,
        "supabase_key": config.SUPABASE_ANON_KEY,
    }


@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    role_id = _get_role_id(user)
    info = ROLE_INFO.get(role_id, ROLE_INFO[3])
    return {"role_id": role_id, "role_name": info["name"], "allowed_paths": info["allowed_paths"]}


# ==========================================
# 3. Document Management API (RBAC)
# ==========================================
@app.get("/api/list-files")
async def list_files(user: dict = Depends(get_current_user)):
    try:
        files = list_bucket("Documents", path="general")
        return {"is_admin": check_is_admin(user), "files": files}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/upload-file")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    try:
        file_bytes = await file.read()
        safe_name = "".join(
            c for c in file.filename if c.isalnum() or c in (" ", "_", ".", "-")
        ).strip()
        upload_to_bucket(
            "Documents",
            f"general/{safe_name}",
            file_bytes,
            file.content_type or "application/octet-stream",
        )
        return {"success": True}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.get("/api/get-file-url/{filename}")
async def get_file_url(filename: str, user: dict = Depends(get_current_user)):
    try:
        return {"url": signed_url("Documents", f"general/{filename}", expires_in=3600)}
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 4. E-Sign API
# ==========================================
@app.post("/api/create-signature")
async def create_signature(data: dict, user: dict = Depends(get_current_user)):
    category = data.get("category", "Internal").strip()
    form_type = data.get("form_type")
    signers_count = str(data.get("signers_count", "1"))
    prefix = data.get("prefix", "").strip()

    template_id, submitters = docuseal.resolve_template_and_submitters(
        form_type, signers_count, data
    )
    if not template_id:
        return {"error": True, "message": "Template mapping failed"}

    base_name = f"{prefix} {form_type}" if prefix else form_type
    document_name = f"[{category}] {base_name}"

    return docuseal.create_submission(int(template_id), document_name, submitters)


@app.get("/api/get-signing-submissions")
async def get_submissions(user: dict = Depends(get_current_user)):
    return docuseal.list_submissions()


@app.delete("/api/signing-submissions/{sub_id}")
async def delete_signing_submission(sub_id: int, user: dict = Depends(get_current_user)):
    if not check_can_sign(user):
        raise HTTPException(status_code=403, detail="Admin or Technical role required")
    ok, body = docuseal.delete_submission(sub_id)
    if ok:
        return {"success": True}
    return {"error": True, "message": body.get("message", "DocuSeal rejected the request.")}


@app.patch("/api/signing-submissions/{sub_id}/archive")
async def archive_signing_submission(sub_id: int, user: dict = Depends(get_current_user)):
    if not check_can_sign(user):
        raise HTTPException(status_code=403, detail="Admin or Technical role required")
    ok, body = docuseal.archive_submission(sub_id)
    if ok:
        return {"success": True}
    return {"error": True, "message": body.get("message", "DocuSeal rejected the request.")}


@app.get("/api/get-document-download/{sub_id}")
async def get_download(sub_id: str, user: dict = Depends(get_current_user)):
    try:
        ok, data = docuseal.get_submission(sub_id)
        if not ok:
            return {"error": True, "message": "DocuSeal Record not found"}

        docs = data.get("documents", [])
        download_url = docs[0].get("url") if docs else None

        if data.get("status") == "completed" and download_url:
            file_bytes = docuseal.fetch_url_bytes(download_url)
            if file_bytes:
                raw_name = data.get("name", "")

                form_folder = "Others"
                if "Form A" in raw_name:
                    form_folder = "Form A"
                elif "Form D" in raw_name:
                    form_folder = "Form D"
                elif "Form 1" in raw_name:
                    form_folder = "Form 1"

                cat_folder = "Internal" if "[Internal]" in raw_name else "External"

                filename = f"{datetime.now().strftime('%Y%m%d')}_{raw_name}.pdf"
                safe_name = "".join(
                    c for c in filename if c.isalnum() or c in (" ", "_", ".", "-")
                ).strip()

                final_path = f"{cat_folder}/{form_folder}/{safe_name}"
                upload_to_bucket("Form", final_path, file_bytes, "application/pdf")

        return {"download_url": download_url}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/resend-signature/{submitter_id}")
async def resend_signature(submitter_id: int, user: dict = Depends(get_current_user)):
    try:
        ok, body = docuseal.resend_submitter(submitter_id)
        if ok:
            return {"success": True}
        return {
            "error": True,
            "message": body.get("message", "DocuSeal rejected the request."),
        }
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 5. Billing — PDF generation pipeline
# ==========================================
async def load_dataframe(file: UploadFile, sheet_name=None):
    if not file:
        raise ValueError("File is missing!")
    name = file.filename.lower()
    if name.endswith('.csv'):
        return pd.read_csv(file.file)
    if sheet_name:
        try:
            return pd.read_excel(file.file, sheet_name=sheet_name)
        except Exception:
            file.file.seek(0)
            return pd.read_excel(file.file)
    return pd.read_excel(file.file)


@app.post("/process-pdf")
async def process_pdf(files: List[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    try:
        gp_tx, gp_crm, sp_tx, sp_crm, rate_file = None, None, None, None, None

        for f in files:
            name = f.filename.lower()
            if 'threshold' in name or 'rate' in name:
                rate_file = f
            elif ('gp' in name or 'goparkin' in name) and ('vehicle' in name or 'crm' in name):
                gp_crm = f
            elif ('sp' in name or 'evone' in name) and ('vehicle' in name or 'crm' in name):
                sp_crm = f
            elif ('gp' in name or 'goparkin' in name) and ('transaction' in name or 'row' in name):
                gp_tx = f
            elif ('sp' in name or 'evone' in name) and ('transaction' in name or 'report' in name or 'breakdown' in name):
                sp_tx = f

        missing = []
        if not gp_tx: missing.append("GoParkin Transaction")
        if not gp_crm: missing.append("GoParkin CRM")
        if not sp_tx: missing.append("SP Transaction")
        if not sp_crm: missing.append("SP CRM")
        if not rate_file: missing.append("Threshold and Rate")
        if missing:
            return {"error": True, "message": f"缺少文件: {', '.join(missing)}"}

        crm_gp = await load_dataframe(gp_crm)
        df_gp = await load_dataframe(gp_tx)
        crm_sp = await load_dataframe(sp_crm)
        df_sp = await load_dataframe(sp_tx, sheet_name='EVOne Corporate fleet')
        df_rates = await load_dataframe(rate_file)

        rates_dict = {}
        for _, row in df_rates.iterrows():
            comp_name = str(row.get('company', '')).strip().lower()
            rates_dict[comp_name] = {
                'base': pd.to_numeric(row.get('base', 0), errors='coerce'),
                'threshold': pd.to_numeric(row.get('Threshold', 0), errors='coerce'),
                'discounted': pd.to_numeric(row.get('discounted', 0), errors='coerce'),
            }

        crm_gp = crm_gp[['Vehicle No.', 'Company']].dropna()
        crm_gp['Vehicle No.'] = crm_gp['Vehicle No.'].astype(str).str.strip().str.upper()
        crm_gp = crm_gp.drop_duplicates(subset=['Vehicle No.'], keep='first')

        if 'payment_status' in df_gp.columns:
            df_gp = df_gp[df_gp['payment_status'] == 'Success'].copy()
        if 'transaction_type' in df_gp.columns:
            df_gp = df_gp[df_gp['transaction_type'].astype(str).str.strip().str.lower() == 'corporate'].copy()
        df_gp['vehicle_plate_number'] = df_gp['vehicle_plate_number'].astype(str).str.strip().str.upper()
        gp_merged = pd.merge(df_gp, crm_gp, left_on='vehicle_plate_number', right_on='Vehicle No.', how='left')
        gp_merged['Company'] = gp_merged['Company'].fillna('Unmatched GoParkin')

        crm_sp = crm_sp[['Email', 'Company']].dropna()
        crm_sp['Email'] = crm_sp['Email'].astype(str).str.strip().str.lower()
        crm_sp = crm_sp.drop_duplicates(subset=['Email'], keep='first')

        df_sp['Driver Email'] = df_sp['Driver Email'].astype(str).str.strip().str.lower()
        df_sp['CDR Total Energy'] = pd.to_numeric(df_sp['CDR Total Energy'], errors='coerce').fillna(0)
        sp_merged = pd.merge(df_sp, crm_sp, left_on='Driver Email', right_on='Email', how='left')
        sp_merged['Company'] = sp_merged['Company'].fillna('Unmatched SP Email')

        def extract_details(df, source):
            res = pd.DataFrame()
            if df.empty:
                return res
            res['Company'] = df['Company']
            if source == 'GP':
                res['Vehicle_Email'] = df['vehicle_plate_number']
                res['Start Time'] = df.get('start_date_time', df['end_date_time'])
                res['End Time'] = df['end_date_time']
                res['Location'] = df.get('carpark_code', df.get('site_name', 'GoParkin Station'))
                res['Energy (kWh)'] = df['total_energy_supplied_kwh']
            else:
                res['Vehicle_Email'] = df['Driver Email']
                res['Start Time'] = df.get('Start Date', df.get('Date', ''))
                res['End Time'] = df.get('End Date', df.get('Date', ''))
                res['Location'] = df.get('Location Name', df.get('Location', 'SP Station'))
                res['Energy (kWh)'] = df['CDR Total Energy']
            return res

        all_details = pd.concat([extract_details(gp_merged, 'GP'), extract_details(sp_merged, 'SP')], ignore_index=True)
        all_details = all_details[all_details['Energy (kWh)'] > 0]
        all_details['Year-Month'] = all_details['End Time'].astype(str).str[0:7]

        zip_buffer = io.BytesIO()
        internal_summary_data = []

        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            months = all_details['Year-Month'].dropna().unique()
            for month in months:
                month_df = all_details[all_details['Year-Month'] == month]
                unique_companies = month_df['Company'].dropna().unique()
                used_file_names = set()

                for company in unique_companies:
                    comp_df = month_df[month_df['Company'] == company]
                    total_kwh = comp_df['Energy (kWh)'].sum()
                    comp_key = str(company).strip().lower()
                    r_info = rates_dict.get(comp_key, {'base': 0, 'threshold': float('inf'), 'discounted': 0})

                    base_rate = r_info['base'] if pd.notna(r_info['base']) else 0
                    threshold = r_info['threshold'] if pd.notna(r_info['threshold']) else float('inf')
                    discounted = r_info['discounted'] if pd.notna(r_info['discounted']) else 0
                    applied_rate = discounted if total_kwh > threshold else base_rate
                    total_price = total_kwh * applied_rate

                    internal_summary_data.append({
                        "Billing Month": month,
                        "Company": company,
                        "Total Energy (kWh)": round(total_kwh, 2),
                        "Base Rate ($)": base_rate,
                        "Threshold (kWh)": threshold if threshold != float('inf') else "N/A",
                        "Discounted Rate ($)": discounted,
                        "Applied Rate ($)": applied_rate,
                        "Total Amount ($)": round(total_price, 2),
                    })

                    pdf_buf = io.BytesIO()
                    doc = SimpleDocTemplate(pdf_buf, pagesize=A4)
                    elements, styles = [], getSampleStyleSheet()

                    logo_path = "static/logo.png"
                    if os.path.exists(logo_path):
                        logo_img = Image(logo_path, width=120, height=40)
                        logo_img.hAlign = 'LEFT'
                        elements.extend([logo_img, Spacer(1, 10)])

                    elements.extend([
                        Paragraph("<b>Corporate Charging Statement</b>", styles['Title']), Spacer(1, 12),
                        Paragraph(f"<b>Company:</b> {company}", styles['Normal']),
                        Paragraph(f"<b>Billing Month:</b> {month}", styles['Normal']),
                    ])
                    disp_thresh = f"{threshold:g}" if threshold != float('inf') else "N/A"
                    elements.extend([
                        Paragraph(f"<b>Threshold Limit:</b> {disp_thresh}", styles['Normal']),
                        Paragraph(f"<b>Base Rate:</b> ${base_rate:.2f}", styles['Normal']),
                        Paragraph(f"<b>Discounted Rate:</b> ${discounted:.2f}", styles['Normal']),
                        Paragraph(f"<b>Applied Rate:</b> ${applied_rate:.2f}", styles['Normal']), Spacer(1, 20),
                    ])

                    elements.append(Paragraph("<b>1. Billing Summary</b>", styles['Heading2']))
                    t_summary = Table([
                        ["Total Energy (kWh)", "Threshold Limit", "Applied Rate ($)", "Total Amount ($)"],
                        [f"{total_kwh:.2f}", f"{disp_thresh}", f"${applied_rate:.2f}", f"${total_price:.2f}"],
                    ], colWidths=[120, 110, 110, 120])
                    t_summary.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00ad5f')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ]))
                    elements.extend([t_summary, Spacer(1, 24)])

                    elements.append(Paragraph("<b>2. Vehicle Breakdown</b>", styles['Heading2']))
                    veh_summary = comp_df.groupby('Vehicle_Email')['Energy (kWh)'].sum().reset_index().sort_values('Energy (kWh)', ascending=False)
                    veh_data = [["Vehicle / Driver Email", "Energy Used (kWh)"]]
                    for _, v_row in veh_summary.iterrows():
                        veh_data.append([str(v_row['Vehicle_Email']), f"{v_row['Energy (kWh)']:.2f}"])
                    t_veh = Table(veh_data, colWidths=[250, 150])
                    t_veh.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00ad5f')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ]))
                    elements.extend([t_veh, Spacer(1, 24)])

                    elements.extend([Paragraph("<b>3. Detailed Charging Log</b>", styles['Heading2']), Spacer(1, 10)])
                    for vehicle, grp in comp_df.groupby('Vehicle_Email'):
                        elements.extend([Paragraph(f"<b>Vehicle / Driver Email:</b> {vehicle}", styles['Normal']), Spacer(1, 6)])
                        detail_data = [["Location", "Start Time", "End Time", "Energy (kWh)"]]
                        veh_total = 0
                        for _, d_row in grp.sort_values('Start Time').iterrows():
                            detail_data.append([str(d_row['Location']), str(d_row['Start Time']), str(d_row['End Time']), f"{d_row['Energy (kWh)']:.2f}"])
                            veh_total += d_row['Energy (kWh)']
                        detail_data.append(["", "", "Total:", f"{veh_total:.2f}"])
                        t_detail = Table(detail_data, colWidths=[170, 100, 100, 80])
                        t_detail.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#00ad5f')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                            ('FONTNAME', (2, -1), (2, -1), 'Helvetica-Bold'),
                            ('FONTNAME', (3, -1), (3, -1), 'Helvetica-Bold'),
                            ('BACKGROUND', (0, -1), (-1, -1), colors.whitesmoke),
                        ]))
                        elements.extend([t_detail, Spacer(1, 16)])

                    doc.build(elements)

                    base_name = str(company).replace('/', '-').replace('\\', '-').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '').strip()
                    safe_comp = base_name
                    counter = 1
                    while safe_comp.lower() in used_file_names:
                        safe_comp = f"{base_name}_{counter}"
                        counter += 1
                    used_file_names.add(safe_comp.lower())

                    zip_file.writestr(f"{month}/{safe_comp}_{month}.pdf", pdf_buf.getvalue())

            if internal_summary_data:
                summary_df = pd.DataFrame(internal_summary_data)
                summary_df = summary_df.sort_values(by=['Billing Month', 'Total Amount ($)'], ascending=[True, False])

                excel_buf = io.BytesIO()
                with pd.ExcelWriter(excel_buf, engine='xlsxwriter') as writer:
                    summary_df.to_excel(writer, index=False, sheet_name='Internal Summary')

                zip_file.writestr("Internal_Summary_内部结算总表.xlsx", excel_buf.getvalue())

        del df_gp, df_sp, gp_merged, sp_merged, all_details, df_rates
        gc.collect()

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=Monthly_PDF_Reports.zip"},
        )
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 6. CRM — Customers
# ==========================================
class CustomerCreate(BaseModel):
    name: str
    type: str = "Residential"
    attention_to: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    lead_source: str | None = None
    status: str = "active"
    joined_at: str | None = None
    notes: str | None = None


@app.get("/api/customers")
async def get_customers(user: dict = Depends(get_current_user)):
    try:
        return {"customers": sales.list_customers()}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/customers")
async def post_customer(data: CustomerCreate, user: dict = Depends(get_current_user)):
    try:
        customer = sales.create_customer(data.model_dump(exclude_none=True))
        return {"customer": customer}
    except Exception as e:
        return {"error": True, "message": str(e)}


class CustomerUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    attention_to: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    lead_source: str | None = None
    status: str | None = None
    joined_at: str | None = None
    notes: str | None = None


@app.get("/api/customers/{customer_id}")
async def get_customer(customer_id: str, user: dict = Depends(get_current_user)):
    try:
        customer = sales.get_customer(customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return {"customer": customer}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.put("/api/customers/{customer_id}")
async def put_customer(customer_id: str, data: CustomerUpdate, user: dict = Depends(get_current_user)):
    try:
        payload = data.model_dump(exclude_none=True)
        if not payload:
            raise HTTPException(status_code=400, detail="No fields to update")
        customer = sales.update_customer(customer_id, payload)
        return {"customer": customer}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.delete("/api/customers/{customer_id}")
async def delete_customer(customer_id: str, _user: dict = Depends(get_current_user)):
    try:
        return sales.delete_customer(customer_id)
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 7. Inventory & Products
# ==========================================
class ProductCreate(BaseModel):
    sku: str
    name: str
    category: str | None = None
    cost: float = 0.0
    price: float = 0.0
    stock_qty: int = 0
    reorder_level: int = 0
    supplier: str | None = None
    storage_location: str | None = None


class ProductUpdate(BaseModel):
    sku: str | None = None
    name: str | None = None
    category: str | None = None
    cost: float | None = None
    price: float | None = None
    stock_qty: int | None = None
    reorder_level: int | None = None
    supplier: str | None = None
    storage_location: str | None = None


@app.get("/inventory")
async def serve_inventory(request: Request):
    return templates.TemplateResponse(request=request, name="inventory.html")


@app.get("/api/products")
async def get_products(user: dict = Depends(get_current_user)):
    try:
        return {"products": inventory.list_products()}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/products")
async def post_product(data: ProductCreate, user: dict = Depends(get_current_user)):
    try:
        product = inventory.create_product(data.model_dump(exclude_none=True))
        return {"product": product}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.get("/api/products/{product_id}")
async def get_product(product_id: str, user: dict = Depends(get_current_user)):
    try:
        product = inventory.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"product": product}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.put("/api/products/{product_id}")
async def put_product(product_id: str, data: ProductUpdate, user: dict = Depends(get_current_user)):
    try:
        payload = data.model_dump(exclude_none=True)
        if not payload:
            raise HTTPException(status_code=400, detail="No fields to update")
        product = inventory.update_product(product_id, payload)
        return {"product": product}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.delete("/api/products/{product_id}")
async def delete_product(product_id: str, _user: dict = Depends(get_current_user)):
    try:
        return inventory.delete_product(product_id)
    except Exception as e:
        return {"error": True, "message": str(e)}


class StockMovementCreate(BaseModel):
    product_id: str
    product_sku: str
    product_name: str
    type: str  # 'in' or 'out'
    qty: int
    reason: str | None = None
    notes: str | None = None


@app.get("/api/stock-movements")
async def get_stock_movements(user: dict = Depends(get_current_user)):
    try:
        return {"movements": inventory.list_movements()}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/stock-movements")
async def post_stock_movement(data: StockMovementCreate, user: dict = Depends(get_current_user)):
    try:
        movement = inventory.create_movement(data.model_dump(exclude_none=True))
        return {"movement": movement}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 8. Deals
# ==========================================
class DealCreate(BaseModel):
    title: str
    customer_id: str | None = None
    customer_name: str | None = None
    type: str | None = None
    value: float = 0.0
    stage: str = "Lead"
    expected_close: str | None = None
    closed_at: str | None = None
    notes: str | None = None


class DealUpdate(BaseModel):
    title: str | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    type: str | None = None
    value: float | None = None
    stage: str | None = None
    expected_close: str | None = None
    closed_at: str | None = None
    notes: str | None = None


@app.get("/deals")
async def serve_deals(request: Request):
    return templates.TemplateResponse(request=request, name="deals.html")


@app.get("/api/deals")
async def get_deals(user: dict = Depends(get_current_user)):
    try:
        return {"deals": deals.list_deals()}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.post("/api/deals")
async def post_deal(data: DealCreate, user: dict = Depends(get_current_user)):
    try:
        deal = deals.create_deal(data.model_dump(exclude_none=True))
        return {"deal": deal}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.get("/api/deals/{deal_id}")
async def get_deal(deal_id: str, user: dict = Depends(get_current_user)):
    try:
        deal = deals.get_deal(deal_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        return {"deal": deal}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.put("/api/deals/{deal_id}")
async def put_deal(deal_id: str, data: DealUpdate, user: dict = Depends(get_current_user)):
    try:
        payload = data.model_dump(exclude_none=True)
        if not payload:
            raise HTTPException(status_code=400, detail="No fields to update")
        deal = deals.update_deal(deal_id, payload)
        return {"deal": deal}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.delete("/api/deals/{deal_id}")
async def delete_deal(deal_id: str, _user: dict = Depends(get_current_user)):
    try:
        return deals.delete_deal(deal_id)
    except Exception as e:
        return {"error": True, "message": str(e)}


# ==========================================
# 9. User Management (Admin Only)
# ==========================================

class UpdateRolePayload(BaseModel):
    role_id: int


class InviteUserPayload(BaseModel):
    email: str
    password: str
    role_id: int = 3


@app.get("/team")
async def serve_team(request: Request):
    return templates.TemplateResponse(request=request, name="users.html")


@app.get("/api/users")
async def list_team_users(user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    try:
        auth_users = supabase_admin.auth.admin.list_users()
        roles_res = supabase_admin.schema("evone_billing").table("users").select("id,role_id").execute()
        role_map = {r["id"]: r["role_id"] for r in (roles_res.data or [])}

        result = []
        for u in auth_users:
            if not u.email:
                continue
            result.append({
                "id": u.id,
                "email": u.email,
                "last_sign_in_at": u.last_sign_in_at.isoformat() if u.last_sign_in_at else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "role_id": role_map.get(u.id, 3),
            })
        result.sort(key=lambda x: x["created_at"] or "")
        return {"users": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/users/{user_id}/role")
async def update_user_role(user_id: str, payload: UpdateRolePayload, user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    if payload.role_id not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="role_id must be 1, 2, 3, or 4")
    try:
        # Fetch email from auth to satisfy any BEFORE UPDATE trigger that
        # reads auth.users.email and writes it back to evone_billing.users.email
        auth_resp = supabase_admin.auth.admin.get_user_by_id(user_id)
        email = auth_resp.user.email if (auth_resp and auth_resp.user) else None

        update_data: dict = {"role_id": payload.role_id}
        if email:
            update_data["email"] = email

        supabase_admin.schema("evone_billing").table("users").update(
            update_data
        ).eq("id", user_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/users/invite")
async def invite_team_user(payload: InviteUserPayload, user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    try:
        res = supabase_admin.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
        })
        new_user = res.user if hasattr(res, "user") else res
        if new_user and new_user.id:
            hashed_pw = hashlib.sha256(payload.password.encode()).hexdigest()
            supabase_admin.schema("evone_billing").table("users").upsert(
                {"id": new_user.id, "email": payload.email, "role_id": payload.role_id, "hashed_password": hashed_pw},
                on_conflict="id",
            ).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/users/{user_id}")
async def delete_team_user(user_id: str, user: dict = Depends(get_current_user)):
    if not check_is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    if user.get("sub") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    try:
        supabase_admin.auth.admin.delete_user(user_id)
        supabase_admin.schema("evone_billing").table("users").delete().eq("id", user_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
