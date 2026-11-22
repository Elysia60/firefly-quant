# -*- coding: utf-8 -*-
"""news_pit_probe.py — LLM 舆情因子 PoC-0: PIT 新闻源可用性探测(2026-11-23 · 只读)

对应 METHODS.md [S20] 预注册登记的数据闸部分。只读探测,零写入湖:
  1. 确认 akshare 新闻接口清单(本机安装版本)
  2. 实弹采样一次 stock_news_em(单股票,限 3 行)——检查返回字段是否含发布时间(PIT 能力)
  3. 实弹采样一次 stock_notice_report——公告源
  4. 判定: 每源 → {可用, 字段, PIT 能力, 结论}

PIT 判定标准(预注册写死):
  - 含发布时间戳字段 + 可按日期过滤 → "PIT 归档可行"(需每日归档累积,无历史回溯)
  - 无时间戳 → "非 PIT,禁用于回测"
  - 接口不存在/限流 → "不可用"

用法: python scripts/verify/news_pit_probe.py   # 产物 results/news_pit_probe.json
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = REPO_ROOT / "results" / "news_pit_probe.json"
SAMPLE_CODE = "600519"  # 贵州茅台——流动性最好,新闻覆盖最稳


def probe(name, fn, pit_time_field):
    t0 = time.time()
    try:
        df = fn(symbol=SAMPLE_CODE) if name == "stock_news_em" else fn()
        rows = df.head(3)
        fields = list(df.columns)
        has_time = pit_time_field in fields and rows[pit_time_field].notna().any()
        latest = str(rows[pit_time_field].max()) if has_time else ""
        n = len(df)
        verdict = ("PIT 归档可行(实时流,无历史回溯)" if has_time
                   else "非 PIT,禁用于回测")
        return {"source": name, "ok": True, "rows": n, "fields": fields,
                "time_field": pit_time_field, "has_time": bool(has_time),
                "latest_ts": latest, "verdict": verdict,
                "elapsed_s": round(time.time() - t0, 1),
                "sample_headline": str(rows.iloc[0, 1])[:60] if n else ""}
    except Exception as e:  # noqa: BLE001
        return {"source": name, "ok": False, "error": f"{type(e).__name__}: {e}",
                "verdict": "不可用/限流", "elapsed_s": round(time.time() - t0, 1)}


def main() -> int:
    import akshare as ak
    print(f"akshare {ak.__version__}")
    results = {
        "probe_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "akshare_version": ak.__version__,
        "sample_code": SAMPLE_CODE,
        "pit_standard": "含发布时间戳→归档可行;无→禁用于回测;无历史回溯是常态",
        "sources": [
            probe("stock_news_em", ak.stock_news_em, "发布时间"),
            probe("stock_notice_report", ak.stock_notice_report, "公告日期"),
        ],
    }
    ok = sum(1 for s in results["sources"] if s.get("ok"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in results["sources"]:
        print(f"{s['source']}: {'✓' if s.get('ok') else '✗'} {s['verdict']}"
              + (f" | 最新: {s.get('latest_ts', '')[:19]}" if s.get("ok") else f" | {s.get('error')}"))
    print(f"保存 {OUT} ({ok}/{len(results['sources'])} 可用)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
