"""
Global configuration for the Asia AI Pipeline.
Import from here in all modules; do NOT import from each other's configs.
"""

COUNTRIES: list[str] = ["SG", "TH", "MY", "ID", "PH"]

COUNTRY_NAMES: dict[str, str] = {
    "SG": "Singapore",
    "TH": "Thailand",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "PH": "Philippines",
}

LANGUAGES: dict[str, str] = {
    "SG": "English",
    "TH": "Thai",
    "MY": "Bahasa Malaysia",
    "ID": "Bahasa Indonesia",
    "PH": "Filipino/English",
}

# markup:   profit multiplier (covers logistics shrinkage)
# shipping: flat shipping buffer in local currency
# round_to: psychological pricing rule
#   < 1   → x.90 style  (e.g. 15.90, 29.90)
#   == 9  → ends-in-9   (e.g. 189, 299)
#   >= 10 → round up to nearest N  (e.g. 1000 → 45000, 89000)
PRICING_CONFIG: dict[str, dict] = {
    "SG": {"currency": "SGD", "markup": 3.0, "shipping": 2.0,   "round_to": 0.90},
    "TH": {"currency": "THB", "markup": 3.5, "shipping": 30,    "round_to": 9},
    "MY": {"currency": "MYR", "markup": 3.0, "shipping": 3.0,   "round_to": 0.90},
    "ID": {"currency": "IDR", "markup": 3.8, "shipping": 5000,  "round_to": 1000},
    "PH": {"currency": "PHP", "markup": 3.2, "shipping": 20,    "round_to": 9},
}

TTS_VOICES: dict[str, str] = {
    "SG": "en-SG-WayneNeural",
    "TH": "th-TH-PremwadeeNeural",
    "MY": "ms-MY-YasminNeural",
    "ID": "id-ID-ArdiNeural",
    "PH": "en-PH-RosaNeural",
}

AI_CONFIG: dict[str, object] = {
    "text_model":    "deepseek-chat",      # M2: DeepSeek-V3，稳定支持 JSON mode
    "vision_model":  "claude-sonnet-4-6",  # M3: Claude Vision 图片文字检测
    "script_model":  "claude-sonnet-4-6",  # M4: Claude 视频脚本生成
    "video_provider": "kling",             # kling | runway
    "video_duration": 30,                  # seconds
    "text_max_workers": 50,                # M2 并发请求数
}
