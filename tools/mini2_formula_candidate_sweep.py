#!/usr/bin/env python3
"""Sweep many Mini2 raw->Celsius formula candidates against 5 JPEG+CSV pairs.

The goal is not to invent a pretty curve from min/max only. The goal is to
stress-test candidate families with pixel-level residuals and leave-one-image-
out validation so we can separate:

* exact-but-not-predictive same-file lookup,
* useful practical approximations,
* overfit formulas that only look good in-sample,
* formulas that need unavailable SDK/frame calibration metadata.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auto_titrator.thermal_camera import load_hikmicro_temperature_csv
from tools.mini2_extract_rjpeg_raw_win import iter_jpeg_segments, parse_sdmp_ifd

RAW_SHAPE = (192, 256)
EPS = 1e-12


@dataclass
class ImageData:
    stem: str
    raw: np.ndarray
    temp: np.ndarray
    metadata_u16: np.ndarray

    @property
    def x(self) -> np.ndarray:
        return self.raw.ravel().astype(float)

    @property
    def y(self) -> np.ndarray:
        return self.temp.ravel().astype(float)

    @property
    def raw_min(self) -> float:
        return float(self.raw.min())

    @property
    def raw_max(self) -> float:
        return float(self.raw.max())

    @property
    def raw_range(self) -> float:
        return self.raw_max - self.raw_min

    @property
    def raw_mean(self) -> float:
        return float(self.raw.mean())

    @property
    def raw_std(self) -> float:
        return float(self.raw.std())

    @property
    def temp_min(self) -> float:
        return float(self.temp.min())

    @property
    def temp_max(self) -> float:
        return float(self.temp.max())

    @property
    def temp_range(self) -> float:
        return self.temp_max - self.temp_min

    @property
    def temp_mean(self) -> float:
        return float(self.temp.mean())

    @property
    def temp_std(self) -> float:
        return float(self.temp.std())

    def u_minmax(self) -> np.ndarray:
        return (self.x - self.raw_min) / (self.raw_range + EPS)

    def y_minmax(self) -> np.ndarray:
        return (self.y - self.temp_min) / (self.temp_range + EPS)

    def q_rank(self) -> np.ndarray:
        # Percentile rank by raw value within the image. Ties get the average
        # percentile of their raw bin.
        flat = self.raw.ravel()
        values, inverse, counts = np.unique(flat, return_inverse=True, return_counts=True)
        starts = np.cumsum(np.r_[0, counts[:-1]])
        mids = starts + (counts - 1) / 2.0
        denom = max(float(flat.size - 1), 1.0)
        return mids[inverse] / denom


def load_metadata_u16(jpeg_path: Path) -> np.ndarray:
    data = jpeg_path.read_bytes()
    for _off, marker, _payload_start, payload in iter_jpeg_segments(data):
        if marker == 0xE3 and payload.startswith(b"SDMP"):
            by_tag = {entry.tag: entry for entry in parse_sdmp_ifd(payload)}
            if {0, 1, 2, 3, 4, 5}.issubset(by_tag):
                entry = by_tag[1]
                if entry.data_offset_from_payload_start is None or entry.byte_count is None:
                    continue
                block = payload[
                    entry.data_offset_from_payload_start : entry.data_offset_from_payload_start + entry.byte_count
                ]
                return np.frombuffer(block, dtype="<u2").copy()
    return np.zeros(512, dtype=np.uint16)


def load_images(data_dir: Path) -> list[ImageData]:
    images: list[ImageData] = []
    for raw_path in sorted((data_dir / "raw").glob("IR_*_lpld_raw_u16_256x192.bin")):
        stem = raw_path.name.replace("_lpld_raw_u16_256x192.bin", "")
        raw = np.fromfile(raw_path, dtype="<u2").reshape(RAW_SHAPE)
        temp = load_hikmicro_temperature_csv(Path("data/fixtures/mini2") / f"{stem}_이미지.csv").values.astype(float)
        metadata = load_metadata_u16(Path("data/fixtures/mini2") / f"{stem}.jpeg")
        images.append(ImageData(stem=stem, raw=raw, temp=temp, metadata_u16=metadata))
    if not images:
        raise FileNotFoundError(f"no raw files found under {data_dir / 'raw'}")
    return images


def residual_stats(pred: np.ndarray, target: np.ndarray) -> dict[str, float | int]:
    err = pred.astype(float) - target.astype(float)
    return {
        "mae_c": float(np.mean(np.abs(err))),
        "rmse_c": float(math.sqrt(float(np.mean(err * err)))),
        "max_abs_c": float(np.max(np.abs(err))),
        "mean_error_c": float(np.mean(err)),
        "round_0p1_mismatch_pixels": int(np.count_nonzero(np.round(pred, 1) != target)),
        "pixel_count": int(target.size),
    }


def combine_stats(chunks: list[tuple[np.ndarray, np.ndarray]]) -> dict[str, float | int]:
    pred = np.concatenate([p.ravel() for p, _t in chunks])
    target = np.concatenate([t.ravel() for _p, t in chunks])
    return residual_stats(pred, target)


class StandardizedLinearModel:
    def __init__(self, mean: np.ndarray, scale: np.ndarray, coef: np.ndarray):
        self.mean = mean
        self.scale = scale
        self.coef = coef

    def predict(self, features: np.ndarray) -> np.ndarray:
        x = (features - self.mean) / self.scale
        return x @ self.coef


def fit_linear(features: np.ndarray, target: np.ndarray, ridge: float = 0.0) -> StandardizedLinearModel:
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    constant = scale < EPS
    # Preserve constant/intercept columns instead of centering them to zero.
    mean[constant] = 0.0
    scale[constant] = 1.0
    x = (features - mean) / scale
    if ridge > 0:
        reg = np.eye(x.shape[1]) * ridge
        reg[0, 0] = 0.0  # do not penalize constant column
        try:
            coef = np.linalg.solve(x.T @ x + reg, x.T @ target)
        except np.linalg.LinAlgError:
            coef, *_ = np.linalg.lstsq(x.T @ x + reg, x.T @ target, rcond=None)
    else:
        coef, *_ = np.linalg.lstsq(x, target, rcond=None)
    return StandardizedLinearModel(mean, scale, coef)


def column_stack(parts: list[np.ndarray]) -> np.ndarray:
    return np.column_stack([part.ravel().astype(float) for part in parts])


def raw_poly_features(img: ImageData, degree: int) -> np.ndarray:
    # Normalize raw globally-ish around Mini2 values to avoid raw^10 explosions.
    z = (img.x - 5100.0) / 300.0
    return column_stack([np.ones_like(z), *[z**d for d in range(1, degree + 1)]])


def normalized_u_features(img: ImageData, degree: int) -> np.ndarray:
    u = img.u_minmax()
    return column_stack([np.ones_like(u), *[u**d for d in range(1, degree + 1)]])


def rank_features(img: ImageData, degree: int) -> np.ndarray:
    q = img.q_rank()
    return column_stack([np.ones_like(q), *[q**d for d in range(1, degree + 1)]])


def raw_stats_features(img: ImageData, degree: int = 3) -> np.ndarray:
    z = (img.x - img.raw_mean) / (img.raw_std + EPS)
    u = img.u_minmax()
    ones = np.ones_like(z)
    scalar_parts = [
        ones,
        z,
        u,
        *[u**d for d in range(2, degree + 1)],
        ones * img.raw_min,
        ones * img.raw_max,
        ones * img.raw_range,
        ones * img.raw_mean,
        ones * img.raw_std,
        z * img.raw_min,
        z * img.raw_max,
        z * img.raw_range,
    ]
    return column_stack(scalar_parts)


def metadata_word_features(img: ImageData, word_index: int, degree: int = 2) -> np.ndarray:
    z = (img.x - 5100.0) / 300.0
    m = float(img.metadata_u16[word_index]) if word_index < img.metadata_u16.size else 0.0
    mn = (m - 30000.0) / 30000.0
    return column_stack(
        [
            np.ones_like(z),
            z,
            *[z**d for d in range(2, degree + 1)],
            np.ones_like(z) * mn,
            z * mn,
        ]
    )


def metadata_multi_features(img: ImageData, word_indices: list[int]) -> np.ndarray:
    z = (img.x - 5100.0) / 300.0
    cols = [np.ones_like(z), z, z * z, z * z * z]
    for idx in word_indices:
        m = float(img.metadata_u16[idx]) if idx < img.metadata_u16.size else 0.0
        mn = (m - 30000.0) / 30000.0
        cols.extend([np.ones_like(z) * mn, z * mn])
    return column_stack(cols)


def metadata_offset_poly_features(img: ImageData, word_index: int, degree: int) -> np.ndarray:
    """Interpretable candidate: temperature from (raw - metadata_word).

    Word 284 looked offset-like in the JPEG tag1 block during manual probing.
    This family tests that idea for every metadata word that changes across
    images instead of hard-coding the answer.
    """

    m = float(img.metadata_u16[word_index]) if word_index < img.metadata_u16.size else 0.0
    d = (img.x - m) / 300.0
    return column_stack([np.ones_like(d), *[d**power for power in range(1, degree + 1)]])


def direct_offset_poly_formula(images: list[ImageData], word_index: int, degree: int) -> dict[str, object]:
    """Fit an unstandardized formula with d=(raw-metadata[word_index]).

    Returned coefficients are directly readable:
    `T = c0 + c1*d + c2*d^2 + ...`.
    """

    def features(img: ImageData) -> np.ndarray:
        m = float(img.metadata_u16[word_index])
        d = img.x - m
        return column_stack([np.ones_like(d), *[d**power for power in range(1, degree + 1)]])

    x = np.vstack([features(img) for img in images])
    y = np.concatenate([img.y for img in images])
    coeff, *_ = np.linalg.lstsq(x, y, rcond=None)
    train_stats = residual_stats(x @ coeff, y)
    heldout = []
    chunks = []
    for hold in images:
        train_imgs = [img for img in images if img.stem != hold.stem]
        x_train = np.vstack([features(img) for img in train_imgs])
        y_train = np.concatenate([img.y for img in train_imgs])
        held_coeff, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
        pred = features(hold) @ held_coeff
        st = residual_stats(pred, hold.y)
        heldout.append({"held_out": hold.stem, "coefficients": [float(v) for v in held_coeff], **st})
        chunks.append((pred, hold.y))
    loo_stats = combine_stats(chunks)
    return {
        "word_index": word_index,
        "degree": degree,
        "metadata_values_by_image": {img.stem: int(img.metadata_u16[word_index]) for img in images},
        "formula": "T_celsius = c0 + c1*d + c2*d^2 + ... where d = raw_u16 - metadata_u16[word_index]",
        "coefficients_c0_to_cd": [float(v) for v in coeff],
        "train": train_stats,
        "leave_one_image_out": loo_stats,
        "heldout_details": heldout,
    }


def evaluate_linear_candidate(
    name: str,
    family: str,
    images: list[ImageData],
    feature_fn: Callable[[ImageData], np.ndarray],
    target_fn: Callable[[ImageData], np.ndarray],
    output_fn: Callable[[ImageData, np.ndarray], np.ndarray],
    *,
    uses_temp_minmax: bool = False,
    uses_metadata: bool = False,
    ridge: float = 0.0,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    x_train = np.vstack([feature_fn(img) for img in images])
    y_train = np.concatenate([target_fn(img) for img in images])
    model = fit_linear(x_train, y_train, ridge=ridge)
    train_chunks = [(output_fn(img, model.predict(feature_fn(img))), img.y) for img in images]
    train = combine_stats(train_chunks)

    heldout_rows: list[dict[str, object]] = []
    heldout_chunks: list[tuple[np.ndarray, np.ndarray]] = []
    for hold in images:
        train_imgs = [img for img in images if img.stem != hold.stem]
        x = np.vstack([feature_fn(img) for img in train_imgs])
        y = np.concatenate([target_fn(img) for img in train_imgs])
        loo_model = fit_linear(x, y, ridge=ridge)
        pred = output_fn(hold, loo_model.predict(feature_fn(hold)))
        row = {"candidate": name, "held_out": hold.stem, **residual_stats(pred, hold.y)}
        heldout_rows.append(row)
        heldout_chunks.append((pred, hold.y))
    loo = combine_stats(heldout_chunks)
    result = {
        "candidate": name,
        "family": family,
        "uses_target_temp_minmax": uses_temp_minmax,
        "uses_jpeg_metadata": uses_metadata,
        "ridge": ridge,
        "train_mae_c": train["mae_c"],
        "train_rmse_c": train["rmse_c"],
        "train_max_abs_c": train["max_abs_c"],
        "train_round_0p1_mismatch_pixels": train["round_0p1_mismatch_pixels"],
        "loo_mae_c": loo["mae_c"],
        "loo_rmse_c": loo["rmse_c"],
        "loo_max_abs_c": loo["max_abs_c"],
        "loo_round_0p1_mismatch_pixels": loo["round_0p1_mismatch_pixels"],
    }
    return result, heldout_rows


def evaluate_no_train(
    name: str,
    family: str,
    images: list[ImageData],
    pred_fn: Callable[[ImageData], np.ndarray],
    *,
    uses_temp_minmax: bool,
    uses_metadata: bool = False,
) -> dict[str, object]:
    chunks = [(pred_fn(img), img.y) for img in images]
    result_stats = combine_stats(chunks)
    return {
        "candidate": name,
        "family": family,
        "uses_target_temp_minmax": uses_temp_minmax,
        "uses_jpeg_metadata": uses_metadata,
        "ridge": "",
        "train_mae_c": result_stats["mae_c"],
        "train_rmse_c": result_stats["rmse_c"],
        "train_max_abs_c": result_stats["max_abs_c"],
        "train_round_0p1_mismatch_pixels": result_stats["round_0p1_mismatch_pixels"],
        "loo_mae_c": "",
        "loo_rmse_c": "",
        "loo_max_abs_c": "",
        "loo_round_0p1_mismatch_pixels": "",
    }


def per_image_lookup_lower_bound(images: list[ImageData]) -> dict[str, object]:
    chunks = []
    ambiguous = 0
    for img in images:
        mapping: dict[int, float] = {}
        for raw_value in np.unique(img.raw):
            vals = img.temp[img.raw == raw_value]
            if len(set(float(v) for v in vals)) > 1:
                ambiguous += 1
            mapping[int(raw_value)] = float(vals[0])
        pred = np.vectorize(mapping.__getitem__)(img.raw).ravel()
        chunks.append((pred, img.y))
    result_stats = combine_stats(chunks)
    return {
        "candidate": "same_file_raw_lookup_lower_bound",
        "family": "lower_bound",
        "uses_target_temp_minmax": True,
        "uses_jpeg_metadata": False,
        "ridge": "",
        "train_mae_c": result_stats["mae_c"],
        "train_rmse_c": result_stats["rmse_c"],
        "train_max_abs_c": result_stats["max_abs_c"],
        "train_round_0p1_mismatch_pixels": result_stats["round_0p1_mismatch_pixels"],
        "loo_mae_c": "",
        "loo_rmme_c": "",
        "loo_max_abs_c": "",
        "loo_round_0p1_mismatch_pixels": "",
        "ambiguous_raw_values_within_files": ambiguous,
    }


def evaluate_gamma(images: list[ImageData]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    gammas = np.concatenate(
        [
            np.linspace(0.25, 0.95, 15),
            np.linspace(1.0, 3.0, 41),
            np.linspace(3.25, 8.0, 20),
        ]
    )
    for gamma in gammas:
        def pred_fn(img: ImageData, gamma: float = float(gamma)) -> np.ndarray:
            yn = np.clip(img.u_minmax(), 0, 1) ** gamma
            return img.temp_min + img.temp_range * yn

        row = evaluate_no_train(
            f"minmax_gamma_{gamma:.4f}",
            "target_minmax_gamma",
            images,
            pred_fn,
            uses_temp_minmax=True,
        )
        row["gamma"] = float(gamma)
        rows.append(row)
    return rows


def varying_metadata_indices(images: list[ImageData]) -> list[int]:
    arr = np.stack([img.metadata_u16 for img in images])
    varying = np.where(np.ptp(arr, axis=0) != 0)[0]
    # Keep all variable words; there are only about 56 in the current files.
    return [int(v) for v in varying]


def run_sweep(output_dir: Path) -> dict[str, object]:
    images = load_images(output_dir)
    rows: list[dict[str, object]] = []
    heldout_rows: list[dict[str, object]] = []

    rows.append(per_image_lookup_lower_bound(images))

    rows.append(
        evaluate_no_train(
            "per_image_raw_minmax_to_temp_minmax_linear",
            "target_minmax_no_train",
            images,
            lambda img: img.temp_min + img.temp_range * img.u_minmax(),
            uses_temp_minmax=True,
        )
    )

    rows.append(
        evaluate_no_train(
            "per_image_raw_rank_to_temp_minmax_linear",
            "target_minmax_rank_no_train",
            images,
            lambda img: img.temp_min + img.temp_range * img.q_rank(),
            uses_temp_minmax=True,
        )
    )

    # Per-image fitted lower bounds: tells us how much error is due to curvature
    # after allowing a different fitted formula for every image.
    for degree in range(1, 9):
        chunks = []
        for img in images:
            coeff = np.polyfit(img.u_minmax(), img.y, degree)
            pred = np.polyval(coeff, img.u_minmax())
            chunks.append((pred, img.y))
        st = combine_stats(chunks)
        rows.append(
            {
                "candidate": f"per_image_fitted_u_poly_degree_{degree}_lower_bound",
                "family": "per_image_fitted_lower_bound",
                "uses_target_temp_minmax": False,
                "uses_jpeg_metadata": False,
                "ridge": "",
                "train_mae_c": st["mae_c"],
                "train_rmse_c": st["rmse_c"],
                "train_max_abs_c": st["max_abs_c"],
                "train_round_0p1_mismatch_pixels": st["round_0p1_mismatch_pixels"],
                "loo_mae_c": "",
                "loo_rmme_c": "",
                "loo_max_abs_c": "",
                "loo_round_0p1_mismatch_pixels": "",
            }
        )

    # Raw-only global polynomials.
    for degree in range(1, 11):
        result, detail = evaluate_linear_candidate(
            f"global_raw_poly_degree_{degree}",
            "global_raw_only",
            images,
            lambda img, degree=degree: raw_poly_features(img, degree),
            lambda img: img.y,
            lambda _img, pred_norm: pred_norm,
        )
        rows.append(result)
        heldout_rows.extend(detail)

    # Image raw stats only: no target temp min/max, no metadata.
    for degree in range(1, 7):
        result, detail = evaluate_linear_candidate(
            f"raw_stats_u_poly_degree_{degree}",
            "raw_image_stats_only",
            images,
            lambda img, degree=degree: raw_stats_features(img, degree),
            lambda img: img.y,
            lambda _img, pred_norm: pred_norm,
        )
        rows.append(result)
        heldout_rows.extend(detail)

    # Normalized min/max polynomial: tests the user's hypothesis directly. This
    # uses target image temp_min/temp_max, so it is a hypothesis test, not a live
    # conversion unless those temperatures come from SDK/metadata.
    for degree in range(1, 16):
        result, detail = evaluate_linear_candidate(
            f"target_minmax_normalized_u_poly_degree_{degree}",
            "target_minmax_normalized_curve",
            images,
            lambda img, degree=degree: normalized_u_features(img, degree),
            lambda img: img.y_minmax(),
            lambda img, pred_norm: img.temp_min + img.temp_range * pred_norm,
            uses_temp_minmax=True,
        )
        rows.append(result)
        heldout_rows.extend(detail)

    # Rank/percentile version of the same idea.
    for degree in range(1, 11):
        result, detail = evaluate_linear_candidate(
            f"target_minmax_rank_poly_degree_{degree}",
            "target_minmax_rank_curve",
            images,
            lambda img, degree=degree: rank_features(img, degree),
            lambda img: img.y_minmax(),
            lambda img, pred_norm: img.temp_min + img.temp_range * pred_norm,
            uses_temp_minmax=True,
        )
        rows.append(result)
        heldout_rows.extend(detail)

    # Gamma curves as another compact nonlinear family.
    rows.extend(evaluate_gamma(images))

    # Piecewise interpolation in normalized u.
    for bins in [8, 16, 32, 64, 128]:
        centers = np.linspace(0, 1, bins)
        # Train an empirical normalized curve on all images.
        all_u = np.concatenate([img.u_minmax() for img in images])
        all_yn = np.concatenate([img.y_minmax() for img in images])
        order = np.argsort(all_u)
        quant_x = np.quantile(all_u[order], centers)
        quant_y = np.array([np.median(all_yn[np.abs(all_u - qx) <= (1.0 / bins)]) for qx in quant_x])
        # Fill potential empty bins with direct interpolation on sorted samples.
        if np.any(~np.isfinite(quant_y)):
            quant_y = np.interp(quant_x, all_u[order], all_yn[order])

        def pred_piece(img: ImageData, qx=quant_x, qy=quant_y) -> np.ndarray:
            return img.temp_min + img.temp_range * np.interp(img.u_minmax(), qx, qy)

        row = evaluate_no_train(
            f"target_minmax_piecewise_u_bins_{bins}_train_all",
            "target_minmax_piecewise_curve_in_sample",
            images,
            pred_piece,
            uses_temp_minmax=True,
        )
        rows.append(row)

        # LOO version.
        held_chunks = []
        for hold in images:
            train_imgs = [img for img in images if img.stem != hold.stem]
            all_u_tr = np.concatenate([img.u_minmax() for img in train_imgs])
            all_yn_tr = np.concatenate([img.y_minmax() for img in train_imgs])
            order_tr = np.argsort(all_u_tr)
            qx = np.quantile(all_u_tr[order_tr], centers)
            qy = np.array([np.median(all_yn_tr[np.abs(all_u_tr - item) <= (1.0 / bins)]) for item in qx])
            if np.any(~np.isfinite(qy)):
                qy = np.interp(qx, all_u_tr[order_tr], all_yn_tr[order_tr])
            pred = hold.temp_min + hold.temp_range * np.interp(hold.u_minmax(), qx, qy)
            st = residual_stats(pred, hold.y)
            heldout_rows.append({"candidate": f"target_minmax_piecewise_u_bins_{bins}_loo", "held_out": hold.stem, **st})
            held_chunks.append((pred, hold.y))
        loo = combine_stats(held_chunks)
        rows.append(
            {
                "candidate": f"target_minmax_piecewise_u_bins_{bins}_loo_summary",
                "family": "target_minmax_piecewise_curve",
                "uses_target_temp_minmax": True,
                "uses_jpeg_metadata": False,
                "ridge": "",
                "train_mae_c": row["train_mae_c"],
                "train_rmse_c": row["train_rmme_c"] if "train_rmme_c" in row else row["train_rmse_c"],
                "train_max_abs_c": row["train_max_abs_c"],
                "train_round_0p1_mismatch_pixels": row["train_round_0p1_mismatch_pixels"],
                "loo_mae_c": loo["mae_c"],
                "loo_rmse_c": loo["rmse_c"],
                "loo_max_abs_c": loo["max_abs_c"],
                "loo_round_0p1_mismatch_pixels": loo["round_0p1_mismatch_pixels"],
            }
        )

    # Metadata-aware single-word affine/curved candidates.
    metadata_indices = varying_metadata_indices(images)
    for idx in metadata_indices:
        result, detail = evaluate_linear_candidate(
            f"metadata_word_{idx}_raw_poly2_interaction",
            "metadata_single_word",
            images,
            lambda img, idx=idx: metadata_word_features(img, idx, degree=2),
            lambda img: img.y,
            lambda _img, pred_norm: pred_norm,
            uses_metadata=True,
        )
        result["metadata_word_index"] = idx
        rows.append(result)
        heldout_rows.extend(detail)

    # Interpretable metadata-as-offset candidates. These are important because
    # they can become a simple usable formula if a word behaves like a raw offset.
    for idx in metadata_indices:
        for degree in range(1, 6):
            result, detail = evaluate_linear_candidate(
                f"raw_minus_metadata_word_{idx}_poly_degree_{degree}",
                "metadata_offset_poly",
                images,
                lambda img, idx=idx, degree=degree: metadata_offset_poly_features(img, idx, degree),
                lambda img: img.y,
                lambda _img, pred_norm: pred_norm,
                uses_metadata=True,
            )
            result["metadata_word_index"] = idx
            result["offset_polynomial_degree"] = degree
            rows.append(result)
            heldout_rows.extend(detail)

    # Metadata multi-word with ridge. Use the words that vary early plus the
    # calibration-looking indices observed in prior reports.
    chosen_meta = sorted(set(metadata_indices[:25] + [0, 1, 20, 25, 201, 202, 203, 204, 205, 264, 284]))
    for ridge in [0.0, 1e-6, 1e-3, 1e-1, 1.0, 10.0, 100.0, 1000.0]:
        result, detail = evaluate_linear_candidate(
            f"metadata_multiword_raw_poly3_ridge_{ridge:g}",
            "metadata_multi_word",
            images,
            lambda img, chosen_meta=chosen_meta: metadata_multi_features(img, chosen_meta),
            lambda img: img.y,
            lambda _img, pred_norm: pred_norm,
            uses_metadata=True,
            ridge=ridge,
        )
        result["metadata_word_indices"] = chosen_meta
        rows.append(result)
        heldout_rows.extend(detail)

    # Sort after converting blank LOO to infinity where needed.
    def loo_key(row: dict[str, object]) -> tuple[float, float]:
        value = row.get("loo_mae_c", "")
        max_value = row.get("loo_max_abs_c", "")
        return (
            float(value) if value != "" else float("inf"),
            float(max_value) if max_value != "" else float("inf"),
        )

    rows_sorted = sorted(rows, key=loo_key)
    train_sorted = sorted(rows, key=lambda r: (float(r["train_mae_c"]), float(r["train_max_abs_c"])))

    report = {
        "input_images": [
            {
                "stem": img.stem,
                "raw_range": [int(img.raw.min()), int(img.raw.max())],
                "raw_mean": img.raw_mean,
                "temp_range_c": [img.temp_min, img.temp_max],
                "temp_mean_c": img.temp_mean,
                "metadata_varying_word_count": len(metadata_indices),
            }
            for img in images
        ],
        "candidate_family_count": len({str(row["family"]) for row in rows}),
        "candidate_count": len(rows),
        "heldout_row_count": len(heldout_rows),
        "metadata_varying_indices": metadata_indices,
        "interpretable_offset_formula_word_284_degree_2": direct_offset_poly_formula(images, 284, 2)
        if 284 in metadata_indices
        else None,
        "best_interpretable_offset_formula_word_284_degree_4": direct_offset_poly_formula(images, 284, 4)
        if 284 in metadata_indices
        else None,
        "top_by_leave_one_image_out": rows_sorted[:25],
        "top_by_training_error": train_sorted[:25],
        "all_candidates": rows_sorted,
        "heldout_details": heldout_rows,
        "interpretation": {
            "best_predictive_family": rows_sorted[0]["family"],
            "best_predictive_candidate": rows_sorted[0]["candidate"],
            "best_predictive_loo_mae_c": rows_sorted[0]["loo_mae_c"],
            "best_predictive_loo_max_abs_c": rows_sorted[0]["loo_max_abs_c"],
            "best_in_sample_candidate": train_sorted[0]["candidate"],
            "warning": "Models using target temperature min/max are not live formulas unless temp_min/temp_max are obtained from SDK/metadata. Same-file lookup is an exact lower bound but not a general formula.",
        },
    }
    return report


def write_csvs(report: dict[str, object], output_dir: Path) -> None:
    out = output_dir / "formula_sweep"
    out.mkdir(parents=True, exist_ok=True)
    candidates = report["all_candidates"]
    fieldnames = sorted({key for row in candidates for key in row.keys()})
    with (out / "formula_candidate_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidates)

    heldout = report["heldout_details"]
    held_fields = sorted({key for row in heldout for key in row.keys()})
    with (out / "formula_candidate_heldout_details.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=held_fields)
        writer.writeheader()
        writer.writerows(heldout)

    with (out / "formula_sweep_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


def write_markdown(report: dict[str, object], output_dir: Path) -> None:
    out = output_dir / "formula_sweep"
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Mini2 Formula Candidate Sweep",
        "",
        "## 결론",
        "",
        f"- 테스트 후보 수: `{report['candidate_count']}`",
        f"- 후보 family 수: `{report['candidate_family_count']}`",
        f"- JPEG tag1에서 변하는 metadata word 수: `{len(report['metadata_varying_indices'])}`",
        "",
        "가장 중요한 판정:",
        "",
        "- 같은 파일 lookup은 0 오차지만 정답식이 아니라 같은 CSV에서 만든 lower bound다.",
        "- target temp min/max를 쓰는 정규화 곡선은 꽤 좋아지지만, min/max 온도를 이미 알아야 하므로 실시간 변환식으로는 불완전하다.",
        "- metadata word를 raw offset처럼 쓰는 후보가 가장 좋았다. 특히 `metadata_u16[284]`가 강한 후보로 나왔다.",
        "- 그래도 same-file lookup처럼 0 오차는 아니므로, 공식 SDK/프레임 보정식을 완전히 복원한 것은 아니다.",
        "",
        "## Leave-one-image-out 상위 후보",
        "",
        "| rank | candidate | family | uses temp min/max | uses metadata | LOO MAE °C | LOO max °C | train MAE °C |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for rank, row in enumerate(report["top_by_leave_one_image_out"][:15], start=1):
        lines.append(
            f"| {rank} | `{row['candidate']}` | {row['family']} | {row['uses_target_temp_minmax']} | "
            f"{row['uses_jpeg_metadata']} | {float(row['loo_mae_c']):.4f} | {float(row['loo_max_abs_c']):.4f} | {float(row['train_mae_c']):.4f} |"
        )

    lines += [
        "",
        "## Training error 상위 후보",
        "",
        "| rank | candidate | family | train MAE °C | train max °C | note |",
        "| ---: | --- | --- | ---: | ---: | --- |",
    ]
    for rank, row in enumerate(report["top_by_training_error"][:15], start=1):
        note = ""
        if row["family"] == "lower_bound":
            note = "same-file CSV lookup; exact but not predictive"
        elif row["uses_target_temp_minmax"]:
            note = "uses target image temp min/max"
        elif row["uses_jpeg_metadata"]:
            note = "metadata candidate"
        lines.append(
            f"| {rank} | `{row['candidate']}` | {row['family']} | {float(row['train_mae_c']):.4f} | {float(row['train_max_abs_c']):.4f} | {note} |"
        )

    best_offset_formula = report.get("best_interpretable_offset_formula_word_284_degree_4")
    simple_offset_formula = report.get("interpretable_offset_formula_word_284_degree_2")
    if best_offset_formula:
        coeff = best_offset_formula["coefficients_c0_to_cd"]
        loo = best_offset_formula["leave_one_image_out"]
        train = best_offset_formula["train"]
        values = best_offset_formula["metadata_values_by_image"]
        lines += [
            "",
            "## 가장 좋은 해석 가능 후보식: metadata word 284 offset 4차식",
            "",
            "JPEG tag1 metadata의 `u16[284]` 값을 `m`이라고 두고, `d = raw_u16 - m`으로 계산한 4차식이다.",
            "",
            "```text",
            f"T ≈ {coeff[0]:.12f} + {coeff[1]:.12f}*d + {coeff[2]:.12e}*d^2",
            f"    + {coeff[3]:.12e}*d^3 + {coeff[4]:.12e}*d^4",
            "d = raw_u16 - metadata_u16[284]",
            "```",
            "",
            f"- metadata_u16[284] 값: `{values}`",
            f"- 전체 5장 학습 오차: MAE `{train['mae_c']:.4f}°C`, max `{train['max_abs_c']:.4f}°C`",
            f"- leave-one-image-out 오차: MAE `{loo['mae_c']:.4f}°C`, max `{loo['max_abs_c']:.4f}°C`",
            "",
            "이 후보는 target 온도 min/max를 쓰지 않고 JPEG metadata와 raw만 사용하므로, 현재까지는 가장 실사용에 가까운 식이다.",
        ]
    if simple_offset_formula:
        coeff = simple_offset_formula["coefficients_c0_to_cd"]
        loo = simple_offset_formula["leave_one_image_out"]
        train = simple_offset_formula["train"]
        lines += [
            "",
            "## 더 단순한 후보식: metadata word 284 offset 2차식",
            "",
            "```text",
            f"T ≈ {coeff[0]:.12f} + {coeff[1]:.12f}*d + {coeff[2]:.12e}*d^2",
            "d = raw_u16 - metadata_u16[284]",
            "```",
            "",
            f"- 전체 5장 학습 오차: MAE `{train['mae_c']:.4f}°C`, max `{train['max_abs_c']:.4f}°C`",
            f"- leave-one-image-out 오차: MAE `{loo['mae_c']:.4f}°C`, max `{loo['max_abs_c']:.4f}°C`",
        ]

    lines += [
        "",
        "## 산출물",
        "",
        "- `formula_candidate_scores.csv`: 전체 후보 점수",
        "- `formula_candidate_heldout_details.csv`: 이미지별 held-out 세부 오차",
        "- `formula_sweep_report.json`: 전체 JSON",
    ]
    (out / "formula_sweep_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/mini2_multi_image_formula")
    args = parser.parse_args()

    output_dir = Path(args.data_dir)
    report = run_sweep(output_dir)
    write_csvs(report, output_dir)
    write_markdown(report, output_dir)
    print(json.dumps(report["interpretation"], ensure_ascii=False, indent=2))
    print(f"saved: {output_dir / 'formula_sweep' / 'formula_sweep_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
