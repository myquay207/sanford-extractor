"""
╔══════════════════════════════════════════════════════════════════╗
║        KHÁNG SINH TOOL — Phiên bản Paste Text                  ║
║  Quy trình: Chụp ảnh → Gemini app → Copy text → Paste vào đây ║
║  Tab 1: Thuốc Sanford Guide  → data-sanford.js                 ║
║  Tab 2: Phác đồ Chợ Rẫy     → data-choray.js                  ║
╚══════════════════════════════════════════════════════════════════╝
pip install streamlit google-generativeai pillow
streamlit run sanford_tool_mobile.py
"""

import streamlit as st
import json, re, time, requests
import google.generativeai as genai

GEMINI_MODEL = "gemini-2.5-flash-lite"

# ══════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════

SANFORD_PROMPT = """Bạn là chuyên gia Dược lâm sàng. Đọc TOÀN BỘ nội dung text dưới đây được trích xuất từ Sanford Guide.
Tổng hợp thành JSON TIẾNG VIỆT theo schema sau. Chỉ trả về JSON thuần, không markdown, không giải thích.

SCHEMA:
{
  "name": "Tên thuốc quốc tế",
  "class": "Nhóm thuốc",
  "spectrum": "Phổ tác dụng",
  "tag": "Chỉ định chính, cách nhau · (chấm giữa)",
  "standard": "Liều chuẩn người lớn",
  "severe": "Liều nặng / ICU",
  "pediatric": "Liều trẻ em (ghi rõ theo tuổi/cân nặng nếu có)",
  "cns_dose": "Liều viêm màng não / nhiễm khuẩn TKTW (nếu không có: '')",
  "hepatic": "Chỉnh liều suy gan",
  "ecmo": "Chỉnh liều ECMO (nếu không có: 'Chưa đủ dữ liệu')",
  "obesity": "Chỉnh liều béo phì",
  "pregnancy": "An toàn thai kỳ — FDA category + diễn giải ngắn",
  "lactation": "An toàn cho con bú",
  "adverse_effects": "Tác dụng không mong muốn chính (dùng dấu • phân cách)",
  "pk": "Dược động học: T1/2, Vd, protein binding, thải trừ",
  "sanford_note": "Lưu ý lâm sàng quan trọng (2–5 câu súc tích)",
  "color": "#e63946",
  "renal": [
    { "label": "Ngưỡng CrCl", "dose": "Liều", "note": "Ghi chú" }
  ]
}

QUY TẮC:
- Giữ nguyên tên thuốc gốc
- Liệt kê ĐẦY ĐỦ các mức CrCl có trong text bao gồm HD, CAPD, CRRT, SLED
- Trường không có thông tin: để chuỗi rỗng ""
- "color" luôn là "#e63946" (sẽ được thay sau)
- Chỉ trả về JSON thuần

NỘI DUNG SANFORD GUIDE:
"""

CHORAY_EMPIRICAL_PROMPT = """Bạn là chuyên gia Dược lâm sàng tại Bệnh viện Chợ Rẫy.
Đọc TOÀN BỘ nội dung text dưới đây trích từ sách Phác Đồ Điều Trị Kháng Sinh Chợ Rẫy — phần phác đồ KINH NGHIỆM.
Trích xuất thành JSON theo schema. Chỉ trả về JSON thuần, không markdown, không giải thích.
Nếu text chứa NHIỀU bệnh cảnh khác nhau → trả về JSON ARRAY [ {...}, {...} ].

SCHEMA (1 phác đồ):
{
  "source": "choray",
  "system": "Hệ cơ quan (vd: Hệ thần kinh trung ương, Hô hấp...)",
  "condition": "Tên bệnh cảnh cụ thể",
  "type": "empirical",
  "color": "#7209b7",
  "groups": [
    {
      "group": "Nhóm bệnh nhân (vd: Người ≤ 50 tuổi, Hậu phẫu TKTW...)",
      "organisms": "Tác nhân tiên lượng",
      "regimens": [
        {
          "rank": 1,
          "label": "Lựa chọn đầu tay",
          "drugs": "Tên thuốc + liều + đường dùng + tần suất đầy đủ",
          "duration": "Thời gian điều trị nếu có, null nếu text không đề cập",
          "note": "Ghi chú lâm sàng quan trọng, null nếu text không đề cập"
        },
        {
          "rank": 2,
          "label": "Lựa chọn thay thế",
          "drugs": "...",
          "duration": null,
          "note": null
        }
      ]
    }
  ]
}

QUY TẮC BẮT BUỘC VỀ FIELD "note" VÀ "duration":
- Đây là 2 field hay bị bỏ sót nhất khi đọc bảng — đọc THẬT KỸ trước khi quyết định.
- Nếu trong text gốc CÓ thông tin ghi chú/thời gian cho mục này → bắt buộc phải lấy ra, dù chỉ là 1 câu ngắn hoặc 1 chú thích chân bảng (ký hiệu *, **, °, hoặc đoạn chữ nghiêng/nhỏ đặt ngay dưới hoặc cuối bảng).
- Nếu trong text gốc thực sự KHÔNG có ghi chú/thời gian cho mục này → bắt buộc dùng giá trị null (không phải chuỗi rỗng "", không phải bỏ qua key).
- TUYỆT ĐỐI KHÔNG được tự tóm tắt rút gọn ghi chú để "cho gọn" — phải lấy đủ ý, kể cả khi dài.
- TUYỆT ĐỐI KHÔNG được suy diễn hay tự viết thêm ghi chú không có trong text gốc.

QUY TẮC CHUNG:
- Trích xuất TẤT CẢ nhóm bệnh nhân và phác đồ, không bỏ sót nhóm nào
- Giữ nguyên liều thuốc chính xác, không làm tròn hay diễn giải lại số liệu
- "color" luôn là "#7209b7"

NỘI DUNG PHÁC ĐỒ:
"""

CHORAY_TARGETED_PROMPT = """Bạn là chuyên gia Dược lâm sàng tại Bệnh viện Chợ Rẫy.
Đọc TOÀN BỘ nội dung text dưới đây trích từ sách Phác Đồ Điều Trị Kháng Sinh Chợ Rẫy — phần điều trị THEO VI KHUẨN.
Trích xuất thành JSON theo schema. Chỉ trả về JSON thuần, không markdown, không giải thích.
Nếu text chứa NHIỀU vi khuẩn → trả về JSON ARRAY [ {...}, {...} ].

SCHEMA (1 vi khuẩn):
{
  "source": "choray",
  "organism": "Tên vi khuẩn",
  "natural_resistance": "Kháng tự nhiên với (nếu có), null nếu text không đề cập",
  "color": "#e63946",
  "sites": [
    {
      "site": "Vị trí nhiễm khuẩn",
      "conditions": "Bệnh cảnh cụ thể",
      "duration": "Thời gian điều trị chung, null nếu text không đề cập",
      "tiers": [
        {
          "tier": "Mức kháng thuốc (Nhạy nhiều nhóm KS / MDR / PDR / XDR)",
          "mic_note": "Ngưỡng MIC nếu có, null nếu text không đề cập",
          "regimens": [
            {
              "rank": 1,
              "label": "Lựa chọn đầu tay",
              "drugs": "Tên thuốc + liều + đường dùng + tần suất đầy đủ",
              "note": "Ghi chú lâm sàng quan trọng, null nếu text không đề cập"
            }
          ]
        }
      ]
    }
  ]
}

QUY TẮC BẮT BUỘC VỀ FIELD "note", "duration", "mic_note", "natural_resistance":
- Đây là các field hay bị bỏ sót nhất khi đọc bảng — đọc THẬT KỸ trước khi quyết định.
- Nếu trong text gốc CÓ thông tin cho field này → bắt buộc phải lấy ra, dù chỉ là 1 câu ngắn hoặc 1 chú thích chân bảng (ký hiệu *, **, °, hoặc đoạn chữ nghiêng/nhỏ đặt ngay dưới hoặc cuối bảng).
- Nếu trong text gốc thực sự KHÔNG có thông tin cho field này → bắt buộc dùng giá trị null (không phải chuỗi rỗng "", không phải bỏ qua key).
- TUYỆT ĐỐI KHÔNG được tự tóm tắt rút gọn ghi chú để "cho gọn" — phải lấy đủ ý, kể cả khi dài.
- TUYỆT ĐỐI KHÔNG được suy diễn hay tự viết thêm ghi chú không có trong text gốc.
- Đặc biệt chú ý công thức tính liều Colistin (CBA) — đây là phần hay có chú thích công thức quy đổi (vd: 1mg CBA = ... IU) thường nằm ở cuối — không được bỏ sót.

QUY TẮC CHUNG:
- Trích xuất TẤT CẢ vị trí nhiễm khuẩn và mức kháng thuốc, không bỏ sót mức nào (kể cả PDR/XDR nếu có)
- Giữ nguyên liều — đặc biệt công thức Colistin (CBA), không làm tròn số liệu
- "color" luôn là "#e63946"

NỘI DUNG PHÁC ĐỒ:
"""

# ── Prompt đối chiếu (self-audit) — chạy SAU khi đã có JSON ─────────
AUDIT_PROMPT = """Bạn là người kiểm tra chất lượng dữ liệu y khoa, đóng vai trò phản biện.
Dưới đây là (1) text gốc trích từ sách, và (2) JSON đã được trích xuất từ text đó.

Nhiệm vụ: so sánh JSON với text gốc, tìm các trường hợp:
- Có chú thích / ghi chú / thời gian điều trị / điều kiện đặc biệt trong text gốc nhưng KHÔNG xuất hiện (hoặc bị null/rỗng) trong JSON
- Có thuốc/liều/nhóm bệnh nhân trong text gốc nhưng bị thiếu hoàn toàn trong JSON
- Số liệu liều dùng trong JSON không khớp với text gốc

Chỉ trả về JSON THUẦN theo format sau, không markdown, không giải thích thêm:
{
  "issues": [
    {"loc": "Mô tả ngắn vị trí (vd: 'Nhóm Người >50 tuổi, lựa chọn thay thế')", "problem": "Mô tả ngắn vấn đề"}
  ],
  "ok": true/false
}
Nếu không phát hiện vấn đề gì, trả về {"issues": [], "ok": true}.

TEXT GỐC:
{ORIGINAL}

JSON ĐÃ TRÍCH XUẤT:
{EXTRACTED}
"""


def run_audit(original_text: str, extracted_json) -> dict:
    """Gọi Gemini lần 2 để đối chiếu JSON với text gốc, tìm chỗ nghi thiếu."""
    api_key = get_api_key()
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = AUDIT_PROMPT.replace("{ORIGINAL}", original_text).replace(
        "{EXTRACTED}", json.dumps(extracted_json, ensure_ascii=False, indent=2)
    )
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=8192),
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        return {"issues": [], "ok": None, "error": str(e)}


# ══════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ══════════════════════════════════════════════════════════════════

def get_supabase_cfg():
    url = st.session_state.get("sb_url") or st.secrets.get("SUPABASE_URL", "")
    key = st.session_state.get("sb_key") or st.secrets.get("SUPABASE_KEY", "")
    return url.rstrip("/"), key

def sb_get_next_id(table: str, prefix: str) -> str:
    url, key = get_supabase_cfg()
    r = requests.get(
        f"{url}/rest/v1/{table}?select=id&order=id.desc&limit=100",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=10
    )
    r.raise_for_status()
    ids = [row["id"] for row in r.json() if row.get("id","").startswith(prefix + "_")]
    nums = [int(i.split("_")[-1]) for i in ids if i.split("_")[-1].isdigit()]
    return f"{prefix}_{max(nums)+1}" if nums else f"{prefix}_1"

def sb_insert(table: str, record: dict):
    url, key = get_supabase_cfg()
    r = requests.post(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        },
        json=record,
        timeout=15
    )
    r.raise_for_status()
    return r.json()

# ══════════════════════════════════════════════════════════════════
# HÀM XỬ LÝ
# ══════════════════════════════════════════════════════════════════

def get_api_key() -> str:
    return (
        st.session_state.get("manual_api_key", "")
        or st.secrets.get("GEMINI_API_KEY", "")
    )

def call_ai(text_content: str, prompt: str) -> dict | list:
    api_key = get_api_key()
    if not api_key:
        raise ValueError("Chưa có API key.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    full_prompt = prompt + text_content
    last_err = None
    for attempt in range(3):
        try:
            response = model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=65536),
            )
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            if attempt < 2:
                time.sleep(2)
    raise json.JSONDecodeError(f"JSON lỗi sau 3 lần thử: {last_err}", "", 0)


def generate_new_id(content: str, prefix: str) -> str:
    # Match cả 2 format:
    #   JS object style:  id: "emp_5"
    #   JSON style:       "id": "emp_5"
    ids = re.findall(rf'"?id"?\s*:\s*"{prefix}_(\d+)"', content)
    next_num = max(int(i) for i in ids) + 1 if ids else 1
    return f"{prefix}_{next_num}"


def append_to_js_array(js_content: str, obj_str: str, array_name: str) -> str | None:
    pattern = rf"(const\s+{array_name}\s*=\s*\[.*?)(\n\s*\];)"
    match = re.search(pattern, js_content, re.DOTALL)
    if not match:
        return None
    insert_pos = match.start(2)
    return js_content[:insert_pos] + ",\n" + obj_str + "\n" + js_content[insert_pos:]


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace('\n', ' ')


def sanford_to_js(drug: dict, new_id: str) -> str:
    p2 = "    "
    renal_lines = [
        f'{p2}  {{ label: "{esc(r.get("label",""))}", dose: "{esc(r.get("dose",""))}", note: "{esc(r.get("note",""))}" }}'
        for r in drug.get("renal", [])
    ]
    fields = [
        f'id: "{new_id}"',
        f'source: "sanford"',
        f'name: "{esc(drug.get("name",""))}"',
        f'class: "{esc(drug.get("class",""))}"',
        f'spectrum: "{esc(drug.get("spectrum",""))}"',
        f'tag: "{esc(drug.get("tag",""))}"',
        f'standard: "{esc(drug.get("standard",""))}"',
        f'severe: "{esc(drug.get("severe",""))}"',
        f'pediatric: "{esc(drug.get("pediatric",""))}"',
        f'cns_dose: "{esc(drug.get("cns_dose",""))}"',
        f'hepatic: "{esc(drug.get("hepatic",""))}"',
        f'ecmo: "{esc(drug.get("ecmo",""))}"',
        f'obesity: "{esc(drug.get("obesity",""))}"',
        f'pregnancy: "{esc(drug.get("pregnancy",""))}"',
        f'lactation: "{esc(drug.get("lactation",""))}"',
        f'adverse_effects: "{esc(drug.get("adverse_effects",""))}"',
        f'pk: "{esc(drug.get("pk",""))}"',
        f'choray_note: ""',
        f'sanford_note: "{esc(drug.get("sanford_note",""))}"',
        f'color: "{drug.get("color","#e63946")}"',
        f'renal: [\n{chr(10).join(renal_lines)}\n{p2}]',
    ]
    body = f",\n{p2}".join(fields)
    return f"  {{\n{p2}{body}\n  }}"


def choray_to_js(obj: dict, new_id: str) -> str:
    obj_copy = dict(obj)
    obj_copy["id"] = new_id
    obj_copy["source"] = "choray"
    raw = json.dumps(obj_copy, ensure_ascii=False, indent=4)
    lines = raw.split("\n")
    return "\n".join("  " + l for l in lines)


# ══════════════════════════════════════════════════════════════════
# GIAO DIỆN
# ══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="KS Tool 📱", page_icon="💊", layout="centered")

st.markdown("""
<style>
    .tool-title { font-size: 1.5rem; font-weight: 700; color: #e63946; margin-bottom: .2rem; }
    .step-label {
        font-weight: 600; font-size: 1rem;
        border-left: 4px solid #e63946; padding-left: .6rem;
        margin: 1.2rem 0 .4rem;
    }
    .workflow-box {
        background: #f8f9fa; border-radius: 10px; padding: .8rem 1rem;
        font-size: .9rem; border-left: 3px solid #e63946; margin-bottom: 1rem;
    }
    .stButton > button {
        font-size: 1.1rem !important; padding: .65rem 1rem !important;
        border-radius: 10px !important;
    }
    textarea { font-size: .85rem !important; font-family: monospace !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="tool-title">💊 Kháng Sinh Tool</div>', unsafe_allow_html=True)

# Quy trình hướng dẫn nhanh
st.markdown("""
<div class="workflow-box">
📱 <b>Quy trình:</b>
Chụp ảnh sách → Mở <b>Gemini app</b> → Đính ảnh → Nhắn <i>"đọc hết text trong ảnh này, giữ nguyên, đừng tóm tắt"</i>
→ Copy toàn bộ text → Paste vào ô bên dưới → Nhấn Trích xuất
</div>
""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Cấu hình")

    # Kiểm tra key từ secrets trước
    _secret_key = st.secrets.get("GEMINI_API_KEY", "")
    if _secret_key:
        st.success("✅ Gemini API Key đã cấu hình")
    else:
        st.markdown("**🔑 Gemini API Key** (miễn phí)")
        _manual_key = st.text_input(
            "API Key",
            type="password",
            placeholder="AIza...",
            label_visibility="collapsed",
            key="manual_api_key_input",
        )
        if _manual_key:
            st.session_state["manual_api_key"] = _manual_key
            st.success("✅ Key đã nhập — sẽ nhớ trong phiên này")
        else:
            st.warning("Cần nhập Gemini API Key")
            st.caption("[Lấy key miễn phí tại aistudio.google.com](https://aistudio.google.com/app/apikey)")
            st.caption("Free tier: 15 req/phút, không tốn tiền")

    st.divider()
    st.divider()
    st.markdown("**🗄️ Supabase**")
    _sb_url = st.text_input("Project URL", placeholder="https://xxx.supabase.co",
        value=st.session_state.get("sb_url",""), key="sb_url_input",
        label_visibility="visible")
    if _sb_url: st.session_state["sb_url"] = _sb_url
    _sb_key = st.text_input("Publishable Key", type="password",
        placeholder="sb_publishable_...", value=st.session_state.get("sb_key",""),
        key="sb_key_input", label_visibility="visible")
    if _sb_key: st.session_state["sb_key"] = _sb_key
    if _sb_url and _sb_key:
        st.success("✅ Supabase đã cấu hình")
    else:
        st.warning("Cần nhập URL + Key để push lên Supabase")

    st.divider()
    st.markdown("**Màu nhóm thuốc** (Tab Sanford)")
    color_presets = {
        "🔴 Đỏ (Carbapenem)":           "#e63946",
        "🟢 Xanh lá (Glycopeptide)":    "#2a9d8f",
        "🟠 Cam (Beta-lactam)":          "#f4a261",
        "🔵 Xanh dương (Cephalosporin)":"#0077b6",
        "🟣 Tím (Oxazolidinone)":        "#7209b7",
        "💙 Indigo (Aminoglycoside)":    "#4361ee",
        "🟤 Nâu đỏ (Polymyxin)":        "#9b2226",
        "🟡 Vàng (Quinolone)":           "#e9c46a",
    }
    sel = st.selectbox("Chọn màu", list(color_presets.keys()))
    final_color = st.color_picker("Tùy chỉnh", value=color_presets[sel], key="cp")


# ══════════════════════════════════════════════════════════════════
tab_sanford, tab_choray = st.tabs(["📘 Thuốc Sanford Guide", "🏥 Phác đồ Chợ Rẫy"])


# ──────────────────────────────────────────────────────────────────
# TAB 1 — SANFORD
# ──────────────────────────────────────────────────────────────────
with tab_sanford:

    st.markdown('<div class="step-label">Bước 1 — Tên thuốc</div>', unsafe_allow_html=True)
    drug_name = st.text_input("Tên thuốc", placeholder="vd: Ertapenem",
                              label_visibility="collapsed", key="sf_name")

    st.markdown('<div class="step-label">Bước 2 — Paste text từ Gemini app</div>', unsafe_allow_html=True)
    st.caption("Chụp tất cả ảnh của 1 thuốc → Gemini đọc → copy toàn bộ text → paste vào đây")
    sf_text = st.text_area(
        "Nội dung Sanford",
        height=280,
        placeholder="Paste text từ Gemini vào đây...\n\nVí dụ:\nErtapenem (Invanz)\nAdult Dose: 1g IV/IM q24h\nPediatric Dose: 3 months–12 years: 15mg/kg q12h...\n...",
        label_visibility="collapsed",
        key="sf_text",
    )
    # Upload file .txt thay thế cho paste
    sf_txt_file = st.file_uploader(
        "Hoặc upload file .txt",
        type=["txt"],
        label_visibility="visible",
        key="sf_txt",
        help="Upload file .txt từ Gemini app — tự động điền vào ô text trên"
    )
    if sf_txt_file:
        sf_text = sf_txt_file.read().decode("utf-8")
        st.success(f"✅ Đã đọc file: {sf_txt_file.name} — {len(sf_text.split())} từ")
    elif sf_text:
        word_count = len(sf_text.split())
        st.caption(f"📝 {word_count} từ — {len(sf_text)} ký tự")

    st.markdown('<div class="step-label">Bước 3 — Trích xuất & Push Supabase</div>', unsafe_allow_html=True)
    sb_ok = bool(st.session_state.get("sb_url")) and bool(st.session_state.get("sb_key"))
    sf_ready = bool(drug_name.strip()) and bool(sf_text.strip()) and bool(st.session_state.get("manual_api_key") or st.secrets.get("GEMINI_API_KEY","")) and sb_ok
    if not sf_ready:
        miss = []
        if not (st.session_state.get("manual_api_key") or st.secrets.get("GEMINI_API_KEY","")): miss.append("Gemini API Key")
        if not drug_name.strip(): miss.append("tên thuốc")
        if not sf_text.strip(): miss.append("text Sanford")
        if not sb_ok: miss.append("Supabase URL + Key (sidebar)")
        st.info(f"ℹ️ Còn thiếu: {', '.join(miss)}")

    if st.button("🚀 Trích xuất & Push lên Supabase", disabled=not sf_ready,
                 type="primary", use_container_width=True, key="sf_run"):
        prog = st.progress(0, text="Đang gửi đến Gemini...")
        try:
            t0 = time.time()
            prog.progress(20, text="🤖 Gemini đang phân tích text...")
            full_text = f"Thuốc: {drug_name.strip()}\n\n{sf_text.strip()}"
            result = call_ai(full_text, SANFORD_PROMPT)
            elapsed = time.time() - t0
            result["color"] = final_color
            prog.progress(60, text="✅ Xong — đang push lên Supabase...")

            st.subheader("📋 JSON trích xuất")
            st.json(result)

            new_id = sb_get_next_id("sanford_antibiotics", "sf")
            result["id"] = new_id
            result["source"] = "sanford"
            sb_insert("sanford_antibiotics", result)

            prog.progress(100, text="✅ Hoàn thành!")
            st.success(f"🎉 **{result.get('name', drug_name)}** (ID: `{new_id}`) đã push lên Supabase — {elapsed:.1f}s")
            st.balloons()

        except json.JSONDecodeError as e:
            prog.progress(0)
            st.error(f"❌ JSON lỗi: {e}")
            st.warning("Thử paste thêm text hoặc kiểm tra nội dung có đủ không.")
        except Exception as e:
            prog.progress(0)
            st.error(f"❌ {type(e).__name__}: {e}")
            st.exception(e)



# ──────────────────────────────────────────────────────────────────
# TAB 2 — CHỢ RẪY
# ──────────────────────────────────────────────────────────────────
with tab_choray:

    st.markdown('<div class="step-label">Bước 1 — Loại phác đồ</div>', unsafe_allow_html=True)
    cr_type = st.radio(
        "Loại",
        ["📋 Phác đồ kinh nghiệm (theo bệnh cảnh)", "🦠 Phác đồ theo vi khuẩn (MDR/PDR)"],
        label_visibility="collapsed", key="cr_type",
    )
    is_empirical = "kinh nghiệm" in cr_type

    if is_empirical:
        st.info("Phần 5.1, 5.2... — phân nhánh theo nhóm BN → ghi vào **CHORAY_EMPIRICAL**")
        cr_array, cr_prefix, cr_prompt = "CHORAY_EMPIRICAL", "emp", CHORAY_EMPIRICAL_PROMPT
    else:
        st.info("Phần 5.15, 5.16... — phân nhánh Nhạy/MDR/PDR → ghi vào **CHORAY_TARGETED**")
        cr_array, cr_prefix, cr_prompt = "CHORAY_TARGETED", "tgt", CHORAY_TARGETED_PROMPT

    st.markdown('<div class="step-label">Bước 2 — Paste text từ Gemini app</div>', unsafe_allow_html=True)
    st.caption("Chụp ảnh sách Chợ Rẫy → Gemini đọc → copy toàn bộ text → paste vào đây")
    st.caption("💡 Paste nhiều phần cùng lúc cũng được — Gemini sẽ tự tách thành nhiều phác đồ")
    cr_text = st.text_area(
        "Nội dung phác đồ",
        height=320,
        placeholder="Paste text từ Gemini vào đây...\n\nVí dụ:\n5.1.1 Viêm màng não do vi khuẩn cấp tính\n* Người ≤ 50 tuổi:\n  - Tác nhân: S. pneumoniae...\n  - Đầu tay: Ceftriaxone 2g TM mỗi 12h...\n...",
        label_visibility="collapsed",
        key="cr_text",
    )
    # Upload file .txt thay thế cho paste
    cr_txt_file = st.file_uploader(
        "Hoặc upload file .txt",
        type=["txt"],
        label_visibility="visible",
        key="cr_txt",
        help="Upload file .txt từ Gemini app — tự động điền vào ô text trên"
    )
    if cr_txt_file:
        cr_text = cr_txt_file.read().decode("utf-8")
        st.success(f"✅ Đã đọc file: {cr_txt_file.name} — {len(cr_text.split())} từ")
    elif cr_text:
        word_count = len(cr_text.split())
        st.caption(f"📝 {word_count} từ — {len(cr_text)} ký tự")

    st.markdown('<div class="step-label">Bước 3 — Trích xuất & Push Supabase</div>', unsafe_allow_html=True)
    sb_ok = bool(st.session_state.get("sb_url")) and bool(st.session_state.get("sb_key"))
    cr_ready = bool(cr_text.strip()) and bool(st.session_state.get("manual_api_key") or st.secrets.get("GEMINI_API_KEY","")) and sb_ok
    if not cr_ready:
        miss = []
        if not (st.session_state.get("manual_api_key") or st.secrets.get("GEMINI_API_KEY","")): miss.append("Gemini API Key")
        if not cr_text.strip(): miss.append("text phác đồ")
        if not sb_ok: miss.append("Supabase URL + Key (sidebar)")
        st.info(f"ℹ️ Còn thiếu: {', '.join(miss)}")

    if st.button("🚀 Trích xuất & Push lên Supabase", disabled=not cr_ready,
                 type="primary", use_container_width=True, key="cr_run"):
        prog = st.progress(0, text="Đang gửi đến Gemini...")
        try:
            t0 = time.time()
            prog.progress(20, text="🤖 Gemini đang phân tích phác đồ...")
            result = call_ai(cr_text.strip(), cr_prompt)
            elapsed = time.time() - t0
            prog.progress(50, text="🔍 Đang đối chiếu lại với text gốc...")

            items = result if isinstance(result, list) else [result]
            st.subheader(f"📋 Trích xuất được {len(items)} phác đồ")
            st.json(result)

            # ── Bước đối chiếu (self-audit) ─────────────────────────
            audit = run_audit(cr_text.strip(), result)
            if audit.get("ok") is None:
                st.warning(f"⚠️ Không chạy được bước đối chiếu tự động ({audit.get('error','')}). Bạn nên tự rà lại JSON phía trên.")
            elif audit.get("issues"):
                st.error(f"⚠️ Phát hiện {len(audit['issues'])} chỗ NGHI THIẾU/SAI — hãy kiểm tra lại trước khi dùng:")
                for iss in audit["issues"]:
                    st.markdown(f"- **{iss.get('loc','?')}**: {iss.get('problem','')}")
                st.caption("Đây chỉ là cảnh báo tự động — bạn vẫn có thể push nếu thấy ổn.")
            else:
                st.success("✅ Đối chiếu xong — không phát hiện chỗ nghi thiếu rõ ràng.")

            prog.progress(70, text="🗄️ Đang push lên Supabase...")

            cr_table = "choray_empirical" if is_empirical else "choray_targeted"
            added_ids = []
            for item in items:
                new_id = sb_get_next_id(cr_table, cr_prefix)
                item["id"] = new_id
                item["source"] = "choray"
                sb_insert(cr_table, item)
                added_ids.append(new_id)

            prog.progress(100, text="✅ Hoàn thành!")
            ids_str = ", ".join(f"`{i}`" for i in added_ids)
            st.success(f"🎉 Đã push **{len(items)} phác đồ** lên Supabase (ID: {ids_str}) — {elapsed:.1f}s")
            st.balloons()

        except json.JSONDecodeError as e:
            prog.progress(0)
            st.error(f"❌ JSON lỗi: {e}")
            st.warning("Thử lại hoặc bớt text nếu quá dài.")
        except Exception as e:
            prog.progress(0)
            st.error(f"❌ {type(e).__name__}: {e}")
            st.exception(e)


    with st.expander("📖 Hướng dẫn chi tiết"):
        st.markdown("""
**Quy trình đầy đủ trên điện thoại:**

1. Chụp ảnh sách (chụp bao nhiêu cũng được)
2. Mở **Gemini app** → đính tất cả ảnh vào → nhắn:
   > *"Đọc hết toàn bộ text trong các ảnh này, giữ nguyên từng chữ, đừng tóm tắt hay bỏ bớt"*
3. Copy toàn bộ text Gemini trả về
4. Mở Streamlit → chọn đúng tab → paste vào ô text
5. Upload file JS → nhấn Trích xuất → Tải file mới về
6. Thay file cũ → commit GitHub → Vercel deploy

**Lợi thế so với upload ảnh trực tiếp:**
- Không bị giới hạn 1 ảnh/lần trên iOS
- Không tốn Gemini API token cho việc đọc ảnh
- Paste được nhiều phần cùng lúc → 1 lần chạy = nhiều phác đồ
- File JS tích lũy dần — upload lần sau là file đã có dữ liệu cũ

**Mẹo:**
- Gemini app miễn phí, không cần API key để đọc ảnh
- Nên paste 1 chương/1 vi khuẩn mỗi lần để kết quả chính xác hơn
- API Key Gemini chỉ dùng cho bước Trích xuất JSON — nhập 1 lần/phiên
        """)
