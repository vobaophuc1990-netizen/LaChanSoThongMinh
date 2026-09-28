import streamlit as st
import urllib.request
import urllib.error
import json
import time
import random
import re


# =========================================================
# 1. CẤU HÌNH
# =========================================================

st.set_page_config(
    page_title="Lá Chắn Số THPT",
    page_icon="🛡️",
    layout="wide"
)

# Gemini 3.8 Flash
MODEL = "gemini-3.8-flash"

# Không gọi API liên tục
COOLDOWN_SECONDS = 5

# Giới hạn nội dung gửi lên Gemini
MAX_ANALYSIS_CHARS = 12000

# Timeout ngắn hơn để tránh app bị treo quá lâu
GEMINI_TIMEOUT = 25

# Chỉ retry các lỗi tạm thời
GEMINI_MAX_ATTEMPTS = 2


# =========================================================
# 2. LẤY API KEY
# =========================================================

try:
    API_KEY = st.secrets.get("GEMINI_API_KEY", "").strip()
except Exception:
    API_KEY = ""


# =========================================================
# 3. SESSION STATE
# =========================================================

DEFAULT_STATE = {
    "last_api_call": 0.0,
    "analysis_count": 0,

    "game_question": None,
    "game_result": None,
    "game_answer": None,

    "used_scenarios": [],
    "game_round": 0,

    "last_gemini_status": None,
    "last_gemini_error": None,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# 4. CSS
# =========================================================

st.markdown(
    """
    <style>

    .main {
        padding-top: 1rem;
    }

    .hero {
        padding: 1.5rem 1.5rem 1.2rem 1.5rem;
        border-radius: 20px;
        background: linear-gradient(
            135deg,
            rgba(30, 64, 175, 0.12),
            rgba(16, 185, 129, 0.10)
        );
        border: 1px solid rgba(100, 116, 139, 0.18);
        margin-bottom: 1.2rem;
    }

    .hero-title {
        font-size: 2.4rem;
        font-weight: 800;
        margin-bottom: 0.3rem;
    }

    .hero-subtitle {
        font-size: 1.05rem;
        color: #64748b;
    }

    .risk-card {
        padding: 1.2rem;
        border-radius: 18px;
        border: 1px solid rgba(100, 116, 139, 0.2);
        background: rgba(248, 250, 252, 0.75);
        margin-top: 1rem;
    }

    .small-muted {
        color: #64748b;
        font-size: 0.9rem;
    }

    .status-box {
        padding: 0.9rem 1rem;
        border-radius: 14px;
        border: 1px solid rgba(100, 116, 139, 0.2);
        margin-top: 0.8rem;
    }

    .danger-box {
        padding: 1rem;
        border-radius: 14px;
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.25);
    }

    .safe-box {
        padding: 1rem;
        border-radius: 14px;
        background: rgba(16, 185, 129, 0.08);
        border: 1px solid rgba(16, 185, 129, 0.25);
    }

    .warning-box {
        padding: 1rem;
        border-radius: 14px;
        background: rgba(245, 158, 11, 0.08);
        border: 1px solid rgba(245, 158, 11, 0.25);
    }

    .info-box {
        padding: 1rem;
        border-radius: 14px;
        background: rgba(59, 130, 246, 0.08);
        border: 1px solid rgba(59, 130, 246, 0.25);
    }

    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# 5. HEADER
# =========================================================

st.markdown(
    """
    <div class="hero">
        <div class="hero-title">🛡️ Lá Chắn Số THPT</div>
        <div class="hero-subtitle">
            Công cụ hỗ trợ học sinh nhận diện tin nhắn và tình huống có dấu hiệu lừa đảo.
        </div>
    </div>
    """,
    unsafe_allow_html=True
)


# =========================================================
# 6. TIỆN ÍCH
# =========================================================

def can_call_api():
    """
    Kiểm tra cooldown trước khi gọi Gemini.
    """

    now = time.time()
    elapsed = now - st.session_state.last_api_call

    if elapsed < COOLDOWN_SECONDS:
        remaining = COOLDOWN_SECONDS - elapsed
        return False, remaining

    return True, 0


def mark_api_call():
    st.session_state.last_api_call = time.time()


def safe_text(value):
    """
    Chuyển dữ liệu bất kỳ thành string an toàn.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


# =========================================================
# 7. PARSE JSON
# =========================================================

def extract_json(text):
    """
    Cố gắng lấy JSON từ phản hồi Gemini.

    Hỗ trợ:
    - JSON thuần
    - ```json ... ```
    - JSON nằm giữa phần text khác
    """

    if not text:
        return None

    text = text.strip()

    # -----------------------------------------------------
    # Trường hợp 1: JSON thuần
    # -----------------------------------------------------

    try:
        return json.loads(text)
    except Exception:
        pass

    # -----------------------------------------------------
    # Trường hợp 2: fenced JSON
    # -----------------------------------------------------

    fenced = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if fenced:
        candidate = fenced.group(1).strip()

        try:
            return json.loads(candidate)
        except Exception:
            pass

    # -----------------------------------------------------
    # Trường hợp 3: tìm object JSON
    # -----------------------------------------------------

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end > start:

        candidate = text[start:end + 1]

        try:
            return json.loads(candidate)
        except Exception:
            pass

    # -----------------------------------------------------
    # Trường hợp 4: tìm array JSON
    # -----------------------------------------------------

    start = text.find("[")
    end = text.rfind("]")

    if start != -1 and end > start:

        candidate = text[start:end + 1]

        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


# =========================================================
# 8. TÍNH ĐIỂM RỦI RO LOCAL
# =========================================================

def calculate_risk_score(message):
    """
    Bộ phân tích local.

    Gemini KHÔNG quyết định điểm cuối cùng.
    Điều này giúp app vẫn hoạt động ngay cả khi API lỗi.
    """

    text = safe_text(message).lower()

    score = 0
    detected = []
    signals = []

    # -----------------------------------------------------
    # Mật khẩu / tài khoản
    # -----------------------------------------------------

    password_patterns = [
        r"\bmật khẩu\b",
        r"\bpassword\b",
        r"\bpass\b",
        r"\btài khoản\b",
        r"\baccount\b",
        r"\bđăng nhập\b",
        r"\blogin\b",
    ]

    if any(re.search(p, text) for p in password_patterns):
        score += 18
        detected.append("Yêu cầu thông tin tài khoản")
        signals.append("Tin nhắn đề cập đến tài khoản hoặc mật khẩu.")

    # -----------------------------------------------------
    # OTP / mã xác minh
    # -----------------------------------------------------

    otp_patterns = [
        r"\botp\b",
        r"mã xác minh",
        r"mã xác thực",
        r"mã đăng nhập",
        r"verification code",
        r"mã bảo mật",
    ]

    if any(re.search(p, text) for p in otp_patterns):
        score += 25
        detected.append("Thu thập mã xác thực")
        signals.append("Có dấu hiệu yêu cầu hoặc đề cập đến mã OTP/xác minh.")

    # -----------------------------------------------------
    # Tiền
    # -----------------------------------------------------

    money_patterns = [
        r"\bchuyển khoản\b",
        r"\bchuyển tiền\b",
        r"\bthanh toán\b",
        r"\bnạp tiền\b",
        r"\bphí\b",
        r"\btiền\b",
        r"\bvnd\b",
        r"\bđồng\b",
        r"\btriệu\b",
        r"\bnghìn\b",
        r"\busd\b",
    ]

    if any(re.search(p, text) for p in money_patterns):
        score += 22
        detected.append("Yếu tố tiền bạc")
        signals.append("Tin nhắn có liên quan đến tiền hoặc giao dịch.")

    # -----------------------------------------------------
    # Link
    # -----------------------------------------------------

    link_patterns = [
        r"https?://",
        r"www\.",
        r"\bbit\.ly\b",
        r"\btinyurl\b",
        r"\blink\b",
        r"\bđường dẫn\b",
        r"\btruy cập\b",
    ]

    if any(re.search(p, text) for p in link_patterns):
        score += 18
        detected.append("Liên kết đáng chú ý")
        signals.append("Tin nhắn có chứa hoặc nhắc đến đường dẫn.")

    # -----------------------------------------------------
    # Khẩn cấp
    # -----------------------------------------------------

    urgency_patterns = [
        r"\bgấp\b",
        r"\bkhẩn cấp\b",
        r"\bngay lập tức\b",
        r"\bngay\b",
        r"\bhạn cuối\b",
        r"\bsắp hết hạn\b",
        r"\btrong hôm nay\b",
        r"\b5 phút\b",
        r"\b10 phút\b",
        r"\b30 phút\b",
    ]

    if any(re.search(p, text) for p in urgency_patterns):
        score += 15
        detected.append("Tạo cảm giác khẩn cấp")
        signals.append("Người nhận bị thúc ép phải hành động nhanh.")

    # -----------------------------------------------------
    # Đe dọa
    # -----------------------------------------------------

    threat_patterns = [
        r"\bkhóa tài khoản\b",
        r"\bkhóa\b",
        r"\bphạt\b",
        r"\bcông an\b",
        r"\btòa án\b",
        r"\bkiện\b",
        r"\bxử lý\b",
        r"\bvi phạm\b",
        r"\btruy cứu\b",
    ]

    if any(re.search(p, text) for p in threat_patterns):
        score += 20
        detected.append("Đe dọa / gây áp lực")
        signals.append("Có ngôn ngữ tạo sợ hãi hoặc áp lực.")

    # -----------------------------------------------------
    # Mạo danh
    # -----------------------------------------------------

    impersonation_patterns = [
        r"\bngân hàng\b",
        r"\bcông an\b",
        r"\bnhà trường\b",
        r"\bgiáo viên\b",
        r"\bshipper\b",
        r"\bcơ quan\b",
        r"\bfacebook\b",
        r"\bzalo\b",
        r"\bgoogle\b",
        r"\bmicrosoft\b",
        r"\bnhân viên\b",
    ]

    if any(re.search(p, text) for p in impersonation_patterns):
        score += 15
        detected.append("Dấu hiệu mạo danh")
        signals.append("Tin nhắn có thể đang sử dụng danh nghĩa của một tổ chức/người khác.")

    # -----------------------------------------------------
    # Thông tin cá nhân
    # -----------------------------------------------------

    personal_patterns = [
        r"\bcccd\b",
        r"\bcmnd\b",
        r"\bsố điện thoại\b",
        r"\bđịa chỉ\b",
        r"\bngày sinh\b",
        r"\bhọ tên\b",
        r"\bthông tin cá nhân\b",
        r"\bsố tài khoản\b",
    ]

    if any(re.search(p, text) for p in personal_patterns):
        score += 17
        detected.append("Thu thập thông tin cá nhân")
        signals.append("Có dấu hiệu yêu cầu thông tin cá nhân hoặc định danh.")

    # -----------------------------------------------------
    # Quà / thưởng
    # -----------------------------------------------------

    reward_patterns = [
        r"\btrúng thưởng\b",
        r"\bgiải thưởng\b",
        r"\bquà tặng\b",
        r"\bnhận quà\b",
        r"\btrúng\b",
        r"\bthưởng\b",
        r"\bkhuyến mãi\b",
        r"\bmiễn phí\b",
    ]

    if any(re.search(p, text) for p in reward_patterns):
        score += 15
        detected.append("Mồi quà tặng / phần thưởng")
        signals.append("Tin nhắn sử dụng lợi ích hoặc phần thưởng để thu hút.")

    # -----------------------------------------------------
    # Giữ bí mật
    # -----------------------------------------------------

    secrecy_patterns = [
        r"\bđừng nói\b",
        r"\bkhông được nói\b",
        r"\bgiữ bí mật\b",
        r"\bkhông cho ai biết\b",
        r"\bđừng kể\b",
    ]

    if any(re.search(p, text) for p in secrecy_patterns):
        score += 15
        detected.append("Yêu cầu giữ bí mật")
        signals.append("Có dấu hiệu muốn người nhận không trao đổi với người khác.")

    # -----------------------------------------------------
    # Hành động
    # -----------------------------------------------------

    action_patterns = [
        r"\bclick\b",
        r"\bbấm\b",
        r"\bnhấn\b",
        r"\bgửi\b",
        r"\bcung cấp\b",
        r"\bđăng nhập\b",
        r"\bchuyển\b",
        r"\btải\b",
        r"\bcài\b",
    ]

    if any(re.search(p, text) for p in action_patterns):
        score += 10
        detected.append("Thúc đẩy hành động")
        signals.append("Tin nhắn yêu cầu người nhận thực hiện một hành động cụ thể.")

    # -----------------------------------------------------
    # Combo nguy hiểm
    # -----------------------------------------------------

    if (
        any(re.search(p, text) for p in otp_patterns)
        and any(re.search(p, text) for p in action_patterns)
    ):
        score += 12

    if (
        any(re.search(p, text) for p in money_patterns)
        and any(re.search(p, text) for p in urgency_patterns)
    ):
        score += 12

    if (
        any(re.search(p, text) for p in link_patterns)
        and any(re.search(p, text) for p in urgency_patterns)
    ):
        score += 10

    if (
        any(re.search(p, text) for p in impersonation_patterns)
        and any(re.search(p, text) for p in money_patterns)
    ):
        score += 12

    if (
        any(re.search(p, text) for p in threat_patterns)
        and any(re.search(p, text) for p in action_patterns)
    ):
        score += 10

    # -----------------------------------------------------
    # Giới hạn
    # -----------------------------------------------------

    score = min(100, max(0, score))

    # -----------------------------------------------------
    # Mức độ
    # -----------------------------------------------------

    if score >= 70:
        level = "Rất cao"
    elif score >= 45:
        level = "Cao"
    elif score >= 25:
        level = "Trung bình"
    else:
        level = "Thấp"

    return {
        "risk_score": score,
        "risk_level": level,
        "detected_strategies": detected,
        "manipulation_signals": signals,
    }


# =========================================================
# 9. FALLBACK ANALYSIS
# =========================================================

def fallback_analysis(message, local_result=None):
    """
    Phân tích hoàn toàn bằng rule engine khi Gemini không hoạt động.
    """

    if local_result is None:
        local_result = calculate_risk_score(message)

    score = local_result["risk_score"]
    level = local_result["risk_level"]

    strategies = local_result.get("detected_strategies", [])
    signals = local_result.get("manipulation_signals", [])

    if score >= 70:

        main_strategy = (
            "Tin nhắn có nhiều dấu hiệu gây áp lực, "
            "yêu cầu hành động hoặc thu thập thông tin nhạy cảm."
        )

        mechanism = (
            "Người gửi có thể đang kết hợp nhiều kỹ thuật như "
            "tạo khẩn cấp, gây sợ hãi, mạo danh hoặc đánh vào lợi ích."
        )

    elif score >= 45:

        main_strategy = (
            "Tin nhắn có một số dấu hiệu đáng chú ý liên quan đến "
            "tài khoản, tiền bạc, liên kết hoặc hành động khẩn cấp."
        )

        mechanism = (
            "Nội dung có thể đang tạo áp lực để người nhận "
            "ra quyết định nhanh trước khi kiểm tra thông tin."
        )

    elif score >= 25:

        main_strategy = (
            "Tin nhắn có một vài dấu hiệu cần kiểm tra thêm."
        )

        mechanism = (
            "Một số yếu tố trong nội dung có thể khiến người nhận "
            "hành động mà chưa xác minh nguồn gửi."
        )

    else:

        main_strategy = (
            "Chưa phát hiện nhiều dấu hiệu rõ ràng từ các quy tắc hiện tại."
        )

        mechanism = (
            "Không có nhiều tín hiệu thuộc các nhóm rủi ro được hệ thống theo dõi."
        )

    recommended_actions = [
        "Không cung cấp mật khẩu hoặc mã OTP.",
        "Không chuyển tiền chỉ vì một tin nhắn yêu cầu.",
        "Không bấm vào liên kết đáng ngờ.",
        "Kiểm tra thông tin bằng kênh chính thức.",
        "Nếu thấy bất thường, hãy hỏi phụ huynh, giáo viên hoặc người lớn đáng tin cậy."
    ]

    evidence = []

    if signals:
        evidence.extend(signals)

    if not evidence:
        evidence.append(
            "Chưa phát hiện tín hiệu mạnh theo bộ quy tắc hiện tại."
        )

    reasoning = (
        "Kết quả dự phòng được tạo bằng bộ quy tắc nhận diện dấu hiệu "
        "lừa đảo của ứng dụng, không phải bởi Gemini."
    )

    return {
        "risk_score": score,
        "risk_level": level,
        "main_strategy": main_strategy,
        "detected_strategies": strategies,
        "manipulation_signals": signals,
        "evidence": evidence,
        "psychological_mechanism": mechanism,
        "recommended_actions": recommended_actions,
        "reasoning": reasoning,
    }


# =========================================================
# 10. PROMPT GEMINI
# =========================================================

ANALYSIS_SYSTEM = """
Bạn là trợ lý phân tích an toàn số cho học sinh THPT Việt Nam.

Nhiệm vụ:
Phân tích một tin nhắn và xác định các dấu hiệu có thể liên quan đến lừa đảo,
mạo danh, thao túng tâm lý, thu thập thông tin hoặc thúc đẩy hành động nguy hiểm.

QUAN TRỌNG:
- Không tự bịa thông tin.
- Chỉ dựa trên nội dung được cung cấp.
- Không khẳng định chắc chắn rằng một tin nhắn là lừa đảo nếu chưa đủ bằng chứng.
- Điểm rủi ro cuối cùng được ứng dụng tính bằng bộ quy tắc riêng.
- Gemini chỉ hỗ trợ giải thích và nhận diện dấu hiệu.
- Trả về JSON hợp lệ.
"""


# =========================================================
# 11. GỌI GEMINI
# =========================================================

def call_gemini(message):
    """
    Gọi Gemini REST API.

    Trả về:
        success: bool
        data: dict | None
        error: str | None
        status: int | None
    """

    if not API_KEY:

        return {
            "success": False,
            "data": None,
            "error": "Chưa tìm thấy GEMINI_API_KEY trong Streamlit Secrets.",
            "status": None,
        }

    allowed, remaining = can_call_api()

    if not allowed:

        return {
            "success": False,
            "data": None,
            "error": (
                f"Đang chờ cooldown. "
                f"Vui lòng thử lại sau {remaining:.1f} giây."
            ),
            "status": "COOLDOWN",
        }

    mark_api_call()

    # Không gửi nội dung quá dài
    message = safe_text(message)[:MAX_ANALYSIS_CHARS]

    url = (
        f"https://generativelanguage.googleapis.com/"
        f"v1beta/models/{MODEL}:generateContent"
    )

    # -----------------------------------------------------
    # JSON schema đơn giản
    # -----------------------------------------------------

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "main_strategy": {
                "type": "STRING"
            },
            "detected_strategies": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                }
            },
            "manipulation_signals": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                }
            },
            "evidence": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                }
            },
            "psychological_mechanism": {
                "type": "STRING"
            },
            "recommended_actions": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                }
            },
            "reasoning": {
                "type": "STRING"
            }
        },
        "required": [
            "main_strategy",
            "detected_strategies",
            "manipulation_signals",
            "evidence",
            "psychological_mechanism",
            "recommended_actions",
            "reasoning"
        ]
    }

    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": ANALYSIS_SYSTEM
                }
            ]
        },

        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Hãy phân tích tin nhắn sau:\n\n"
                            f"{message}\n\n"
                            "Chỉ trả về JSON theo schema được yêu cầu."
                        )
                    }
                ]
            }
        ],

        "generationConfig": {
            "maxOutputTokens": 1000,

            # Gemini 3.8 không cần temperature
            "responseMimeType": "application/json",

            "responseSchema": response_schema
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY,
    }

    # -----------------------------------------------------
    # Retry
    # -----------------------------------------------------

    last_error = None
    last_status = None

    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):

        try:

            request = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST"
            )

            with urllib.request.urlopen(
                request,
                timeout=GEMINI_TIMEOUT
            ) as response:

                status_code = response.getcode()

                raw = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

            last_status = status_code

            # -------------------------------------------------
            # HTTP thành công
            # -------------------------------------------------

            if 200 <= status_code < 300:

                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:

                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            "Gemini trả về dữ liệu không phải JSON hợp lệ."
                        ),
                        "status": status_code,
                    }

                # ---------------------------------------------
                # Lấy text
                # ---------------------------------------------

                candidates = result.get("candidates", [])

                if not candidates:

                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            "Gemini không trả về candidate nào."
                        ),
                        "status": status_code,
                    }

                candidate = candidates[0]

                finish_reason = candidate.get(
                    "finishReason",
                    ""
                )

                # ---------------------------------------------
                # Kiểm tra safety
                # ---------------------------------------------

                if finish_reason in {
                    "SAFETY",
                    "BLOCKLIST",
                    "PROHIBITED_CONTENT",
                    "SPII"
                }:

                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            "Gemini đã chặn phản hồi vì bộ lọc an toàn."
                        ),
                        "status": status_code,
                    }

                content = candidate.get("content", {})

                parts = content.get("parts", [])

                text_parts = []

                for part in parts:

                    if isinstance(part, dict):

                        part_text = part.get("text")

                        if part_text:
                            text_parts.append(part_text)

                response_text = "\n".join(text_parts).strip()

                if not response_text:

                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            f"Gemini không trả về nội dung. "
                            f"finishReason={finish_reason or 'UNKNOWN'}"
                        ),
                        "status": status_code,
                    }

                parsed = extract_json(response_text)

                if parsed is None:

                    return {
                        "success": False,
                        "data": None,
                        "error": (
                            "Gemini trả về nội dung nhưng không parse được JSON."
                        ),
                        "status": status_code,
                    }

                return {
                    "success": True,
                    "data": parsed,
                    "error": None,
                    "status": status_code,
                }

        # =====================================================
        # HTTP ERROR
        # =====================================================

        except urllib.error.HTTPError as e:

            status_code = e.code
            last_status = status_code

            try:
                error_body = e.read().decode(
                    "utf-8",
                    errors="replace"
                )
            except Exception:
                error_body = ""

            # Parse Google error
            error_message = ""

            try:

                parsed_error = json.loads(error_body)

                error_message = (
                    parsed_error
                    .get("error", {})
                    .get("message", "")
                )

            except Exception:
                pass

            if not error_message:
                error_message = error_body[:600]

            # -------------------------------------------------
            # 400
            # -------------------------------------------------

            if status_code == 400:

                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"HTTP 400 - Request không hợp lệ.\n"
                        f"{error_message}"
                    ),
                    "status": 400,
                }

            # -------------------------------------------------
            # 401
            # -------------------------------------------------

            if status_code == 401:

                return {
                    "success": False,
                    "data": None,
                    "error": (
                        "HTTP 401 - API key không hợp lệ "
                        "hoặc không được xác thực."
                    ),
                    "status": 401,
                }

            # -------------------------------------------------
            # 403
            # -------------------------------------------------

            if status_code == 403:

                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"HTTP 403 - API key không có quyền "
                        f"gọi API này.\n{error_message}"
                    ),
                    "status": 403,
                }

            # -------------------------------------------------
            # 404
            # -------------------------------------------------

            if status_code == 404:

                return {
                    "success": False,
                    "data": None,
                    "error": (
                        f"HTTP 404 - Không tìm thấy model/API endpoint.\n"
                        f"Model: {MODEL}\n"
                        f"{error_message}"
                    ),
                    "status": 404,
                }

            # -------------------------------------------------
            # 429
            # -------------------------------------------------

            if status_code == 429:

                return {
                    "success": False,
                    "data": None,
                    "error": (
                        "HTTP 429 - Gemini đang giới hạn "
                        "tần suất hoặc quota API.\n"
                        f"{error_message}"
                    ),
                    "status": 429,
                }

            # -------------------------------------------------
            # 500 / 502 / 503 / 504
            # -------------------------------------------------

            if status_code in {500, 502, 503, 504}:

                last_error = (
                    f"HTTP {status_code} - Máy chủ Gemini "
                    f"đang gặp lỗi tạm thời.\n"
                    f"{error_message}"
                )

                if attempt < GEMINI_MAX_ATTEMPTS:

                    # exponential backoff nhẹ
                    delay = (2 ** attempt) + random.uniform(
                        0.2,
                        0.8
                    )

                    time.sleep(delay)

                    continue

                return {
                    "success": False,
                    "data": None,
                    "error": last_error,
                    "status": status_code,
                }

            # -------------------------------------------------
            # HTTP khác
            # -------------------------------------------------

            return {
                "success": False,
                "data": None,
                "error": (
                    f"HTTP {status_code}.\n"
                    f"{error_message}"
                ),
                "status": status_code,
            }

        # =====================================================
        # URL ERROR
        # =====================================================

        except urllib.error.URLError as e:

            last_error = (
                "Không kết nối được tới Gemini API.\n"
                f"Chi tiết: {e}"
            )

            if attempt < GEMINI_MAX_ATTEMPTS:

                time.sleep(1)

                continue

            return {
                "success": False,
                "data": None,
                "error": last_error,
                "status": "NETWORK",
            }

        # =====================================================
        # TIMEOUT
        # =====================================================

        except TimeoutError:

            last_error = (
                f"Gemini không phản hồi trong "
                f"{GEMINI_TIMEOUT} giây."
            )

            if attempt < GEMINI_MAX_ATTEMPTS:

                time.sleep(1)

                continue

            return {
                "success": False,
                "data": None,
                "error": last_error,
                "status": "TIMEOUT",
            }

        # =====================================================
        # LỖI KHÁC
        # =====================================================

        except Exception as e:

            return {
                "success": False,
                "data": None,
                "error": (
                    f"Lỗi không xác định khi gọi Gemini: {e}"
                ),
                "status": "UNKNOWN",
            }

    return {
        "success": False,
        "data": None,
        "error": last_error or "Gemini không phản hồi.",
        "status": last_status,
    }


# =========================================================
# 12. PHÂN TÍCH TIN NHẮN
# =========================================================

def analyze_message(message):

    # -----------------------------------------------------
    # Rule engine chạy trước
    # -----------------------------------------------------

    local_result = calculate_risk_score(message)

    fallback = fallback_analysis(
        message,
        local_result
    )

    # -----------------------------------------------------
    # Không có API key
    # -----------------------------------------------------

    if not API_KEY:

        st.session_state.last_gemini_status = "NO_KEY"
        st.session_state.last_gemini_error = (
            "Chưa cấu hình GEMINI_API_KEY."
        )

        return fallback, "fallback"

    # -----------------------------------------------------
    # Gọi Gemini
    # -----------------------------------------------------

    result = call_gemini(message)

    st.session_state.last_gemini_status = result.get("status")
    st.session_state.last_gemini_error = result.get("error")

    # -----------------------------------------------------
    # Gemini thành công
    # -----------------------------------------------------

    if result.get("success"):

        ai_data = result.get("data") or {}

        # -------------------------------------------------
        # Lấy từng field an toàn
        # -------------------------------------------------

        main_strategy = safe_text(
            ai_data.get("main_strategy")
        )

        detected_strategies = ai_data.get(
            "detected_strategies"
        )

        manipulation_signals = ai_data.get(
            "manipulation_signals"
        )

        evidence = ai_data.get("evidence")

        psychological_mechanism = safe_text(
            ai_data.get("psychological_mechanism")
        )

        recommended_actions = ai_data.get(
            "recommended_actions"
        )

        reasoning = safe_text(
            ai_data.get("reasoning")
        )

        # -------------------------------------------------
        # Kiểm tra kiểu dữ liệu
        # -------------------------------------------------

        if not isinstance(detected_strategies, list):
            detected_strategies = []

        if not isinstance(manipulation_signals, list):
            manipulation_signals = []

        if not isinstance(evidence, list):
            evidence = []

        if not isinstance(recommended_actions, list):
            recommended_actions = []

        # -------------------------------------------------
        # Merge với fallback nếu Gemini thiếu dữ liệu
        # -------------------------------------------------

        if not main_strategy:
            main_strategy = fallback["main_strategy"]

        if not detected_strategies:
            detected_strategies = fallback["detected_strategies"]

        if not manipulation_signals:
            manipulation_signals = fallback["manipulation_signals"]

        if not evidence:
            evidence = fallback["evidence"]

        if not psychological_mechanism:
            psychological_mechanism = (
                fallback["psychological_mechanism"]
            )

        if not recommended_actions:
            recommended_actions = (
                fallback["recommended_actions"]
            )

        if not reasoning:
            reasoning = fallback["reasoning"]

        # -------------------------------------------------
        # QUAN TRỌNG:
        # Điểm rủi ro lấy từ local engine
        # -------------------------------------------------

        final_result = {
            "risk_score": local_result["risk_score"],
            "risk_level": local_result["risk_level"],

            "main_strategy": main_strategy,

            "detected_strategies": detected_strategies,

            "manipulation_signals": manipulation_signals,

            "evidence": evidence,

            "psychological_mechanism": (
                psychological_mechanism
            ),

            "recommended_actions": recommended_actions,

            "reasoning": reasoning,
        }

        return final_result, "gemini"

    # -----------------------------------------------------
    # Gemini lỗi -> fallback
    # -----------------------------------------------------

    return fallback, "fallback"


# =========================================================
# 13. GAME DATA
# =========================================================

SCENARIOS = [

    {
        "question": (
            "Bạn nhận được tin nhắn: "
            "\"Bạn đã trúng thưởng. Hãy bấm vào link và đăng nhập "
            "để nhận quà trong 10 phút.\" Bạn nên làm gì?"
        ),
        "answer": "Không bấm link và kiểm tra thông tin bằng kênh chính thức.",
        "explanation": (
            "Tin nhắn sử dụng phần thưởng và giới hạn thời gian "
            "để tạo áp lực. Không nên đăng nhập qua liên kết lạ."
        )
    },

    {
        "question": (
            "Một người tự xưng là nhân viên ngân hàng yêu cầu "
            "bạn đọc mã OTP để xác minh tài khoản. Bạn nên làm gì?"
        ),
        "answer": "Không cung cấp mã OTP.",
        "explanation": (
            "Mã OTP là thông tin xác thực quan trọng. "
            "Không nên đọc mã cho người khác qua tin nhắn hoặc cuộc gọi."
        )
    },

    {
        "question": (
            "Một tài khoản lạ nhắn rằng tài khoản của bạn sắp bị khóa "
            "và yêu cầu đăng nhập vào một đường link. Điều gì đáng ngờ?"
        ),
        "answer": "Dấu hiệu tạo khẩn cấp và dẫn người dùng đến liên kết.",
        "explanation": (
            "Kẻ lừa đảo thường tạo cảm giác gấp để người nhận "
            "không có thời gian kiểm tra."
        )
    },

    {
        "question": (
            "Một người trên mạng nói rằng bạn được nhận quà miễn phí "
            "nhưng phải gửi thông tin cá nhân trước. Bạn nên làm gì?"
        ),
        "answer": "Không gửi thông tin cá nhân khi chưa xác minh.",
        "explanation": (
            "Quà tặng có thể được sử dụng làm mồi để thu thập "
            "thông tin cá nhân."
        )
    },

    {
        "question": (
            "Bạn nhận được tin nhắn yêu cầu chuyển tiền ngay "
            "và nói rằng không được kể cho người khác. Đây là dấu hiệu gì?"
        ),
        "answer": "Tạo áp lực và yêu cầu giữ bí mật.",
        "explanation": (
            "Yêu cầu chuyển tiền kèm việc giữ bí mật là dấu hiệu "
            "cần đặc biệt thận trọng."
        )
    },

    {
        "question": (
            "Một người tự xưng là giáo viên yêu cầu bạn gửi mật khẩu "
            "tài khoản học tập qua tin nhắn. Bạn nên làm gì?"
        ),
        "answer": "Không gửi mật khẩu và xác minh với giáo viên bằng kênh khác.",
        "explanation": (
            "Không nên gửi mật khẩu qua tin nhắn, kể cả khi người gửi "
            "tự xưng là người quen."
        )
    },

    {
        "question": (
            "Một đường link lạ yêu cầu bạn nhập CCCD, số điện thoại "
            "và thông tin tài khoản để nhận phần thưởng. Bạn nên làm gì?"
        ),
        "answer": "Không nhập thông tin và kiểm tra nguồn của chương trình.",
        "explanation": (
            "Nhiều thông tin cá nhân cùng với phần thưởng và link lạ "
            "là dấu hiệu cần cảnh giác."
        )
    },

    {
        "question": (
            "Một người nhắn rằng nếu bạn không chuyển tiền trong 5 phút "
            "thì sẽ bị phạt. Bạn nên làm gì?"
        ),
        "answer": "Không chuyển tiền vội; xác minh thông tin trước.",
        "explanation": (
            "Đây là cách tạo sợ hãi và khẩn cấp để thúc đẩy hành động."
        )
    },

]


# =========================================================
# 14. CHỌN CÂU HỎI GAME
# =========================================================

def get_new_scenario():

    available = [
        item
        for index, item in enumerate(SCENARIOS)
        if index not in st.session_state.used_scenarios
    ]

    if not available:

        st.session_state.used_scenarios = []

        available = SCENARIOS.copy()

    scenario = random.choice(available)

    index = SCENARIOS.index(scenario)

    st.session_state.used_scenarios.append(index)

    st.session_state.game_question = scenario
    st.session_state.game_result = None
    st.session_state.game_answer = None

    st.session_state.game_round += 1


# =========================================================
# 15. GIAO DIỆN TAB
# =========================================================

tab1, tab2, tab3 = st.tabs(
    [
        "🔎 Phân tích tin nhắn",
        "🎮 Thử thách",
        "ℹ️ Hướng dẫn"
    ]
)


# =========================================================
# TAB 1 - PHÂN TÍCH
# =========================================================

with tab1:

    st.subheader("🔎 Phân tích tin nhắn đáng ngờ")

    st.write(
        "Dán nội dung tin nhắn bạn muốn kiểm tra vào ô bên dưới."
    )

    message = st.text_area(
        "Nội dung tin nhắn",
        height=220,
        max_chars=MAX_ANALYSIS_CHARS,
        placeholder=(
            "Ví dụ:\n"
            "Tài khoản của bạn sắp bị khóa. "
            "Hãy bấm vào link và nhập mã OTP để xác minh..."
        )
    )

    col1, col2 = st.columns([1, 4])

    with col1:

        analyze_button = st.button(
            "🛡️ Phân tích",
            use_container_width=True,
            type="primary"
        )

    with col2:

        st.caption(
            f"Giới hạn nội dung: {MAX_ANALYSIS_CHARS:,} ký tự"
        )

    if analyze_button:

        if not message.strip():

            st.warning(
                "Bạn hãy nhập nội dung tin nhắn trước."
            )

        else:

            allowed, remaining = can_call_api()

            if not allowed:

                st.warning(
                    f"Bạn thao tác hơi nhanh. "
                    f"Hãy chờ khoảng {remaining:.1f} giây rồi thử lại."
                )

            else:

                st.session_state.analysis_count += 1

                with st.spinner(
                    "Đang phân tích nội dung..."
                ):

                    result, source = analyze_message(
                        message
                    )

                st.session_state.last_analysis = result
                st.session_state.last_source = source


    # -----------------------------------------------------
    # HIỂN THỊ KẾT QUẢ
    # -----------------------------------------------------

    if "last_analysis" in st.session_state:

        result = st.session_state.last_analysis

        score = result.get(
            "risk_score",
            0
        )

        level = result.get(
            "risk_level",
            "Không xác định"
        )

        source = st.session_state.get(
            "last_source",
            "fallback"
        )

        st.divider()

        st.subheader("📊 Kết quả")

        col1, col2 = st.columns(2)

        with col1:

            st.metric(
                "Mức điểm rủi ro",
                f"{score}/100"
            )

        with col2:

            st.metric(
                "Mức độ",
                level
            )

        # -------------------------------------------------
        # Thanh progress
        # -------------------------------------------------

        st.progress(
            min(max(score / 100, 0.0), 1.0)
        )

        # -------------------------------------------------
        # Màu cảnh báo
        # -------------------------------------------------

        if score >= 70:

            st.markdown(
                """
                <div class="danger-box">
                    <b>🚨 Cần đặc biệt cảnh giác</b><br>
                    Nội dung có nhiều dấu hiệu rủi ro.
                </div>
                """,
                unsafe_allow_html=True
            )

        elif score >= 45:

            st.markdown(
                """
                <div class="warning-box">
                    <b>⚠️ Có dấu hiệu đáng chú ý</b><br>
                    Hãy xác minh thông tin trước khi hành động.
                </div>
                """,
                unsafe_allow_html=True
            )

        elif score >= 25:

            st.markdown(
                """
                <div class="info-box">
                    <b>🔎 Nên kiểm tra thêm</b><br>
                    Một số yếu tố trong tin nhắn cần được xác minh.
                </div>
                """,
                unsafe_allow_html=True
            )

        else:

            st.markdown(
                """
                <div class="safe-box">
                    <b>🟢 Chưa phát hiện nhiều dấu hiệu rõ ràng</b><br>
                    Tuy nhiên vẫn nên kiểm tra nguồn gửi trước khi hành động.
                </div>
                """,
                unsafe_allow_html=True
            )

        st.write("")

        # -------------------------------------------------
        # Nguồn phân tích
        # -------------------------------------------------

        if source == "gemini":

            st.success(
                "🤖 Gemini đã hỗ trợ phân tích nội dung."
            )

        else:

            error = st.session_state.get(
                "last_gemini_error"
            )

            status = st.session_state.get(
                "last_gemini_status"
            )

            st.warning(
                "🛡️ Gemini không hoàn thành lần phân tích này. "
                "Đã sử dụng bộ phân tích dự phòng."
            )

            # Hiển thị lỗi thật
            if error:

                with st.expander(
                    "🔧 Xem lý do Gemini không hoạt động"
                ):

                    st.code(
                        f"Status: {status}\n\n{error}"
                    )

                    st.caption(
                        "Thông tin này dùng để debug. "
                        "Không ảnh hưởng đến bộ phân tích dự phòng."
                    )

        # -------------------------------------------------
        # Chiến thuật
        # -------------------------------------------------

        st.subheader("🎯 Chiến thuật được phát hiện")

        strategies = result.get(
            "detected_strategies",
            []
        )

        if strategies:

            for item in strategies:

                st.markdown(
                    f"- {safe_text(item)}"
                )

        else:

            st.write(
                "Chưa phát hiện chiến thuật rõ ràng."
            )

        # -------------------------------------------------
        # Dấu hiệu thao túng
        # -------------------------------------------------

        st.subheader("🧠 Dấu hiệu thao túng")

        signals = result.get(
            "manipulation_signals",
            []
        )

        if signals:

            for item in signals:

                st.markdown(
                    f"- {safe_text(item)}"
                )

        else:

            st.write(
                "Chưa phát hiện dấu hiệu thao túng rõ ràng."
            )

        # -------------------------------------------------
        # Bằng chứng
        # -------------------------------------------------

        st.subheader("🔍 Bằng chứng")

        evidence = result.get(
            "evidence",
            []
        )

        if evidence:

            for item in evidence:

                st.markdown(
                    f"- {safe_text(item)}"
                )

        else:

            st.write(
                "Không có bằng chứng cụ thể được ghi nhận."
            )

        # -------------------------------------------------
        # Cơ chế tâm lý
        # -------------------------------------------------

        st.subheader("🧠 Cơ chế tâm lý")

        st.write(
            result.get(
                "psychological_mechanism",
                ""
            )
        )

        # -------------------------------------------------
        # Hành động đề xuất
        # -------------------------------------------------

        st.subheader("✅ Bạn nên làm gì?")

        actions = result.get(
            "recommended_actions",
            []
        )

        for action in actions:

            st.markdown(
                f"- {safe_text(action)}"
            )

        # -------------------------------------------------
        # Lý do
        # -------------------------------------------------

        st.subheader("💡 Giải thích")

        st.write(
            result.get(
                "reasoning",
                ""
            )
        )


# =========================================================
# TAB 2 - GAME
# =========================================================

with tab2:

    st.subheader("🎮 Thử thách nhận diện lừa đảo")

    st.write(
        "Hãy đọc tình huống và chọn cách xử lý an toàn nhất."
    )

    if st.session_state.game_question is None:

        if st.button(
            "🎲 Bắt đầu thử thách",
            type="primary"
        ):

            get_new_scenario()

            st.rerun()

    else:

        scenario = st.session_state.game_question

        st.markdown(
            f"""
            <div class="risk-card">
                <b>Vòng {st.session_state.game_round}</b>
                <br><br>
                {scenario["question"]}
            </div>
            """,
            unsafe_allow_html=True
        )

        options = [
            scenario["answer"],
            "Làm theo ngay vì người gửi nói rất khẩn cấp.",
            "Gửi thêm thông tin cá nhân để họ kiểm tra.",
            "Chuyển tiếp tin nhắn cho nhiều người mà không kiểm tra."
        ]

        random_options = options.copy()

        # Không random để tránh thay đổi lựa chọn sau rerun
        if "game_options" not in st.session_state:
            random_options = options.copy()
            random.shuffle(random_options)
            st.session_state.game_options = random_options

        selected = st.radio(
            "Bạn sẽ làm gì?",
            st.session_state.game_options,
            key="game_answer"
        )

        if st.button(
            "✅ Kiểm tra đáp án",
            type="primary"
        ):

            if selected == scenario["answer"]:

                st.session_state.game_result = True

            else:

                st.session_state.game_result = False

        if st.session_state.game_result is not None:

            if st.session_state.game_result:

                st.success(
                    "🎉 Chính xác! Đây là cách xử lý an toàn hơn."
                )

            else:

                st.error(
                    "⚠️ Chưa đúng. Hãy chú ý đến các dấu hiệu gây áp lực, "
                    "yêu cầu thông tin hoặc liên kết đáng ngờ."
                )

            st.info(
                scenario["explanation"]
            )

            if st.button(
                "➡️ Tình huống tiếp theo"
            ):

                st.session_state.pop(
                    "game_options",
                    None
                )

                get_new_scenario()

                st.rerun()


# =========================================================
# TAB 3 - HƯỚNG DẪN
# =========================================================

with tab3:

    st.subheader("ℹ️ Cách sử dụng")

    st.markdown(
        """
        ### 🛡️ 1. Dán tin nhắn

        Sao chép nội dung tin nhắn đáng ngờ vào phần
        **Phân tích tin nhắn**.

        ### 🔎 2. Xem các dấu hiệu

        Hệ thống kiểm tra các nhóm dấu hiệu như:

        - Yêu cầu mật khẩu
        - Yêu cầu mã OTP
        - Chuyển tiền
        - Liên kết đáng ngờ
        - Tạo cảm giác khẩn cấp
        - Đe dọa
        - Mạo danh
        - Thu thập thông tin cá nhân
        - Quà tặng / phần thưởng
        - Yêu cầu giữ bí mật
        - Thúc đẩy hành động

        ### 🧠 3. Không chỉ dựa vào điểm số

        Điểm số chỉ là tín hiệu hỗ trợ. Một tin nhắn có điểm thấp
        vẫn cần được kiểm tra nếu nguồn gửi hoặc yêu cầu có điều gì
        bất thường.

        ### 🚫 4. Không cung cấp thông tin nhạy cảm

        Không chia sẻ mật khẩu, mã OTP hoặc thông tin cá nhân
        chỉ vì một tin nhắn yêu cầu.

        ### 👨‍👩‍👧 5. Khi không chắc chắn

        Hãy hỏi phụ huynh, giáo viên hoặc một người lớn đáng tin cậy
        trước khi thực hiện hành động quan trọng.
        """
    )

    st.divider()

    st.subheader("🔧 Trạng thái hệ thống")

    st.write(
        f"**Model:** `{MODEL}`"
    )

    st.write(
        f"**Số lần phân tích:** "
        f"`{st.session_state.analysis_count}`"
    )

    if API_KEY:

        st.success(
            "GEMINI_API_KEY đã được phát hiện trong Secrets."
        )

    else:

        st.error(
            "Chưa tìm thấy GEMINI_API_KEY trong Secrets."
        )

    if st.session_state.last_gemini_status:

        st.write(
            f"**Trạng thái Gemini gần nhất:** "
            f"`{st.session_state.last_gemini_status}`"
        )
