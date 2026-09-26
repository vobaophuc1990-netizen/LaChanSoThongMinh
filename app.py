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

MODEL = "gemini-3.8-flash"

COOLDOWN_SECONDS = 5

MAX_ANALYSIS_CHARS = 12000

GEMINI_TIMEOUT = 45

GEMINI_MAX_ATTEMPTS = 3


try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    API_KEY = ""


# =========================================================
# 2. SESSION STATE
# =========================================================

if "last_api_call" not in st.session_state:
    st.session_state.last_api_call = 0.0

if "game_question" not in st.session_state:
    st.session_state.game_question = None

if "game_result" not in st.session_state:
    st.session_state.game_result = None

if "game_answer" not in st.session_state:
    st.session_state.game_answer = None

if "used_scenario_ids" not in st.session_state:
    st.session_state.used_scenario_ids = []

if "game_round" not in st.session_state:
    st.session_state.game_round = 0

if "analysis_count" not in st.session_state:
    st.session_state.analysis_count = 0


# =========================================================
# 3. CSS
# =========================================================

st.markdown(
    """
    <style>

    textarea, input {
        font-family: "Segoe UI", "Arial", sans-serif !important;
        ime-mode: auto !important;
    }

    .main-title {
        font-size: 42px;
        font-weight: 800;
        text-align: center;
        margin-bottom: 5px;
    }

    .subtitle {
        text-align: center;
        color: #777;
        font-size: 18px;
        margin-bottom: 30px;
    }

    .danger-box {
        padding: 20px;
        border-radius: 15px;
        background-color: rgba(255, 80, 80, 0.08);
        border: 1px solid rgba(255, 80, 80, 0.25);
    }

    .safe-box {
        padding: 20px;
        border-radius: 15px;
        background-color: rgba(50, 200, 100, 0.08);
        border: 1px solid rgba(50, 200, 100, 0.25);
    }

    .warning-box {
        padding: 20px;
        border-radius: 15px;
        background-color: rgba(255, 190, 50, 0.10);
        border: 1px solid rgba(255, 190, 50, 0.30);
    }

    .keyword {
        display: inline-block;
        padding: 5px 10px;
        margin: 3px;
        border-radius: 8px;
        background: #ffdddd;
    }

    .game-counter {
        text-align: center;
        font-size: 17px;
        font-weight: 700;
        margin: 10px 0 20px 0;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# 4. HEADER
# =========================================================

st.markdown(
    '<div class="main-title">🛡️ LÁ CHẮN SỐ THÔNG MINH</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    'Hệ thống phát hiện và phân tích thao túng tâm lý trong tin nhắn trực tuyến'
    '</div>',
    unsafe_allow_html=True
)


# =========================================================
# 5. COOLDOWN API
# =========================================================

def can_call_api():

    now = time.time()

    elapsed = (
        now
        - st.session_state.last_api_call
    )

    if elapsed < COOLDOWN_SECONDS:

        remaining = int(
            COOLDOWN_SECONDS
            - elapsed
            + 0.99
        )

        return False, remaining

    return True, 0


# =========================================================
# 6. JSON EXTRACTOR
# =========================================================

def extract_json(text):
    """
    Gemini có thể trả JSON:
        {...}

    hoặc:
        ```json
        {...}
        ```

    hoặc có văn bản trước/sau JSON.

    Hàm này cố gắng lấy JSON thực tế.
    """

    if not text:
        return None

    text = text.strip()

    # -----------------------------------------------------
    # Cách 1: JSON nguyên bản
    # -----------------------------------------------------

    try:
        return json.loads(text)
    except Exception:
        pass

    # -----------------------------------------------------
    # Cách 2: Code fence
    # -----------------------------------------------------

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned
    )

    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # -----------------------------------------------------
    # Cách 3: tìm JSON object
    # -----------------------------------------------------

    first = cleaned.find("{")

    if first != -1:

        depth = 0
        in_string = False
        escape = False

        for index in range(
            first,
            len(cleaned)
        ):

            char = cleaned[index]

            if in_string:

                if escape:

                    escape = False

                elif char == "\\":

                    escape = True

                elif char == '"':

                    in_string = False

                continue

            if char == '"':

                in_string = True

            elif char == "{":

                depth += 1

            elif char == "}":

                depth -= 1

                if depth == 0:

                    candidate = cleaned[
                        first:index + 1
                    ]

                    try:
                        return json.loads(
                            candidate
                        )
                    except Exception:
                        break

    # -----------------------------------------------------
    # Cách 4: JSON array
    # -----------------------------------------------------

    first = cleaned.find("[")

    if first != -1:

        depth = 0
        in_string = False
        escape = False

        for index in range(
            first,
            len(cleaned)
        ):

            char = cleaned[index]

            if in_string:

                if escape:

                    escape = False

                elif char == "\\":

                    escape = True

                elif char == '"':

                    in_string = False

                continue

            if char == '"':

                in_string = True

            elif char == "[":

                depth += 1

            elif char == "]":

                depth -= 1

                if depth == 0:

                    candidate = cleaned[
                        first:index + 1
                    ]

                    try:
                        return json.loads(
                            candidate
                        )
                    except Exception:
                        break

    return None


# =========================================================
# 7. GEMINI API
# =========================================================

def call_gemini(
    prompt,
    system_instruction,
    json_mode=True,
    max_attempts=GEMINI_MAX_ATTEMPTS
):

    if not API_KEY:

        return {
            "success": False,
            "error": (
                "Chưa cấu hình GEMINI_API_KEY."
            ),
            "error_code": "NO_API_KEY"
        }


    allowed, remaining = can_call_api()

    if not allowed:

        return {
            "success": False,
            "error": (
                f"⏳ Vui lòng chờ {remaining} giây "
                "trước khi gửi yêu cầu tiếp theo."
            ),
            "error_code": "COOLDOWN"
        }


    st.session_state.last_api_call = time.time()


    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{MODEL}:generateContent"
        f"?key={API_KEY}"
    )


    generation_config = {
        "temperature": 0.2,
        "maxOutputTokens": 1200
    }


    if json_mode:

        generation_config[
            "responseMimeType"
        ] = "application/json"


    data = {

        "systemInstruction": {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        },

        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],

        "generationConfig": generation_config
    }


    payload = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")


    last_error_code = None


    for attempt in range(
        max_attempts
    ):

        try:

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type":
                        "application/json; charset=utf-8"
                },
                method="POST"
            )


            with urllib.request.urlopen(
                req,
                timeout=GEMINI_TIMEOUT
            ) as response:

                raw_response = (
                    response
                    .read()
                    .decode(
                        "utf-8",
                        errors="ignore"
                    )
                )


            result = json.loads(
                raw_response
            )


            candidates = result.get(
                "candidates",
                []
            )


            if not candidates:

                return {
                    "success": False,
                    "error": (
                        "Gemini không trả về candidate."
                    ),
                    "error_code":
                        "EMPTY_RESPONSE"
                }


            candidate = candidates[0]


            finish_reason = candidate.get(
                "finishReason",
                ""
            )


            if finish_reason in [
                "SAFETY",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII"
            ]:

                return {
                    "success": False,
                    "error": (
                        "Gemini đã chặn phản hồi "
                        "vì chính sách an toàn nội dung."
                    ),
                    "error_code": "SAFETY"
                }


            content = candidate.get(
                "content",
                {}
            )


            parts = content.get(
                "parts",
                []
            )


            response_text = ""


            for part in parts:

                if isinstance(
                    part,
                    dict
                ):

                    part_text = part.get(
                        "text",
                        ""
                    )

                    if part_text:

                        response_text += (
                            part_text
                        )


            response_text = (
                response_text.strip()
            )


            if not response_text:

                return {
                    "success": False,
                    "error": (
                        "Gemini trả về nội dung rỗng."
                    ),
                    "error_code":
                        "EMPTY_TEXT"
                }


            return {
                "success": True,
                "text": response_text
            }


        # =================================================
        # HTTP ERROR
        # =================================================

        except urllib.error.HTTPError as e:

            last_error_code = e.code


            # -------------------------------------------------
            # 503
            # -------------------------------------------------

            if e.code == 503:

                if attempt < max_attempts - 1:

                    base_delay = (
                        2 ** attempt
                    )

                    jitter = random.uniform(
                        0.5,
                        1.5
                    )

                    wait_time = min(
                        base_delay + jitter,
                        8
                    )

                    with st.spinner(
                        "⏳ Gemini đang bận, "
                        f"thử lại sau "
                        f"{wait_time:.1f} giây..."
                    ):

                        time.sleep(
                            wait_time
                        )

                    continue


                return {
                    "success": False,
                    "error": (
                        "⚠️ Gemini đang quá tải."
                    ),
                    "error_code": 503
                }


            # -------------------------------------------------
            # 429
            # -------------------------------------------------

            if e.code == 429:

                return {
                    "success": False,
                    "error": (
                        "⚠️ Gemini đang giới hạn API "
                        "(HTTP 429)."
                    ),
                    "error_code": 429
                }


            # -------------------------------------------------
            # 400
            # -------------------------------------------------

            if e.code == 400:

                try:

                    error_body = (
                        e.read()
                        .decode(
                            "utf-8",
                            errors="ignore"
                        )
                    )

                except Exception:

                    error_body = ""


                return {
                    "success": False,
                    "error": (
                        "❌ Yêu cầu gửi tới Gemini "
                        "không hợp lệ (HTTP 400).\n\n"
                        f"{error_body[:500]}"
                    ),
                    "error_code": 400
                }


            # -------------------------------------------------
            # 401 / 403
            # -------------------------------------------------

            if e.code in [
                401,
                403
            ]:

                return {
                    "success": False,
                    "error": (
                        f"🔑 API key hoặc quyền truy cập "
                        f"có vấn đề (HTTP {e.code})."
                    ),
                    "error_code": e.code
                }


            # -------------------------------------------------
            # 500 / 502 / 504
            # -------------------------------------------------

            if e.code in [
                500,
                502,
                504
            ]:

                if attempt < max_attempts - 1:

                    wait_time = min(
                        2 ** attempt + 1,
                        6
                    )

                    time.sleep(
                        wait_time
                    )

                    continue


                return {
                    "success": False,
                    "error": (
                        f"⚠️ Gemini gặp lỗi "
                        f"HTTP {e.code}."
                    ),
                    "error_code": e.code
                }


            return {
                "success": False,
                "error": (
                    f"❌ Gemini API lỗi HTTP {e.code}."
                ),
                "error_code": e.code
            }


        # =================================================
        # NETWORK
        # =================================================

        except urllib.error.URLError:

            last_error_code = "NETWORK"


            if attempt < max_attempts - 1:

                time.sleep(
                    2 ** attempt
                )

                continue


            return {
                "success": False,
                "error": (
                    "🌐 Không kết nối được tới Gemini."
                ),
                "error_code": "NETWORK"
            }


        # =================================================
        # TIMEOUT
        # =================================================

        except TimeoutError:

            last_error_code = "TIMEOUT"


            if attempt < max_attempts - 1:

                time.sleep(2)

                continue


            return {
                "success": False,
                "error": (
                    "⏱️ Gemini phản hồi quá lâu."
                ),
                "error_code": "TIMEOUT"
            }


        # =================================================
        # JSON ERROR
        # =================================================

        except json.JSONDecodeError:

            return {
                "success": False,
                "error": (
                    "❌ Gemini trả về dữ liệu "
                    "không hợp lệ."
                ),
                "error_code":
                    "INVALID_RESPONSE"
            }


        # =================================================
        # OTHER
        # =================================================

        except Exception as e:

            return {
                "success": False,
                "error": (
                    f"❌ Lỗi hệ thống: {str(e)}"
                ),
                "error_code":
                    "UNKNOWN"
            }


    return {
        "success": False,
        "error": (
            "⚠️ Không thể nhận phản hồi Gemini."
        ),
        "error_code": last_error_code
    }


# =========================================================
# 8. BỘ TỪ KHÓA RỦI RO
# =========================================================

PASSWORD_KEYWORDS = [
    "mật khẩu",
    "mat khau",
    "password",
    "pass",
    "mã đăng nhập",
    "ma dang nhap",
    "thông tin đăng nhập",
    "thong tin dang nhap"
]


OTP_KEYWORDS = [
    "otp",
    "mã otp",
    "ma otp",
    "mã xác thực",
    "ma xac thuc",
    "mã xác nhận",
    "ma xac nhan",
    "mã bảo mật",
    "ma bao mat",
    "verification code",
    "mã code",
    "ma code"
]


MONEY_ACTION_KEYWORDS = [
    "chuyển tiền",
    "chuyen tien",
    "chuyển khoản",
    "chuyen khoan",
    "gửi tiền",
    "gui tien",
    "nộp tiền",
    "nop tien",
    "thanh toán",
    "thanh toan",
    "nạp tiền",
    "nap tien",
    "gửi phí",
    "gui phi",
    "đóng phí",
    "dong phi",
    "đóng tiền",
    "dong tien",
    "nộp phí",
    "nop phi",
    "phí kích hoạt",
    "phi kich hoat"
]


MONEY_UNIT_KEYWORDS = [
    "tỷ",
    "ty",
    "triệu",
    "trieu",
    "nghìn",
    "nghin",
    "ngàn",
    "ngan",
    "vnđ",
    "vnd",
    "đồng",
    "dong"
]


LINK_KEYWORDS = [
    "http://",
    "https://",
    "www.",
    "bit.ly",
    "tinyurl",
    "goo.gl",
    "link này",
    "link nay",
    "bấm link",
    "bam link",
    "nhấn link",
    "nhan link",
    "truy cập link",
    "truy cap link",
    ".com/",
    ".vn/"
]


URGENCY_KEYWORDS = [
    "ngay lập tức",
    "ngay lap tuc",
    "lập tức",
    "lap tuc",
    "ngay",
    "gấp",
    "gap",
    "khẩn cấp",
    "khan cap",
    "trong 5 phút",
    "trong 5 phut",
    "trong 10 phút",
    "trong 10 phut",
    "trong 15 phút",
    "trong 15 phut",
    "trong hôm nay",
    "trong hom nay",
    "hết hạn",
    "het han",
    "lần cuối",
    "lan cuoi",
    "phải làm ngay",
    "phai lam ngay"
]


THREAT_KEYWORDS = [
    "khóa tài khoản",
    "khoa tai khoan",
    "bị khóa",
    "bi khoa",
    "sẽ bị khóa",
    "se bi khoa",
    "phạt",
    "phat",
    "công an",
    "cong an",
    "vi phạm",
    "vi pham",
    "xử phạt",
    "xu phat",
    "khởi kiện",
    "khoi kien",
    "bắt",
    "bat",
    "mất tài khoản",
    "mat tai khoan",
    "hủy tài khoản",
    "huy tai khoan"
]


IMPERSONATION_KEYWORDS = [
    "nhân viên ngân hàng",
    "nhan vien ngan hang",
    "ngân hàng",
    "ngan hang",
    "công an",
    "cong an",
    "giáo viên",
    "giao vien",
    "thầy giáo",
    "thay giao",
    "cô giáo",
    "co giao",
    "nhà trường",
    "nha truong",
    "bộ giáo dục",
    "bo giao duc",
    "shipper",
    "nhân viên",
    "nhan vien",
    "chăm sóc khách hàng",
    "cham soc khach hang",
    "tổng đài",
    "tong dai",
    "admin",
    "quản trị viên",
    "quan tri vien"
]


PERSONAL_INFO_KEYWORDS = [
    "cccd",
    "căn cước",
    "can cuoc",
    "cmnd",
    "chứng minh nhân dân",
    "chung minh nhan dan",
    "số điện thoại",
    "so dien thoai",
    "địa chỉ",
    "dia chi",
    "ngày sinh",
    "ngay sinh",
    "họ tên",
    "ho ten",
    "thông tin cá nhân",
    "thong tin ca nhan",
    "số tài khoản",
    "so tai khoan",
    "tài khoản ngân hàng",
    "tai khoan ngan hang"
]


REWARD_KEYWORDS = [
    "trúng thưởng",
    "trung thuong",
    "trúng giải",
    "trung giai",
    "giải thưởng",
    "giai thuong",
    "phần thưởng",
    "phan thuong",
    "nhận thưởng",
    "nhan thuong",
    "nhận tiền",
    "nhan tien",
    "quà tặng",
    "qua tang",
    "khuyến mãi",
    "khuyen mai",
    "voucher",
    "học bổng",
    "hoc bong"
]


SECRECY_KEYWORDS = [
    "đừng nói với ai",
    "dung noi voi ai",
    "không được nói",
    "khong duoc noi",
    "giữ bí mật",
    "giu bi mat",
    "bí mật",
    "bi mat",
    "đừng cho bố mẹ biết",
    "dung cho bo me biet",
    "đừng nói cho bố mẹ",
    "dung noi cho bo me",
    "đừng nói cho giáo viên",
    "dung noi cho giao vien"
]


ACTION_KEYWORDS = [
    "hãy gửi",
    "hay gui",
    "hãy nhập",
    "hay nhap",
    "hãy cung cấp",
    "hay cung cap",
    "gửi cho tôi",
    "gui cho toi",
    "cho tôi otp",
    "cho toi otp",
    "cho tôi mật khẩu",
    "cho toi mat khau",
    "nhập otp",
    "nhap otp",
    "nhập mật khẩu",
    "nhap mat khau",
    "bấm vào",
    "bam vao",
    "nhấn vào",
    "nhan vao",
    "chuyển ngay",
    "chuyen ngay",
    "gửi ngay",
    "gui ngay"
]


# =========================================================
# 9. TÌM TỪ KHÓA
# =========================================================

def normalize_for_matching(text):

    text = text.lower()

    text = text.replace(
        "đ",
        "d"
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def find_keywords(
    text,
    keywords
):

    normalized = normalize_for_matching(
        text
    )

    found = []

    for keyword in keywords:

        normalized_keyword = (
            normalize_for_matching(
                keyword
            )
        )

        if normalized_keyword in normalized:

            found.append(
                keyword
            )

    return list(
        dict.fromkeys(found)
    )


# =========================================================
# 10. NHẬN DIỆN SỐ TIỀN
# =========================================================

def detect_money_amount(text):

    normalized = normalize_for_matching(
        text
    )

    patterns = [

        # 2 triệu / 10 triệu đồng / 1,5 triệu
        r"\b\d+(?:[.,]\d+)?\s*"
        r"(?:ty|trieu|nghin|ngan)"
        r"(?:\s*dong)?\b",

        # 20.000 đồng / 500,000 đồng
        r"\b\d{1,3}(?:[.,]\d{3})+"
        r"\s*(?:d|dong|vnd|vnd)\b",

        # 50000 đồng
        r"\b\d{4,}\s*"
        r"(?:d|dong|vnd)\b",

        # 100k / 20 nghìn
        r"\b\d+\s*(?:k|nghin|ngan)\b"
    ]

    found = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            normalized
        )

        for match in matches:

            if isinstance(
                match,
                tuple
            ):

                match = " ".join(
                    match
                )

            found.append(
                match
            )

    return list(
        dict.fromkeys(
            found
        )
    )


# =========================================================
# 11. TÍNH RISK SCORE
# =========================================================
#
# QUAN TRỌNG:
#
# GEMINI KHÔNG QUYẾT ĐỊNH risk_score.
#
# Điểm cuối cùng luôn được tính ở đây.
# =========================================================

def calculate_risk_score(text):

    normalized = normalize_for_matching(
        text
    )


    # -----------------------------------------------------
    # PHÁT HIỆN NHÓM
    # -----------------------------------------------------

    password = find_keywords(
        text,
        PASSWORD_KEYWORDS
    )

    otp = find_keywords(
        text,
        OTP_KEYWORDS
    )

    money_action = find_keywords(
        text,
        MONEY_ACTION_KEYWORDS
    )

    money_units = find_keywords(
        text,
        MONEY_UNIT_KEYWORDS
    )

    money_amounts = detect_money_amount(
        text
    )

    links = find_keywords(
        text,
        LINK_KEYWORDS
    )

    urgency = find_keywords(
        text,
        URGENCY_KEYWORDS
    )

    threats = find_keywords(
        text,
        THREAT_KEYWORDS
    )

    impersonation = find_keywords(
        text,
        IMPERSONATION_KEYWORDS
    )

    personal_info = find_keywords(
        text,
        PERSONAL_INFO_KEYWORDS
    )

    rewards = find_keywords(
        text,
        REWARD_KEYWORDS
    )

    secrecy = find_keywords(
        text,
        SECRECY_KEYWORDS
    )

    actions = find_keywords(
        text,
        ACTION_KEYWORDS
    )


    # -----------------------------------------------------
    # CÁC CỜ LOGIC
    # -----------------------------------------------------

    has_password = bool(
        password
    )

    has_otp = bool(
        otp
    )

    has_money_action = bool(
        money_action
    )

    has_amount = bool(
        money_amounts
    )

    has_strong_money_unit = any(
        keyword in [
            "tỷ",
            "ty",
            "triệu",
            "trieu",
            "nghìn",
            "nghin",
            "ngàn",
            "ngan",
            "vnđ",
            "vnd"
        ]
        for keyword in money_units
    )

    has_money = (
        has_money_action
        or has_amount
        or has_strong_money_unit
    )

    has_link = bool(
        links
    )

    has_urgency = bool(
        urgency
    )

    has_threat = bool(
        threats
    )

    has_impersonation = bool(
        impersonation
    )

    has_personal = bool(
        personal_info
    )

    has_reward = bool(
        rewards
    )

    has_secrecy = bool(
        secrecy
    )

    has_action = bool(
        actions
    )


    # -----------------------------------------------------
    # ĐIỂM CƠ BẢN
    # -----------------------------------------------------

    score = 0

    signals = []

    matched = []


    # -----------------------------------------------------
    # PASSWORD
    # -----------------------------------------------------

    if has_password:

        score += 45

        signals.append(
            "Có đề cập hoặc yêu cầu thông tin mật khẩu."
        )

        matched.append(
            "🔑 Mật khẩu"
        )


    # -----------------------------------------------------
    # OTP
    # -----------------------------------------------------

    if has_otp:

        score += 45

        signals.append(
            "Có đề cập hoặc yêu cầu mã OTP/mã xác thực."
        )

        matched.append(
            "🔐 OTP / mã xác thực"
        )


    # -----------------------------------------------------
    # MONEY ACTION
    # -----------------------------------------------------

    if has_money_action:

        score += 35

        signals.append(
            "Có yêu cầu chuyển, gửi, nộp hoặc thanh toán tiền."
        )

        matched.append(
            "💰 Yêu cầu tiền"
        )


    # -----------------------------------------------------
    # SỐ TIỀN
    # -----------------------------------------------------

    if has_amount:

        score += 18

        signals.append(
            "Tin nhắn có đề cập một số tiền cụ thể."
        )

        matched.append(
            "💵 Số tiền cụ thể"
        )

    elif has_strong_money_unit:

        score += 12

        signals.append(
            "Tin nhắn có đề cập đơn vị tiền đáng chú ý."
        )

        matched.append(
            "💵 Triệu / tỷ / nghìn"
        )

    elif (
        "đồng" in normalized
        or "dong" in normalized
    ):

        # "20.000 đồng tiền nước" chỉ được cộng nhẹ.
        score += 3

        matched.append(
            "💵 Có đề cập đồng tiền"
        )


    # -----------------------------------------------------
    # LINK
    # -----------------------------------------------------

    if has_link:

        score += 15

        signals.append(
            "Có liên kết hoặc yêu cầu truy cập liên kết."
        )

        matched.append(
            "🔗 Link"
        )


    # -----------------------------------------------------
    # URGENCY
    # -----------------------------------------------------

    if has_urgency:

        score += 18

        signals.append(
            "Có dấu hiệu tạo áp lực phải hành động nhanh."
        )

        matched.append(
            "⏰ Khẩn cấp"
        )


    # -----------------------------------------------------
    # THREAT
    # -----------------------------------------------------

    if has_threat:

        score += 22

        signals.append(
            "Có ngôn ngữ đe dọa hoặc gây sợ hãi."
        )

        matched.append(
            "⚠️ Đe dọa"
        )


    # -----------------------------------------------------
    # IMPERSONATION
    # -----------------------------------------------------

    if has_impersonation:

        score += 20

        signals.append(
            "Có dấu hiệu giả danh tổ chức hoặc người có thẩm quyền."
        )

        matched.append(
            "👤 Giả danh"
        )


    # -----------------------------------------------------
    # PERSONAL INFORMATION
    # -----------------------------------------------------

    if has_personal:

        score += 18

        signals.append(
            "Có yêu cầu hoặc đề cập thông tin cá nhân."
        )

        matched.append(
            "🪪 Thông tin cá nhân"
        )


    # -----------------------------------------------------
    # REWARD
    # -----------------------------------------------------

    if has_reward:

        score += 15

        signals.append(
            "Có yếu tố phần thưởng, quà tặng hoặc lợi ích."
        )

        matched.append(
            "🎁 Phần thưởng"
        )


    # -----------------------------------------------------
    # SECRECY
    # -----------------------------------------------------

    if has_secrecy:

        score += 15

        signals.append(
            "Có dấu hiệu yêu cầu giữ bí mật."
        )

        matched.append(
            "🤫 Giữ bí mật"
        )


    # -----------------------------------------------------
    # ACTION
    # -----------------------------------------------------

    if has_action:

        score += 8

        signals.append(
            "Tin nhắn thúc đẩy người nhận thực hiện hành động."
        )


    # =====================================================
    # COMBO BONUS
    # =====================================================

    # -----------------------------------------------------
    # OTP + MONEY
    # -----------------------------------------------------

    if (
        has_otp
        and has_money
    ):

        score += 25

        signals.append(
            "Kết hợp mã xác thực với yếu tố tiền bạc."
        )


    # -----------------------------------------------------
    # PASSWORD + OTP
    # -----------------------------------------------------

    if (
        has_password
        and has_otp
    ):

        score += 25

        signals.append(
            "Kết hợp mật khẩu với mã xác thực."
        )


    # -----------------------------------------------------
    # PASSWORD + LINK
    # -----------------------------------------------------

    if (
        has_password
        and has_link
    ):

        score += 20

        signals.append(
            "Kết hợp yêu cầu mật khẩu với liên kết."
        )


    # -----------------------------------------------------
    # OTP + LINK
    # -----------------------------------------------------

    if (
        has_otp
        and has_link
    ):

        score += 18

        signals.append(
            "Kết hợp mã xác thực với liên kết."
        )


    # -----------------------------------------------------
    # MONEY + THREAT
    # -----------------------------------------------------

    if (
        has_money
        and has_threat
    ):

        score += 20

        signals.append(
            "Kết hợp yêu cầu tiền với đe dọa."
        )


    # -----------------------------------------------------
    # MONEY + URGENCY
    # -----------------------------------------------------

    if (
        has_money
        and has_urgency
    ):

        score += 18

        signals.append(
            "Kết hợp tiền với áp lực thời gian."
        )


    # -----------------------------------------------------
    # MONEY + LINK + URGENCY
    # -----------------------------------------------------

    if (
        has_money
        and has_link
        and has_urgency
    ):

        score += 15

        signals.append(
            "Kết hợp tiền, liên kết và áp lực thời gian."
        )


    # -----------------------------------------------------
    # IMPERSONATION + OTP
    # -----------------------------------------------------

    if (
        has_impersonation
        and has_otp
    ):

        score += 20

        signals.append(
            "Giả danh kết hợp yêu cầu mã xác thực."
        )


    # -----------------------------------------------------
    # IMPERSONATION + MONEY
    # -----------------------------------------------------

    if (
        has_impersonation
        and has_money
    ):

        score += 20

        signals.append(
            "Giả danh kết hợp yêu cầu tiền."
        )


    # -----------------------------------------------------
    # REWARD + OTP / MONEY
    # -----------------------------------------------------

    if (
        has_reward
        and (
            has_otp
            or has_money
        )
    ):

        score += 15

        signals.append(
            "Phần thưởng kết hợp với yêu cầu nhạy cảm."
        )


    # -----------------------------------------------------
    # SECRECY + MONEY / OTP / PASSWORD
    # -----------------------------------------------------

    if (
        has_secrecy
        and (
            has_money
            or has_otp
            or has_password
        )
    ):

        score += 15

        signals.append(
            "Yêu cầu giữ bí mật kết hợp với thông tin/giao dịch nhạy cảm."
        )


    # =====================================================
    # ĐIỂM SÀN
    # =====================================================

    # -----------------------------------------------------
    # PASSWORD + OTP
    # -----------------------------------------------------

    if (
        has_password
        and has_otp
    ):

        score = max(
            score,
            85
        )


    # -----------------------------------------------------
    # OTP + MONEY
    # -----------------------------------------------------

    if (
        has_otp
        and has_money
    ):

        score = max(
            score,
            85
        )


    # -----------------------------------------------------
    # PASSWORD + LINK
    # -----------------------------------------------------

    if (
        has_password
        and has_link
    ):

        score = max(
            score,
            80
        )


    # -----------------------------------------------------
    # OTP + LINK
    # -----------------------------------------------------

    if (
        has_otp
        and has_link
    ):

        score = max(
            score,
            75
        )


    # -----------------------------------------------------
    # MONEY + THREAT
    # -----------------------------------------------------

    if (
        has_money
        and has_threat
    ):

        score = max(
            score,
            75
        )


    # -----------------------------------------------------
    # MONEY + URGENCY + LINK
    # -----------------------------------------------------

    if (
        has_money
        and has_urgency
        and has_link
    ):

        score = max(
            score,
            80
        )


    # -----------------------------------------------------
    # OTP + MONEY + URGENCY
    # -----------------------------------------------------

    if (
        has_otp
        and has_money
        and has_urgency
    ):

        score = max(
            score,
            90
        )


    # -----------------------------------------------------
    # PASSWORD + OTP + MONEY
    # -----------------------------------------------------

    if (
        has_password
        and has_otp
        and has_money
    ):

        score = max(
            score,
            95
        )


    # =====================================================
    # GIỚI HẠN 0-100
    # =====================================================

    score = max(
        0,
        min(
            100,
            score
        )
    )


    # =====================================================
    # MỨC ĐỘ
    # =====================================================

    if score >= 85:

        level = "Cực kỳ cao"

    elif score >= 70:

        level = "Rất cao"

    elif score >= 50:

        level = "Cao"

    elif score >= 25:

        level = "Cần chú ý"

    else:

        level = "Thấp"


    # =====================================================
    # FALLBACK SIGNAL
    # =====================================================

    if not signals:

        signals.append(
            "Chưa phát hiện dấu hiệu thao túng rõ ràng."
        )


    return {

        "risk_score": score,

        "risk_level": level,

        "signals": list(
            dict.fromkeys(
                signals
            )
        ),

        "matched": list(
            dict.fromkeys(
                matched
            )
        ),

        "keywords": {

            "password": password,

            "otp": otp,

            "money_action": money_action,

            "money_units": money_units,

            "money_amounts": money_amounts,

            "links": links,

            "urgency": urgency,

            "threats": threats,

            "impersonation": impersonation,

            "personal_info": personal_info,

            "rewards": rewards,

            "secrecy": secrecy,

            "actions": actions
        }
    }


# =========================================================
# 12. FALLBACK PHÂN TÍCH
# =========================================================

def fallback_analysis(message):

    rule_result = calculate_risk_score(
        message
    )

    score = rule_result[
        "risk_score"
    ]

    level = rule_result[
        "risk_level"
    ]

    signals = rule_result[
        "signals"
    ]


    if score >= 85:

        mechanism = (
            "Tin nhắn kết hợp nhiều tín hiệu rủi ro mạnh "
            "như thông tin xác thực, tiền bạc, liên kết, "
            "đe dọa hoặc áp lực thời gian."
        )

        reasoning = (
            "Điểm rủi ro được tính bởi bộ luật của ứng dụng "
            "dựa trên các tín hiệu trực tiếp xuất hiện trong tin nhắn."
        )


    elif score >= 70:

        mechanism = (
            "Tin nhắn có một hoặc nhiều yếu tố có khả năng "
            "khiến người nhận hành động trước khi kiểm tra."
        )

        reasoning = (
            "Hệ thống phát hiện các tín hiệu rủi ro đáng kể "
            "và tự động tăng điểm theo mức độ kết hợp."
        )


    elif score >= 50:

        mechanism = (
            "Tin nhắn có nhiều dấu hiệu cần cảnh giác "
            "nhưng cần thêm ngữ cảnh để kết luận."
        )

        reasoning = (
            "Kết quả dựa trên các từ khóa và mối liên hệ "
            "giữa các nhóm dấu hiệu."
        )


    elif score >= 25:

        mechanism = (
            "Tin nhắn có một số tín hiệu cần được kiểm tra "
            "trước khi thực hiện hành động."
        )

        reasoning = (
            "Một số yếu tố đáng chú ý được phát hiện "
            "nhưng chưa tạo thành tổ hợp rủi ro mạnh."
        )


    else:

        mechanism = (
            "Chưa phát hiện dấu hiệu thao túng rõ ràng "
            "từ nội dung được cung cấp."
        )

        reasoning = (
            "Tin nhắn hiện có ít tín hiệu thuộc các nhóm "
            "rủi ro mà hệ thống đang kiểm tra."
        )


    actions = [

        "Không cung cấp mật khẩu hoặc mã OTP.",

        "Không chuyển tiền chỉ vì một tin nhắn yêu cầu.",

        "Không bấm vào liên kết đáng ngờ.",

        "Kiểm tra người gửi bằng một kênh độc lập.",

        "Nếu không chắc chắn, hãy hỏi phụ huynh, "
        "giáo viên hoặc người lớn đáng tin cậy."
    ]


    detected = []

    if rule_result[
        "keywords"
    ]["password"]:

        detected.append(
            "Yêu cầu/đề cập mật khẩu"
        )

    if rule_result[
        "keywords"
    ]["otp"]:

        detected.append(
            "Yêu cầu/đề cập OTP"
        )

    if rule_result[
        "keywords"
    ]["money_action"]:

        detected.append(
            "Yêu cầu giao dịch tiền"
        )

    if rule_result[
        "keywords"
    ]["links"]:

        detected.append(
            "Liên kết đáng ngờ"
        )

    if rule_result[
        "keywords"
    ]["urgency"]:

        detected.append(
            "Tạo áp lực thời gian"
        )

    if rule_result[
        "keywords"
    ]["threats"]:

        detected.append(
            "Đe dọa/gây sợ hãi"
        )

    if rule_result[
        "keywords"
    ]["impersonation"]:

        detected.append(
            "Giả danh"
        )

    if rule_result[
        "keywords"
    ]["personal_info"]:

        detected.append(
            "Thông tin cá nhân"
        )

    if rule_result[
        "keywords"
    ]["rewards"]:

        detected.append(
            "Phần thưởng"
        )

    if rule_result[
        "keywords"
    ]["secrecy"]:

        detected.append(
            "Yêu cầu giữ bí mật"
        )


    if detected:

        main_strategy = detected[0]

    else:

        main_strategy = (
            "Chưa phát hiện rõ"
        )


    evidence = []

    for item in rule_result[
        "matched"
    ]:

        evidence.append(
            f"Phát hiện nhóm tín hiệu: {item}"
        )


    if not evidence:

        evidence.append(
            "Không phát hiện nhóm tín hiệu nguy cơ rõ ràng."
        )


    return {

        "risk_score": score,

        "risk_level": level,

        "main_strategy": main_strategy,

        "detected_strategies": detected,

        "manipulation_signals": signals,

        "evidence": evidence,

        "psychological_mechanism": mechanism,

        "recommended_actions": actions,

        "reasoning": reasoning
    }


# =========================================================
# 13. SYSTEM PROMPT
# =========================================================

ANALYSIS_SYSTEM = """
Bạn là chuyên gia giáo dục an toàn số cho học sinh THPT.

Nhiệm vụ:

Phân tích một tin nhắn và nhận diện các dấu hiệu:
- thao túng tâm lý
- lừa đảo
- tạo áp lực
- giả danh
- yêu cầu thông tin nhạy cảm
- yêu cầu tiền
- yêu cầu OTP/mật khẩu
- liên kết đáng ngờ

QUAN TRỌNG:

Điểm risk_score KHÔNG do bạn quyết định.

Ứng dụng sẽ tự tính điểm bằng một bộ luật riêng.

Bạn chỉ cung cấp:
- giải thích
- chiến thuật
- bằng chứng
- cơ chế tâm lý
- khuyến nghị

Không được tự bịa bằng chứng.

Không được khẳng định người gửi chắc chắn là tội phạm
nếu chỉ dựa trên một tin nhắn.

Trả về JSON đúng cấu trúc:

{
    "risk_score": 0,
    "risk_level": "",
    "main_strategy": "",
    "detected_strategies": [],
    "manipulation_signals": [],
    "evidence": [],
    "psychological_mechanism": "",
    "recommended_actions": [],
    "reasoning": ""
}

Không Markdown.
Không ```json.
Không thêm văn bản bên ngoài JSON.
"""


# =========================================================
# 14. PHÂN TÍCH BẰNG GEMINI + RULE ENGINE
# =========================================================

def analyze_message(message):

    # -----------------------------------------------------
    # RULE ENGINE TÍNH ĐIỂM TRƯỚC
    # -----------------------------------------------------

    rule_result = calculate_risk_score(
        message
    )

    rule_score = rule_result[
        "risk_score"
    ]

    rule_level = rule_result[
        "risk_level"
    ]


    # -----------------------------------------------------
    # NẾU KHÔNG CÓ API KEY
    # -----------------------------------------------------

    if not API_KEY:

        return (
            fallback_analysis(
                message
            ),
            "fallback"
        )


    prompt = f"""
Hãy phân tích tin nhắn dưới đây.

Tin nhắn:

--- BẮT ĐẦU ---
{message}
--- KẾT THÚC ---

Lưu ý:
Điểm rủi ro của hệ thống sẽ được tính riêng.
Bạn chỉ cần cung cấp phần giải thích và nhận diện thủ đoạn.

Trả về JSON.
"""


    response = call_gemini(
        prompt,
        ANALYSIS_SYSTEM,
        json_mode=True
    )


    # -----------------------------------------------------
    # GEMINI THÀNH CÔNG
    # -----------------------------------------------------

    if response[
        "success"
    ]:

        gemini_result = extract_json(
            response["text"]
        )


        if isinstance(
            gemini_result,
            dict
        ):

            # =============================================
            # CỰC KỲ QUAN TRỌNG
            #
            # BỎ QUA risk_score GEMINI TRẢ VỀ.
            #
            # LẤY ĐIỂM TỪ RULE ENGINE.
            # =============================================

            final_result = {

                "risk_score":
                    rule_score,

                "risk_level":
                    rule_level,

                "main_strategy":
                    gemini_result.get(
                        "main_strategy",
                        "Không xác định"
                    ),

                "detected_strategies":
                    gemini_result.get(
                        "detected_strategies",
                        []
                    ),

                "manipulation_signals":
                    gemini_result.get(
                        "manipulation_signals",
                        rule_result["signals"]
                    ),

                "evidence":
                    gemini_result.get(
                        "evidence",
                        []
                    ),

                "psychological_mechanism":
                    gemini_result.get(
                        "psychological_mechanism",
                        ""
                    ),

                "recommended_actions":
                    gemini_result.get(
                        "recommended_actions",
                        []
                    ),

                "reasoning":
                    gemini_result.get(
                        "reasoning",
                        ""
                    )
            }


            # -------------------------------------------------
            # Nếu Gemini không trả một số phần,
            # lấy fallback tương ứng.
            # -------------------------------------------------

            fallback = fallback_analysis(
                message
            )


            if not final_result[
                "manipulation_signals"
            ]:

                final_result[
                    "manipulation_signals"
                ] = fallback[
                    "manipulation_signals"
                ]


            if not final_result[
                "evidence"
            ]:

                final_result[
                    "evidence"
                ] = fallback[
                    "evidence"
                ]


            if not final_result[
                "recommended_actions"
            ]:

                final_result[
                    "recommended_actions"
                ] = fallback[
                    "recommended_actions"
                ]


            if not final_result[
                "psychological_mechanism"
            ]:

                final_result[
                    "psychological_mechanism"
                ] = fallback[
                    "psychological_mechanism"
                ]


            if not final_result[
                "reasoning"
            ]:

                final_result[
                    "reasoning"
                ] = fallback[
                    "reasoning"
                ]


            return (
                final_result,
                "gemini"
            )


    # -----------------------------------------------------
    # GEMINI LỖI
    # -----------------------------------------------------

    return (
        fallback_analysis(
            message
        ),
        "fallback"
    )


# =========================================================
# 15. NGÂN HÀNG 30 TÌNH HUỐNG
# =========================================================
#
# GEMINI KHÔNG TẠO GAME.
#
# Mỗi tình huống có ID riêng.
#
# Hệ thống sẽ đi hết 30 tình huống
# trước khi bắt đầu vòng mới.
# =========================================================

FALLBACK_SCENARIOS = [

    {
        "id": 1,
        "category": "OTP / Phần thưởng",
        "message": (
            "Chúc mừng! Bạn đã trúng phần thưởng 20 triệu đồng. "
            "Hãy gửi mã OTP trong 5 phút để xác nhận nhận thưởng."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi OTP ngay để nhận tiền.",
            "Hỏi người gửi rồi gửi OTP.",
            "Không gửi OTP và kiểm tra thông tin bằng kênh chính thức.",
            "Chuyển trước một khoản phí nhỏ."
        ],
        "correct_index": 2,
        "explanation": (
            "OTP là thông tin xác thực nhạy cảm. "
            "Không nên cung cấp OTP cho người khác chỉ vì "
            "một tin nhắn thông báo phần thưởng."
        )
    },

    {
        "id": 2,
        "category": "Ngân hàng / Link",
        "message": (
            "Ngân hàng thông báo tài khoản của bạn sắp bị khóa. "
            "Hãy bấm vào đường link bên dưới và đăng nhập để xác minh."
        ),
        "question": "Cách xử lý an toàn nhất là gì?",
        "options": [
            "Bấm link ngay.",
            "Đăng nhập theo link.",
            "Tự mở ứng dụng hoặc website chính thức để kiểm tra.",
            "Gửi mật khẩu cho nhân viên."
        ],
        "correct_index": 2,
        "explanation": (
            "Không nên đăng nhập thông qua một đường link "
            "đáng ngờ được gửi bất ngờ. Hãy tự mở kênh chính thức."
        )
    },

    {
        "id": 3,
        "category": "Việc làm online",
        "message": (
            "Một người lạ giới thiệu việc làm online với thu nhập "
            "3 triệu đồng mỗi ngày nhưng yêu cầu bạn chuyển trước "
            "200.000 đồng để kích hoạt tài khoản."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển tiền để bắt đầu.",
            "Chuyển một nửa số tiền.",
            "Không chuyển tiền khi chưa xác minh.",
            "Mượn tiền bạn bè để tham gia."
        ],
        "correct_index": 2,
        "explanation": (
            "Yêu cầu trả tiền trước để nhận việc là dấu hiệu cần "
            "được kiểm tra kỹ. Không nên chuyển tiền chỉ dựa trên lời hứa."
        )
    },

    {
        "id": 4,
        "category": "Giả danh giáo viên",
        "message": (
            "Cô giáo nhắn: 'Em chuyển ngay 500.000 đồng vào tài khoản "
            "này để nhà trường hoàn tất hồ sơ. Cô đang bận nên không gọi được.'"
        ),
        "question": "Bạn nên phản ứng thế nào?",
        "options": [
            "Chuyển ngay.",
            "Gửi một nửa trước.",
            "Liên hệ cô giáo hoặc nhà trường qua kênh chính thức.",
            "Hỏi bạn cùng lớp rồi chuyển."
        ],
        "correct_index": 2,
        "explanation": (
            "Người gửi có thể bị giả mạo. Khi có yêu cầu tiền bất thường, "
            "hãy xác minh bằng kênh khác."
        )
    },

    {
        "id": 5,
        "category": "Giả danh người thân",
        "message": (
            "Một tài khoản nhắn: 'Mẹ đang bận nên không nghe máy được. "
            "Con chuyển gấp 2 triệu đồng vào số tài khoản này giúp mẹ nhé.'"
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển ngay vì người gửi nói là mẹ.",
            "Gọi trực tiếp cho mẹ để xác minh.",
            "Gửi mật khẩu để chứng minh danh tính.",
            "Nhờ người lạ kiểm tra."
        ],
        "correct_index": 1,
        "explanation": (
            "Tài khoản có thể bị giả mạo. Hãy gọi trực tiếp cho người thân "
            "bằng số điện thoại quen thuộc để xác minh."
        )
    },

    {
        "id": 6,
        "category": "Shipper / Thanh toán",
        "message": (
            "Shipper nhắn rằng đơn hàng đang bị giữ và yêu cầu bạn "
            "thanh toán 35.000 đồng qua một đường link lạ."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Bấm link và thanh toán.",
            "Gửi thông tin thẻ.",
            "Kiểm tra đơn hàng trong ứng dụng chính thức.",
            "Chuyển 35.000 đồng ngay."
        ],
        "correct_index": 2,
        "explanation": (
            "Không nên thanh toán qua link lạ. Hãy kiểm tra trạng thái "
            "đơn hàng trên ứng dụng hoặc website chính thức."
        )
    },

    {
        "id": 7,
        "category": "Mạng xã hội",
        "message": (
            "Tài khoản mạng xã hội của bạn sẽ bị khóa trong 10 phút. "
            "Hãy đăng nhập vào link này để xác minh ngay."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Đăng nhập ngay.",
            "Gửi mật khẩu cho người gửi.",
            "Tự mở ứng dụng chính thức và kiểm tra.",
            "Chuyển tiền để mở khóa."
        ],
        "correct_index": 2,
        "explanation": (
            "Thông báo tạo áp lực thời gian kèm link đăng nhập là dấu hiệu "
            "cần cảnh giác."
        )
    },

    {
        "id": 8,
        "category": "Học bổng",
        "message": (
            "Bạn được chọn nhận học bổng 15 triệu đồng. "
            "Vui lòng gửi CCCD, số tài khoản và ảnh cá nhân "
            "cho người gửi để hoàn tất thủ tục."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi toàn bộ thông tin.",
            "Gửi CCCD trước.",
            "Xác minh chương trình học bổng qua nhà trường.",
            "Gửi ảnh nhưng không gửi tên."
        ],
        "correct_index": 2,
        "explanation": (
            "Thông tin cá nhân cần được bảo vệ. Hãy xác minh chương trình "
            "thông qua nhà trường hoặc nguồn chính thức."
        )
    },

    {
        "id": 9,
        "category": "Mật khẩu",
        "message": (
            "Bộ phận kỹ thuật yêu cầu bạn gửi mật khẩu hiện tại "
            "để họ kiểm tra tài khoản."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi mật khẩu.",
            "Gửi một phần mật khẩu.",
            "Không gửi mật khẩu.",
            "Gửi mật khẩu sau khi đăng xuất."
        ],
        "correct_index": 2,
        "explanation": (
            "Mật khẩu là thông tin bí mật. Không nên gửi mật khẩu "
            "cho người khác qua tin nhắn."
        )
    },

    {
        "id": 10,
        "category": "OTP ngân hàng",
        "message": (
            "Hệ thống phát hiện giao dịch bất thường. "
            "Nhân viên yêu cầu bạn đọc mã OTP để hủy giao dịch."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Đọc OTP.",
            "Gửi ảnh màn hình OTP.",
            "Không cung cấp OTP và tự liên hệ ngân hàng.",
            "Gửi số tài khoản trước."
        ],
        "correct_index": 2,
        "explanation": (
            "Không cung cấp OTP cho người khác. Hãy tự liên hệ "
            "ngân hàng bằng kênh chính thức."
        )
    },

    {
        "id": 11,
        "category": "Giả danh công an",
        "message": (
            "Một người tự nhận là công an nói rằng tài khoản của bạn "
            "liên quan đến vụ việc và yêu cầu chuyển tiền để xác minh."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển tiền ngay.",
            "Gửi OTP.",
            "Không chuyển tiền và trao đổi với người lớn đáng tin cậy.",
            "Gửi mật khẩu để xác minh."
        ],
        "correct_index": 2,
        "explanation": (
            "Yêu cầu tiền qua một cuộc trò chuyện bất ngờ cần được xác minh. "
            "Không nên chuyển tiền chỉ vì người gửi tự nhận là cơ quan chức năng."
        )
    },

    {
        "id": 12,
        "category": "Voucher",
        "message": (
            "Bạn nhận được voucher trị giá 5 triệu đồng. "
            "Nhấn vào link và nhập thông tin tài khoản để nhận."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Nhấn link ngay.",
            "Nhập thông tin rồi kiểm tra sau.",
            "Kiểm tra chương trình trên website chính thức.",
            "Gửi mật khẩu cho người gửi."
        ],
        "correct_index": 2,
        "explanation": (
            "Phần thưởng bất ngờ kèm yêu cầu nhập thông tin nhạy cảm "
            "là dấu hiệu cần cảnh giác."
        )
    },

    {
        "id": 13,
        "category": "Bạn bè",
        "message": (
            "Một người bạn nhắn rằng tài khoản đang lỗi và nhờ bạn "
            "chuyển giúp 300.000 đồng ngay, hứa sẽ trả sau."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển ngay.",
            "Chuyển 100.000 đồng trước.",
            "Gọi hoặc gặp trực tiếp bạn để xác minh.",
            "Đăng thông tin tài khoản lên nhóm lớp."
        ],
        "correct_index": 2,
        "explanation": (
            "Tài khoản của bạn bè có thể bị chiếm quyền. "
            "Hãy xác minh bằng một kênh khác."
        )
    },

    {
        "id": 14,
        "category": "Facebook",
        "message": (
            "Tài khoản Facebook của bạn vi phạm chính sách. "
            "Hãy nhập mật khẩu tại link này trong 15 phút để tránh bị khóa."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Nhập mật khẩu.",
            "Gửi mật khẩu cho admin.",
            "Tự mở Facebook để kiểm tra thông báo.",
            "Chuyển tiền để mở khóa."
        ],
        "correct_index": 2,
        "explanation": (
            "Không nên nhập mật khẩu qua link được gửi bất ngờ. "
            "Hãy tự mở nền tảng chính thức."
        )
    },

    {
        "id": 15,
        "category": "Đầu tư",
        "message": (
            "Bạn chỉ cần đầu tư 1 triệu đồng hôm nay và sẽ nhận "
            "10 triệu đồng trong tuần tới. Cơ hội chỉ còn vài suất."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Đầu tư ngay.",
            "Mượn tiền để đầu tư.",
            "Không chuyển tiền chỉ dựa trên lời hứa lợi nhuận.",
            "Gửi thông tin ngân hàng."
        ],
        "correct_index": 2,
        "explanation": (
            "Lời hứa lợi nhuận cao kèm áp lực thời gian cần được kiểm tra "
            "độc lập trước khi thực hiện giao dịch."
        )
    },

    {
        "id": 16,
        "category": "Mã QR",
        "message": (
            "Bạn được hoàn tiền 2 triệu đồng. "
            "Hãy quét mã QR và đăng nhập ngân hàng để nhận tiền."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Quét QR ngay.",
            "Đăng nhập ngân hàng theo hướng dẫn.",
            "Kiểm tra chương trình hoàn tiền qua kênh chính thức.",
            "Gửi OTP sau khi quét."
        ],
        "correct_index": 2,
        "explanation": (
            "Không nên đăng nhập tài khoản tài chính qua QR hoặc link "
            "không rõ nguồn gốc."
        )
    },

    {
        "id": 17,
        "category": "Tài khoản game",
        "message": (
            "Bạn được tặng 5.000 kim cương miễn phí. "
            "Hãy nhập mật khẩu tài khoản game để nhận quà."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Nhập mật khẩu.",
            "Gửi mật khẩu cho admin.",
            "Không cung cấp mật khẩu và kiểm tra trong game chính thức.",
            "Đổi mật khẩu rồi gửi mật khẩu mới."
        ],
        "correct_index": 2,
        "explanation": (
            "Mật khẩu không nên được cung cấp cho người khác "
            "để nhận phần thưởng."
        )
    },

    {
        "id": 18,
        "category": "Giả danh giáo viên",
        "message": (
            "Thầy nhắn rằng đang họp nên không nghe điện thoại được "
            "và yêu cầu em gửi ngay 1 triệu đồng để đóng phí cho lớp."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển ngay.",
            "Hỏi một người lạ xác nhận.",
            "Liên hệ thầy hoặc nhà trường bằng kênh chính thức.",
            "Gửi OTP để xác minh."
        ],
        "correct_index": 2,
        "explanation": (
            "Việc người gửi viện lý do không thể nghe máy và yêu cầu tiền "
            "là lý do để xác minh trước khi giao dịch."
        )
    },

    {
        "id": 19,
        "category": "Quà tặng",
        "message": (
            "Bạn có một phần quà trị giá 10 triệu đồng. "
            "Hãy gửi phí vận chuyển 100.000 đồng trước để nhận."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi phí ngay.",
            "Gửi một nửa phí.",
            "Kiểm tra nguồn chương trình và không chuyển tiền vội.",
            "Gửi OTP để xác nhận."
        ],
        "correct_index": 2,
        "explanation": (
            "Phần thưởng lớn đi kèm yêu cầu đóng phí trước "
            "là tình huống cần được xác minh kỹ."
        )
    },

    {
        "id": 20,
        "category": "Ngân hàng",
        "message": (
            "Nhân viên ngân hàng yêu cầu số tài khoản, mật khẩu "
            "và OTP để xác minh danh tính ngay trong cuộc trò chuyện."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi tất cả thông tin.",
            "Chỉ gửi OTP.",
            "Không cung cấp mật khẩu hoặc OTP.",
            "Gửi ảnh thẻ ngân hàng."
        ],
        "correct_index": 2,
        "explanation": (
            "Mật khẩu và OTP là thông tin xác thực nhạy cảm. "
            "Không nên cung cấp cho người khác qua tin nhắn."
        )
    },

    {
        "id": 21,
        "category": "Việc làm",
        "message": (
            "Muốn nhận mức lương 20 triệu mỗi tháng, "
            "bạn cần đóng phí kích hoạt hồ sơ 500.000 đồng hôm nay."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Đóng phí ngay.",
            "Mượn tiền đóng phí.",
            "Kiểm tra công ty và thông tin tuyển dụng độc lập.",
            "Gửi CCCD trước."
        ],
        "correct_index": 2,
        "explanation": (
            "Không nên chuyển tiền chỉ để được nhận một công việc "
            "khi chưa xác minh nguồn tuyển dụng."
        )
    },

    {
        "id": 22,
        "category": "Cảnh báo giả",
        "message": (
            "Thiết bị của bạn phát hiện hoạt động đáng ngờ. "
            "Bấm link ngay nếu không tài khoản sẽ bị khóa."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Bấm link ngay.",
            "Nhập mật khẩu.",
            "Tự mở ứng dụng chính thức để kiểm tra.",
            "Gửi OTP."
        ],
        "correct_index": 2,
        "explanation": (
            "Tin nhắn kết hợp cảnh báo, đe dọa và link cần được "
            "kiểm tra qua nguồn chính thức."
        )
    },

    {
        "id": 23,
        "category": "Giữ bí mật",
        "message": (
            "Một người tự nhận là người quen nói đang gặp chuyện gấp. "
            "Họ yêu cầu bạn chuyển 700.000 đồng và đừng nói với ai."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Chuyển ngay và giữ bí mật.",
            "Chuyển một phần.",
            "Xác minh người đó và nói với người lớn đáng tin cậy.",
            "Gửi mật khẩu để xác minh."
        ],
        "correct_index": 2,
        "explanation": (
            "Yêu cầu tiền kết hợp với yêu cầu giữ bí mật là dấu hiệu "
            "cần đặc biệt cảnh giác."
        )
    },

    {
        "id": 24,
        "category": "Mạng xã hội",
        "message": (
            "Bạn được chọn làm người thử nghiệm tính năng mới. "
            "Hãy gửi số điện thoại và mã xác thực để tham gia."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi mã xác thực.",
            "Gửi ảnh màn hình.",
            "Kiểm tra chương trình trên kênh chính thức.",
            "Gửi mật khẩu."
        ],
        "correct_index": 2,
        "explanation": (
            "Mã xác thực không nên được chia sẻ cho người khác. "
            "Hãy kiểm tra chương trình trên nguồn chính thức."
        )
    },

    {
        "id": 25,
        "category": "Tình huống bình thường",
        "message": (
            "Chiều nay nhớ mang 20.000 đồng tiền nước của lớp nhé."
        ),
        "question": "Bạn nên xử lý thế nào?",
        "options": [
            "Coi đây chắc chắn là lừa đảo.",
            "Kiểm tra với lớp nếu thấy bất thường.",
            "Gửi OTP để xác nhận.",
            "Bấm vào một link lạ."
        ],
        "correct_index": 1,
        "explanation": (
            "Việc đề cập đến tiền không tự động có nghĩa là lừa đảo. "
            "Trong tình huống bình thường, có thể xác nhận lại với lớp "
            "nếu cần."
        )
    },

    {
        "id": 26,
        "category": "Tình huống bình thường",
        "message": (
            "Nhà trường thông báo lịch kiểm tra học kỳ sẽ được "
            "cập nhật trên hệ thống chính thức vào ngày mai."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Tìm một link lạ để xem trước.",
            "Kiểm tra hệ thống chính thức của trường.",
            "Gửi mật khẩu cho giáo viên.",
            "Chuyển tiền để xem lịch."
        ],
        "correct_index": 1,
        "explanation": (
            "Đối với thông báo học tập, hãy sử dụng hệ thống "
            "chính thức của nhà trường."
        )
    },

    {
        "id": 27,
        "category": "Tình huống bình thường",
        "message": (
            "Đơn hàng của bạn sẽ được giao vào ngày mai. "
            "Vui lòng chuẩn bị tiền khi nhận hàng."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Bấm vào link lạ.",
            "Kiểm tra đơn hàng trong ứng dụng mua hàng.",
            "Gửi OTP cho shipper.",
            "Gửi mật khẩu tài khoản."
        ],
        "correct_index": 1,
        "explanation": (
            "Việc thanh toán khi nhận hàng có thể là hoạt động bình thường. "
            "Bạn nên kiểm tra đơn hàng trên ứng dụng chính thức."
        )
    },

    {
        "id": 28,
        "category": "Tình huống bình thường",
        "message": (
            "Nhà trường sẽ công bố danh sách học sinh nhận học bổng "
            "trên bảng tin chính thức."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi CCCD cho một tài khoản lạ.",
            "Theo dõi thông báo chính thức của trường.",
            "Chuyển phí để được xem danh sách.",
            "Gửi OTP."
        ],
        "correct_index": 1,
        "explanation": (
            "Thông tin học bổng nên được kiểm tra trên nguồn chính thức "
            "của nhà trường."
        )
    },

    {
        "id": 29,
        "category": "Tình huống bình thường",
        "message": (
            "Cuộc thi của trường sẽ diễn ra vào thứ sáu. "
            "Các đội nhớ kiểm tra email trường để nhận lịch thi."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi mật khẩu email cho người tổ chức.",
            "Kiểm tra email trường.",
            "Chuyển tiền để nhận lịch.",
            "Bấm vào link không rõ nguồn."
        ],
        "correct_index": 1,
        "explanation": (
            "Đây là yêu cầu thông thường. Hãy sử dụng email "
            "hoặc hệ thống chính thức của trường."
        )
    },

    {
        "id": 30,
        "category": "An toàn tài khoản",
        "message": (
            "Nếu nhận được tin nhắn yêu cầu cung cấp OTP hoặc mật khẩu, "
            "hãy dừng lại và xác minh người gửi bằng một kênh khác."
        ),
        "question": "Bạn nên làm gì?",
        "options": [
            "Gửi OTP để xác minh.",
            "Gửi mật khẩu nếu người gửi tự nhận là nhân viên.",
            "Dừng lại và xác minh bằng kênh độc lập.",
            "Chuyển tiền để bảo vệ tài khoản."
        ],
        "correct_index": 2,
        "explanation": (
            "Không chia sẻ OTP hoặc mật khẩu. Khi có yêu cầu bất thường, "
            "hãy dừng lại và xác minh bằng kênh độc lập."
        )
    }
]


# =========================================================
# 16. LẤY TÌNH HUỐNG KHÔNG LẶP
# =========================================================

def get_next_scenario():

    total = len(
        FALLBACK_SCENARIOS
    )

    used = st.session_state.used_scenario_ids


    # -----------------------------------------------------
    # Nếu đã chơi hết toàn bộ 30 tình huống
    # -----------------------------------------------------

    if len(used) >= total:

        st.session_state.used_scenario_ids = []

        used = []

        st.toast(
            "🎉 Bạn đã hoàn thành một vòng 30 tình huống! "
            "Bắt đầu vòng mới.",
            icon="🛡️"
        )


    # -----------------------------------------------------
    # Lấy các tình huống chưa chơi
    # -----------------------------------------------------

    available = [
        scenario
        for scenario in FALLBACK_SCENARIOS
        if scenario["id"] not in used
    ]


    # -----------------------------------------------------
    # Phòng trường hợp bất thường
    # -----------------------------------------------------

    if not available:

        st.session_state.used_scenario_ids = []

        available = (
            FALLBACK_SCENARIOS.copy()
        )


    # -----------------------------------------------------
    # Chọn random từ phần chưa dùng
    # -----------------------------------------------------

    scenario = random.choice(
        available
    )


    # -----------------------------------------------------
    # Ghi nhận ID
    # -----------------------------------------------------

    st.session_state.used_scenario_ids.append(
        scenario["id"]
    )


    # -----------------------------------------------------
    # Tăng round
    # -----------------------------------------------------

    st.session_state.game_round += 1


    # -----------------------------------------------------
    # Lưu tình huống
    # -----------------------------------------------------

    st.session_state.game_question = (
        scenario
    )

    st.session_state.game_result = None


    # -----------------------------------------------------
    # Reset answer
    # -----------------------------------------------------

    st.session_state.game_answer = None


    return scenario


# =========================================================
# 17. HIỂN THỊ RISK SCORE
# =========================================================

def display_risk_score(
    score,
    level
):

    if score >= 70:

        box_class = "danger-box"

    elif score >= 25:

        box_class = "warning-box"

    else:

        box_class = "safe-box"


    st.markdown(
        f"""
        <div class="{box_class}">

            <div style="
                text-align:center;
                font-size:52px;
                font-weight:800;
            ">
                {score}/100
            </div>

            <div style="
                text-align:center;
                font-size:24px;
                font-weight:700;
            ">
                {level}
            </div>

        </div>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# 18. TAB
# =========================================================

tab1, tab2, tab3 = st.tabs([
    "🔍 QUÉT TIN NHẮN",
    "🎮 TÌNH HUỐNG GIẢ LẬP",
    "📚 KIẾN THỨC TỰ VỆ"
])


# =========================================================
# TAB 1 - QUÉT TIN NHẮN
# =========================================================

with tab1:

    st.header(
        "🔍 Phân tích tin nhắn đáng ngờ"
    )

    st.write(
        "Dán một tin nhắn, email hoặc đoạn hội thoại "
        "mà bạn muốn kiểm tra."
    )


    user_input = st.text_area(
        "Nội dung cần phân tích:",
        height=180,
        max_chars=MAX_ANALYSIS_CHARS,
        placeholder=(
            "Ví dụ:\n"
            "Tài khoản của bạn sắp bị khóa. "
            "Hãy gửi OTP và chuyển 2 triệu đồng "
            "trong 5 phút..."
        )
    )


    if st.button(
        "🚀 PHÂN TÍCH",
        type="primary",
        use_container_width=True
    ):

        if not user_input.strip():

            st.warning(
                "⚠️ Vui lòng nhập nội dung trước."
            )

        else:

            with st.spinner(
                "🧠 Đang phân tích..."
            ):

                result, source = analyze_message(
                    user_input.strip()
                )


            st.session_state.analysis_count += 1


            # =================================================
            # SCORE
            # =================================================

            score = int(
                result.get(
                    "risk_score",
                    0
                )
            )


            score = max(
                0,
                min(
                    100,
                    score
                )
            )


            level = result.get(
                "risk_level",
                "Không xác định"
            )


            display_risk_score(
                score,
                level
            )


            st.progress(
                score / 100
            )


            # =================================================
            # NGUỒN
            # =================================================

            if source == "gemini":

                st.success(
                    "🤖 Gemini đã hỗ trợ phân tích nội dung."
                )

                st.caption(
                    "🔐 Điểm rủi ro được tính bởi bộ luật "
                    "của Lá Chắn Số, không lấy điểm Gemini trả về."
                )

            else:

                st.warning(
                    "🛡️ Gemini đang bận. "
                    "Đã kích hoạt bộ phân tích dự phòng."
                )

                st.caption(
                    "Điểm rủi ro được tính toán dựa trên bộ quy tắc của ứng dụng."
                )


            st.divider()


            # =================================================
            # 3 METRICS
            # =================================================

            col1, col2, col3 = st.columns(3)


            with col1:

                st.metric(
                    "📊 Điểm rủi ro",
                    f"{score}/100"
                )


            with col2:

                st.metric(
                    "⚠️ Mức độ",
                    level
                )


            with col3:

                st.metric(
                    "🎯 Chiến thuật chính",
                    result.get(
                        "main_strategy",
                        "Không xác định"
                    )
                )


            st.divider()


            # =================================================
            # LEFT / RIGHT
            # =================================================

            col_left, col_right = st.columns(2)


            # -------------------------------------------------
            # LEFT
            # -------------------------------------------------

            with col_left:

                st.subheader(
                    "🧠 Cơ chế thao túng"
                )


                st.write(
                    result.get(
                        "psychological_mechanism",
                        "Không có dữ liệu."
                    )
                )


                st.subheader(
                    "🚨 Dấu hiệu phát hiện"
                )


                signals = result.get(
                    "manipulation_signals",
                    []
                )


                if signals:

                    for signal in signals:

                        st.markdown(
                            f"- ⚠️ {signal}"
                        )

                else:

                    st.write(
                        "Không phát hiện dấu hiệu rõ ràng."
                    )


            # -------------------------------------------------
            # RIGHT
            # -------------------------------------------------

            with col_right:

                st.subheader(
                    "🔎 Bằng chứng"
                )


                evidence = result.get(
                    "evidence",
                    []
                )


                if evidence:

                    for item in evidence:

                        st.info(
                            str(item)
                        )

                else:

                    st.write(
                        "Không có bằng chứng cụ thể."
                    )


                st.subheader(
                    "🛡️ Nên làm gì?"
                )


                actions = result.get(
                    "recommended_actions",
                    []
                )


                if actions:

                    for i, action in enumerate(
                        actions,
                        start=1
                    ):

                        st.write(
                            f"**{i}.** {action}"
                        )

                else:

                    st.write(
                        "Chưa có khuyến nghị."
                    )


            st.divider()


            # =================================================
            # STRATEGIES
            # =================================================

            st.subheader(
                "🧩 Các chiến thuật được phát hiện"
            )


            strategies = result.get(
                "detected_strategies",
                []
            )


            if strategies:

                for strategy in strategies:

                    st.markdown(
                        f"🔴 **{strategy}**"
                    )

            else:

                st.write(
                    "Không phát hiện chiến thuật rõ ràng."
                )


            st.divider()


            # =================================================
            # REASONING
            # =================================================

            st.subheader(
                "📝 Lý do đánh giá"
            )


            st.write(
                result.get(
                    "reasoning",
                    "Không có dữ liệu."
                )
            )


            # =================================================
            # RULE ENGINE DEBUG / MINH BẠCH
            # =================================================

            with st.expander(
                "🔬 Xem dấu hiệu mà chúng tôi đã phát hiện"
            ):

                rule_result = calculate_risk_score(
                    user_input.strip()
                )


                matched = rule_result.get(
                    "matched",
                    []
                )


                if matched:

                    st.write(
                        "**Nhóm tín hiệu:**"
                    )

                    for item in matched:

                        st.markdown(
                            f"- {item}"
                        )


                keywords = rule_result.get(
                    "keywords",
                    {}
                )


                st.write(
                    "**Từ khóa cụ thể:**"
                )


                for category, values in keywords.items():

                    if values:

                        st.write(
                            f"**{category}:** "
                            + ", ".join(
                                map(
                                    str,
                                    values
                                )
                            )
                        )


                money_amounts = (
                    rule_result[
                        "keywords"
                    ].get(
                        "money_amounts",
                        []
                    )
                )


                if money_amounts:

                    st.write(
                        "**Số tiền nhận diện:** "
                        + ", ".join(
                            money_amounts
                        )
                    )


# =========================================================
# TAB 2 - GAME
# =========================================================

with tab2:

    st.header(
        "🎮 Phòng thực hành phản xạ số"
    )


    st.info(
        "Bạn sẽ gặp các tình huống giả lập. "
        "Hãy đọc kỹ và chọn cách xử lý an toàn nhất."
    )


    total_scenarios = len(
        FALLBACK_SCENARIOS
    )


    used_count = len(
        st.session_state.used_scenario_ids
    )


    st.markdown(
        f"""
        <div class="game-counter">
            🎯 Tình huống đã chơi:
            {used_count}/{total_scenarios}
        </div>
        """,
        unsafe_allow_html=True
    )


    st.progress(
        used_count / total_scenarios
    )


    # =====================================================
    # NÚT TẠO TÌNH HUỐNG
    # =====================================================

    if st.button(
        "🎲 TẠO TÌNH HUỐNG",
        use_container_width=True
    ):

        # =================================================
        # KHÔNG GỌI GEMINI.
        #
        # Đây là điểm thay đổi quan trọng nhất.
        # =================================================

        get_next_scenario()

        st.rerun()


    # =====================================================
    # HIỂN THỊ GAME
    # =====================================================

    if st.session_state.game_question:

        game = (
            st.session_state.game_question
        )


        st.divider()


        # -------------------------------------------------
        # ID + CATEGORY
        # -------------------------------------------------

        st.caption(
            f"🧩 Tình huống #{game['id']} "
            f"• Chủ đề: {game['category']}"
        )


        st.subheader(
            "📩 Tin nhắn bạn nhận được:"
        )


        st.warning(
            str(
                game.get(
                    "message",
                    ""
                )
            )
        )


        st.subheader(
            str(
                game.get(
                    "question",
                    "Bạn nên làm gì?"
                )
            )
        )


        options = game.get(
            "options",
            []
        )


        if (
            isinstance(
                options,
                list
            )
            and len(options) == 4
        ):


            # -------------------------------------------------
            # DÙNG KEY THEO GAME ROUND
            #
            # Như vậy Streamlit không giữ đáp án cũ
            # khi chuyển sang tình huống mới.
            # -------------------------------------------------

            answer_key = (
                f"game_answer_"
                f"{st.session_state.game_round}"
            )


            answer = st.radio(
                "Chọn cách xử lý:",
                options,
                index=None,
                key=answer_key
            )


            if st.button(
                "✅ KIỂM TRA",
                use_container_width=True
            ):

                if answer is None:

                    st.warning(
                        "⚠️ Hãy chọn một phương án."
                    )

                else:

                    try:

                        selected_index = (
                            options.index(
                                answer
                            )
                        )

                        correct_index = int(
                            game.get(
                                "correct_index",
                                0
                            )
                        )

                    except (
                        ValueError,
                        TypeError
                    ):

                        selected_index = -1

                        correct_index = 0


                    if (
                        selected_index
                        == correct_index
                    ):

                        st.success(
                            "🎉 Chính xác! "
                            "Đây là phản ứng an toàn."
                        )

                    else:

                        st.error(
                            "⚠️ Chưa phải lựa chọn "
                            "an toàn nhất."
                        )


                    st.info(
                        "💡 **Giải thích:** "
                        + str(
                            game.get(
                                "explanation",
                                ""
                            )
                        )
                    )


            st.divider()


            # -------------------------------------------------
            # TÌNH HUỐNG KHÁC
            # -------------------------------------------------

            if st.button(
                "➡️ TÌNH HUỐNG KHÁC",
                use_container_width=True
            ):

                get_next_scenario()

                st.rerun()


        else:

            st.error(
                "Tình huống không hợp lệ."
            )


    else:

        st.markdown(
            """
            ### 👋 Chưa có tình huống

            Nhấn **🎲 TẠO TÌNH HUỐNG** để bắt đầu.

            
            """
        )


    # =====================================================
    # RESET VÒNG GAME
    # =====================================================

    st.divider()


    with st.expander(
        "⚙️ Tùy chọn game"
    ):

        st.write(
            f"Chúng tôi hiện có **{total_scenarios} tình huống**."
        )


        if st.button(
            "🔄 CHƠI LẠI TỪ ĐẦU"
        ):

            st.session_state.used_scenario_ids = []

            st.session_state.game_question = None

            st.session_state.game_result = None

            st.session_state.game_answer = None

            st.session_state.game_round = 0

            st.rerun()


# =========================================================
# TAB 3 - KIẾN THỨC
# =========================================================

with tab3:

    st.header(
        "📚 5 nguyên tắc tự vệ số"
    )


    principles = [

        (
            "1️⃣ DỪNG LẠI",
            "Không hành động ngay khi có một tin nhắn "
            "cố tạo áp lực."
        ),

        (
            "2️⃣ KIỂM TRA",
            "Xác minh người gửi và thông tin bằng "
            "một kênh độc lập."
        ),

        (
            "3️⃣ KHÔNG CHIA SẺ",
            "Không cung cấp mật khẩu, mã xác thực "
            "hoặc thông tin cá nhân nhạy cảm "
            "cho người lạ."
        ),

        (
            "4️⃣ KHÔNG VỘI BẤM LINK",
            "Đặc biệt cảnh giác với liên kết được gửi "
            "kèm lời đe dọa, phần thưởng hoặc thời hạn gấp."
        ),

        (
            "5️⃣ BÁO NGƯỜI ĐÁNG TIN",
            "Nếu không chắc chắn, hãy hỏi phụ huynh, "
            "giáo viên hoặc người lớn đáng tin cậy."
        )
    ]


    for title, description in principles:

        with st.container(
            border=True
        ):

            st.subheader(
                title
            )

            st.write(
                description
            )


    st.divider()


    st.subheader(
        "🔐 Những thông tin không nên chia sẻ"
    )


    sensitive_items = [
        "Mật khẩu",
        "OTP / mã xác thực",
        "PIN",
        "Thông tin đăng nhập",
        "Thông tin tài khoản ngân hàng",
        "CCCD/căn cước khi chưa xác minh nguồn yêu cầu"
    ]


    for item in sensitive_items:

        st.markdown(
            f"- 🔒 {item}"
        )


    st.divider()


    st.subheader(
        "🚨 Dấu hiệu cần đặc biệt cảnh giác"
    )


    warning_items = [

        "Yêu cầu chuyển tiền bất ngờ.",

        "Yêu cầu OTP hoặc mật khẩu.",

        "Hứa phần thưởng rất lớn.",

        "Tạo áp lực phải làm ngay.",

        "Đe dọa khóa tài khoản hoặc phạt.",

        "Gửi link lạ để đăng nhập.",

        "Tự nhận là ngân hàng, công an, giáo viên hoặc người quen.",

        "Yêu cầu giữ bí mật với người lớn đáng tin cậy."
    ]


    for item in warning_items:

        st.markdown(
            f"- ⚠️ {item}"
        )


    st.divider()


    st.caption(
        "🛡️ Lá Chắn Số THPT — Công cụ giáo dục "
        "nhận thức và kỹ năng tự vệ số."
    )


# =========================================================
# 19. FOOTER
# =========================================================

st.divider()


st.caption(
    "🛡️ Lá Chắn Số THPT"
)


st.caption(
    f"📊 Đã thực hiện "
    f"{st.session_state.analysis_count} lượt phân tích "
    f"trong phiên này."
)

