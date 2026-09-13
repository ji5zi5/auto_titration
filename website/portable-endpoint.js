/* Frozen post-run endpoint inference. No fitting, theory input or pump commands.
 * Numerical source: auto_titrator/type_conditioned_sensor_live_model.py and
 * tools/sensor_transition_candidate_union.py. Node and phone WebWorker share it.
 */
(function (root) {
  'use strict';
  const COLS = ['visible_H_mean', 'visible_S_mean', 'visible_V_mean', 'thermal_raw_roi_p50', 'thermal_raw_roi_p95'];
  const WINDOWS = [2, 3, 5, 8, 12, 16];
  const finite = x => x === null || x === undefined || x === '' || typeof x === 'boolean' || !Number.isFinite(Number(x)) ? null : Number(x);
  const mean = a => a.reduce((s, x) => s + x, 0) / a.length;
  function median(a) { const x = Array.from(a).sort((a, b) => a - b), n = x.length; return n ? n % 2 ? x[n >> 1] : (x[n / 2 - 1] + x[n / 2]) / 2 : NaN; }
  const norm = a => Math.sqrt(a.reduce((s, x) => s + x * x, 0));
  const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
  const diff = (a, b, scale) => a.map((x, i) => (x - b[i]) / scale[i]);
  const std = (a, ddof = 0) => { const m = mean(a); return a.length > ddof ? Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - ddof)) : 0; };
  function evenRound(x) { const n = Math.floor(x); return x - n === 0.5 ? (n % 2 ? n + 1 : n) : Math.round(x); }
  const round6 = x => Number(x.toFixed(6));
  const colMedian = rows => [0, 1, 2, 3, 4].map(k => median(rows.map(r => r[k])));
  function scaleFor(matrix, n) {
    const block = matrix.slice(0, n), center = colMedian(block), floors = [0.01, 0.01, 0.01, 2, 2];
    return [center, center.map((c, i) => Math.max(floors[i], median(block.map(r => Math.abs(r[i] - c))) * 1.4826))];
  }
  function sensorMatrix(rows) {
    const matrix = [], valid = [], previous = [0, 0, 0, 0, 0];
    for (const row of rows) {
      const h = finite(row[COLS[0]]), s = finite(row[COLS[1]]), v = finite(row[COLS[2]]);
      const p50 = finite(row[COLS[3]]), p95 = finite(row[COLS[4]]);
      const ok = p50 !== null && p95 !== null && (Math.abs(p50) > 1e-12 || Math.abs(p95 - p50) > 1e-12);
      const values = [h !== null && s !== null ? s * Math.cos(h * Math.PI / 180) : null,
        h !== null && s !== null ? s * Math.sin(h * Math.PI / 180) : null, v, ok ? p50 : null, ok ? p95 - p50 : null];
      matrix.push(values.map((x, i) => { if (x !== null && Number.isFinite(x)) previous[i] = x; return previous[i]; })); valid.push(ok ? 1 : 0);
    }
    return { matrix, valid };
  }
  function localFeatures(matrix, valid, boundary, support, colors, thermals) {
    const base = Math.min(16, Math.max(6, Math.floor(matrix.length / 8)));
    const [initial, scale] = scaleFor(matrix, base), last = colMedian(matrix.slice(-base));
    const direction = diff(last, initial, scale), out = [];
    for (const w of WINDOWS) {
      const before = colMedian(matrix.slice(Math.max(0, boundary - w), boundary));
      const after = colMedian(matrix.slice(boundary, Math.min(matrix.length, boundary + w)));
      const shift = diff(after, before, scale), departure = diff(after, initial, scale);
      out.push(norm(shift.slice(0, 3)) / Math.sqrt(3), norm(shift.slice(3)) / Math.sqrt(2), norm(departure.slice(0, 3)) / Math.sqrt(3), norm(departure.slice(3)) / Math.sqrt(2));
    }
    const departure = diff(colMedian(matrix.slice(boundary, Math.min(matrix.length, boundary + 5))), initial, scale);
    for (const [lo, hi] of [[0, 3], [3, 5]]) {
      const d = direction.slice(lo, hi), state = departure.slice(lo, hi), coordinate = dot(state, d) / (dot(d, d) + 1e-9);
      out.push(coordinate, norm(state.map((x, i) => x - coordinate * d[i])), norm(d));
    }
    out.push(Math.log1p(support), Math.log1p(colors), Math.log1p(thermals), mean(valid.slice(Math.max(0, boundary - 8), Math.min(matrix.length, boundary + 8))));
    return out;
  }
  function candidates(rows) {
    const { matrix, valid } = sensorMatrix(rows), evidence = new Map(), cache = new Map();
    for (const w of WINDOWS) {
      const stats = [];
      for (let end = 2 * w - 1; end < matrix.length; end++) {
        const start = end - 2 * w + 1;
        stats.push([end, colMedian(matrix.slice(start, end - w + 1)), colMedian(matrix.slice(end - w + 1, end + 1)), mean(valid.slice(start, end + 1))]);
      }
      cache.set(w, stats);
    }
    for (const base of [6, 10, 16, 24]) for (const w of WINDOWS) for (const modality of ['color', 'thermal']) {
      if (base + 2 * w + 1 >= matrix.length || (modality === 'thermal' && mean(valid.slice(0, base)) < 0.75)) continue;
      const [center, scale] = scaleFor(matrix, base), first = Math.max(base, 2 * w - 1), scores = [];
      const lo = modality === 'color' ? 0 : 3, hi = modality === 'color' ? 3 : 5, divisor = Math.sqrt(hi - lo);
      for (const [end, before, after, coverage] of cache.get(w)) {
        if (end < first) continue;
        if (modality === 'thermal' && coverage < 0.75) scores.push([end, 0, 0]);
        else scores.push([end, norm(diff(after, before, scale).slice(lo, hi)) / divisor, norm(diff(after, center, scale).slice(lo, hi)) / divisor]);
      }
      for (const threshold of [0.15, 0.35, 0.70]) for (const confirm of [1, 2, 3]) for (const refractory of [1, 3, 6]) {
        if (base + 2 * w + confirm >= matrix.length) continue;
        let lastBoundary = -refractory;
        for (let i = 0; i < scores.length - confirm; i++) {
          const future = scores.slice(i, i + confirm + 1), [end, score] = scores[i];
          const lasting = Math.min(...future.map(x => x[2]));
          if (score < threshold || lasting < threshold || score < Math.max(...future.map(x => x[1]))) continue;
          const boundary = end - w + 1;
          if (boundary - lastBoundary < refractory) continue;
          lastBoundary = boundary;
          let item = evidence.get(boundary);
          if (!item) { item = { boundary, confirmation: Infinity, support: 0, strength: 0, color: 0, thermal: 0 }; evidence.set(boundary, item); }
          item.confirmation = Math.min(item.confirmation, future[future.length - 1][0]); item.support++; item.strength += score + 0.25 * lasting; item[modality]++;
        }
      }
    }
    let list = Array.from(evidence.values());
    if (list.length > 128) list = list.sort((a, b) => b.support - a.support || b.strength - a.strength || a.boundary - b.boundary).slice(0, 128);
    return list.sort((a, b) => a.boundary - b.boundary).map(c => ({ ...c, features: localFeatures(matrix, valid, c.boundary, c.support, c.color, c.thermal) }));
  }
  function scoreEstimator(pipeline, row) {
    if (!pipeline) throw Error('endpoint estimator missing');
    let x = row;
    for (const step of pipeline) {
      if (step.kind === 'scale') { x = x.map((v, i) => (v - step.mean[i]) / step.scale[i]); continue; }
      if (step.kind === 'linear') return dot(x.map((v, i) => v - step.center[i]), step.coef) + step.intercept;
      if (step.kind === 'rbf') return step.x.reduce((sum, train, k) => sum + Math.exp(-step.gamma * train.reduce((s, v, i) => s + (x[i] - v) ** 2, 0)) * step.dual[k], 0);
      if (step.kind === 'qda') {
        const logp = step.means.map((mu, k) => {
          const delta = x.map((v, i) => v - mu[i]), rotation = step.rotations[k], scales = step.scalings[k];
          let n2 = 0;
          for (let j = 0; j < scales.length; j++) { let value = 0; for (let i = 0; i < delta.length; i++) value += delta[i] * rotation[i][j] / Math.sqrt(scales[j]); n2 += value * value; }
          return -0.5 * (n2 + scales.reduce((s, v) => s + Math.log(v), 0)) + Math.log(step.priors[k]);
        }); return logp[1] - logp[0];
      }
      throw Error('unsupported portable estimator');
    }
    throw Error('endpoint estimator has no scorer');
  }
  function normalize(values, method) {
    if (values.some(x => !Number.isFinite(x))) throw Error('non-finite candidate score');
    if (method === 'zscore') { const sd = std(values), m = mean(values); return values.map(x => sd <= 1e-12 ? 0 : (x - m) / sd); }
    if (method === 'rank') { const order = values.map((_, i) => i).sort((a, b) => values[a] - values[b] || a - b), result = values.map(() => 0); order.forEach((i, rank) => { result[i] = rank / Math.max(1, values.length - 1); }); return result; }
    throw Error('unsupported score normalization');
  }
  function combined(entry, list, cfg) {
    const designs = list.map(c => cfg.feature_indices.map(i => c.features[i]).map(x => cfg.feature_transform === 'signed_log1p' ? Math.sign(x) * Math.log1p(Math.abs(x)) : x));
    if (!['raw', 'signed_log1p'].includes(cfg.feature_transform) || designs.some(a => a.some(x => !Number.isFinite(x)))) throw Error('invalid candidate features');
    const weight = Number(cfg.global_weight || 0), result = list.map(() => 0);
    for (const [key, w] of [['global_estimator', weight], ['type_estimator', 1 - weight]]) {
      if (w <= 0) continue;
      const scores = normalize(designs.map(row => scoreEstimator(entry[key], row)), cfg.score_normalization || 'zscore');
      scores.forEach((score, i) => { result[i] += score * w; });
    }
    return result;
  }
  function aggregate(list, scores, cfg) {
    const order = list.map((_, i) => i).sort((a, b) => scores[b] - scores[a] || a - b), top = order[0];
    const selected = cfg.top_k ? order.slice(0, cfg.top_k) : order, temperature = cfg.softmax_temperature || 1;
    if (!(temperature > 0)) throw Error('invalid softmax temperature');
    const maximum = Math.max(...selected.map(i => scores[i])), weights = selected.map(i => Math.exp((scores[i] - maximum) / temperature)), total = weights.reduce((a, b) => a + b, 0);
    const centroid = selected.reduce((s, i, k) => s + weights[k] / total * list[i].boundary, 0), blend = cfg.top_candidate_weight || 0;
    return { frame: evenRound(blend * list[top].boundary + (1 - blend) * centroid), confirmation: list[top].confirmation, margin: order.length > 1 ? scores[top] - scores[order[1]] : Infinity };
  }
  function interp(xs, ys, point) {
    if (point <= xs[0]) return ys[0]; if (point >= xs[xs.length - 1]) return ys[ys.length - 1];
    let lo = 0, hi = xs.length - 1;
    while (lo + 1 < hi) { const mid = (lo + hi) >> 1; if (xs[mid] <= point) lo = mid; else hi = mid; }
    return ys[lo] + (point - xs[lo]) * (ys[hi] - ys[lo]) / (xs[hi] - xs[lo]);
  }
  function resample(rows, step, phase) {
    const samples = rows.map((row, i) => ({ row, i, v: finite(row.injected_volume_ml) })).filter(x => x.v !== null && x.v >= 0).sort((a, b) => a.v - b.v || a.i - b.i);
    if (samples.length < 2) throw Error('too few volume observations');
    const start = samples[0].v, end = samples[samples.length - 1].v;
    if (end - start < step) throw Error('recorded volume range too short');
    const gridStart = start + phase * step, grid = [];
    for (let i = 0; i < Math.ceil((end + step * 0.5 - gridStart) / step); i++) { const x = gridStart + i * step; if (x <= end + 1e-9) grid.push(x); }
    if (grid.length < 2) throw Error('volume resampling produced too few rows');
    const out = grid.map(v => ({ injected_volume_ml: v }));
    for (const key of COLS) {
      const observed = samples.filter(x => finite(x.row[key]) !== null), grouped = new Map();
      if (observed.length < 2) { out.forEach(row => { row[key] = null; }); continue; }
      for (const x of observed) { if (!grouped.has(x.v)) grouped.set(x.v, []); grouped.get(x.v).push(Number(x.row[key])); }
      const xs = Array.from(grouped.keys()); let ys;
      if (key === COLS[0]) {
        ys = xs.map(x => { const radians = grouped.get(x).map(v => v * Math.PI / 180); return Math.atan2(mean(radians.map(Math.sin)), mean(radians.map(Math.cos))); });
        let correction = 0, prior = ys[0];
        ys = ys.map((angle, i) => { if (i) { const delta = angle - prior; let adjusted = ((delta + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI; if (adjusted === -Math.PI && delta > 0) adjusted = Math.PI; if (Math.abs(delta) >= Math.PI) correction += adjusted - delta; } prior = angle; return angle + correction; });
      } else ys = xs.map(x => median(grouped.get(x)));
      out.forEach((row, i) => { let value = interp(xs, ys, grid[i]); if (key === COLS[0]) value = ((value * 180 / Math.PI) % 360 + 360) % 360; row[key] = value; });
    }
    const indices = grid.map(v => { let pos = 0; while (pos < samples.length && samples[pos].v < v) pos++; pos = Math.min(pos, samples.length - 1); return pos > 0 && Math.abs(samples[pos - 1].v - v) < Math.abs(samples[pos].v - v) ? samples[pos - 1].i : samples[pos].i; });
    return { rows: out, indices };
  }
  function variants(rows, entry) {
    const visible = rows.filter(r => COLS.slice(0, 3).every(k => finite(r[k]) !== null)).length / rows.length;
    const thermal = rows.filter(r => { const a = finite(r[COLS[3]]), b = finite(r[COLS[4]]); return a !== null && b !== null && Math.abs(a) > 1e-12 && Math.abs(b) > 1e-12 && b >= a; }).length / rows.length;
    if (visible < 0.8 || thermal < 0.8) throw Error('insufficient_visible_or_thermal_sensor_coverage');
    const step = finite(entry.training_median_positive_volume_step_ml), volumes = rows.map(r => finite(r.injected_volume_ml)).filter(v => v !== null);
    if (step === null || step <= 0 || volumes.length < 2 || (Math.max(...volumes) - Math.min(...volumes)) / Math.max(1, volumes.length - 1) >= step * 0.7) return [{ rows, indices: rows.map((_, i) => i), mode: 'native_rows' }];
    return [0, 0.5].map(phase => ({ ...resample(rows, step, phase), mode: `volume_resampled_${step.toFixed(6)}ml_phase_${phase.toFixed(2)}` }));
  }
  function predictVariant(artifact, entry, rows) {
    const list = candidates(rows), cfg = entry.config;
    if (!list.length) throw Error('no_endpoint_candidates');
    const bounded = n => Math.max(0, Math.min(n, rows.length - 1));
    function evaluate(e) { const a = aggregate(list, combined(e, list, cfg), cfg), frame = bounded(a.frame), volume = finite(rows[frame].injected_volume_ml); if (!(volume > 0)) throw Error('selected_volume_invalid'); return { ...a, frame, volume }; }
    if (entry.fold_estimators?.length) {
      const folds = entry.fold_estimators.map(evaluate), middle = median(folds.map(f => f.volume));
      let chosen = folds[0]; for (const f of folds) if (Math.abs(f.volume - middle) < Math.abs(chosen.volume - middle)) chosen = f;
      const strategy = artifact.deployment_strategy || 'median_of_12_leave_one_run_out_rankers';
      const result = strategy === 'single_full_fit_with_12_fold_dispersion' ? evaluate(entry) : { ...chosen, volume: middle, confirmation: evenRound(median(folds.map(f => f.confirmation))) };
      return { ...result, foldSd: std(folds.map(f => f.volume), 1), foldCount: folds.length, strategy };
    }
    const result = evaluate(entry), m = Number.isFinite(result.margin) ? result.margin : 20;
    return { ...result, foldSd: 0, foldCount: 0, strategy: 'single_full_fit_ranker', marginConfidence: 1 / (1 + Math.exp(-Math.max(-20, Math.min(20, m)))) };
  }
  function predict(artifact, rows, type) {
    if (artifact?.artifact_type !== 'type_conditioned_sensor_endpoint_ranker_v1' || artifact?.portable_schema !== 'endpoint_portable_v1') throw Error('unsupported_endpoint_artifact');
    if (!Array.isArray(rows) || !rows.length) throw Error('recorded_rows_required');
    const entry = artifact.models?.[type]; if (!entry?.config) throw Error('no_model_for_titration_type');
    const results = variants(rows, entry).map(v => ({ ...v, result: predictVariant(artifact, entry, v.rows) }));
    const volume = mean(results.map(x => x.result.volume)); let chosen = results[0];
    for (const r of results) if (Math.abs(r.result.volume - volume) < Math.abs(chosen.result.volume - volume)) chosen = r;
    const dispersion = Math.max(results.length > 1 ? std(results.map(x => x.result.volume), 1) : 0, ...results.map(x => x.result.foldSd));
    const confidence = results.length === 1 && chosen.result.marginConfidence !== undefined ? chosen.result.marginConfidence : 1 / (1 + Math.max(0, dispersion));
    return { predicted_equivalence_status: 'available', predicted_equivalence_volume_ml: round6(volume), predicted_equivalence_confidence: round6(confidence), predicted_equivalence_source: 'type_conditioned_sensor_endpoint_ranker', predicted_equivalence_evidence: `${type} ${entry.config.family}; strategy=${chosen.result.strategy}; folds=${chosen.result.foldCount}; sampling=${results.map(x => x.mode).join('+')}`, candidate_index: chosen.indices[chosen.result.frame], model_key: artifact.model_key };
  }
  function readiness(rows) {
    if (!Array.isArray(rows) || rows.length < 8) return 'insufficient_usable_sensor_time_volume_observations';
    const usable = rows.filter(r => finite(r.time_s) !== null && Number(r.time_s) >= 0 && finite(r.injected_volume_ml) !== null && Number(r.injected_volume_ml) >= 0 && COLS.slice(0, 3).every(k => finite(r[k]) !== null));
    if (usable.length < 8) return 'insufficient_usable_sensor_time_volume_observations';
    const times = usable.map(r => Number(r.time_s)), volumes = usable.map(r => Number(r.injected_volume_ml));
    if (Math.max(...times) - Math.min(...times) < 3) return 'insufficient_recording_time_span';
    if (!(Math.max(...volumes) > Math.min(...volumes))) return 'insufficient_recorded_volume_progression';
    if (COLS.every(k => { const values = usable.map(r => finite(r[k])).filter(x => x !== null); return values.length < 2 || Math.max(...values) - Math.min(...values) <= 1e-12; })) return 'flat_recorded_sensor_signals';
    return null;
  }
  const api = { predict, candidates, scoreEstimator, resample, readiness, evenRound };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.AutoTitrationEndpoint = api;
})(typeof self !== 'undefined' ? self : globalThis);
