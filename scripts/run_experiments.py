"""Run the controlled experiments required by REPORT_TEMPLATE.md.

The script mutates copies of the public configuration in memory.  It never
changes the submitted production settings in ``configs/gameday.yaml``.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gameday_lab.cache import CachingClient, SemanticCache
from gameday_lab.client import ResilientClient
from gameday_lab.sim.config import LabConfig, load_config
from gameday_lab.sim.engine import run_scenario


class UnsafeToolClient(ResilientClient):
    """Experiment only: deliberately omits the tool-capability guard."""

    def ladder(self, task: str) -> list[str]:
        return list(self.order)


def fresh_config(cache_tape: bool = False) -> LabConfig:
    scenarios = "configs/scenarios_cache.yaml" if cache_tape else "configs/scenarios.yaml"
    return load_config(ROOT / "configs/gameday.yaml", ROOT / scenarios)


def client(cfg: LabConfig, *, unsafe_tools: bool = False) -> ResilientClient:
    cls = UnsafeToolClient if unsafe_tools else ResilientClient
    return cls(cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=cfg.seed)


def select(metrics: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {field: metrics.get(field) for field in fields}


def run_client(cfg: LabConfig, scenario: str, *, unsafe_tools: bool = False) -> dict[str, object]:
    return run_scenario(cfg, scenario, client(cfg, unsafe_tools=unsafe_tools)).metrics()


def run_cache(cfg: LabConfig) -> dict[str, object]:
    inner = client(cfg)
    cached = CachingClient(inner, SemanticCache(**cfg.cache))
    return run_scenario(cfg, "C1_faq_outage", cached).metrics()


def main() -> None:
    output: dict[str, object] = {}

    # Experiment 1: breaker deliberately disabled, with and without budget.
    budget_rows: dict[str, object] = {}
    for mode in ("budget_on", "budget_off"):
        cfg = fresh_config()
        cfg.client["max_attempts_per_provider"] = 5
        cfg.client["breaker"] = copy.deepcopy(cfg.client["breaker"])
        cfg.client["breaker"]["min_calls"] = 1_000_000_000
        if mode == "budget_off":
            cfg.client.update(
                retry_budget_ratio=100.0,
                retry_budget_max_tokens=1.0e9,
                retry_budget_min_per_s=1.0e6,
            )
        budget_rows[mode] = {
            scenario: select(
                run_client(cfg, scenario),
                ("availability", "amplification", "retry_ratio", "recovery_s"),
            )
            for scenario in ("G2_overload_storm", "G3_brownout")
        }
    output["retry_budget_with_broken_breaker"] = budget_rows

    # Experiment 2: an attempt consumes the complete user deadline.
    cfg = fresh_config()
    cfg.client["attempt_timeout_s"] = 30.0
    output["timeout_30s"] = {
        scenario: select(
            run_client(cfg, scenario),
            ("availability", "latency_p95_s", "give_up_reasons", "amplification"),
        )
        for scenario in ("G6_provider_outage", "G4_slow_region")
    }

    # Experiment 3: deliberately route tool calls to the incompatible mini model.
    cfg = fresh_config()
    output["without_tool_filter"] = select(
        run_client(cfg, "G6_provider_outage", unsafe_tools=True),
        ("availability", "incompatible_routes", "attempts_by_provider", "give_up_reasons"),
    )

    # Cache experiments required by report section 8.
    threshold_rows: dict[str, object] = {}
    for value in (0.80, 0.90, 0.97):
        cfg = fresh_config(cache_tape=True)
        cfg.cache["similarity_threshold"] = value
        threshold_rows[f"{value:.2f}"] = select(
            run_cache(cfg),
            ("faq_availability", "cache_hit_ratio", "wrong_answers", "wrong_answers_by_reason", "cost_per_good_turn"),
        )
    output["cache_threshold"] = threshold_rows

    ttl_rows: dict[str, object] = {}
    for value in (30, 60, 300):
        cfg = fresh_config(cache_tape=True)
        cfg.cache["ttl_s"] = value
        ttl_rows[str(value)] = select(
            run_cache(cfg),
            ("faq_availability", "cache_hit_ratio", "wrong_answers", "outdated_answers", "cost_per_good_turn"),
        )
    output["cache_ttl"] = ttl_rows

    cfg = fresh_config(cache_tape=True)
    cfg.cache["max_stale_s"] = 0
    output["cache_without_stale"] = select(
        run_cache(cfg),
        ("faq_availability", "cache_hit_ratio", "stale_served", "wrong_answers", "outdated_answers"),
    )

    path = ROOT / "reports/experiments.json"
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nWrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
