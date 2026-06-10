#!/usr/bin/env python3
"""Trace HIKMICRO Analyzer's real temperature-conversion SDK calls.

This is an evidence tool, not a fitting tool.  It attaches to or launches the
installed HIKMICRO Analyzer and records calls into MicroTA/MTlib_OL while the
official app opens/exports a Mini2 radiometric JPEG temperature matrix.

The useful output is under data/analyzer_sdk_trace/<timestamp>/:
  - events.jsonl: ordered call log
  - *.bin: raw payloads passed to MT_SetConfig / MicroTA setters

Run from Windows Python because Frida must instrument the Windows process.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path


ANALYZER_DIR = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
ANALYZER_EXE = ANALYZER_DIR / "HIKMICRO Analyzer.exe"


FRIDA_JS = r"""
'use strict';

const MAX_SETCONFIG_DUMP = 512 * 1024;
const MAX_STRUCT_DUMP = 4096;
const POINT_SIZE = 0x24;
const hooked = {};
let seq = 0;

function nowMs() { return Date.now(); }
function nextSeq() { seq += 1; return seq; }
function ptrStr(p) {
  try { return p.isNull() ? null : p.toString(); } catch (_) { return String(p); }
}
function i32(p) {
  try { return p.toInt32(); } catch (_) { return 0; }
}
function u32At(p, off) {
  try { return p.add(off).readU32(); } catch (_) { return null; }
}
function i32At(p, off) {
  try { return p.add(off).readS32(); } catch (_) { return null; }
}
function u16At(p, off) {
  try { return p.add(off).readU16(); } catch (_) { return null; }
}
function f32At(p, off) {
  try { return p.add(off).readFloat(); } catch (_) { return null; }
}
function f64At(p, off) {
  try { return p.add(off).readDouble(); } catch (_) { return null; }
}
function readBytes(p, len) {
  if (p.isNull() || len <= 0) return null;
  try { return p.readByteArray(len); } catch (_) { return null; }
}
function safeUtf16(p, maxChars) {
  if (p.isNull()) return null;
  try { return p.readUtf16String(maxChars || 512); } catch (_) { return null; }
}
function safeUtf8(p, maxLen) {
  if (p.isNull()) return null;
  try { return p.readUtf8String(maxLen || 512); } catch (_) { return null; }
}
function readMsvcString(p) {
  // MSVC x64 std::string layout used by Analyzer:
  //   [0x00..0x0f] small-string buffer OR pointer at 0x00
  //   [0x10] size_t size
  //   [0x18] size_t capacity
  // If capacity < 16, bytes live inside the object. Otherwise [0x00] is char*.
  if (p.isNull()) return null;
  try {
    const size = Number(p.add(0x10).readU64());
    const cap = Number(p.add(0x18).readU64());
    if (size < 0 || size > 4096 || cap < 0 || cap > 1048576) {
      return { error: "bad_msvc_string_bounds", size: size, cap: cap, ptr: ptrStr(p) };
    }
    let dataPtr = p;
    if (cap >= 16) dataPtr = p.readPointer();
    const s = size === 0 ? "" : dataPtr.readUtf8String(size);
    return { value: s, size: size, cap: cap, data_ptr: ptrStr(dataPtr) };
  } catch (e) {
    return { error: String(e), ptr: ptrStr(p) };
  }
}
function readMsvcVectorHeader(p) {
  if (p.isNull()) return null;
  try {
    const first = p.readPointer();
    const last = p.add(Process.pointerSize).readPointer();
    const end = p.add(Process.pointerSize * 2).readPointer();
    return {
      first: ptrStr(first),
      last: ptrStr(last),
      end: ptrStr(end),
      bytes: last.sub(first).toInt32(),
      capacity_bytes: end.sub(first).toInt32()
    };
  } catch (e) {
    return { error: String(e), ptr: ptrStr(p) };
  }
}
function emit(event) {
  event.seq = nextSeq();
  event.t_ms = nowMs();
  send(event);
}
function emitBlob(name, meta, ptr, len, maxLen) {
  const n = Math.max(0, Math.min(len || 0, maxLen || MAX_STRUCT_DUMP));
  const data = readBytes(ptr, n);
  const ev = Object.assign({ event: "blob", name: name, requested_len: len || 0, dumped_len: n }, meta || {});
  ev.seq = nextSeq();
  ev.t_ms = nowMs();
  if (data === null) send(Object.assign(ev, { read_error: true }));
  else send(ev, data);
}
function samplePoint(base, index) {
  const p = base.add(index * POINT_SIZE);
  return {
    index: index,
    code: i32At(p, 0x00),
    gray: i32At(p, 0x04),
    temp_i32_at_0x0c: i32At(p, 0x0c),
    temp_f32_at_0x10: f32At(p, 0x10),
    emissivity_f32_at_0x14: f32At(p, 0x14),
    reflected_f32_at_0x18: f32At(p, 0x18),
    distance_f32_at_0x1c: f32At(p, 0x1c),
    tail_u32_at_0x20: u32At(p, 0x20)
  };
}
function samplePoints(base, count) {
  const out = [];
  if (base.isNull() || count <= 0) return out;
  const idxs = [0, 1, 2, 3, Math.floor(count / 2), count - 1];
  const seen = {};
  idxs.forEach(function (idx) {
    if (idx >= 0 && idx < count && !seen[idx]) {
      seen[idx] = true;
      out.push(samplePoint(base, idx));
    }
  });
  return out;
}
function moduleBase(moduleName) {
  try {
    const m = Process.getModuleByName(moduleName);
    return m.base.toString();
  } catch (_) { return null; }
}
function hookExport(moduleName, exportName, callbacks) {
  const key = moduleName + "!" + exportName;
  if (hooked[key]) return;
  let addr = null;
  try {
    const mod = Process.getModuleByName(moduleName);
    if (typeof mod.findExportByName === "function") addr = mod.findExportByName(exportName);
    else if (typeof mod.getExportByName === "function") {
      try { addr = mod.getExportByName(exportName); } catch (_) { addr = null; }
    }
  } catch (_) {
    return;
  }
  if (addr === null) return;
  hooked[key] = true;
  try {
    Interceptor.attach(addr, callbacks);
    emit({ event: "hooked", module: moduleName, export: exportName, addr: addr.toString(), module_base: moduleBase(moduleName) });
  } catch (e) {
    emit({ event: "hook_error", module: moduleName, export: exportName, error: String(e) });
  }
}

function hookMT() {
  ["MT_SetConfig", "MT_SetConfig_OL", "MT_SetConfig_INT"].forEach(function (name) {
    hookExport("MTlib_OL.dll", name, {
      onEnter(args) {
        this.name = name;
        this.handle = args[0];
        this.type = i32(args[1]);
        this.buf = args[2];
        this.len = i32(args[3]);
        const meta = {
          event: "MT_SetConfig_enter",
          api: name,
          handle: ptrStr(this.handle),
          config_type: this.type,
          buf: ptrStr(this.buf),
          len: this.len,
          first_u32: u32At(this.buf, 0),
          second_u32: u32At(this.buf, 4),
          first_i32: i32At(this.buf, 0),
          second_i32: i32At(this.buf, 4)
        };
        if (this.type === 1 && this.len >= 8) {
          meta.key = u32At(this.buf, 0);
          meta.value_u32 = u32At(this.buf, 4);
          meta.value_i32 = i32At(this.buf, 4);
        }
        if (this.type === 6 && this.len >= 16) {
          meta.tag519_magic_u32 = u32At(this.buf, 0);
          meta.tag519_calib_type_u32_at_8 = u32At(this.buf, 8);
        }
        if (this.type === 7 && this.len >= 16) {
          meta.raw_first_u16 = [u16At(this.buf, 0), u16At(this.buf, 2), u16At(this.buf, 4), u16At(this.buf, 6)];
        }
        emit(meta);
        emitBlob(name + "_type" + this.type + "_payload", {
          api: name,
          handle: ptrStr(this.handle),
          config_type: this.type
        }, this.buf, this.len, MAX_SETCONFIG_DUMP);
      },
      onLeave(retval) {
        emit({ event: "MT_SetConfig_leave", api: this.name, handle: ptrStr(this.handle), config_type: this.type, len: this.len, retval: i32(retval) });
      }
    });
  });

  ["MT_Process", "MT_Process_OL", "MT_Process_INT"].forEach(function (name) {
    hookExport("MTlib_OL.dll", name, {
      onEnter(args) {
        this.name = name;
        this.handle = args[0];
        this.process_type = i32(args[1]);
        this.points = args[2];
        this.count = i32(args[3]);
        emit({
          event: "MT_Process_enter",
          api: name,
          handle: ptrStr(this.handle),
          process_type: this.process_type,
          points: ptrStr(this.points),
          count: this.count,
          samples_before: samplePoints(this.points, this.count)
        });
      },
      onLeave(retval) {
        emit({
          event: "MT_Process_leave",
          api: this.name,
          handle: ptrStr(this.handle),
          process_type: this.process_type,
          count: this.count,
          retval: i32(retval),
          samples_after: samplePoints(this.points, this.count)
        });
      }
    });
  });

  ["MT_Create", "MT_Create_OL", "MT_Create_INT"].forEach(function (name) {
    hookExport("MTlib_OL.dll", name, {
      onEnter(args) {
        this.name = name;
        this.params = args[0];
        this.desc = args[1];
        this.outHandle = args[2];
        emit({
          event: "MT_Create_enter",
          api: name,
          params: ptrStr(this.params),
          desc: ptrStr(this.desc),
          out_handle_ptr: ptrStr(this.outHandle),
          params_u32_first8: [u32At(this.params, 0), u32At(this.params, 4), u32At(this.params, 8), u32At(this.params, 12), u32At(this.params, 16), u32At(this.params, 20), u32At(this.params, 24), u32At(this.params, 28)]
        });
        emitBlob(name + "_params", { api: name, kind: "params" }, this.params, 0x80, 0x80);
        emitBlob(name + "_desc", { api: name, kind: "desc" }, this.desc, 0x100, 0x100);
      },
      onLeave(retval) {
        emit({
          event: "MT_Create_leave",
          api: this.name,
          retval: i32(retval),
          out_handle_value: ptrStr(this.outHandle.readPointer())
        });
      }
    });
  });

  ["MT_GetConfig", "MT_GetConfig_OL", "MT_GetConfig_INT", "MT_SubFunction", "MT_SubFunction_OL"].forEach(function (name) {
    hookExport("MTlib_OL.dll", name, {
      onEnter(args) {
        this.name = name;
        this.a0 = args[0]; this.a1 = args[1]; this.a2 = args[2]; this.a3 = args[3];
        emit({ event: name + "_enter", api: name, a0: ptrStr(args[0]), a1: i32(args[1]), a2: ptrStr(args[2]), a3: i32(args[3]) });
      },
      onLeave(retval) {
        emit({ event: this.name + "_leave", api: this.name, retval: i32(retval), a0: ptrStr(this.a0), a1: i32(this.a1) });
      }
    });
  });
}

function hookMicroTA() {
  const ta = "MicroTA_Release_x64.dll";
  const ctor = "??0TempAnalyzer@MicroSDK@@QEAA@AEBUTempInitParameters@1@AEBURawDataInfo@1@@Z";
  hookExport(ta, ctor, {
    onEnter(args) {
      this.self = args[0];
      emit({ event: "TempAnalyzer_ctor_enter", this_ptr: ptrStr(args[0]), init_ptr: ptrStr(args[1]), raw_ptr: ptrStr(args[2]) });
      emitBlob("TempAnalyzer_ctor_init", { kind: "TempInitParameters", this_ptr: ptrStr(args[0]) }, args[1], 0x200, 0x200);
      emitBlob("TempAnalyzer_ctor_raw", { kind: "RawDataInfo", this_ptr: ptrStr(args[0]) }, args[2], 0x200, 0x200);
    },
    onLeave(retval) { emit({ event: "TempAnalyzer_ctor_leave", this_ptr: ptrStr(this.self), retval: ptrStr(retval) }); }
  });
  [
    ["?setModelConfig@TempAnalyzer@MicroSDK@@QEAA_NAEBUMeasureModelParameters@2@@Z", "setModelConfig", 0x400],
    ["?setExpertConfig@TempAnalyzer@MicroSDK@@QEAA_NAEBUMeasureExpertParams@2@@Z", "setExpertConfig", 0x400],
    ["?setTempRange@TempAnalyzer@MicroSDK@@QEAA_NAEBUTempRange@2@@Z", "setTempRange", 0x100],
    ["?changeSrc@TempAnalyzer@MicroSDK@@QEAA_NAEBURawDataInfo@2@@Z", "changeSrc", 0x200]
  ].forEach(function (t) {
    hookExport(ta, t[0], {
      onEnter(args) {
        this.label = t[1]; this.self = args[0]; this.ptr = args[1];
        emit({ event: "TempAnalyzer_" + this.label + "_enter", this_ptr: ptrStr(args[0]), struct_ptr: ptrStr(args[1]) });
        emitBlob("TempAnalyzer_" + this.label + "_struct", { kind: this.label, this_ptr: ptrStr(args[0]) }, args[1], t[2], t[2]);
      },
      onLeave(retval) { emit({ event: "TempAnalyzer_" + this.label + "_leave", this_ptr: ptrStr(this.self), retval_bool_or_i32: i32(retval) }); }
    });
  });
  hookExport(ta, "?calculate@TempAnalyzer@MicroSDK@@QEAA_NAEAHG@Z", {
    onEnter(args) {
      this.self = args[0]; this.out = args[1]; this.gray = i32(args[2]);
      emit({ event: "TempAnalyzer_calculate_gray_enter", this_ptr: ptrStr(args[0]), out_ptr: ptrStr(args[1]), gray: this.gray });
    },
    onLeave(retval) {
      emit({ event: "TempAnalyzer_calculate_gray_leave", this_ptr: ptrStr(this.self), gray: this.gray, retval: i32(retval), out_i32: i32At(this.out, 0) });
    }
  });
  hookExport(ta, "?temperatureTable@TempAnalyzer@MicroSDK@@QEAA_NAEAUSharedBlock@2@@Z", {
    onEnter(args) { this.self = args[0]; this.block = args[1]; emit({ event: "TempAnalyzer_temperatureTable_enter", this_ptr: ptrStr(args[0]), shared_block_ptr: ptrStr(args[1]) }); },
    onLeave(retval) { emit({ event: "TempAnalyzer_temperatureTable_leave", this_ptr: ptrStr(this.self), retval: i32(retval), shared_block_ptr: ptrStr(this.block) }); emitBlob("TempAnalyzer_temperatureTable_sharedblock_after", { this_ptr: ptrStr(this.self) }, this.block, 0x80, 0x80); }
  });
}

function hookMicroJITA() {
  const j = "MicroJITA_Release_x64.dll";
  [
    ["?createFromJPEG@MicroSDK@@YA_NAEAPEAXAEBUBareBlock@1@@Z", "createFromJPEG", 0x80],
    ["?setRawDataInfo@MicroSDK@@YA_NAEBURawDataInfo@1@PEAX@Z", "setRawDataInfo", 0x200],
    ["?setTempDeviceConfigParams@MicroSDK@@YA_NAEBUTempDeviceConfigParams@1@PEAX@Z", "setTempDeviceConfigParams", 0x400],
    ["?setTempMeasurementParams@MicroSDK@@YA_NAEBUTempMeasurementParameters@1@PEAX@Z", "setTempMeasurementParams", 0x800],
    ["?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z", "getRawDataInfo", 0x200],
    ["?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z", "getTempDeviceConfigParams", 0x400],
    ["?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z", "getTempMeasurementParams", 0x800]
  ].forEach(function (t) {
    hookExport(j, t[0], {
      onEnter(args) {
        this.label = t[1]; this.a0 = args[0]; this.a1 = args[1];
        emit({ event: "MicroJITA_" + this.label + "_enter", a0: ptrStr(args[0]), a1: ptrStr(args[1]) });
        if (this.label.indexOf("set") === 0) emitBlob("MicroJITA_" + this.label + "_struct", { kind: this.label, ctx: ptrStr(args[1]) }, args[0], t[2], t[2]);
      },
      onLeave(retval) {
        emit({ event: "MicroJITA_" + this.label + "_leave", retval: i32(retval), a0: ptrStr(this.a0), a1: ptrStr(this.a1) });
        if (this.label.indexOf("get") === 0) emitBlob("MicroJITA_" + this.label + "_out", { kind: this.label, ctx: ptrStr(this.a1) }, this.a0, t[2], t[2]);
      }
    });
  });
  hookExport(j, "?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z", {
    onEnter(args) { this.out = args[0]; this.gray = i32(args[1]); this.ctx = args[2]; emit({ event: "MicroJITA_grayToTemperature_enter", out: ptrStr(args[0]), gray: this.gray, ctx: ptrStr(args[2]) }); },
    onLeave(retval) { emit({ event: "MicroJITA_grayToTemperature_leave", retval: i32(retval), gray: this.gray, out_i32: i32At(this.out, 0), ctx: ptrStr(this.ctx) }); }
  });
}

function hookMicroAnalytics() {
  const a = "MicroAnalytics_Release_x64.dll";
  [
    ["?createMaterial@FileParseFactory@MicroAnalytics@@QEAAPEAVTakedMaterial@MICROPIXELER@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@6@_N@Z", "FileParseFactory_createMaterial_member"],
    ["?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@6@@Z", "FileParseFactory_createMaterialQ_path"],
    ["?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z", "FileParseFactory_createMaterialQ_type_path"],
    ["?doImgAnalyze@BaseAnalyzeWidgetMag@MicroAnalytics@@UEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z", "BaseAnalyzeWidgetMag_doImgAnalyze"],
    ["?startExportMatrixTask@TempMartixInfoCache@MicroAnalytics@@AEAA_NAEBVQString@@@Z", "TempMartixInfoCache_startExportMatrixTask"],
    ["?startExportTask@TempMartixInfoCache@MicroAnalytics@@QEAA_NAEBVQString@@@Z", "TempMartixInfoCache_startExportTask"],
    ["?writeCsvFile@TempMartixInfoCache@MicroAnalytics@@AEAAXAEAVQFile@@AEBVQString@@_N@Z", "TempMartixInfoCache_writeCsvFile"],
    ["?write@TempMartixInfoCache@MicroAnalytics@@QEAA_NAEBUTempMartixInfo@2@@Z", "TempMartixInfoCache_write"],
    ["?read@TempMartixInfoCache@MicroAnalytics@@QEAA_NAEAUTempMartixInfo@2@@Z", "TempMartixInfoCache_read"],
    ["?genericSingleRuleMartixData@TempMartixInfoCache@MicroAnalytics@@AEAA?AVQString@@V?$shared_ptr@UMeasurementStats@MicroSDK@@@std@@@Z", "TempMartixInfoCache_genericSingleRuleMartixData"],
    ["?grayToTemp@TempMeasuredResultModel@MicroAnalytics@@QEAA_NAEAHG@Z", "TempMeasuredResultModel_grayToTemp"],
    ["?getTempByPos@TempMeasuredResultModel@MicroAnalytics@@QEBA_NAEANAEAW4TempratureReliability@iVMS4800@@AEBUCoordinate@4@@Z", "TempMeasuredResultModel_getTempByPos"],
    ["?getGrayToTempTable@TempMeasuredResultModel@MicroAnalytics@@QEBA_NV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@@Z", "TempMeasuredResultModel_getGrayToTempTable"]
  ].forEach(function (t) {
    hookExport(a, t[0], {
      onEnter(args) {
        this.label = t[1]; this.self = args[0]; this.a1 = args[1]; this.a2 = args[2]; this.a3 = args[3];
        const ev = { event: "MicroAnalytics_" + this.label + "_enter", this_ptr: ptrStr(args[0]), a1: ptrStr(args[1]), a2: ptrStr(args[2]), a3: ptrStr(args[3]), a1_i32: i32(args[1]), a2_i32: i32(args[2]), a3_i32: i32(args[3]) };
        if (this.label.indexOf("getTempByPos") >= 0 && !args[3].isNull()) ev.coord_xy = [i32At(args[3], 0), i32At(args[3], 4)];
        if (this.label.indexOf("grayToTemp") >= 0) ev.gray = i32(args[2]);
        if (this.label === "FileParseFactory_createMaterial_member") {
          ev.path_string = readMsvcString(args[1]);
          ev.fusion_vector = readMsvcVectorHeader(args[2]);
          ev.bool_arg = i32(args[3]) & 0xff;
        }
        if (this.label === "FileParseFactory_createMaterialQ_path") {
          ev.path_string = readMsvcString(args[0]);
          ev.fusion_vector = readMsvcVectorHeader(args[1]);
        }
        if (this.label === "FileParseFactory_createMaterialQ_type_path") {
          ev.material_type = i32(args[0]);
          ev.path_string = readMsvcString(args[1]);
          ev.fusion_vector = readMsvcVectorHeader(args[2]);
          ev.bool_arg = i32(args[3]) & 0xff;
        }
        emit(ev);
        if (this.label.indexOf("FileParseFactory") >= 0) {
          emitBlob("MicroAnalytics_" + this.label + "_arg0", { label: this.label, kind: "arg0" }, args[0], 0x80, 0x80);
          emitBlob("MicroAnalytics_" + this.label + "_arg1", { label: this.label, kind: "arg1" }, args[1], 0x80, 0x80);
          emitBlob("MicroAnalytics_" + this.label + "_arg2", { label: this.label, kind: "arg2" }, args[2], 0x80, 0x80);
        }
      },
      onLeave(retval) {
        const ev = { event: "MicroAnalytics_" + this.label + "_leave", this_ptr: ptrStr(this.self), retval: i32(retval) };
        if (this.label.indexOf("getTempByPos") >= 0) {
          ev.temp_double = f64At(this.a1, 0);
          ev.reliability_i32 = i32At(this.a2, 0);
        }
        if (this.label.indexOf("grayToTemp") >= 0) ev.out_i32 = i32At(this.a1, 0);
        emit(ev);
      }
    });
  });
}

function hookMicroPixeler() {
  const p = "MicroPixeler_Release_x64.dll";
  [
    ["?analyseFile@MaterialParseFactory@MICROPIXELER@@SA?AUSharedBlock@MicroSDK@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z", "MaterialParseFactory_analyseFile"],
    ["?typeOfMaterial@MaterialParse@MICROPIXELER@@SA?AW4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z", "MaterialParse_typeOfMaterial"],
    ["?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z", "parseRadiometricsJPEG"],
    ["?parseElecThermalJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z", "parseElecThermalJPEG"],
    ["?parseNormalJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z", "parseNormalJPEG"],
    ["?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z", "TakedMaterialAnalyzControl_tempAnalyze_ptr"],
    ["?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z", "TakedMaterialAnalyzControl_tempAnalyze_shared"],
    ["?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z", "TakedMaterialAnalyzControl_imgAnalyzeSyn_shared"],
    ["?imgAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@_N@Z", "TakedMaterialAnalyzControl_imgAnalyze_shared"],
    ["?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z", "TakedMaterialAnalyzControl_grayToTemp"],
    ["?tempToGray@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAGV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z", "TakedMaterialAnalyzControl_tempToGray"],
    ["?getGrayToTempTable@ThermalPicInterface@MICROPIXELER@@UEBA?AV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@XZ", "ThermalPicInterface_getGrayToTempTable"],
    ["?setGrayToTempTable@ThermalPicInterface@MICROPIXELER@@UEAAXV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@@Z", "ThermalPicInterface_setGrayToTempTable"],
    ["?setMeasureEnvParams@ThermalPicInterface@MICROPIXELER@@UEAA_NAEBUMeasurementEnvParams@MicroSDK@@@Z", "ThermalPicInterface_setMeasureEnvParams"],
    ["?setRawDataInfo@ThermalPicInterface@MICROPIXELER@@UEAA_NAEBURawDataInfo@MicroSDK@@@Z", "ThermalPicInterface_setRawDataInfo"],
    ["?setThermalPic@ThermalPicInterface@MICROPIXELER@@QEAAXAEBUImage@MicroSDK@@@Z", "ThermalPicInterface_setThermalPic"],
    ["?setThermalJPEG@ThermalPicInterface@MICROPIXELER@@QEAAXAEBUImage@MicroSDK@@@Z", "ThermalPicInterface_setThermalJPEG"],
    ["?setGlobeTempParam@ThermalPicInterface@MICROPIXELER@@QEAAXAEBUGlobeTempParam@iVMS4800@@@Z", "ThermalPicInterface_setGlobeTempParam"],
    ["?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ", "TakedMaterial_thermalPicInterface"],
    ["?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ", "TakedMaterial_getThermalPicInterface"]
  ].forEach(function (t) {
    hookExport(p, t[0], {
      onEnter(args) {
        this.label = t[1];
        this.a0 = args[0]; this.a1 = args[1]; this.a2 = args[2]; this.a3 = args[3]; this.a4 = args[4];
        const ev = { event: "MicroPixeler_" + this.label + "_enter", a0: ptrStr(args[0]), a1: ptrStr(args[1]), a2: ptrStr(args[2]), a3: ptrStr(args[3]), a4: ptrStr(args[4]), a0_i32: i32(args[0]), a1_i32: i32(args[1]), a2_i32: i32(args[2]), a3_i32: i32(args[3]) };
        if (this.label === "MaterialParseFactory_analyseFile" || this.label === "MaterialParse_typeOfMaterial" || this.label === "parseElecThermalJPEG" || this.label === "parseNormalJPEG") {
          ev.path_string = readMsvcString(args[0]);
        }
        if (this.label === "parseRadiometricsJPEG") {
          ev.type_out_before = u32At(args[0], 0);
          ev.bool_out_before = u16At(args[1], 0);
          ev.path_string = readMsvcString(args[2]);
          ev.fusion_vector = readMsvcVectorHeader(args[3]);
          ev.bool_arg_stack_unknown = i32(args[4]) & 0xff;
        }
        if (this.label === "TakedMaterialAnalyzControl_grayToTemp") {
          ev.out_before = i32At(args[1], 0);
          ev.shared_ptr = ptrStr(args[2]);
          ev.gray = i32(args[3]);
        }
        if (this.label === "TakedMaterialAnalyzControl_tempToGray") {
          ev.out_before_u16 = u16At(args[1], 0);
          ev.shared_ptr = ptrStr(args[2]);
          ev.temp_arg_i32 = i32(args[3]);
        }
        emit(ev);
        if (this.label.indexOf("setMeasureEnvParams") >= 0) emitBlob("MicroPixeler_setMeasureEnvParams_struct", { label: this.label, kind: "MeasurementEnvParams" }, args[1], 0x400, 0x400);
        if (this.label.indexOf("setRawDataInfo") >= 0) emitBlob("MicroPixeler_setRawDataInfo_struct", { label: this.label, kind: "RawDataInfo" }, args[1], 0x300, 0x300);
        if (this.label.indexOf("setGlobeTempParam") >= 0) emitBlob("MicroPixeler_setGlobeTempParam_struct", { label: this.label, kind: "GlobeTempParam" }, args[1], 0x300, 0x300);
        if (this.label.indexOf("setThermalPic") >= 0 || this.label.indexOf("setThermalJPEG") >= 0) emitBlob("MicroPixeler_" + this.label + "_image_struct", { label: this.label, kind: "Image" }, args[1], 0x200, 0x200);
        if (this.label.indexOf("GrayToTempTable") >= 0) {
          emitBlob("MicroPixeler_" + this.label + "_self", { label: this.label, kind: "self" }, args[0], 0x200, 0x200);
          emitBlob("MicroPixeler_" + this.label + "_shared_ptr", { label: this.label, kind: "shared_ptr" }, args[1], 0x80, 0x80);
        }
      },
      onLeave(retval) {
        const ev = { event: "MicroPixeler_" + this.label + "_leave", retval_ptr: ptrStr(retval), retval_i32: i32(retval) };
        if (this.label === "parseRadiometricsJPEG") {
          ev.type_out_after = u32At(this.a0, 0);
          ev.bool_out_after = u16At(this.a1, 0);
        }
        if (this.label === "TakedMaterialAnalyzControl_grayToTemp") ev.out_after = i32At(this.a1, 0);
        if (this.label === "TakedMaterialAnalyzControl_tempToGray") ev.out_after_u16 = u16At(this.a1, 0);
        emit(ev);
      }
    });
  });
}

function hookAll() {
  hookMT();
  hookMicroTA();
  hookMicroJITA();
  hookMicroAnalytics();
  hookMicroPixeler();
}

emit({ event: "script_loaded", pid: Process.id, arch: Process.arch, platform: Process.platform });
hookAll();
// Keep polling frequently: short helper processes may load the DLLs and call
// them almost immediately after resume. Analyzer GUI is slower, but this also
// makes self-tests catch MTlib calls reliably.
setInterval(hookAll, 50);
"""


def sanitize(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.@+-]+", "_", name)
    return name[:140] or "blob"


def default_out_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data") / "analyzer_sdk_trace" / stamp


def on_message_factory(events_path: Path, blob_dir: Path):
    events = events_path.open("a", encoding="utf-8")
    blob_seq = {"n": 0}

    def on_message(message, data):
        payload = message.get("payload")
        if message.get("type") == "error":
            payload = {
                "event": "frida_error",
                "description": message.get("description"),
                "stack": message.get("stack"),
            }
        elif not isinstance(payload, dict):
            payload = {"event": "frida_message", "message": message}

        if data:
            blob_seq["n"] += 1
            seq = payload.get("seq", blob_seq["n"])
            name = sanitize(str(payload.get("name") or payload.get("event") or "blob"))
            blob_path = blob_dir / f"{int(seq):06d}_{name}.bin"
            blob_path.write_bytes(bytes(data))
            payload["blob_path"] = str(blob_path)
            payload["blob_size"] = len(data)

        events.write(json.dumps(payload, ensure_ascii=False) + "\n")
        events.flush()

        ev = payload.get("event")
        if ev in {"hooked", "MT_SetConfig_enter", "MT_Create_enter", "TempAnalyzer_ctor_enter", "MicroAnalytics_TempMeasuredResultModel_getTempByPos_leave"}:
            print(json.dumps(payload, ensure_ascii=False)[:1200], flush=True)

    return on_message


def find_analyzer_process(frida, device, process_name: str | None = None):
    if process_name:
        wanted = process_name.lower()
        candidates = [
            proc
            for proc in device.enumerate_processes()
            if proc.name.lower() == wanted or wanted in proc.name.lower()
        ]
        if not candidates:
            raise SystemExit(f"No running process matching {process_name!r} found.")
        candidates.sort(key=lambda p: (p.name.lower() != wanted, p.name.lower()))
        return candidates[0]

    names = {"HIKMICRO Analyzer.exe", "HIKMICRO Analyzer", "Pixler.exe", "Pixler"}
    candidates = []
    for proc in device.enumerate_processes():
        if proc.name in names or "HIKMICRO" in proc.name.upper() or "Analyzer" in proc.name or proc.name == "Pixler.exe":
            candidates.append(proc)
    if not candidates:
        raise SystemExit("No running HIKMICRO Analyzer/Pixler process found. Use --spawn or open Analyzer first.")
    # Prefer exact process name.
    candidates.sort(key=lambda p: (p.name not in names, p.name.lower()))
    return candidates[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--spawn", action="store_true", help="launch HIKMICRO Analyzer and trace it")
    mode.add_argument("--attach", action="store_true", help="attach to an already-running Analyzer")
    ap.add_argument("--exe", type=Path, default=ANALYZER_EXE)
    ap.add_argument("--process-name", default=None, help="when attaching, match a specific process name, e.g. Pixler.exe")
    ap.add_argument("--cwd", type=Path, default=ANALYZER_DIR)
    ap.add_argument("--image", type=Path, default=Path("data/fixtures/mini2/IR_00001.jpeg"), help="optional image path to pass when spawning")
    ap.add_argument("--arg", action="append", default=[], help="extra raw argument to append when spawning (repeatable)")
    ap.add_argument("--out", type=Path, default=default_out_dir())
    ap.add_argument("--duration", type=float, default=0.0, help="seconds to trace; 0 means until Ctrl+C/app exit")
    ap.add_argument("--no-image-arg", action="store_true", help="spawn Analyzer without passing the image path")
    args = ap.parse_args(argv)

    try:
        import frida  # type: ignore
    except ImportError:
        raise SystemExit("Missing frida. Install with: py -3 -m pip install --user frida frida-tools")

    out_dir = args.out.resolve()
    blob_dir = out_dir / "payloads"
    blob_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"

    device = frida.get_local_device()
    pid = None
    session = None
    spawned = False
    if args.attach:
        proc = find_analyzer_process(frida, device, args.process_name)
        pid = proc.pid
        print(f"Attaching to {proc.name} pid={pid}")
        session = device.attach(pid)
    else:
        exe = args.exe
        if not exe.exists():
            raise SystemExit(f"Analyzer exe not found: {exe}")
        argv_spawn = [str(exe)]
        if args.arg:
            argv_spawn.extend(args.arg)
        elif not args.no_image_arg:
            image = args.image.resolve()
            if image.exists():
                argv_spawn.append(str(image))
        print("Spawning:", argv_spawn)
        pid = device.spawn(argv_spawn, cwd=str(args.cwd))
        spawned = True
        session = device.attach(pid)

    script = session.create_script(FRIDA_JS)
    script.on("message", on_message_factory(events_path, blob_dir))
    script.load()
    if spawned:
        device.resume(pid)

    print()
    print("TRACE ACTIVE")
    print(f"events: {events_path}")
    print(f"payloads: {blob_dir}")
    print("Now in Analyzer: open data/fixtures/mini2/IR_00001.jpeg if it did not open automatically, then export the temperature matrix CSV.")
    print("Leave this window running until export finishes; press Ctrl+C to stop.")
    print()

    stop = {"flag": False}

    def _stop(_sig=None, _frame=None):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    started = time.time()
    try:
        while not stop["flag"]:
            if args.duration > 0 and time.time() - started >= args.duration:
                break
            time.sleep(0.25)
    finally:
        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass
    print(f"Trace saved: {events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
