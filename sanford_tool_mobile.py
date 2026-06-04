"""
╔══════════════════════════════════════════════════════════════════╗
║     SANFORD DATA EXTRACTOR — Phiên bản Mobile (Upload ảnh)     ║
║   Chụp ảnh điện thoại → Upload thẳng → Gemini phân tích       ║
╚══════════════════════════════════════════════════════════════════╝

Cài đặt:
    pip install streamlit google-generativeai pillow

Chạy:
    streamlit run sanford_tool_mobile.py
"""

import streamlit as st
import google.generativeai as genai
import json, os, re, time
from PIL import Image
import io

# ─────────────────────────────────────────────
# CẤU HÌNH
# ─────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """Bạn là một chuyên gia Dược lâm sàng và dịch thuật y khoa.
Tôi sẽ cung cấp các hình ảnh chụp từ ứng dụng Sanford Guide (tiếng Anh).

Nhiệm vụ của bạn là đọc TOÀN BỘ chữ trong các ảnh này, dịch nghĩa và tổng hợp lại
thành một cấu trúc JSON HOÀN TOÀN BẰNG TIẾNG VIỆT theo schema bên dưới.

QUY TẮC DỊCH THUẬT:
- Giữ nguyên tên thuốc gốc (Ciprofloxacin, Amikacin, v.v.)
- Adult Dose → Liều người lớn
- Pediatric Dose → Liều trẻ em
- Renal Impairment / Adjustment → Hiệu chỉnh liều cho bệnh nhân suy thận
- CrCl (Creatinine Clearance) → Độ thanh thải Creatinin (CrCl)
- Hemodialysis → Lọc máu chu kỳ (HD)
- Peritoneal Dialysis → Thẩm phân phúc mạc (PD)
- Adverse Effects → Tác dụng không mong muốn (ADR)
- Pregnancy / Lactation → Phụ nữ mang thai / Cho con bú
- Dịch thoát ý, ngắn gọn, dễ hiểu để tra cứu nhanh khi đi buồng
- Các mốc kỹ thuật quan trọng: ghi dạng "Tiếng Việt (tiếng Anh gốc)"

SCHEMA JSON CẦN TRẢ VỀ (chỉ JSON thuần, không markdown, không giải thích):
{
  "name": "Tên thuốc (giữ nguyên tên quốc tế)",
  "class": "Nhóm thuốc",
  "spectrum": "Phổ tác dụng (Gram âm / Gram dương / ...)",
  "tag": "Chỉ định chính ngắn gọn, cách nhau · (chấm giữa)",
  "standard": "Liều chuẩn người lớn",
  "severe": "Liều nặng / ICU",
  "hepatic": "Chỉnh liều suy gan (nếu không cần: 'Không cần chỉnh liều')",
  "sanford_note": "Lưu ý lâm sàng quan trọng từ Sanford (2–5 câu súc tích)",
  "color": "#e63946",
  "renal": [
    { "label": "Ngưỡng CrCl (mL/phút)", "dose": "Liều dùng", "note": "Ghi chú" },
    { "label": ">50", "dose": "...", "note": "Liều chuẩn" },
    { "label": "10–50", "dose": "...", "note": "..." },
    { "label": "<10", "dose": "...", "note": "..." },
    { "label": "HD", "dose": "...", "note": "Lọc máu chu kỳ" }
  ]
}

LƯU Ý QUAN TRỌNG:
- Trường "color" luôn là "#e63946"
- Trường "renal" phải liệt kê ĐẦY ĐỦ các mức CrCl có trong ảnh
- Nếu không có thông tin cho một trường, để chuỗi rỗng ""
- Chỉ trả về JSON, không có bất kỳ văn bản nào khác
"""

# ─────────────────────────────────────────────
# HÀM XỬ LÝ
# ─────────────────────────────────────────────

def call_gemini(pil_images: list, drug_name: str, api_key: str) -> dict:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    parts = [
        f"Thuốc cần trích xuất: **{drug_name}**\n\n"
        f"Dưới đây là {len(pil_images)} ảnh chụp từ Sanford Guide. "
        f"Hãy đọc TOÀN BỘ và tổng hợp theo schema JSON đã hướng dẫn.\n\n"
        f"{SYSTEM_PROMPT}"
    ]
    for img in pil_images:
        parts.append(img)

    response = model.generate_content(
        parts,
        generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=4096),
    )

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def generate_new_id(content: str, prefix: str = "sf") -> str:
    ids = re.findall(rf'id:\s*"{prefix}_(\d+)"', content)
    next_num = max(int(i) for i in ids) + 1 if ids else 1
    return f"{prefix}_{next_num}"


def drug_dict_to_js_object(drug: dict, new_id: str, indent: int = 2) -> str:
    pad = " " * indent
    pad2 = " " * (indent + 2)

    renal_lines = [
        f'{pad2}  {{ label: "{r.get("label","")}", dose: "{r.get("dose","")}", note: "{r.get("note","")}" }}'
        for r in drug.get("renal", [])
    ]
    renal_str = ",\n".join(renal_lines)

    return (
        f'{pad}{{\n'
        f'{pad2}id: "{new_id}",\n'
        f'{pad2}source: "sanford",\n'
        f'{pad2}name: "{drug.get("name", "")}",\n'
        f'{pad2}class: "{drug.get("class", "")}",\n'
        f'{pad2}spectrum: "{drug.get("spectrum", "")}",\n'
        f'{pad2}tag: "{drug.get("tag", "")}",\n'
        f'{pad2}standard: "{drug.get("standard", "")}",\n'
        f'{pad2}severe: "{drug.get("severe", "")}",\n'
        f'{pad2}hepatic: "{drug.get("hepatic", "")}",\n'
        f'{pad2}choray_note: "",\n'
        f'{pad2}sanford_note: "{drug.get("sanford_note", "")}",\n'
        f'{pad2}color: "{drug.get("color", "#e63946")}",\n'
        f'{pad2}renal: [\n{renal_str}\n{pad2}]\n'
        f'{pad}}}'
    )


def append_drug_to_js(js_content: str, drug_obj_str: str, array_name: str = "SANFORD_ANTIBIOTICS") -> str | None:
    """Chèn thuốc vào mảng JS, trả về nội dung mới (không ghi file trực tiếp)"""
    pattern = rf"(const\s+{array_name}\s*=\s*\[.*?)(\n\s*\];)"
    match = re.search(pattern, js_content, re.DOTALL)
    if not match:
        return None
    insert_pos = match.start(2)
    return js_content[:insert_pos] + ",\n" + drug_obj_str + "\n" + js_content[insert_pos:]


# ─────────────────────────────────────────────
# GIAO DIỆN
# ─────────────────────────────────────────────

st.set_page_config(page_title="Sanford Extractor 📱", page_icon="💊", layout="centered")

st.markdown("""
<style>
    /* Tăng kích thước vùng upload cho điện thoại */
    [data-testid="stFileUploader"] {
        min-height: 120px;
    }
    [data-testid="stFileUploader"] section {
        padding: 1.5rem;
        border: 2px dashed #e63946 !important;
        border-radius: 12px;
    }
    .drug-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: #e63946;
    }
    .step-label {
        font-weight: 600;
        font-size: 1rem;
        border-left: 4px solid #e63946;
        padding-left: 0.6rem;
        margin: 1.2rem 0 0.5rem 0;
    }
    /* Nút lớn hơn cho điện thoại */
    .stButton > button {
        font-size: 1.1rem !important;
        padding: 0.65rem 1rem !important;
        border-radius: 10px !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="drug-title">💊 Sanford Extractor</div>', unsafe_allow_html=True)
st.caption("Chụp ảnh Sanford Guide → Upload → Tự động tạo JSON & JS")

# ── Sidebar cấu hình ───────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Cấu hình")

    api_key = st.text_input(
        "Gemini API Key",
        type="password",
        help="Lấy tại https://aistudio.google.com/app/apikey",
        placeholder="AIza...",
    )

    st.divider()
    st.markdown("**Màu nhóm thuốc**")
    color_presets = {
        "🔴 Đỏ (Carbapenem)": "#e63946",
        "🟢 Xanh lá (Glycopeptide)": "#2a9d8f",
        "🟠 Cam (Beta-lactam)": "#f4a261",
        "🔵 Xanh dương (Cephalosporin)": "#0077b6",
        "🟣 Tím (Oxazolidinone)": "#7209b7",
        "💙 Indigo (Aminoglycoside)": "#4361ee",
        "🟤 Nâu đỏ (Polymyxin)": "#9b2226",
        "🟡 Vàng (Quinolone)": "#e9c46a",
    }
    selected_label = st.selectbox("Chọn màu", list(color_presets.keys()))
    selected_color = color_presets[selected_label]
    final_color = st.color_picker("Hoặc tùy chỉnh", value=selected_color, key="color_pick")

    st.divider()
    array_name = st.selectbox(
        "Mảng JS",
        ["SANFORD_ANTIBIOTICS", "SANFORD_PROTOCOLS"],
    )


# ══════════════════════════════════════════════
# BƯỚC 1: NHẬP TÊN THUỐC
# ══════════════════════════════════════════════
st.markdown('<div class="step-label">Bước 1 — Tên thuốc</div>', unsafe_allow_html=True)
drug_name = st.text_input(
    "Tên thuốc",
    placeholder="Ciprofloxacin",
    label_visibility="collapsed",
)

# ══════════════════════════════════════════════
# BƯỚC 2: UPLOAD ẢNH (hỗ trợ nhiều ảnh)
# ══════════════════════════════════════════════
st.markdown('<div class="step-label">Bước 2 — Upload ảnh Sanford Guide</div>', unsafe_allow_html=True)
st.caption("📱 Chọn nhiều ảnh cùng lúc — không giới hạn số lượng (30–40 ảnh đều được)")

uploaded_files = st.file_uploader(
    "Chọn ảnh",
    type=["jpg", "jpeg", "png", "webp", "bmp", "gif"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    help="Bấm vào đây → chọn tất cả ảnh cần nạp",
)

pil_images = []
if uploaded_files:
    st.success(f"✅ Đã chọn **{len(uploaded_files)} ảnh**")
    # Chỉ preview 4 ảnh đầu, load hết vào bộ nhớ nhưng không render tất cả
    cols = st.columns(2)
    for i, f in enumerate(uploaded_files):
        img = Image.open(f)
        pil_images.append(img)
        if i < 4:
            with cols[i % 2]:
                st.image(img, caption=f.name, use_container_width=True)
    if len(uploaded_files) > 4:
        st.caption(f"... và {len(uploaded_files) - 4} ảnh khác (đã nạp vào bộ nhớ, không hiển thị để tránh lag)")


# ══════════════════════════════════════════════
# BƯỚC 3: UPLOAD FILE data-sanford.js
# ══════════════════════════════════════════════
st.markdown('<div class="step-label">Bước 3 — Upload file data-sanford.js</div>', unsafe_allow_html=True)
st.caption("Upload file JS của project để tool đọc ID và ghi thuốc mới vào")

js_file = st.file_uploader(
    "Upload data-sanford.js",
    type=["js"],
    label_visibility="collapsed",
    help="File JS chứa mảng SANFORD_ANTIBIOTICS",
)

js_content = None
if js_file:
    js_content = js_file.read().decode("utf-8")
    current_ids = re.findall(r'id:\s*"sf_(\d+)"', js_content)
    next_id = f"sf_{max(int(i) for i in current_ids) + 1}" if current_ids else "sf_1"
    st.success(f"✅ File hợp lệ — **{len(current_ids)}** thuốc hiện có — ID tiếp theo: **`{next_id}`**")


# ══════════════════════════════════════════════
# BƯỚC 4: CHẠY
# ══════════════════════════════════════════════
st.markdown('<div class="step-label">Bước 4 — Trích xuất</div>', unsafe_allow_html=True)

can_run = (
    bool(drug_name.strip()) and
    bool(pil_images) and
    bool(js_content) and
    bool(api_key) and api_key != "AIza..."
)

if not can_run:
    missing = []
    if not drug_name.strip(): missing.append("tên thuốc")
    if not pil_images: missing.append("ảnh")
    if not js_content: missing.append("file JS")
    if not api_key or api_key == "AIza...": missing.append("Gemini API Key (sidebar)")
    st.info(f"ℹ️ Còn thiếu: {', '.join(missing)}")

run_btn = st.button(
    "🚀 Bắt đầu trích xuất",
    disabled=not can_run,
    type="primary",
    use_container_width=True,
)

# ══════════════════════════════════════════════
# XỬ LÝ
# ══════════════════════════════════════════════
if run_btn:
    progress = st.progress(0, text="Đang khởi động...")

    try:
        progress.progress(20, text=f"🤖 Gửi {len(pil_images)} ảnh đến Gemini 2.5 Flash...")
        t0 = time.time()

        drug_dict = call_gemini(pil_images, drug_name.strip(), api_key)
        elapsed = time.time() - t0

        progress.progress(70, text="✅ Gemini xong — đang xử lý JSON...")

        # Áp màu đã chọn
        drug_dict["color"] = final_color

        # Hiển thị JSON
        st.subheader("📋 JSON trích xuất")
        st.json(drug_dict)

        # Ghi vào JS
        progress.progress(85, text="💾 Đang ghép vào file JS...")

        new_id = generate_new_id(js_content, prefix="sf")
        drug_obj_str = drug_dict_to_js_object(drug_dict, new_id, indent=2)
        new_js_content = append_drug_to_js(js_content, drug_obj_str, array_name=array_name)

        if new_js_content is None:
            st.error(f"❌ Không tìm thấy mảng `{array_name}` trong file JS!")
        else:
            progress.progress(100, text="✅ Hoàn thành!")
            st.success(
                f"🎉 **Thành công!** Thuốc **{drug_dict.get('name', drug_name)}** "
                f"(ID: `{new_id}`) đã được thêm vào — {elapsed:.1f}s"
            )

            # ── TẢI FILE JS MỚI VỀ ──────────────────────────
            st.markdown("### 📥 Tải file JS đã cập nhật")
            st.caption("Tải về → thay thế file cũ trên máy tính → commit lên GitHub")
            st.download_button(
                label="⬇️ Tải data-sanford.js mới",
                data=new_js_content.encode("utf-8"),
                file_name="data-sanford.js",
                mime="text/javascript",
                use_container_width=True,
                type="primary",
            )

            # Xem đoạn JS vừa thêm
            with st.expander("👁️ Xem đoạn JS vừa thêm"):
                st.code(drug_obj_str, language="javascript")

    except json.JSONDecodeError as e:
        progress.progress(0)
        st.error(f"❌ Gemini trả về JSON không hợp lệ: {e}")
        st.warning("Thử chụp lại ảnh rõ hơn hoặc thêm ảnh bổ sung.")

    except Exception as e:
        progress.progress(0)
        st.error(f"❌ Lỗi: {type(e).__name__}: {e}")
        st.exception(e)


# ── Hướng dẫn ────────────────────────────────
with st.expander("📖 Hướng dẫn sử dụng"):
    st.markdown("""
### Cài đặt (chạy lần đầu trên máy)

```bash
pip install streamlit google-generativeai pillow
streamlit run sanford_tool_mobile.py
```

### Quy trình dùng trên điện thoại

1. **Sidebar** → nhập **Gemini API Key**, chọn **màu nhóm thuốc**
2. **Bước 1** → nhập tên thuốc (vd: Ciprofloxacin)
3. **Bước 2** → bấm vào ô upload → **chụp ảnh hoặc chọn từ thư viện**
   - Có thể chọn **nhiều ảnh một lúc** (2–3 ảnh/thuốc)
4. **Bước 3** → upload file `data-sanford.js` từ project của bạn
5. **Bước 4** → nhấn **🚀 Bắt đầu trích xuất**
6. Kiểm tra JSON → nhấn **⬇️ Tải file JS mới**
7. Thay thế file cũ trên máy → **commit lên GitHub** → Vercel tự deploy

### Lấy Gemini API Key

1. Vào https://aistudio.google.com/app/apikey
2. Nhấn **Create API Key** → copy key
3. Dán vào ô **Gemini API Key** ở sidebar

### Lưu ý

- Mỗi lần chạy xử lý **1 thuốc** (có thể nhiều ảnh)
- Muốn nạp thuốc tiếp: **làm mới trang** hoặc upload ảnh mới + đổi tên thuốc
- ID tự động tăng: sf_1, sf_2, sf_3...
    """)
