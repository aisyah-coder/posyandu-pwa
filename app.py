"""
Posyandu PWA — FastAPI backend.

Routes:
  GET  /              — Dashboard (supervisor view)
  GET  /app           — PWA app shell (kader view)
  GET  /hasil/{id}    — Patient result page

  POST /api/kader/auth      — Login / check existing kader by phone
  POST /api/kader/register  — Register new kader
  GET  /api/kader/{id}/patients   — Kader's patient list
  GET  /api/kader/{id}/search     — Search patients by name (?q=)
  POST /api/screen/pregnant — Submit pregnant screening
  POST /api/screen/child    — Submit child screening

  GET  /api/stats           — Dashboard stats
  GET  /api/patients        — All patients (dashboard)
  GET  /api/patient/{id}    — Single patient detail
  GET  /api/chws            — CHW list
  GET  /api/districts       — District list
  GET  /api/who-reference   — WHO growth curves
  POST /api/patient/{id}/qa — Claude Q&A
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from dotenv import load_dotenv

from database import init_db, get_db, HealthWorker, Patient, PregnantScreening, ChildScreening
import screening as sc
from claude_ai import generate_education_message

load_dotenv()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    init_db()
    print("✅ Database initialised")
    print(f"🌐 Server running on port {os.getenv('PORT', 8000)}")
    yield

app = FastAPI(title="Posyandu PWA", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/app", response_class=HTMLResponse)
async def pwa_app(request: Request):
    return templates.TemplateResponse("app.html", {"request": request})


@app.get("/hasil/{patient_id}", response_class=HTMLResponse)
async def patient_result_page(patient_id: int, request: Request, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter_by(id=patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Pasien tidak ditemukan")
    return templates.TemplateResponse("hasil.html", {"request": request, "patient_id": patient_id})


# ---------------------------------------------------------------------------
# Kader auth
# ---------------------------------------------------------------------------

@app.post("/api/kader/auth")
async def kader_auth(request: Request, db: Session = Depends(get_db)):
    """Check if a kader exists by phone number."""
    body = await request.json()
    phone = body.get("phone", "").strip()
    if not phone:
        raise HTTPException(400, "Nomor HP diperlukan")

    chw = db.query(HealthWorker).filter_by(phone=phone).first()
    if chw:
        return {
            "exists": True,
            "id": chw.id,
            "name": chw.name,
            "village": chw.village,
            "district": chw.district,
            "kabupaten": chw.kabupaten,
        }
    return {"exists": False}


@app.post("/api/kader/register")
async def kader_register(request: Request, db: Session = Depends(get_db)):
    """Register a new kader."""
    body = await request.json()
    phone = body.get("phone", "").strip()
    name = body.get("name", "").strip()
    village = body.get("village", "").strip()
    district = body.get("district", "").strip()
    kabupaten = body.get("kabupaten", "").strip()

    if not phone or not name:
        raise HTTPException(400, "Nomor HP dan nama diperlukan")

    existing = db.query(HealthWorker).filter_by(phone=phone).first()
    if existing:
        return {"id": existing.id, "name": existing.name, "village": existing.village, "district": existing.district, "kabupaten": existing.kabupaten}

    chw = HealthWorker(
        phone=phone,
        name=name.title(),
        village=village.title() or None,
        district=district.title() or None,
        kabupaten=kabupaten or None,
    )
    db.add(chw)
    db.commit()
    db.refresh(chw)
    return {"id": chw.id, "name": chw.name, "village": chw.village, "district": chw.district, "kabupaten": chw.kabupaten}


# ---------------------------------------------------------------------------
# Kader patient routes
# ---------------------------------------------------------------------------

@app.get("/api/kader/{kader_id}/patients")
async def kader_patients(kader_id: int, db: Session = Depends(get_db)):
    """Return all patients for a kader with their latest screening status."""
    patients = (
        db.query(Patient)
        .filter_by(chw_id=kader_id)
        .order_by(Patient.created_at.desc())
        .all()
    )
    result = []
    for p in patients:
        if p.patient_type == "pregnant" and p.pregnant_screenings:
            latest = p.pregnant_screenings[-1]
            status = latest.overall_status
            needs_referral = latest.needs_referral
            last_visit = latest.screened_at.isoformat()
            visit_count = len(p.pregnant_screenings)
        elif p.patient_type == "cu2" and p.child_screenings:
            latest = p.child_screenings[-1]
            status = latest.overall_status
            needs_referral = latest.needs_referral
            last_visit = latest.screened_at.isoformat()
            visit_count = len(p.child_screenings)
        else:
            status = "not_screened"
            needs_referral = False
            last_visit = None
            visit_count = 0

        result.append({
            "id": p.id,
            "name": p.name,
            "patient_type": p.patient_type,
            "overall_status": status,
            "needs_referral": needs_referral,
            "last_visit": last_visit,
            "created_at": p.created_at.isoformat(),
            "visit_count": visit_count,
        })
    return result


@app.get("/api/kader/{kader_id}/search")
async def search_kader_patients(kader_id: int, q: str = "", db: Session = Depends(get_db)):
    """Search kader's patients by name."""
    if len(q) < 2:
        return []
    patients = (
        db.query(Patient)
        .filter(Patient.chw_id == kader_id, Patient.name.ilike(f"%{q}%"))
        .order_by(Patient.created_at.desc())
        .limit(8)
        .all()
    )
    result = []
    for p in patients:
        if p.patient_type == "pregnant" and p.pregnant_screenings:
            status = p.pregnant_screenings[-1].overall_status
        elif p.patient_type == "cu2" and p.child_screenings:
            status = p.child_screenings[-1].overall_status
        else:
            status = "not_screened"
        result.append({
            "id": p.id,
            "name": p.name,
            "patient_type": p.patient_type,
            "overall_status": status,
        })
    return result


# ---------------------------------------------------------------------------
# Screening submission
# ---------------------------------------------------------------------------

@app.post("/api/screen/pregnant")
async def screen_pregnant(request: Request, db: Session = Depends(get_db)):
    """Submit pregnant screening and return result with education message."""
    body = await request.json()
    kader_id = body.get("kader_id")
    patient_name = body.get("patient_name", "").strip()
    patient_id = body.get("patient_id")
    mother_age = body.get("mother_age")
    months_pregnant = body.get("months_pregnant")
    muac_cm = body.get("muac_cm")
    systolic_bp = body.get("systolic_bp")
    diastolic_bp = body.get("diastolic_bp")
    bp_skipped = body.get("bp_skipped", False)
    anemia_symptoms = body.get("anemia_symptoms")
    hb_gdl = body.get("hb_gdl")

    chw = db.query(HealthWorker).filter_by(id=kader_id).first()
    if not chw:
        raise HTTPException(404, "Kader tidak ditemukan")

    if patient_id:
        patient = db.query(Patient).filter_by(id=patient_id).first()
        if not patient:
            raise HTTPException(404, "Pasien tidak ditemukan")
    else:
        if not patient_name:
            raise HTTPException(400, "Nama pasien diperlukan")
        patient = Patient(chw_id=kader_id, name=patient_name, patient_type="pregnant")
        db.add(patient)
        db.commit()
        db.refresh(patient)

    muac_res = sc.screen_muac(float(muac_cm))
    anemia_res = sc.screen_anemia(
        hb_gdl=float(hb_gdl) if hb_gdl else None,
        has_symptoms=anemia_symptoms,
    )
    bp_res = None
    if not bp_skipped and systolic_bp and diastolic_bp:
        bp_res = sc.screen_hypertension(int(systolic_bp), int(diastolic_bp))

    classification = sc.classify_pregnant(muac_res, anemia_res, bp_res)
    weeks = int(months_pregnant) * 4 if months_pregnant else None

    education_msg = generate_education_message(
        patient_type="pregnant",
        patient_name=patient.name,
        results={
            "muac_cm": muac_cm,
            "muac_status": muac_res.status,
            "muac_label": muac_res.label,
            "anemia_status": anemia_res.status,
            "anemia_label": anemia_res.label,
            "hb_gdl": hb_gdl,
            "anemia_symptoms": anemia_symptoms,
            "weeks_pregnant": weeks,
            "months_pregnant": months_pregnant,
            "systolic_bp": systolic_bp,
            "diastolic_bp": diastolic_bp,
            "bp_status": bp_res.status if bp_res else "skipped",
            "bp_label": bp_res.label if bp_res else "Tidak diukur",
            "needs_referral": classification["needs_referral"],
        },
    )

    record = PregnantScreening(
        patient_id=patient.id,
        mother_age=int(mother_age) if mother_age else None,
        weeks_pregnant=weeks,
        muac_cm=float(muac_cm),
        hb_gdl=float(hb_gdl) if hb_gdl else None,
        anemia_symptoms=anemia_symptoms,
        systolic_bp=int(systolic_bp) if (systolic_bp and not bp_skipped) else None,
        diastolic_bp=int(diastolic_bp) if (diastolic_bp and not bp_skipped) else None,
        muac_status=classification["muac_status"],
        anemia_status=classification["anemia_status"],
        bp_status=classification.get("bp_status", "skipped"),
        overall_status=classification["overall_status"],
        needs_referral=classification["needs_referral"],
        education_message=education_msg,
    )
    db.add(record)
    db.commit()

    return {
        "patient_id": patient.id,
        "patient_name": patient.name,
        "overall_status": classification["overall_status"],
        "needs_referral": classification["needs_referral"],
        "muac_cm": muac_cm,
        "muac_status": muac_res.status,
        "muac_label": muac_res.label,
        "anemia_status": anemia_res.status,
        "anemia_label": anemia_res.label,
        "bp_status": bp_res.status if bp_res else "skipped",
        "bp_label": bp_res.label if bp_res else "Tidak diukur",
        "education_message": education_msg,
    }


@app.post("/api/screen/child")
async def screen_child(request: Request, db: Session = Depends(get_db)):
    """Submit child under 2 screening and return result with education message."""
    body = await request.json()
    kader_id = body.get("kader_id")
    patient_name = body.get("patient_name", "").strip()
    patient_id = body.get("patient_id")
    age_months = body.get("age_months")
    sex = body.get("sex")
    weight_kg = body.get("weight_kg")
    height_cm = body.get("height_cm")

    chw = db.query(HealthWorker).filter_by(id=kader_id).first()
    if not chw:
        raise HTTPException(404, "Kader tidak ditemukan")

    if patient_id:
        patient = db.query(Patient).filter_by(id=patient_id).first()
        if not patient:
            raise HTTPException(404, "Pasien tidak ditemukan")
    else:
        if not patient_name:
            raise HTTPException(400, "Nama pasien diperlukan")
        patient = Patient(chw_id=kader_id, name=patient_name, patient_type="cu2")
        db.add(patient)
        db.commit()
        db.refresh(patient)

    age = int(age_months)
    weight = float(weight_kg)
    height = float(height_cm)

    waz = sc.calculate_waz(age, sex, weight)
    haz = sc.calculate_haz(age, sex, height)
    waz_res = sc.classify_waz(waz) if waz is not None else sc.ScreeningResult("unknown", "Tidak dapat dihitung", False)
    haz_res = sc.classify_haz(haz) if haz is not None else sc.ScreeningResult("unknown", "Tidak dapat dihitung", False)
    classification = sc.classify_child(waz_res, haz_res)

    education_msg = generate_education_message(
        patient_type="cu2",
        patient_name=patient.name,
        results={
            "age_months": age,
            "sex": sex,
            "weight_kg": weight,
            "height_cm": height,
            "waz": waz,
            "haz": haz,
            "weight_status": waz_res.status,
            "weight_label": waz_res.label,
            "height_status": haz_res.status,
            "height_label": haz_res.label,
            "needs_referral": classification["needs_referral"],
        },
    )

    record = ChildScreening(
        patient_id=patient.id,
        age_months=age,
        sex=sex,
        weight_kg=weight,
        height_cm=height,
        waz=waz,
        haz=haz,
        weight_status=classification["weight_status"],
        height_status=classification["height_status"],
        overall_status=classification["overall_status"],
        needs_referral=classification["needs_referral"],
        education_message=education_msg,
    )
    db.add(record)
    db.commit()

    return {
        "patient_id": patient.id,
        "patient_name": patient.name,
        "overall_status": classification["overall_status"],
        "needs_referral": classification["needs_referral"],
        "age_months": age,
        "sex": sex,
        "sex_label": "Laki-laki" if sex == "M" else "Perempuan",
        "weight_kg": weight,
        "height_cm": height,
        "waz": waz,
        "haz": haz,
        "weight_status": waz_res.status,
        "weight_label": waz_res.label,
        "height_status": haz_res.status,
        "height_label": haz_res.label,
        "education_message": education_msg,
    }


# ---------------------------------------------------------------------------
# Dashboard API (supervisor view)
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats(db: Session = Depends(get_db)):
    week_ago = datetime.utcnow() - timedelta(days=7)

    total_chws = db.query(func.count(HealthWorker.id)).scalar()
    total_patients = db.query(func.count(Patient.id)).scalar()
    total_pregnant = db.query(func.count(Patient.id)).filter(Patient.patient_type == "pregnant").scalar()
    total_cu2 = db.query(func.count(Patient.id)).filter(Patient.patient_type == "cu2").scalar()

    screenings_week_p = db.query(func.count(PregnantScreening.id)).filter(
        PregnantScreening.screened_at >= week_ago
    ).scalar()
    screenings_week_c = db.query(func.count(ChildScreening.id)).filter(
        ChildScreening.screened_at >= week_ago
    ).scalar()

    p_status = db.query(PregnantScreening.overall_status, func.count(PregnantScreening.id).label("count")).group_by(PregnantScreening.overall_status).all()
    c_status = db.query(ChildScreening.overall_status, func.count(ChildScreening.id).label("count")).group_by(ChildScreening.overall_status).all()

    pregnant_referred = db.query(func.count(PregnantScreening.id)).filter(PregnantScreening.needs_referral == True).scalar()
    child_referred = db.query(func.count(ChildScreening.id)).filter(ChildScreening.needs_referral == True).scalar()

    muac_breakdown = db.query(PregnantScreening.muac_status, func.count(PregnantScreening.id).label("count")).group_by(PregnantScreening.muac_status).all()
    weight_breakdown = db.query(ChildScreening.weight_status, func.count(ChildScreening.id).label("count")).group_by(ChildScreening.weight_status).all()
    height_breakdown = db.query(ChildScreening.height_status, func.count(ChildScreening.id).label("count")).group_by(ChildScreening.height_status).all()

    monthly_trend = []
    for i in range(5, -1, -1):
        start = datetime.utcnow() - timedelta(days=(i + 1) * 30)
        end = datetime.utcnow() - timedelta(days=i * 30)
        p_count = db.query(func.count(PregnantScreening.id)).filter(PregnantScreening.screened_at.between(start, end)).scalar()
        c_count = db.query(func.count(ChildScreening.id)).filter(ChildScreening.screened_at.between(start, end)).scalar()
        month_label = (datetime.utcnow() - timedelta(days=i * 30)).strftime("%b")
        monthly_trend.append({"month": month_label, "pregnant": p_count, "children": c_count})

    return {
        "summary": {
            "total_chws": total_chws,
            "total_patients": total_patients,
            "total_pregnant": total_pregnant,
            "total_cu2": total_cu2,
            "screenings_this_week": screenings_week_p + screenings_week_c,
            "total_referred": pregnant_referred + child_referred,
        },
        "pregnant_status": {row.overall_status: row.count for row in p_status},
        "child_status": {row.overall_status: row.count for row in c_status},
        "muac_breakdown": {row.muac_status: row.count for row in muac_breakdown},
        "weight_breakdown": {row.weight_status: row.count for row in weight_breakdown},
        "height_breakdown": {row.height_status: row.count for row in height_breakdown},
        "monthly_trend": monthly_trend,
    }


@app.get("/api/patients")
async def api_patients(
    page: int = 1,
    per_page: int = 20,
    patient_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    district: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Patient)
    if patient_type:
        query = query.filter(Patient.patient_type == patient_type)
    if search:
        query = query.filter(Patient.name.ilike(f"%{search}%"))
    if district:
        chw_ids = db.query(HealthWorker.id).filter(HealthWorker.district.ilike(f"%{district}%")).subquery()
        query = query.filter(Patient.chw_id.in_(chw_ids))

    total = query.count()
    patients = query.order_by(Patient.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for p in patients:
        chw = db.query(HealthWorker).filter_by(id=p.chw_id).first()
        if p.patient_type == "pregnant" and p.pregnant_screenings:
            latest = p.pregnant_screenings[-1]
            screening_data = {
                "muac_cm": latest.muac_cm,
                "muac_status": latest.muac_status,
                "anemia_status": latest.anemia_status,
                "overall_status": latest.overall_status,
                "needs_referral": latest.needs_referral,
                "screened_at": latest.screened_at.isoformat(),
            }
        elif p.patient_type == "cu2" and p.child_screenings:
            latest = p.child_screenings[-1]
            screening_data = {
                "waz": latest.waz,
                "haz": latest.haz,
                "weight_status": latest.weight_status,
                "height_status": latest.height_status,
                "overall_status": latest.overall_status,
                "needs_referral": latest.needs_referral,
                "screened_at": latest.screened_at.isoformat(),
            }
        else:
            screening_data = {"overall_status": "not_screened", "needs_referral": False}

        if status and screening_data.get("overall_status") != status:
            continue

        result.append({
            "id": p.id,
            "name": p.name,
            "patient_type": p.patient_type,
            "chw": {"name": chw.name if chw else "Unknown", "village": chw.village if chw else None, "district": chw.district if chw else None},
            "created_at": p.created_at.isoformat(),
            "screening": screening_data,
        })

    return {"patients": result, "total": total, "page": page, "per_page": per_page}


@app.get("/api/patient/{patient_id}")
async def api_patient_detail(patient_id: int, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter_by(id=patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    chw = db.query(HealthWorker).filter_by(id=patient.chw_id).first()
    screenings = []

    if patient.patient_type == "pregnant":
        for s in patient.pregnant_screenings:
            screenings.append({
                "type": "pregnant",
                "weeks_pregnant": s.weeks_pregnant,
                "mother_age": s.mother_age,
                "muac_cm": s.muac_cm,
                "hb_gdl": s.hb_gdl,
                "muac_status": s.muac_status,
                "anemia_status": s.anemia_status,
                "systolic_bp": getattr(s, "systolic_bp", None),
                "diastolic_bp": getattr(s, "diastolic_bp", None),
                "bp_status": getattr(s, "bp_status", None),
                "overall_status": s.overall_status,
                "needs_referral": s.needs_referral,
                "education_message": s.education_message,
                "referral_message": s.referral_message,
                "screened_at": s.screened_at.isoformat(),
            })
    else:
        for s in patient.child_screenings:
            screenings.append({
                "type": "cu2",
                "age_months": s.age_months,
                "sex": s.sex,
                "weight_kg": s.weight_kg,
                "height_cm": s.height_cm,
                "waz": s.waz,
                "haz": s.haz,
                "weight_status": s.weight_status,
                "height_status": s.height_status,
                "overall_status": s.overall_status,
                "needs_referral": s.needs_referral,
                "education_message": s.education_message,
                "referral_message": s.referral_message,
                "screened_at": s.screened_at.isoformat(),
            })

    return {
        "id": patient.id,
        "name": patient.name,
        "patient_type": patient.patient_type,
        "created_at": patient.created_at.isoformat(),
        "chw": {"name": chw.name if chw else "Unknown", "village": chw.village if chw else None, "district": chw.district if chw else None},
        "screenings": screenings,
    }


@app.get("/api/chws")
async def api_chws(db: Session = Depends(get_db)):
    chws = db.query(HealthWorker).order_by(HealthWorker.district, HealthWorker.village).all()
    return [{
        "id": c.id, "name": c.name, "village": c.village, "district": c.district,
        "patient_count": len(c.patients), "created_at": c.created_at.isoformat(),
    } for c in chws]


@app.get("/api/districts")
async def api_districts(db: Session = Depends(get_db)):
    rows = db.query(HealthWorker.district).filter(HealthWorker.district.isnot(None)).distinct().order_by(HealthWorker.district).all()
    return [r[0] for r in rows if r[0]]


@app.get("/api/who-reference")
async def who_reference(sex: str = "M"):
    import math
    from screening import WAZ_BOYS, WAZ_GIRLS, HAZ_BOYS, HAZ_GIRLS

    waz_table = WAZ_BOYS if sex == "M" else WAZ_GIRLS
    haz_table = HAZ_BOYS if sex == "M" else HAZ_GIRLS

    def x_at_z(L, M, S, z):
        try:
            return round(M * math.pow(1 + L * S * z, 1 / L), 2)
        except Exception:
            return None

    ages = list(range(0, 25))
    weight = {"ages": ages, "median": [], "minus1": [], "minus2": [], "minus3": []}
    height = {"ages": ages, "median": [], "minus1": [], "minus2": [], "minus3": []}

    for age in ages:
        L, M, S = waz_table[age]
        weight["median"].append(round(M, 2))
        weight["minus1"].append(x_at_z(L, M, S, -1))
        weight["minus2"].append(x_at_z(L, M, S, -2))
        weight["minus3"].append(x_at_z(L, M, S, -3))

        Lh, Mh, Sh = haz_table[age]
        height["median"].append(round(Mh, 2))
        height["minus1"].append(x_at_z(Lh, Mh, Sh, -1))
        height["minus2"].append(x_at_z(Lh, Mh, Sh, -2))
        height["minus3"].append(x_at_z(Lh, Mh, Sh, -3))

    return {"sex": sex, "weight": weight, "height": height}


@app.post("/api/patient/{patient_id}/qa")
async def patient_qa(patient_id: int, request: Request, db: Session = Depends(get_db)):
    from claude_ai import generate_qa_answer
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"answer": "Pertanyaan tidak boleh kosong."}, status_code=400)

    patient = db.query(Patient).filter_by(id=patient_id).first()
    if not patient:
        return JSONResponse({"answer": "Pasien tidak ditemukan."}, status_code=404)

    answer = generate_qa_answer(question, patient.patient_type, patient.name)
    return {"answer": answer}
