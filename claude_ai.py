"""
Claude AI integration for generating education and referral messages.
Messages are written in simple language suitable for CHWs to read aloud
to rural mothers who may have low literacy.
"""
import os
import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """Kamu adalah asisten edukasi kesehatan yang membantu Kader Posyandu
berkomunikasi dengan ibu-ibu di desa tentang kesehatan ibu dan anak.

Tugasmu menulis pesan edukasi singkat dan jelas berdasarkan panduan Kemenkes RI, dengan ketentuan:
1. Gunakan bahasa Indonesia yang sangat sederhana (bayangkan menjelaskan kepada ibu rumah tangga di desa)
2. Bersikap hangat, mendukung, dan menyemangati — JANGAN menyalahkan atau mempermalukan ibu
3. Fokus pada 2–3 tindakan praktis yang bisa dilakukan ibu mulai HARI INI
4. Sertakan tanda bahaya yang harus diwaspadai
5. Tulis dalam 3–5 kalimat pendek atau poin-poin singkat
6. Hindari istilah medis — gunakan bahasa sehari-hari yang mudah dipahami

Panduan Kemenkes yang harus dirujuk:
- Ibu hamil: minum TTD (Tablet Tambah Darah) setiap hari selama kehamilan
- Ibu hamil: makan sesuai Isi Piringku — nasi, lauk protein hewani (telur, ayam, ikan, daging), sayuran, buah
- Ibu hamil KEK: makan lebih banyak, khususnya protein hewani setiap hari
- Ibu hamil hipertensi: hindari makanan asin, makanan manis, dan minuman manis; istirahat cukup
- Bayi 0–6 bulan: ASI Eksklusif saja, tidak perlu makanan/minuman lain
- Bayi 6–24 bulan: MP-ASI kaya protein hewani (telur, ayam, ikan, daging) sesuai usia
- Tanda bahaya bayi: demam, diare, tubuh dingin, kejang, kulit/mata kuning — segera ke Puskesmas
- Tanda bahaya ibu hamil: perdarahan, sakit kepala hebat, tangan/muka bengkak, bayi tidak bergerak

Jika perlu dirujuk: sampaikan dengan tenang tapi tegas bahwa ini penting dan mendesak.
Selalu ingatkan kader untuk menyemangati ibu dengan penuh kasih sayang."""


def _build_pregnant_prompt(patient_name: str, results: dict) -> str:
    weeks = results.get("weeks_pregnant", "?")
    months = results.get("months_pregnant") or (round(weeks / 4) if isinstance(weeks, int) else "?")
    trimester = "1" if isinstance(weeks, int) and weeks <= 13 else ("2" if isinstance(weeks, int) and weeks <= 26 else "3")
    muac = results.get("muac_cm")
    muac_status = results.get("muac_status", "unknown")
    anemia_status = results.get("anemia_status", "unknown")
    bp_status = results.get("bp_status", "skipped")
    bp_label = results.get("bp_label", "Tidak diukur")
    hb = results.get("hb_gdl")
    needs_referral = results.get("needs_referral", False)

    lines = [
        f"Pasien: {patient_name} (ibu hamil, bulan ke-{months} / trimester {trimester})",
        f"LiLA/MUAC: {muac} cm → {muac_status}",
    ]
    if hb:
        lines.append(f"Hemoglobin: {hb} g/dL → {anemia_status}")
    else:
        lines.append(f"Tanda anemia: {'Ada' if results.get('anemia_symptoms') else 'Tidak ada'} → {anemia_status}")
    lines.append(f"Tekanan darah: {bp_label} → {bp_status}")
    lines.append(f"Perlu dirujuk: {'YA — SEGERA' if needs_referral else 'Tidak'}")

    prompt = "\n".join(lines)
    prompt += (
        "\n\nBalas dengan FORMAT PERSIS seperti ini:\n\n"
        "📚 *Anjuran untuk Ibu:*\n"
        "• [Anjuran 1 paling relevan dengan kondisi di atas]\n"
        "• [Anjuran 2 paling relevan dengan kondisi di atas]\n"
        "[Jika perlu dirujuk: tambahkan 1 kalimat tegas bahwa harus ke Puskesmas sekarang]\n"
        "[1 kalimat penyemangat]\n\n"
        "ATURAN KETAT:\n"
        "- HANYA 2 poin anjuran, disesuaikan dengan masalah utama yang ditemukan\n"
        "- JANGAN tulis tanda bahaya\n"
        "- Bahasa sederhana, hangat, maksimal 60 kata total"
    )
    return prompt


def _build_child_prompt(patient_name: str, results: dict) -> str:
    age = results.get("age_months", "?")
    sex_label = "laki-laki" if results.get("sex") == "M" else "perempuan"
    weight = results.get("weight_kg")
    height = results.get("height_cm")
    waz = results.get("waz")
    haz = results.get("haz")
    weight_status = results.get("weight_status", "unknown")
    height_status = results.get("height_status", "unknown")
    needs_referral = results.get("needs_referral", False)

    # Determine feeding stage
    if isinstance(age, int) and age < 6:
        feeding_stage = "ASI Eksklusif (0-5 bulan)"
    else:
        feeding_stage = "MP-ASI + ASI (6-24 bulan)"

    lines = [
        f"Pasien: {patient_name} (anak {sex_label}, {age} bulan)",
        f"Tahap makan: {feeding_stage}",
        f"Berat badan: {weight} kg (Z-skor: {waz}) → {weight_status}",
        f"Tinggi badan: {height} cm (Z-skor: {haz}) → {height_status}",
        f"Perlu dirujuk: {'YA — SEGERA' if needs_referral else 'Tidak'}",
    ]
    prompt = "\n".join(lines)
    prompt += (
        "\n\nBalas dengan FORMAT PERSIS seperti ini:\n\n"
        "📚 *Anjuran untuk Ibu:*\n"
        "• [Anjuran 1 paling relevan dengan kondisi anak di atas]\n"
        "• [Anjuran 2 paling relevan dengan kondisi anak di atas]\n"
        "[Jika perlu dirujuk: tambahkan 1 kalimat tegas bahwa harus ke Puskesmas sekarang]\n"
        "[1 kalimat penyemangat]\n\n"
        "ATURAN KETAT:\n"
        "- HANYA 2 poin anjuran, disesuaikan dengan masalah utama yang ditemukan\n"
        "- JANGAN tulis tanda bahaya\n"
        "- Bahasa sederhana, hangat, maksimal 60 kata total"
    )
    return prompt


# ---------------------------------------------------------------------------
# Fallback messages (used if Claude API is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_PREGNANT = {
    "normal": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Makan sesuai Isi Piringku: nasi, protein hewani (telur/ikan/ayam), sayur, buah\n"
        "• Minum TTD (Tablet Tambah Darah) setiap hari, jangan dilewatkan\n\n"
        "Semangat ya Bu, ibu dan bayi sehat! 💪"
    ),
    "at_risk": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Makan LEBIH BANYAK — terutama protein hewani: telur, ikan, ayam, daging setiap hari\n"
        "• Minum TTD setiap hari dan periksa ke Puskesmas minggu depan\n\n"
        "Ibu pasti bisa! Kami selalu siap membantu. 🌟"
    ),
    "referred": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Tetap makan dan minum yang cukup, minum TTD hari ini\n"
        "• Segera ke Puskesmas hari ini — minta keluarga menemani\n\n"
        "Ini penting, jangan ditunda ya Bu. Kami peduli dengan kesehatan ibu dan bayi. 🙏"
    ),
}

FALLBACK_CHILD = {
    "normal": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Teruskan ASI Eksklusif (< 6 bulan) atau MP-ASI kaya protein hewani 3–5x sehari (≥ 6 bulan)\n"
        "• Rutin timbang di Posyandu setiap bulan\n\n"
        "Hebat ya Bu, {name} tumbuh sehat! 🌱"
    ),
    "at_risk": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Berikan makan LEBIH SERING — minimal 5x sehari dengan protein hewani (telur/ikan/ayam)\n"
        "• Kembali timbang di Posyandu 4 minggu lagi\n\n"
        "Semangat Bu, {name} butuh dukungan ibu! 💚"
    ),
    "referred": (
        "📚 *Anjuran untuk Ibu:*\n"
        "• Tetap berikan ASI atau makanan sesering mungkin\n"
        "• Segera bawa {name} ke Puskesmas hari ini — minta keluarga menemani\n\n"
        "Ibu sudah melakukan langkah yang tepat. Ayo segera ke Puskesmas. 🙏"
    ),
}


QA_SYSTEM_PROMPT = """Kamu adalah asisten kesehatan untuk Kader Posyandu di Indonesia.
Kamu menjawab pertanyaan seputar kesehatan ibu hamil dan anak bawah 2 tahun
berdasarkan kurikulum dan modul resmi Kemenkes RI tentang pencegahan stunting dan BBLR.

Pengetahuan yang kamu pegang (dari modul Kemenkes):

IBU HAMIL:
- KEK (Kekurangan Energi Kronis): LiLA < 23.5 cm → perlu makan lebih banyak, protein hewani setiap hari
- Hipertensi kehamilan: tekanan darah ≥ 140/90 mmHg → rujuk Puskesmas, hindari asin dan manis
- Anemia: Hb rendah / tanda pucat, lemas, pusing → minum TTD (Tablet Tambah Darah) setiap hari
- TTD: diminum setiap hari selama hamil, sebaiknya malam hari, bisa dengan air jeruk (vitamin C)
- Gizi: Isi Piringku = nasi/umbi, lauk protein hewani (telur/ikan/ayam/daging), sayuran, buah
- Suplemen kalsium juga dianjurkan selama kehamilan
- Hindari makanan asin (jika hipertensi), hindari makanan/minuman manis berlebihan
- Pantau kenaikan berat badan dan LiLA tiap kunjungan di Buku KIA
- Tanda bahaya ibu hamil: perdarahan, sakit kepala hebat, tangan/muka bengkak, pandangan kabur, bayi tidak bergerak → SEGERA ke Puskesmas
- Kunjungan ANC minimal 6 kali selama kehamilan
- Prioritas kunjungan rumah: ibu hamil trimester 1 dengan KEK atau hipertensi

BAYI DAN ANAK BAWAH 2 TAHUN:
- 0–6 bulan: ASI Eksklusif SAJA — tidak perlu air putih, madu, atau makanan lain
- 6–24 bulan: MP-ASI kaya protein hewani (telur, ayam, ikan, daging) + terus ASI
- Porsi MP-ASI: mulai 2-3 sdm, bertambah sesuai usia; frekuensi 3-5x sehari
- Tekstur: dimulai dari halus/lumat, berangsur kasar sesuai usia
- Stunting: tinggi badan < -2 SD untuk usia → deteksi dini lewat pengukuran rutin
- Perlambatan pertumbuhan (growth faltering): berat tidak naik sesuai KBM → perbaiki pola makan
- Pantau berat badan SETIAP BULAN di Posyandu dan catat di Buku KIA / KMS
- Tanda bahaya bayi: demam, diare, tubuh dingin, kejang, kulit/mata kuning (ikterus) → SEGERA ke Puskesmas
- Imunisasi dasar lengkap sesuai usia (jadwal di Buku KIA)

PERAN KADER:
- Pengukuran: timbang berat badan, ukur panjang/tinggi badan, ukur LiLA, ukur tekanan darah
- Catat di formulir kunjungan rumah dan Buku KIA
- Lakukan kunjungan rumah untuk kasus berisiko
- Rujuk ke Puskesmas jika ada tanda bahaya atau kondisi berat

Cara menjawab:
1. Gunakan Bahasa Indonesia yang sederhana dan hangat
2. Jawaban singkat dan praktis (3-5 kalimat atau poin pendek)
3. Jika di luar topik kesehatan ibu/anak, minta maaf dan arahkan kembali ke topik
4. Jangan memberikan diagnosis atau saran medis yang melampaui peran kader
5. Jika ada tanda bahaya, selalu anjurkan rujuk ke Puskesmas"""


def generate_qa_answer(question: str, patient_type: str, patient_name: str) -> str:
    """
    Answer a follow-up health question from a CHW, grounded in Kemenkes curriculum.
    Falls back to a helpful redirect message if API is unavailable.
    """
    context = f"Konteks: kader baru selesai skrining {patient_type} bernama {patient_name}."
    user_prompt = f"{context}\n\nPertanyaan kader: {question}"
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=QA_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        import traceback
        print(f"[QA ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return (
            "Maaf, saat ini tidak bisa menjawab. "
            "Silakan hubungi bidan atau petugas Puskesmas untuk informasi lebih lanjut."
        )


def generate_education_message(patient_type: str, patient_name: str,
                                results: dict) -> str:
    """
    Generate an education message using Claude API.
    Falls back to a static template if API is unavailable.
    """
    try:
        client = _get_client()
        if patient_type == "pregnant":
            user_prompt = _build_pregnant_prompt(patient_name, results)
        else:
            user_prompt = _build_child_prompt(patient_name, results)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()

    except Exception as e:
        import traceback
        print(f"[EDUCATION ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        # Graceful fallback to static messages
        overall = results.get("needs_referral")
        if overall:
            status_key = "referred"
        elif results.get("muac_status") in ("mam",) or results.get("anemia_status") == "moderate" \
                or results.get("weight_status") == "underweight" or results.get("height_status") == "stunted":
            status_key = "at_risk"
        else:
            status_key = "normal"

        templates = FALLBACK_PREGNANT if patient_type == "pregnant" else FALLBACK_CHILD
        return templates[status_key].format(name=patient_name)
