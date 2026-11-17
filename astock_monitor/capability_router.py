"""能力路由矩阵 — 数据源按能力声明与路由(P-REA-1,逆向自 TSP tick-stock-panel §4.1)。

背景(2026-11-18):萤火 11-13/11-16 双缺口事故的根因=EM 单点绑定——EM 被 WAF 拒
→ 日更全链瘫痪。TSP 的解法:6 类数据集按源声明的能力独立路由,"换源不换口径",
未声明口径即拒绝(fail-closed)。本模块把这套机制移植到萤火采集层。

设计纪律(三条,与 TSP 对齐):
  ①换源不换口径:路由只决定"从哪拿",不改变"怎么算"——指标/回测口径与源无关
  ②fail-closed:未声明某能力的源,绝不路由到该能力(宁缺不错)
  ③健康衰减:源失败→指数退避冷却(复用 collect.RateLimiter 的语义),冷却期满自动
    恢复试探;成功重置。冷却状态持久化(与 rate_limit_cooldown.json 同风格)

用法:
    router = CapabilityRouter.default()
    src = router.route("index_bars")       # -> "eastmoney" / "sina" / None(fail-closed)
    ...
    router.report_failure("eastmoney")     # 请求失败,EM 进冷却
    router.save_state()                    # 冷却状态落盘
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# 能力清单(全小写下划线;新增能力必须在此登记,否则 route 一律拒绝)
CAPABILITIES = (
    "daily_bars",       # 个股日线
    "spot_snapshot",    # 全市场实时快照
    "index_bars",       # 指数日线
    "zt_pool",          # 涨停池/昨涨停表现
    "margin",           # 两融余额
    "erp",              # 股债利差
    "lhb",              # 龙虎榜
    "calendar",         # 交易日历
    "macro_house",      # 地产代理(居民中长贷等,P7 待接)
)


@dataclass
class SourceHealth:
    failed_at: float | None = None
    cooldown_until: float | None = None
    fails: int = 0
    ok_since: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class SourceDecl:
    """数据源声明:name + 声明的能力集合 + 优先级(小者先)。"""
    name: str
    capabilities: tuple[str, ...]
    priority: int = 100
    health: SourceHealth = field(default_factory=SourceHealth)


class CapabilityRouter:
    """能力路由器:按能力选源,失败冷却,健康持久化。纯逻辑,零网络。"""

    def __init__(self, sources: list[SourceDecl],
                 cooldown_base: float = 60.0, cooldown_max: float = 3600.0,
                 now=None):
        self.sources = list(sources)
        self.cooldown_base = float(cooldown_base)
        self.cooldown_max = float(cooldown_max)
        self._now = now or time.time

    # ---- 工厂:萤火现役/备役源声明(能力→源→优先级) ----
    @classmethod
    def default(cls, **kw) -> "CapabilityRouter":
        """萤火默认路由表。优先级:数值小者先试。

        现役(11-18 事故后定案):
          · spot_snapshot: EM(主) — 唯一实时源,WAF 冷却期只能等(实时快照无备源)
          · index_bars:    EM(主) → sina(备,11-16 回补已验证 244/244 同源口径)
          · daily_bars:    cne/TDX(主) → sina(备,退市回补已验证) → EM hfq(仅小补丁)
          · zt_pool:       EM push2ex(唯一,~3 周窗口不可回补)
          · margin:        中证金融(非 EM 域,EM 封锁期实测可用)
          · erp:           乐咕(非 EM 域)
          · calendar:      cne 湖(本地) → 新浪对拍(联网校验)
        """
        decls = [
            SourceDecl("eastmoney", ("daily_bars", "spot_snapshot", "index_bars",
                                     "zt_pool"), priority=10),
            SourceDecl("sina", ("index_bars", "daily_bars", "calendar"), priority=20),
            SourceDecl("tdx_cne", ("daily_bars", "calendar"), priority=5),
            SourceDecl("csf_margin", ("margin",), priority=10),
            SourceDecl("legu", ("erp",), priority=10),
        ]
        return cls(decls, **kw)

    # ---- 路由 ----
    def route(self, capability: str) -> str | None:
        """按能力返回最优源名;全部冷却中/无源声明该能力 → None(fail-closed)。"""
        if capability not in CAPABILITIES:
            return None  # 未登记能力,fail-closed
        cands = [s for s in self.sources
                 if capability in s.capabilities
                 and not self._cooling(s)]
        if not cands:
            return None
        return min(cands, key=lambda s: s.priority).name

    def route_all(self, capability: str) -> list[str]:
        """按优先级返回全部可用源(failover 用)。"""
        if capability not in CAPABILITIES:
            return []
        cands = [s for s in self.sources
                 if capability in s.capabilities and not self._cooling(s)]
        return [s.name for s in sorted(cands, key=lambda s: s.priority)]

    def _cooling(self, s: SourceDecl) -> bool:
        cu = s.health.cooldown_until
        return cu is not None and self._now() < cu

    # ---- 健康 ----
    def report_failure(self, source_name: str) -> float | None:
        """源失败:指数退避冷却(60s→120s→...→封顶 1h)。返回冷却到期时刻。"""
        s = self._get(source_name)
        if s is None:
            return None
        h = s.health
        h.fails += 1
        backoff = min(self.cooldown_base * (2 ** (h.fails - 1)), self.cooldown_max)
        h.failed_at = self._now()
        h.cooldown_until = h.failed_at + backoff
        h.ok_since = None
        return h.cooldown_until

    def report_success(self, source_name: str) -> None:
        s = self._get(source_name)
        if s is not None:
            s.health = SourceHealth(ok_since=self._now())

    def _get(self, name: str) -> SourceDecl | None:
        return next((s for s in self.sources if s.name == name), None)

    # ---- 持久化(冷却跨进程生效——计划任务每次新进程) ----
    def save_state(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {s.name: s.health.to_dict() for s in self.sources}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def load_state(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            return
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # 损坏即忽略(健康状态宁可重置,不可带毒)
        for s in self.sources:
            if s.name in payload:
                for k, v in payload[s.name].items():
                    setattr(s.health, k, v)
