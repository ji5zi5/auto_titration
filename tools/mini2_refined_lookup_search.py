#!/usr/bin/env python3
"""Refined 5-image Mini2 formula/lookup search.

This script focuses on the strongest discovery so far:

    d = raw_u16 - metadata_u16[284]

It searches lookup, hierarchical lookup, Chebyshev polynomial, and simple
rational candidates, reporting both five-image in-sample performance and
leave-one-image-out performance.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Hashable

import numpy as np
from numpy.polynomial import Chebyshev

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mini2_formula_candidate_sweep import ImageData, load_images


def residual_stats(pred: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    err = pred.astype(float) - target.astype(float)
    return {
        "mae_c": float(np.mean(np.abs(err))),
        "rmse_c": float(math.sqrt(float(np.mean(err * err)))),
        "max_abs_c": float(np.max(np.abs(err))),
        "mean_error_c": float(np.mean(err)),
        "round_0p1_match_pixels": int(np.count_nonzero(np.round(pred, 1) == target)),
        "round_0p1_mismatch_pixels": int(np.count_nonzero(np.round(pred, 1) != target)),
        "pixel_count": int(target.size),
    }


def combine(chunks: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, float | int]:
    return residual_stats(
        np.concatenate([pred.ravel() for pred, _target in chunks]),
        np.concatenate([target.ravel() for _pred, target in chunks]),
    )


def d_values(img: ImageData) -> np.ndarray:
    return img.raw.ravel().astype(int) - int(img.metadata_u16[284])


def key_d(img: ImageData) -> list[tuple[int]]:
    return [(int(d),) for d in d_values(img)]


def key_d_m284(img: ImageData) -> list[tuple[int, int]]:
    m = int(img.metadata_u16[284])
    return [(int(d), m) for d in d_values(img)]


def key_d_m284_m0(img: ImageData) -> list[tuple[int, int, int]]:
    m = int(img.metadata_u16[284])
    m0 = int(img.metadata_u16[0])
    return [(int(d), m, m0) for d in d_values(img)]


def build_lookup(
    images: list[ImageData],
    key_fn: Callable[[ImageData], list[Hashable]],
    reducer: str,
) -> dict[Hashable, float]:
    groups: dict[Hashable, list[float]] = defaultdict(list)
    for img in images:
        for key, temp in zip(key_fn(img), img.temp.ravel()):
            groups[key].append(float(temp))
    lookup: dict[Hashable, float] = {}
    for key, values in groups.items():
        if reducer == "median":
            lookup[key] = float(np.median(values))
        elif reducer == "mean":
            lookup[key] = float(np.mean(values))
        elif reducer == "mode":
            lookup[key] = float(Counter(values).most_common(1)[0][0])
        else:
            raise ValueError(reducer)
    return lookup


def lookup_predict_exact(
    img: ImageData,
    lookup: dict[Hashable, float],
    key_fn: Callable[[ImageData], list[Hashable]],
) -> np.ndarray:
    return np.array([lookup[key] for key in key_fn(img)], dtype=float)


def lookup_predict_d_interp(img: ImageData, lookup: dict[tuple[int], float]) -> np.ndarray:
    xs = np.array([key[0] for key in sorted(lookup)], dtype=float)
    ys = np.array([lookup[(int(x),)] for x in xs], dtype=float)
    return np.interp(d_values(img).astype(float), xs, ys, left=ys[0], right=ys[-1])


def hierarchical_predict(img: ImageData, fine_lookup: dict[Hashable, float], fallback_d: dict[tuple[int], float], key_fn):
    keys = key_fn(img)
    fallback = lookup_predict_d_interp(img, fallback_d)
    pred = np.empty_like(fallback)
    hits = 0
    for i, key in enumerate(keys):
        if key in fine_lookup:
            pred[i] = fine_lookup[key]
            hits += 1
        else:
            pred[i] = fallback[i]
    return pred, hits


def evaluate_lookup(
    name: str,
    images: list[ImageData],
    key_fn: Callable[[ImageData], list[Hashable]],
    reducer: str = "mode",
    fallback_for_loo: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    lookup = build_lookup(images, key_fn, reducer)
    train_chunks = [(lookup_predict_exact(img, lookup, key_fn), img.temp.ravel()) for img in images]
    train = combine(train_chunks)

    # Ambiguity in the full five-image lookup.
    groups: dict[Hashable, Counter[float]] = defaultdict(Counter)
    for img in images:
        for key, temp in zip(key_fn(img), img.temp.ravel()):
            groups[key][float(temp)] += 1
    ambiguous = [counter for counter in groups.values() if len(counter) > 1]
    max_spread = max((max(counter) - min(counter) for counter in ambiguous), default=0.0)

    heldout_rows: list[dict[str, object]] = []
    heldout_chunks: list[tuple[np.ndarray, np.ndarray]] = []
    total_exact_key_hits = 0
    for hold in images:
        train_imgs = [img for img in images if img.stem != hold.stem]
        fine = build_lookup(train_imgs, key_fn, reducer)
        if key_fn is key_d:
            pred = lookup_predict_d_interp(hold, fine)
            hits = int(sum(1 for key in key_fn(hold) if key in fine))
        elif fallback_for_loo:
            fallback = build_lookup(train_imgs, key_d, reducer)
            pred, hits = hierarchical_predict(hold, fine, fallback, key_fn)
        else:
            # Only score pixels whose exact key exists; if none, use d fallback
            # so the LOO summary remains defined.
            fallback = build_lookup(train_imgs, key_d, reducer)
            pred, hits = hierarchical_predict(hold, fine, fallback, key_fn)
        total_exact_key_hits += hits
        st = residual_stats(pred, hold.temp.ravel())
        heldout_rows.append({"candidate": name, "held_out": hold.stem, "exact_key_hits": hits, **st})
        heldout_chunks.append((pred, hold.temp.ravel()))
    loo = combine(heldout_chunks)
    result = {
        "candidate": name,
        "family": "lookup",
        "reducer": reducer,
        "train_mae_c": train["mae_c"],
        "train_rmse_c": train["rmse_c"],
        "train_max_abs_c": train["max_abs_c"],
        "train_round_0p1_match_pixels": train["round_0p1_match_pixels"],
        "train_round_0p1_mismatch_pixels": train["round_0p1_mismatch_pixels"],
        "loo_mae_c": loo["mae_c"],
        "loo_rmse_c": loo["rmse_c"],
        "loo_max_abs_c": loo["max_abs_c"],
        "loo_round_0p1_match_pixels": loo["round_0p1_match_pixels"],
        "loo_round_0p1_mismatch_pixels": loo["round_0p1_mismatch_pixels"],
        "unique_keys": len(groups),
        "ambiguous_keys": len(ambiguous),
        "max_ambiguity_spread_c": float(max_spread),
        "loo_exact_key_hits": total_exact_key_hits,
    }
    return result, heldout_rows


def fit_cheb(images: list[ImageData], degree: int) -> Chebyshev:
    x = np.concatenate([d_values(img).astype(float) for img in images])
    y = np.concatenate([img.temp.ravel() for img in images])
    return Chebyshev.fit(x, y, degree)


def evaluate_cheb(images: list[ImageData], max_degree: int = 40) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    held: list[dict[str, object]] = []
    for degree in range(1, max_degree + 1):
        model = fit_cheb(images, degree)
        train_chunks = [(model(d_values(img).astype(float)), img.temp.ravel()) for img in images]
        train = combine(train_chunks)
        held_chunks: list[tuple[np.ndarray, np.ndarray]] = []
        for hold in images:
            train_imgs = [img for img in images if img.stem != hold.stem]
            loo_model = fit_cheb(train_imgs, degree)
            pred = loo_model(d_values(hold).astype(float))
            st = residual_stats(pred, hold.temp.ravel())
            held.append({"candidate": f"chebyshev_d_degree_{degree}", "held_out": hold.stem, **st})
            held_chunks.append((pred, hold.temp.ravel()))
        loo = combine(held_chunks)
        rows.append(
            {
                "candidate": f"chebyshev_d_degree_{degree}",
                "family": "chebyshev_polynomial",
                "degree": degree,
                "train_mae_c": train["mae_c"],
                "train_rmse_c": train["rmse_c"],
                "train_max_abs_c": train["max_abs_c"],
                "train_round_0p1_match_pixels": train["round_0p1_match_pixels"],
                "train_round_0p1_mismatch_pixels": train["round_0p1_mismatch_pixels"],
                "loo_mae_c": loo["mae_c"],
                "loo_rmse_c": loo["rmse_c"],
                "loo_max_abs_c": loo["max_abs_c"],
                "loo_round_0p1_match_pixels": loo["round_0p1_match_pixels"],
                "loo_round_0p1_mismatch_pixels": loo["round_0p1_mismatch_pixels"],
                "coefficients": [float(v) for v in model.coef],
                "domain": [float(v) for v in model.domain],
                "window": [float(v) for v in model.window],
            }
        )
    return rows, held


def fit_rational(images: list[ImageData], p_degree: int, q_degree: int) -> tuple[np.ndarray, np.ndarray]:
    d = np.concatenate([d_values(img).astype(float) for img in images])
    y = np.concatenate([img.temp.ravel() for img in images])
    x = d / 300.0
    p_cols = [x**i for i in range(p_degree + 1)]
    q_cols = [-(y * (x**j)) for j in range(1, q_degree + 1)]
    features = np.column_stack(p_cols + q_cols)
    coeff, *_ = np.linalg.lstsq(features, y, rcond=None)
    return coeff[: p_degree + 1], coeff[p_degree + 1 :]


def rational_predict(img: ImageData, p: np.ndarray, q: np.ndarray) -> np.ndarray:
    x = d_values(img).astype(float) / 300.0
    num = sum(p[i] * x**i for i in range(len(p)))
    den = 1.0 + sum(q[j - 1] * x**j for j in range(1, len(q) + 1))
    # Avoid catastrophic blow-ups in weird overfit candidates.
    den = np.where(np.abs(den) < 1e-9, np.nan, den)
    return num / den


def evaluate_rational(images: list[ImageData]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    held: list[dict[str, object]] = []
    for p_degree in range(1, 8):
        for q_degree in range(1, 5):
            p, q = fit_rational(images, p_degree, q_degree)
            train_chunks = [(rational_predict(img, p, q), img.temp.ravel()) for img in images]
            if any(np.any(~np.isfinite(pred)) for pred, _target in train_chunks):
                continue
            train = combine(train_chunks)
            held_chunks: list[tuple[np.ndarray, np.ndarray]] = []
            bad = False
            for hold in images:
                train_imgs = [img for img in images if img.stem != hold.stem]
                p_loo, q_loo = fit_rational(train_imgs, p_degree, q_degree)
                pred = rational_predict(hold, p_loo, q_loo)
                if np.any(~np.isfinite(pred)) or np.nanmax(np.abs(pred)) > 1e6:
                    bad = True
                    break
                st = residual_stats(pred, hold.temp.ravel())
                held.append({"candidate": f"rational_d_p{p_degree}_q{q_degree}", "held_out": hold.stem, **st})
                held_chunks.append((pred, hold.temp.ravel()))
            if bad:
                continue
            loo = combine(held_chunks)
            rows.append(
                {
                    "candidate": f"rational_d_p{p_degree}_q{q_degree}",
                    "family": "rational",
                    "p_degree": p_degree,
                    "q_degree": q_degree,
                    "train_mae_c": train["mae_c"],
                    "train_rmse_c": train["rmse_c"],
                    "train_max_abs_c": train["max_abs_c"],
                    "train_round_0p1_match_pixels": train["round_0p1_match_pixels"],
                    "train_round_0p1_mismatch_pixels": train["train_round_0p1_mismatch_pixels"] if "train_round_0p1_mismatch_pixels" in train else train["round_0p1_mismatch_pixels"],
                    "loo_mae_c": loo["mae_c"],
                    "loo_rmse_c": loo["rmse_c"],
                    "loo_max_abs_c": loo["max_abs_c"],
                    "loo_round_0p1_match_pixels": loo["round_0p1_match_pixels"],
                    "loo_round_0p1_mismatch_pixels": loo["round_0p1_mismatch_pixels"],
                    "p_coefficients": [float(v) for v in p],
                    "q_coefficients": [float(v) for v in q],
                }
            )
    return rows, held


def write_table(path: Path, lookup: dict[tuple[int], float]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["d_raw_minus_metadata284", "temp_c"])
        for key in sorted(lookup):
            writer.writerow([key[0], f"{lookup[key]:.6f}"])


def run(data_dir: Path) -> dict[str, object]:
    images = load_images(data_dir)
    out = data_dir / "refined_lookup_search"
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    heldout: list[dict[str, object]] = []
    for reducer in ["mode", "median", "mean"]:
        row, detail = evaluate_lookup(f"d_lookup_{reducer}", images, key_d, reducer)
        rows.append(row)
        heldout.extend(detail)

    for reducer in ["mode", "median", "mean"]:
        row, detail = evaluate_lookup(f"d_m284_lookup_{reducer}_hierarchical", images, key_d_m284, reducer, True)
        rows.append(row)
        heldout.extend(detail)
        row, detail = evaluate_lookup(f"d_m284_m0_lookup_{reducer}_hierarchical", images, key_d_m284_m0, reducer, True)
        rows.append(row)
        heldout.extend(detail)

    cheb_rows, cheb_held = evaluate_cheb(images, 40)
    rows.extend(cheb_rows)
    heldout.extend(cheb_held)

    rational_rows, rational_held = evaluate_rational(images)
    rows.extend(rational_rows)
    heldout.extend(rational_held)

    rows_by_train = sorted(rows, key=lambda r: (float(r["train_mae_c"]), float(r["train_max_abs_c"])))
    rows_by_loo = sorted(rows, key=lambda r: (float(r["loo_mae_c"]), float(r["loo_max_abs_c"])))

    d_lookup = build_lookup(images, key_d, "mode")
    write_table(out / "d_lookup_mode_table.csv", d_lookup)

    report = {
        "images": [
            {
                "stem": img.stem,
                "metadata_u16_284": int(img.metadata_u16[284]),
                "metadata_u16_0": int(img.metadata_u16[0]),
                "raw_range": [int(img.raw.min()), int(img.raw.max())],
                "d_range": [int(d_values(img).min()), int(d_values(img).max())],
                "temp_range_c": [float(img.temp.min()), float(img.temp.max())],
            }
            for img in images
        ],
        "candidate_count": len(rows),
        "top_by_train": rows_by_train[:20],
        "top_by_leave_one_out": rows_by_loo[:20],
        "all_candidates": rows_by_loo,
        "heldout_details": heldout,
        "recommended": {
            "best_five_image_fit": rows_by_train[0],
            "best_predictive_candidate": rows_by_loo[0],
            "practical_table": "d_lookup_mode_table.csv uses d=raw_u16-metadata_u16[284] and maps integer d to Celsius.",
            "warning": "d_m284_m0 lookup is exact for these five images but is a five-image calibration table, not a proven universal SDK formula.",
        },
    }
    return report


def save_report(report: dict[str, object], data_dir: Path) -> None:
    out = data_dir / "refined_lookup_search"
    out.mkdir(parents=True, exist_ok=True)
    (out / "refined_lookup_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = sorted({key for row in report["all_candidates"] for key in row.keys()})
    with (out / "refined_candidate_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report["all_candidates"])

    held_fields = sorted({key for row in report["heldout_details"] for key in row.keys()})
    with (out / "refined_heldout_details.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=held_fields)
        writer.writeheader()
        writer.writerows(report["heldout_details"])

    lines = [
        "# Mini2 Refined Five-Image Approximation Search",
        "",
        "## 결론",
        "",
        "- 기존 4차식보다 더 좋은 방법은 **식 하나**라기보다 `d = raw_u16 - metadata_u16[284]` 기반 lookup table이다.",
        "- `d`만 쓰는 lookup은 5장 전체에서 0.1℃ 반올림 일치율이 매우 높다.",
        "- `d + metadata_u16[284] + metadata_u16[0]` lookup은 5장 내부에서는 exact지만, 사실상 5장 calibration table이라 새 장면 일반화는 검증되지 않았다.",
        "",
        "## 상위: five-image training fit",
        "",
        "| rank | candidate | family | train MAE | train max | train 0.1℃ match | LOO MAE | LOO max |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for i, row in enumerate(report["top_by_train"][:10], start=1):
        lines.append(
            f"| {i} | `{row['candidate']}` | {row['family']} | {float(row['train_mae_c']):.6f} | "
            f"{float(row['train_max_abs_c']):.6f} | {int(row['train_round_0p1_match_pixels'])}/245760 | "
            f"{float(row['loo_mae_c']):.6f} | {float(row['loo_max_abs_c']):.6f} |"
        )
    lines += [
        "",
        "## 상위: leave-one-image-out",
        "",
        "| rank | candidate | family | LOO MAE | LOO max | LOO 0.1℃ match | train MAE |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for i, row in enumerate(report["top_by_leave_one_out"][:10], start=1):
        lines.append(
            f"| {i} | `{row['candidate']}` | {row['family']} | {float(row['loo_mae_c']):.6f} | "
            f"{float(row['loo_max_abs_c']):.6f} | {int(row['loo_round_0p1_match_pixels'])}/245760 | "
            f"{float(row['train_mae_c']):.6f} |"
        )
    lines += [
        "",
        "## 추천 실사용 근사",
        "",
        "```text",
        "m = metadata_u16[284]",
        "d = raw_u16 - m",
        "T ≈ d_lookup_table[d]",
        "```",
        "",
        "- table file: `d_lookup_mode_table.csv`",
        "- 이건 닫힌 다항식보다 훨씬 정확하지만, 5장 calibration 기반이므로 더 많은 JPEG+CSV로 table을 갱신하는 게 좋다.",
    ]
    (out / "refined_lookup_search_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/mini2_multi_image_formula")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    report = run(data_dir)
    save_report(report, data_dir)
    print(json.dumps(report["recommended"], ensure_ascii=False, indent=2))
    print(f"saved: {data_dir / 'refined_lookup_search' / 'refined_lookup_search_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
