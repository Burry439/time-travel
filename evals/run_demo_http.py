"""Live HTTP creation, save/reload, and generated-art check against the demo launcher.

Creates one developer journey in the demo database and waits for its single painting.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run(server):
    with httpx.Client(base_url=server, timeout=20) as client:
        ready = client.get("/health/ai").json()
        if not ready.get("ready") or ready.get("mode") != "live":
            raise RuntimeError("The live demo backend is not ready.")
        response = client.post("/runs", json={"mode": "developer"})
        response.raise_for_status()
        state = response.json()
        run_id = state["run_id"]
        report = {"run_id": run_id, "server": server, "checks": []}
        for number, text in enumerate(
            (
                "Pick up the flint shard and the fallen branch nearby.",
                "Using my flint, carve a shallow spiral groove around the branch, with regular tick marks. Keep the same stick; the groove is a guide for drops of water.",
            ),
            1,
        ):
            started = time.monotonic()
            reply = client.post(
                f"/runs/{run_id}/craft",
                json={
                    "text": text,
                    "selected_ids": [],
                    "expected_version": state["event_seq"],
                    "request_id": f"demo-http-{number}",
                },
            )
            reply.raise_for_status()
            state = reply.json()["state"]
            row = {
                "check": "gather" if number == 1 else "create",
                "category": state["last_action"]["category"],
                "seconds": round(time.monotonic() - started, 2),
            }
            report["checks"].append(row)
            print(json.dumps(row), flush=True)
            if row["category"] not in ("success", "partial_success"):
                raise RuntimeError("The live physical attempt did not succeed.")
        changed = next(
            o
            for o in state["objects"].values()
            if o.get("attributes") and o.get("picture_event_id")
        )
        report["object"] = changed
        reloaded = client.get(f"/runs/{run_id}").json()
        assert reloaded["objects"][changed["id"]] == changed
        report["save_reload"] = True
        end = time.monotonic() + 210
        last_status = None
        while time.monotonic() < end:
            traces = client.get(f"/runs/{run_id}/traces").json()
            asset = next(
                a
                for a in traces["assets"]
                if a["asset_id"] == changed["sprite_asset_id"]
            )
            if asset["status"] != last_status:
                print(json.dumps({"painting": asset["status"]}), flush=True)
                last_status = asset["status"]
            if asset["status"] in ("ready", "failed", "disabled"):
                report["art"] = {
                    "status": asset["status"],
                    "model": asset["call"].get("model"),
                    "latency_ms": asset["call"].get("latency_ms"),
                    "record": asset["record"],
                }
                if asset["status"] == "ready":
                    png = client.get(f"/assets/{changed['sprite_asset_id']}")
                    report["png_served"] = (
                        png.status_code == 200 and png.content.startswith(b"\x89PNG")
                    )
                break
            time.sleep(2)
        report["passed"] = bool(report.get("png_served") and report.get("save_reload"))
        path = (
            ROOT
            / "evals/results"
            / (
                "demo_http_"
                + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                + ".json"
            )
        )
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "art": report.get("art", {}).get("status"),
                    "report": str(path),
                }
            )
        )
        return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8767")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.server) else 1)
