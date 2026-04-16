"""config.yaml 로더"""
from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load() -> dict:
    with _CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    cfg = load()
    print(f"관심 종목 {len(cfg['watchlist'])}개:")
    for s in cfg["watchlist"]:
        print(f"  - {s['name']} ({s['code']}.{s['market']}) / {s['sector']}")
    print(f"\n거시 지표 {len(cfg['macro'])}개:")
    for m in cfg["macro"]:
        print(f"  - {m['name']} ({m['ticker']})")
