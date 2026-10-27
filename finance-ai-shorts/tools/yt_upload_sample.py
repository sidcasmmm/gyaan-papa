"""One-off: upload state/sample.mp4 (the Veo home-loan Reel already on Instagram) to YouTube
as a PUBLIC Short, to test the YouTube connection. Result → state/yt_test.log"""
import sys
import traceback
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import youtube  # noqa: E402

cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
log = ROOT / "state" / "yt_test.log"
if not cfg.get("uploads_enabled", False):
    msg = "SKIPPED uploads are off (uploads_enabled: false). Nothing was sent to YouTube."
    print(msg)
    log.write_text(msg + "\n")
    sys.exit(0)
try:
    url = youtube.upload(
        ROOT / "state" / "sample.mp4",
        "Home Loan EMI Trick: 1 Extra EMI Saves Years! #Shorts",
        "हर साल सिर्फ 1 extra EMI भरने से home loan कई साल पहले ख़त्म हो सकता है। "
        "Financial Papa समझाते हैं कैसे — 30 सेकंड में।\n\n"
        "Sirf jaankari ke liye, investment advice nahi.\n\n#financialpapa #homeloan #emi #personalfinance",
        ["home loan", "home loan prepayment", "extra emi", "emi kaise kam kare", "home loan tips hindi",
         "financial papa", "personal finance hindi"],
        cfg, public=True)
    msg = f"OK {url}"
except Exception:
    msg = "FAILED\n" + traceback.format_exc()[-1500:]
print(msg)
log.write_text(msg + "\n")
