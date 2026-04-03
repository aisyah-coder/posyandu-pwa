"""
WHO-based screening algorithms for:
  - Pregnant mothers: MUAC (chronic malnutrition) + Hemoglobin (anemia)
  - Children Under 2 (CU2): Weight-for-Age Z-score + Height-for-Age Z-score

Reference: WHO Child Growth Standards (2006), WHO Anthro
"""
import math
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# WHO LMS reference tables (L, M, S) for Z-score calculation
# Age 0-24 months, by sex
# Source: WHO Child Growth Standards 2006
# ---------------------------------------------------------------------------

# Weight-for-Age  (boys)
WAZ_BOYS = {
    0:  (-0.3521, 3.3464, 0.14602),  1:  (-0.3521, 4.4709, 0.13395),
    2:  (-0.3521, 5.5675, 0.12385),  3:  (-0.3521, 6.3762, 0.11727),
    4:  (-0.3521, 7.0023, 0.11316),  5:  (-0.3521, 7.5105, 0.10953),
    6:  (-0.3521, 7.9340, 0.10628),  7:  (-0.3521, 8.2970, 0.10368),
    8:  (-0.3521, 8.6151, 0.10138),  9:  (-0.3521, 8.9014, 0.09945),
    10: (-0.3521, 9.1649, 0.09785),  11: (-0.3521, 9.4122, 0.09649),
    12: (-0.3521, 9.6479, 0.09533),  13: (-0.3521, 9.8749, 0.09434),
    14: (-0.3521,10.0953, 0.09348),  15: (-0.3521,10.3108, 0.09275),
    16: (-0.3521,10.5228, 0.09214),  17: (-0.3521,10.7319, 0.09165),
    18: (-0.3521,10.9385, 0.09124),  19: (-0.3521,11.1430, 0.09090),
    20: (-0.3521,11.3462, 0.09063),  21: (-0.3521,11.5486, 0.09042),
    22: (-0.3521,11.7504, 0.09026),  23: (-0.3521,11.9514, 0.09014),
    24: (-0.3521,12.1515, 0.09005),
}

# Weight-for-Age  (girls)
WAZ_GIRLS = {
    0:  (-0.3833, 3.2322, 0.14171),  1:  (-0.3833, 4.1873, 0.13724),
    2:  (-0.3833, 5.1282, 0.13000),  3:  (-0.3833, 5.8458, 0.12619),
    4:  (-0.3833, 6.4232, 0.12402),  5:  (-0.3833, 6.8745, 0.12274),
    6:  (-0.3833, 7.2676, 0.12204),  7:  (-0.3833, 7.6422, 0.12178),
    8:  (-0.3833, 8.0048, 0.12181),  9:  (-0.3833, 8.3577, 0.12202),
    10: (-0.3833, 8.7017, 0.12232),  11: (-0.3833, 9.0370, 0.12264),
    12: (-0.3833, 9.3636, 0.12294),  13: (-0.3833, 9.6816, 0.12321),
    14: (-0.3833, 9.9919, 0.12342),  15: (-0.3833,10.2948, 0.12358),
    16: (-0.3833,10.5908, 0.12367),  17: (-0.3833,10.8802, 0.12369),
    18: (-0.3833,11.1632, 0.12366),  19: (-0.3833,11.4395, 0.12357),
    20: (-0.3833,11.7088, 0.12344),  21: (-0.3833,11.9711, 0.12328),
    22: (-0.3833,12.2264, 0.12308),  23: (-0.3833,12.4746, 0.12286),
    24: (-0.3833,12.7162, 0.12261),
}

# Height-for-Age  (boys)
HAZ_BOYS = {
    0:  (1, 49.8842, 0.03795),  1:  (1, 54.7244, 0.03557),
    2:  (1, 58.4249, 0.03424),  3:  (1, 61.4292, 0.03328),
    4:  (1, 63.8860, 0.03257),  5:  (1, 65.9026, 0.03204),
    6:  (1, 67.6236, 0.03165),  7:  (1, 69.1645, 0.03139),
    8:  (1, 70.5994, 0.03124),  9:  (1, 71.9687, 0.03117),
    10: (1, 73.2812, 0.03117),  11: (1, 74.5388, 0.03122),
    12: (1, 75.7488, 0.03131),  13: (1, 76.9186, 0.03143),
    14: (1, 78.0497, 0.03157),  15: (1, 79.1458, 0.03172),
    16: (1, 80.2113, 0.03189),  17: (1, 81.2487, 0.03206),
    18: (1, 82.2587, 0.03223),  19: (1, 83.2418, 0.03240),
    20: (1, 84.1996, 0.03257),  21: (1, 85.1348, 0.03273),
    22: (1, 86.0477, 0.03289),  23: (1, 86.9401, 0.03305),
    24: (1, 87.8161, 0.03320),
}

# Height-for-Age  (girls)
HAZ_GIRLS = {
    0:  (1, 49.1477, 0.03790),  1:  (1, 53.6872, 0.03625),
    2:  (1, 57.0673, 0.03490),  3:  (1, 59.8029, 0.03408),
    4:  (1, 62.0899, 0.03347),  5:  (1, 64.0301, 0.03296),
    6:  (1, 65.7311, 0.03257),  7:  (1, 67.2873, 0.03226),
    8:  (1, 68.7498, 0.03204),  9:  (1, 70.1435, 0.03188),
    10: (1, 71.4818, 0.03178),  11: (1, 72.7710, 0.03172),
    12: (1, 74.0150, 0.03168),  13: (1, 75.2176, 0.03166),
    14: (1, 76.3817, 0.03165),  15: (1, 77.5099, 0.03165),
    16: (1, 78.6055, 0.03165),  17: (1, 79.6712, 0.03165),
    18: (1, 80.7079, 0.03165),  19: (1, 81.7182, 0.03165),
    20: (1, 82.7036, 0.03166),  21: (1, 83.6654, 0.03166),
    22: (1, 84.6046, 0.03166),  23: (1, 85.5228, 0.03167),
    24: (1, 86.4212, 0.03167),
}


def _lms_zscore(value: float, L: float, M: float, S: float) -> float:
    """Calculate Z-score using the WHO LMS method."""
    if L == 0:
        return math.log(value / M) / S
    return ((value / M) ** L - 1) / (L * S)


def _clamp_zscore(z: float) -> float:
    """WHO recommends capping Z-scores at ±6 for plausibility."""
    return max(-6.0, min(6.0, z))


@dataclass
class ScreeningResult:
    status: str          # "normal" | "mam" | "sam" | "moderate" | "severe"
    label: str           # Human-readable label
    needs_referral: bool
    z_score: Optional[float] = None
    value: Optional[float] = None


# ---------------------------------------------------------------------------
# Pregnant Mother Screening
# ---------------------------------------------------------------------------

def screen_muac(muac_cm: float) -> ScreeningResult:
    """
    Screen pregnant mother MUAC for chronic malnutrition.
    Cutoffs (Kemenkes Indonesia):
      >= 23.5 cm → Normal
      21–23.4 cm → KEK (Kekurangan Energi Kronis / Moderate)
      < 21 cm    → KEK Berat (Severe) → REFER
    Reference: Pedoman Penanganan KEK pada Ibu Hamil, Kemenkes RI
    """
    if muac_cm >= 23.5:
        return ScreeningResult(
            status="normal",
            label="Gizi normal (LiLA cukup)",
            needs_referral=False,
            value=muac_cm,
        )
    elif muac_cm >= 21.0:
        return ScreeningResult(
            status="kek",
            label="KEK (Kekurangan Energi Kronis)",
            needs_referral=False,
            value=muac_cm,
        )
    else:
        return ScreeningResult(
            status="kek_berat",
            label="KEK Berat — RUJUK ke Puskesmas",
            needs_referral=True,
            value=muac_cm,
        )


def screen_anemia(hb_gdl: Optional[float] = None,
                  has_symptoms: Optional[bool] = None) -> ScreeningResult:
    """
    Screen for anemia.
    If Hb available:
      >= 11 g/dL → Normal
      7–10.9 g/dL → Moderate anemia
      < 7 g/dL  → Severe anemia → REFER
    If only symptoms reported (pale palms/eyelids, dizziness, extreme fatigue):
      symptoms present → at risk (treat as moderate)
    """
    if hb_gdl is not None:
        if hb_gdl >= 11.0:
            return ScreeningResult(
                status="normal", label="No anemia", needs_referral=False, value=hb_gdl
            )
        elif hb_gdl >= 7.0:
            return ScreeningResult(
                status="moderate", label="Moderate anemia", needs_referral=False, value=hb_gdl
            )
        else:
            return ScreeningResult(
                status="severe", label="Severe anemia — REFER", needs_referral=True, value=hb_gdl
            )
    elif has_symptoms is True:
        return ScreeningResult(
            status="moderate",
            label="Possible anemia (symptoms present)",
            needs_referral=False,
        )
    else:
        return ScreeningResult(
            status="normal", label="No anemia signs reported", needs_referral=False
        )


def screen_hypertension(systolic: int, diastolic: int) -> ScreeningResult:
    """
    Screen pregnant mother blood pressure for hypertension.
    Cutoffs (Kemenkes Indonesia / JNC-8):
      systolic >= 140 OR diastolic >= 90 → Hipertensi → REFER
    Reference: Pedoman Tatalaksana Hipertensi pada Kehamilan, Kemenkes RI
    """
    if systolic >= 140 or diastolic >= 90:
        return ScreeningResult(
            status="hypertension",
            label=f"Hipertensi ({systolic}/{diastolic} mmHg) — RUJUK ke Puskesmas",
            needs_referral=True,
            value=systolic,
        )
    return ScreeningResult(
        status="normal",
        label=f"Tekanan darah normal ({systolic}/{diastolic} mmHg)",
        needs_referral=False,
        value=systolic,
    )


def classify_pregnant(muac_result: ScreeningResult,
                       anemia_result: ScreeningResult,
                       bp_result: Optional[ScreeningResult] = None) -> dict:
    """Combine MUAC + anemia + blood pressure into overall status and referral decision."""
    needs_referral = muac_result.needs_referral or anemia_result.needs_referral
    if bp_result:
        needs_referral = needs_referral or bp_result.needs_referral

    if needs_referral:
        overall = "referred"
    elif (muac_result.status in ("kek", "mam", "moderate")
          or anemia_result.status == "moderate"
          or (bp_result and bp_result.status not in ("normal", None))):
        overall = "at_risk"
    else:
        overall = "normal"

    result = {
        "muac_status": muac_result.status,
        "anemia_status": anemia_result.status,
        "overall_status": overall,
        "needs_referral": needs_referral,
    }
    if bp_result:
        result["bp_status"] = bp_result.status
    return result


# ---------------------------------------------------------------------------
# Children Under 2 Screening
# ---------------------------------------------------------------------------

def calculate_waz(age_months: int, sex: str, weight_kg: float) -> Optional[float]:
    """Calculate Weight-for-Age Z-score using WHO LMS tables."""
    age_months = min(max(int(age_months), 0), 24)
    table = WAZ_BOYS if sex.upper() in ("M", "MALE", "BOY") else WAZ_GIRLS
    if age_months not in table:
        return None
    L, M, S = table[age_months]
    z = _lms_zscore(weight_kg, L, M, S)
    return round(_clamp_zscore(z), 2)


def calculate_haz(age_months: int, sex: str, height_cm: float) -> Optional[float]:
    """Calculate Height-for-Age Z-score using WHO LMS tables."""
    age_months = min(max(int(age_months), 0), 24)
    table = HAZ_BOYS if sex.upper() in ("M", "MALE", "BOY") else HAZ_GIRLS
    if age_months not in table:
        return None
    L, M, S = table[age_months]
    z = _lms_zscore(height_cm, L, M, S)
    return round(_clamp_zscore(z), 2)


def classify_waz(waz: float) -> ScreeningResult:
    """
    WHO Weight-for-Age Z-score classification:
      >= -2   → Normal
      -3 to -2 → Underweight (MAM)
      < -3    → Severely Underweight (SAM) → REFER
    """
    if waz >= -2.0:
        return ScreeningResult(
            status="normal", label="Normal weight", needs_referral=False, z_score=waz
        )
    elif waz >= -3.0:
        return ScreeningResult(
            status="underweight", label="Underweight (MAM)", needs_referral=False, z_score=waz
        )
    else:
        return ScreeningResult(
            status="severely_underweight",
            label="Severely Underweight (SAM) — REFER",
            needs_referral=True,
            z_score=waz,
        )


def classify_haz(haz: float) -> ScreeningResult:
    """
    WHO Height-for-Age Z-score classification:
      >= -2   → Normal
      -3 to -2 → Stunted
      < -3    → Severely Stunted → REFER
    """
    if haz >= -2.0:
        return ScreeningResult(
            status="normal", label="Normal height", needs_referral=False, z_score=haz
        )
    elif haz >= -3.0:
        return ScreeningResult(
            status="stunted", label="Stunted growth", needs_referral=False, z_score=haz
        )
    else:
        return ScreeningResult(
            status="severely_stunted",
            label="Severely Stunted — REFER",
            needs_referral=True,
            z_score=haz,
        )


def classify_child(waz_result: ScreeningResult,
                   haz_result: ScreeningResult) -> dict:
    """Combine WAZ + HAZ into overall status and referral decision."""
    needs_referral = waz_result.needs_referral or haz_result.needs_referral

    if needs_referral:
        overall = "referred"
    elif waz_result.status in ("underweight",) or haz_result.status in ("stunted",):
        overall = "at_risk"
    else:
        overall = "normal"

    return {
        "weight_status": waz_result.status,
        "height_status": haz_result.status,
        "overall_status": overall,
        "needs_referral": needs_referral,
        "waz": waz_result.z_score,
        "haz": haz_result.z_score,
    }
