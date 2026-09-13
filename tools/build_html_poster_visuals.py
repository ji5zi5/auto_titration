#!/usr/bin/env python3
"""Build self-contained poster infographics using the shared HTML card system."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "poster_html_visuals_2026-08-28"


BASE_CSS = r"""
@page{size:1600px 760px;margin:0}
@font-face{font-family:Pretendard;src:url("../../website/assets/fonts/PretendardVariable.woff2") format("woff2");font-weight:45 920}
*{box-sizing:border-box}
html,body{margin:0;width:1600px;height:760px;overflow:hidden;font-family:Pretendard,"Malgun Gothic",sans-serif;color:#0f172a}
body{display:flex;align-items:center;justify-content:center;background:
radial-gradient(circle at 7% 5%,rgba(37,99,235,.10),transparent 28%),
radial-gradient(circle at 93% 95%,rgba(16,185,129,.10),transparent 28%),#f8fafc}
.canvas{width:1490px;height:680px;position:relative}
.panel{position:relative;background:rgba(255,255,255,.97);border:1px solid #dbe3ea;border-radius:30px;box-shadow:0 16px 44px rgba(15,23,42,.08),0 2px 8px rgba(15,23,42,.035)}
.panel:before{content:"";position:absolute;left:26px;right:26px;top:0;height:7px;border-radius:0 0 10px 10px;background:var(--accent,#2563eb)}
.card{position:relative;background:#fff;border:1px solid #dbe3ea;border-radius:24px;padding:22px;box-shadow:0 10px 28px rgba(15,23,42,.055)}
.soft-blue{--accent:#2563eb;--soft:#eff6ff;--border:#bfdbfe;--deep:#1d4ed8}
.soft-orange{--accent:#f59e0b;--soft:#fff7ed;--border:#fed7aa;--deep:#c2410c}
.soft-teal{--accent:#0f766e;--soft:#f0fdfa;--border:#99f6e4;--deep:#115e59}
.soft-green{--accent:#10b981;--soft:#ecfdf5;--border:#a7f3d0;--deep:#047857}
.soft-violet{--accent:#7c3aed;--soft:#f5f3ff;--border:#ddd6fe;--deep:#6d28d9}
.soft-slate{--accent:#475569;--soft:#f8fafc;--border:#cbd5e1;--deep:#334155}
.topline:before{content:"";position:absolute;left:20px;right:20px;top:0;height:6px;border-radius:0 0 8px 8px;background:var(--accent)}
.fill{background:var(--soft);border-color:var(--border)}
.kicker{font-size:13px;line-height:1;font-weight:850;letter-spacing:.12em;color:var(--accent)}
.title{font-size:28px;line-height:1.16;font-weight:900;letter-spacing:-.045em}
.subtitle{font-size:16px;line-height:1.45;font-weight:650;color:#64748b}
.icon{width:54px;height:54px;display:grid;place-items:center;border-radius:18px;background:var(--soft);color:var(--accent);border:1px solid var(--border)}
.icon svg{width:31px;height:31px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.icon.small{width:44px;height:44px;border-radius:14px}.icon.small svg{width:25px;height:25px}
.pill{display:inline-flex;align-items:center;justify-content:center;padding:9px 13px;border-radius:12px;background:var(--soft);border:1px solid var(--border);color:var(--deep);font-size:14px;font-weight:800}
.dark-pill{display:inline-flex;padding:11px 17px;border-radius:14px;background:#0f172a;color:#fff;font-size:15px;font-weight:850}
.arrow{display:grid;place-items:center;width:31px;height:31px;border-radius:50%;background:#fff;border:1px solid #dbe3ea;color:#64748b;box-shadow:0 5px 15px rgba(15,23,42,.09)}
.arrow svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:2.2}
.metric-value{font-size:48px;line-height:1;font-weight:920;letter-spacing:-.055em}
.metric-label{font-size:14px;font-weight:750;color:#64748b}
.note{font-size:13px;line-height:1.42;font-weight:650;color:#64748b}
.center{text-align:center}.strong{font-weight:900;color:#0f172a}.muted{color:#64748b}
"""


ICONS = {
    "calculator": '<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h2M14 11h2M8 15h2M14 15h2M8 18h2M14 18h2"/></svg>',
    "eye": '<svg viewBox="0 0 24 24"><path d="M2.5 12s3.5-5 9.5-5 9.5 5 9.5 5-3.5 5-9.5 5-9.5-5-9.5-5z"/><circle cx="12" cy="12" r="2.7"/></svg>',
    "model": '<svg viewBox="0 0 24 24"><path d="M4 17l5-5 4 3 7-8"/><path d="M15 7h5v5M4 21h16"/></svg>',
    "clock": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>',
    "camera": '<svg viewBox="0 0 24 24"><path d="M4 7h4l2-2h4l2 2h4v12H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    "thermal": '<svg viewBox="0 0 24 24"><path d="M10 5a2 2 0 1 1 4 0v8.2a4 4 0 1 1-4 0z"/><path d="M12 8v7"/></svg>',
    "queue": '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="4" rx="1"/><rect x="4" y="11" width="16" height="4" rx="1"/><rect x="4" y="17" width="16" height="2" rx="1"/></svg>',
    "csv": '<svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4M9 11h6M9 15h6"/></svg>',
    "chip": '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M18 9h4M2 15h4M18 15h4"/></svg>',
    "branch": '<svg viewBox="0 0 24 24"><path d="M6 4v8a4 4 0 0 0 4 4h8"/><path d="M14 12l4 4-4 4M6 8h6a4 4 0 0 0 4-4"/></svg>',
    "target": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
    "pump": '<svg viewBox="0 0 24 24"><path d="M3 13h12M6 9h7v8H6zM13 11h4v4h-4M17 13h4M8 6v3M11 6v3"/></svg>',
    "motor": '<svg viewBox="0 0 24 24"><circle cx="8" cy="12" r="4"/><path d="M12 12h7M16 8l3 4-3 4M6 8V5M6 19v-3"/></svg>',
    "flask": '<svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M8 15h8"/></svg>',
    "computer": '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
    "color": '<svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 1 0 0 18h1.5a2 2 0 0 0 0-4H12a2 2 0 0 1 0-4h3a6 6 0 0 0-3-10z"/><circle cx="7.5" cy="10" r="1"/><circle cx="10" cy="6.8" r="1"/><circle cx="15" cy="7.5" r="1"/></svg>',
    "shield": '<svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="M9 12l2 2 4-5"/></svg>',
    "stop": '<svg viewBox="0 0 24 24"><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M9 9h6v6H9z"/></svg>',
    "step": '<svg viewBox="0 0 24 24"><path d="M4 18h4v-4h4v-4h4V6h4"/><path d="M16 6h4v4"/></svg>',
    "ack": '<svg viewBox="0 0 24 24"><path d="M4 12l5 5L20 6"/><path d="M4 6h7M13 18h7"/></svg>',
    "scale": '<svg viewBox="0 0 24 24"><path d="M12 4v16M5 7h14M7 7l-4 7h8zM17 7l-4 7h8zM8 20h8"/></svg>',
    "repeat": '<svg viewBox="0 0 24 24"><path d="M4 8h11l-3-3M20 16H9l3 3"/><path d="M18 8a6 6 0 0 1 0 8M6 16a6 6 0 0 1 0-8"/></svg>',
    "warning": '<svg viewBox="0 0 24 24"><path d="M12 3l10 18H2z"/><path d="M12 9v5M12 18h.01"/></svg>',
}


ARROW = '<span class="arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></span>'


def icon(name: str, small: bool = False) -> str:
    size = " small" if small else ""
    return f'<span class="icon{size}">{ICONS[name]}</span>'


def page(extra_css: str, body: str) -> str:
    return f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><style>{BASE_CSS}\n{extra_css}</style></head><body>{body}</body></html>\n"""


def values_visual() -> str:
    css = r"""
.value-grid{height:100%;display:grid;grid-template-columns:repeat(3,1fr);gap:28px;align-items:center}
.value-card{height:500px;padding:30px;display:flex;flex-direction:column}.value-card .head{display:flex;align-items:center;gap:15px}.value-card .title{margin-top:20px}
.value-card .definition{margin-top:12px;font-size:17px;line-height:1.5;color:#475569;font-weight:650}.examples{display:grid;gap:12px;margin-top:26px}
.example{padding:16px;border-radius:17px;background:var(--soft);border:1px solid var(--border)}.example b{display:block;font-size:17px}.example span{display:block;margin-top:5px;color:#64748b;font-size:14px;font-weight:650}
.value-card .bottom{margin-top:auto;padding-top:20px;border-top:1px solid #e2e8f0;font-size:14px;line-height:1.45;font-weight:750;color:var(--deep)}
.formula{position:absolute;left:220px;right:220px;bottom:1px;height:76px;display:flex;align-items:center;justify-content:center;gap:15px}
"""
    cards = [
        ("soft-blue", "CALCULATED", "계산값", "calculator", "명목 조건과 설정값으로 계산한 비교 기준", [("이론 당량점", "20.0 · 30.0 · 40.0 mL"), ("계산 주입량", "작동 시간 × 설정 유량 0.99 mL/s")], "직접 측정 피드백과 구분"),
        ("soft-orange", "OBSERVED", "관찰값", "eye", "카메라 ROI에서 실제로 기록한 변화", [("색 변화", "지시약 종말점의 주요 관찰값"), ("열화상 변화", "용액·용기 영역의 겉보기 표면온도")], "열화상은 보조 관찰값"),
        ("soft-teal", "ESTIMATED", "추정값", "model", "센서 시계열을 분석해 얻은 결과", [("모델 당량점", "실험별 후보에서 선택한 부피"), ("미지 농도", "추정 당량점 부피를 반응식에 대입")], "이론값이나 실측값과 동일하지 않음"),
    ]
    html = []
    for cls, kicker, title, ico, definition, examples, bottom in cards:
        ex = "".join(f'<div class="example"><b>{a}</b><span>{b}</span></div>' for a, b in examples)
        html.append(f'<section class="panel topline value-card {cls}"><div class="head">{icon(ico)}<span class="kicker">{kicker}</span></div><div class="title">{title}</div><div class="definition">{definition}</div><div class="examples">{ex}</div><div class="bottom">{bottom}</div></section>')
    body = f'<main class="canvas"><div class="value-grid">{"".join(html)}</div><div class="formula"><span class="dark-pill">핵심 구분</span><span class="title" style="font-size:21px">비교 기준 · 센서 관찰 · 모델 추정을 분리해 해석</span></div></main>'
    return page(css, body)


def validation_visual() -> str:
    css = r"""
.flow{height:420px;display:grid;grid-template-columns:1fr 46px 1fr 46px 1fr;align-items:center}.stage{height:330px;padding:29px;display:flex;flex-direction:column}.stage .top{display:flex;align-items:center;justify-content:space-between}.stage .title{margin-top:22px}.big{margin-top:24px;font-size:52px;line-height:1;font-weight:920;letter-spacing:-.05em;color:var(--deep)}.stage .note{margin-top:10px}
.boundary{height:112px;margin-top:22px;padding:22px 28px;display:flex;align-items:center;gap:24px}.neq{font-size:45px;font-weight:900;color:#ef4444}.boundary strong{font-size:25px}.repeat{margin-top:18px;height:108px;display:grid;grid-template-columns:1.1fr 1fr 1fr 1.4fr;gap:14px}.mini{padding:17px 20px;border-radius:19px;background:#fff;border:1px solid #dbe3ea}.mini b{display:block;font-size:20px}.mini span{display:block;margin-top:5px;color:#64748b;font-size:13px;font-weight:650}.mini.warn{background:#fff7ed;border-color:#fed7aa;color:#9a3412}
"""
    body = f"""<main class="canvas">
    <div class="flow">
      <section class="panel topline stage soft-blue"><div class="top"><span class="kicker">DATA</span>{icon('csv')}</div><div class="title">개발자료 구성</div><div class="big">4 × 3</div><div class="subtitle">네 적정 종류 × 세 농도<br>서로 다른 반응 조건을 비교</div></section>
      {ARROW}
      <section class="panel topline stage soft-violet"><div class="top"><span class="kicker">SEARCH</span>{icon('branch')}</div><div class="title">설정 탐색</div><div class="big">2,030,370</div><div class="subtitle">같은 개발자료의 정답으로<br>후보 생성과 최종 설정 선택</div></section>
      {ARROW}
      <section class="panel topline stage soft-teal"><div class="top"><span class="kicker">RESULT</span>{icon('target')}</div><div class="title">선택된 결과</div><div class="big">0.30%</div><div class="subtitle">실험별 외부 제외 검증<br>개발자료 내부 MAPE</div></section>
    </div>
    <section class="panel boundary soft-slate"><span class="dark-pill">해석 경계</span><strong>개발자료 내부 최저값</strong><span class="neq">≠</span><strong>새 시료의 독립 검증 정확도</strong></section>
    <div class="repeat"><div class="mini"><b>동일 미지 시료 반복</b><span>고정한 설정을 별도 자료에 적용</span></div><div class="mini"><b>평균 0.09351 M</b><span>반복 예측 농도의 평균</span></div><div class="mini"><b>CV 0.96%</b><span>같은 시료의 반복성</span></div><div class="mini warn"><b>정확도 평가는 불가</b><span>실제 농도를 표정하지 않았음</span></div></div>
    </main>"""
    return page(css, body)


def sensor_visual() -> str:
    css = r"""
.sensor-grid{height:420px;display:grid;grid-template-columns:1fr 44px 1fr 44px 1fr;align-items:center}.sensor-card{height:350px;padding:30px;display:flex;flex-direction:column}.sensor-card .top{display:flex;align-items:center;justify-content:space-between}.sensor-card .title{margin-top:24px}.sensor-card .metric-value{margin-top:20px;color:var(--deep)}.stats{margin-top:auto;display:grid;grid-template-columns:1fr 1fr;gap:10px}.stat{padding:13px;border-radius:15px;background:var(--soft);border:1px solid var(--border)}.stat span{display:block;font-size:12px;color:#64748b;font-weight:700}.stat b{display:block;margin-top:4px;font-size:17px}
.evidence{margin-top:25px;display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.evidence .item{height:103px;padding:19px 20px;border-radius:20px;background:#fff;border:1px solid #dbe3ea}.item b{display:block;font-size:22px}.item span{display:block;margin-top:5px;color:#64748b;font-size:13px;font-weight:650}.conclusion{margin-top:18px;height:92px;display:flex;align-items:center;justify-content:center;gap:18px}.conclusion strong{font-size:24px}.plus{font-size:30px;font-weight:900;color:#94a3b8}
"""
    body = f"""<main class="canvas">
    <div class="sensor-grid">
      <section class="panel topline sensor-card soft-blue"><div class="top"><span class="kicker">COLOR</span>{icon('color')}</div><div class="title">색상 전용</div><div class="metric-value">1.55%</div><div class="metric-label">개발자료 MAPE</div><div class="stats"><div class="stat"><span>MAE</span><b>0.548 mL</b></div><div class="stat"><span>RMSE</span><b>0.754 mL</b></div></div></section>
      <div class="plus">+</div>
      <section class="panel topline sensor-card soft-orange"><div class="top"><span class="kicker">THERMAL</span>{icon('thermal')}</div><div class="title">열화상 전용</div><div class="metric-value">3.66%</div><div class="metric-label">개발자료 MAPE</div><div class="stats"><div class="stat"><span>MAE</span><b>0.917 mL</b></div><div class="stat"><span>RMSE</span><b>1.267 mL</b></div></div></section>
      <div class="arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></div>
      <section class="panel topline sensor-card soft-teal"><div class="top"><span class="kicker">FUSION</span>{icon('model')}</div><div class="title">색상 + 열화상</div><div class="metric-value">1.52%</div><div class="metric-label">개발자료 MAPE</div><div class="stats"><div class="stat"><span>MAE</span><b>0.476 mL</b></div><div class="stat"><span>RMSE</span><b>0.831 mL</b></div></div></section>
    </div>
    <div class="evidence"><div class="item"><b>개선 조건 존재</b><span>융합 후 색상 전용보다 오차 감소</span></div><div class="item"><b>악화 조건 존재</b><span>융합 후 오차 증가</span></div><div class="item"><b>95% 구간에 0 포함</b><span>일관된 향상은 확인되지 않음</span></div><div class="item"><b>열화상 0값 구간</b><span>변환 이상 가능성을 분리해 해석</span></div></div>
    <section class="panel conclusion soft-slate"><span class="dark-pill">결론</span><strong>색상은 주 신호, 열화상은 반응계에 따라 활용하는 탐색적 보조 신호</strong></section>
    </main>"""
    return page(css, body)


def auto_stop_visual() -> str:
    css = r"""
.main-flow{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}.flow-card{height:190px;padding:22px;display:flex;flex-direction:column}.flow-card .head{display:flex;align-items:center;justify-content:space-between}.flow-card .title{margin-top:18px;font-size:22px}.flow-card .note{margin-top:auto}.second{margin-top:18px}.safety{margin-top:25px;display:grid;grid-template-columns:1.3fr repeat(4,1fr);gap:14px}.safe{height:105px;padding:17px 18px;border-radius:19px;background:#fff;border:1px solid #dbe3ea}.safe b{display:block;font-size:20px}.safe span{display:block;margin-top:5px;color:#64748b;font-size:13px;font-weight:650}.safe.label{display:flex;align-items:center;gap:14px;background:#0f172a;color:#fff}.safe.label span{color:#cbd5e1}.warning-bar{margin-top:18px;height:72px;display:flex;align-items:center;justify-content:center;gap:14px;border-radius:20px;background:#fff7ed;border:1px solid #fed7aa;color:#9a3412}.warning-bar strong{font-size:20px}
"""
    def fc(num: str, cls: str, ico: str, title: str, note: str) -> str:
        return f'<section class="panel topline flow-card {cls}"><div class="head"><span class="kicker">{num}</span>{icon(ico, True)}</div><div class="title">{title}</div><div class="note">{note}</div></section>'
    row1 = "".join([
        fc("01", "soft-blue", "color", "기준색·모델 입력 확인", "필수 입력이 없으면 펌프를 시작하지 않음"),
        fc("02", "soft-green", "motor", "연속 주입", "방향·구동시간 응답이 일치할 때만 시작"),
        fc("03", "soft-violet", "model", "접근 점수 0.20", "종말점 접근 구간으로 전환"),
        fc("04", "soft-orange", "clock", "정지 후 0.50초 혼합", "센서값이 안정될 시간을 확보"),
    ])
    row2 = "".join([
        fc("05", "soft-teal", "step", "STEP 5 미세 주입", "설정 유량 기준 명목 0.0495 mL"),
        fc("06", "soft-blue", "ack", "수락·완료 응답 확인", "불확실한 펄스는 자동 재전송하지 않음"),
        fc("07", "soft-violet", "repeat", "센서 재판정", "조건 미충족 시 혼합·펄스·판정을 반복"),
        fc("08", "soft-green", "stop", "점수 0.30 + 색 변화 0.4초", "최종 STOP과 계산 주입량 기록"),
    ])
    body = f"""<main class="canvas"><div class="main-flow">{row1}</div><div class="main-flow second">{row2}</div>
    <div class="safety"><div class="safe label">{icon('shield',True)}<div><b>제어 안전 제한</b><span>센서 판단과 별도로 적용</span></div></div><div class="safe"><b>15 mL</b><span>회당 임시 기본 한도</span></div><div class="safe"><b>100 mL</b><span>애플리케이션 절대 상한</span></div><div class="safe"><b>120초</b><span>펌웨어 연속 구동 상한</span></div><div class="safe"><b>실패-폐쇄</b><span>센서·모델 오류 시 즉시 정지</span></div></div>
    <div class="warning-bar">{icon('warning',True)}<strong>0.0495 mL는 설정값으로 계산한 명목 부피이며, 실측 방울 부피나 습식 정지 정확도가 아님</strong></div></main>"""
    return page(css, body)


def calibration_visual() -> str:
    css = r"""
.cal-flow{height:330px;display:grid;grid-template-columns:1fr 35px 1fr 35px 1fr 35px 1fr 35px 1fr;align-items:center}.cal{height:260px;padding:23px;display:flex;flex-direction:column}.cal .head{display:flex;align-items:center;justify-content:space-between}.cal .title{margin-top:20px;font-size:23px}.cal .note{margin-top:auto}.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.chip{padding:7px 10px;border-radius:10px;background:var(--soft);border:1px solid var(--border);font-size:13px;font-weight:800;color:var(--deep)}
.formula-row{margin-top:22px;display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:18px}.formula-card{height:165px;padding:23px 26px}.formula-card .formula{margin-top:14px;font-size:31px;font-weight:900;letter-spacing:-.03em}.formula-card .note{margin-top:8px}.status{background:#fff7ed;border-color:#fed7aa}.status .title{color:#9a3412}.footer{margin-top:18px;height:108px;display:flex;align-items:center;justify-content:center;gap:16px}.footer strong{font-size:22px}
"""
    def cal(num: str, cls: str, ico: str, title: str, note: str, chips: list[str]) -> str:
        chip_html = "".join(f'<span class="chip">{c}</span>' for c in chips)
        return f'<section class="panel topline cal {cls}"><div class="head"><span class="kicker">{num}</span>{icon(ico,True)}</div><div class="title">{title}</div><div class="chips">{chip_html}</div><div class="note">{note}</div></section>'
    cards = [
        cal("01", "soft-blue", "pump", "피스톤 위치", "잔량에 따른 마찰·압력 차이 확인", ["초기 10%", "중간 50%", "말기 90%"]),
        cal("02", "soft-teal", "step", "명령 크기", "스텝 수와 실측 부피의 선형성 확인", ["STEP 5", "10", "20", "50"]),
        cal("03", "soft-violet", "repeat", "반복 측정", "각 위치·명령 조합을 최소 10회", ["3 위치", "4 명령", "각 최소 10회"]),
        cal("04", "soft-orange", "scale", "질량 차이", "명령 전후 수집 용기의 Δm 기록", ["물 온도", "저울 분해능", "기포 제거"]),
        cal("05", "soft-green", "model", "통계와 지연", "평균·표준편차·CV·선형성·overshoot", ["기울기", "절편", "R²", "잔차"]),
    ]
    flow = f'{cards[0]}{ARROW}{cards[1]}{ARROW}{cards[2]}{ARROW}{cards[3]}{ARROW}{cards[4]}'
    body = f"""<main class="canvas"><div class="cal-flow">{flow}</div>
    <div class="formula-row"><section class="panel formula-card soft-blue"><span class="kicker">VOLUME</span><div class="formula">V = Δm / ρ(T)</div><div class="note">물 밀도 출처와 온도를 함께 기록</div></section><section class="panel formula-card soft-teal"><span class="kicker">REFERENCE</span><div class="formula">5 step = 0.0495 mL</div><div class="note">실측 참값이 아닌 명목 기준</div></section><section class="panel formula-card status"><span class="kicker" style="color:#c2410c">CURRENT STATUS</span><div class="title" style="margin-top:15px">아직 미측정</div><div class="note">후속 습식 보정 계획으로만 제시</div></section></div>
    <section class="panel footer soft-slate"><span class="dark-pill">검증 목적</span><strong>실제 펄스 부피 · 피스톤 위치별 편차 · 정지 후 추가 토출량을 분리해 측정</strong></section></main>"""
    return page(css, body)


def recording_visual() -> str:
    css = r"""
.pipeline{height:430px;display:grid;grid-template-columns:210px 46px 225px 46px 290px 46px 250px 46px 250px;align-items:center}.source{display:grid;gap:15px}.source-card{height:150px;padding:20px;display:flex;flex-direction:column}.source-card .head{display:flex;align-items:center;justify-content:space-between}.source-card .title{margin-top:auto;font-size:20px}
.node{height:300px;padding:26px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center}.node .title{margin-top:22px}.split{height:320px;padding:22px;display:grid;gap:14px}.branch-card{border-radius:18px;padding:18px;background:var(--soft);border:1px solid var(--border)}.branch-card b{display:block;font-size:19px}.branch-card span{display:block;margin-top:6px;color:#64748b;font-size:13px;font-weight:650}
.metric-row{margin-top:28px;display:grid;grid-template-columns:1fr 1fr;gap:20px}.metric-panel{height:190px;padding:25px 28px}.metric-panel .head{display:flex;align-items:center;justify-content:space-between}.numbers{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:21px}.number{padding:14px;border-radius:16px;background:var(--soft);border:1px solid var(--border)}.number b{display:block;font-size:24px}.number span{display:block;margin-top:4px;font-size:12px;color:#64748b;font-weight:650}
"""
    body = f"""<main class="canvas"><div class="pipeline">
    <div class="source"><section class="panel source-card soft-blue"><div class="head"><span class="kicker">VISIBLE</span>{icon('camera',True)}</div><div class="title">색상 ROI 프레임</div></section><section class="panel source-card soft-orange"><div class="head"><span class="kicker">THERMAL</span>{icon('thermal',True)}</div><div class="title">열화상 ROI 프레임</div></section></div>
    {ARROW}<section class="panel node soft-violet">{icon('clock')}<div class="title">공통 PC 시각</div><div class="subtitle" style="margin-top:10px">가장 가까운 두 프레임을 짝지어 시각 차이 기록</div></section>
    {ARROW}<section class="panel split soft-slate"><div class="branch-card"><b>미리보기 경로</b><span>지연되면 최신 프레임만 표시</span></div><div class="branch-card"><b>분석 경로</b><span>ROI 특징과 상태를 계산</span></div><div class="branch-card" style="background:#ecfdf5;border-color:#a7f3d0"><b>기록 전용 FIFO</b><span>프레임을 순서대로 모두 보존</span></div></section>
    {ARROW}<section class="panel node soft-teal">{icon('queue')}<div class="title">종료 시 대기열 비우기</div><div class="subtitle" style="margin-top:10px">남은 프레임까지 처리한 뒤 파일 확정</div></section>
    {ARROW}<section class="panel node soft-green">{icon('csv')}<div class="title">CSV 저장</div><div class="subtitle" style="margin-top:10px">색 · 열 · 펌프 상태를 같은 행에 기록</div></section></div>
    <div class="metric-row"><section class="panel metric-panel soft-blue"><div class="head"><div><span class="kicker">SENSOR SYNC</span><div class="title" style="margin-top:8px;font-size:23px">센서 시간축 정렬</div></div>{icon('clock')}</div><div class="numbers"><div class="number"><b>공통 시각</b><span>PC 기준 시간 기록</span></div><div class="number"><b>3.66 ms</b><span>평균 절대 시각 차이</span></div><div class="number"><b>최근접 매칭</b><span>색상·열화상 프레임</span></div></div></section><section class="panel metric-panel soft-green"><div class="head"><div><span class="kicker">DRY INPUT TEST</span><div class="title" style="margin-top:8px;font-size:23px">25 fps 저장 구조 시험</div></div>{icon('queue')}</div><div class="numbers"><div class="number"><b>25 fps</b><span>모의 프레임 입력</span></div><div class="number"><b>FIFO</b><span>입력 순서 보존</span></div><div class="number"><b>누락 없음</b><span>종료 시 대기열 처리</span></div></div></section></div>
    </main>"""
    return page(css, body)


def system_visual() -> str:
    css = r"""
.system{height:100%;display:grid;grid-template-columns:330px 70px 410px 70px 1fr;align-items:center}.group{display:grid;gap:16px}.component{height:155px;padding:22px;display:flex;align-items:center;gap:17px}.component .title{font-size:22px}.component .subtitle{margin-top:7px;font-size:14px}.center-device{height:520px;padding:30px;display:flex;flex-direction:column;align-items:center;text-align:center}.beaker{width:225px;height:220px;margin-top:24px;position:relative;border:5px solid #94a3b8;border-top:0;border-radius:0 0 34px 34px}.liquid{position:absolute;left:8px;right:8px;bottom:8px;height:115px;border-radius:8px 8px 25px 25px;background:linear-gradient(180deg,#bfdbfe,#60a5fa)}.drop{position:absolute;top:-24px;left:102px;width:21px;height:29px;border-radius:60% 60% 65% 65%;background:#2563eb;transform:rotate(45deg)}.tube{position:absolute;top:-52px;left:110px;width:5px;height:36px;background:#64748b}.stir{position:absolute;left:44px;right:44px;bottom:42px;height:3px;background:#fff;border-radius:99px;box-shadow:0 0 0 1px rgba(255,255,255,.7)}
.sensor-pills{display:flex;gap:10px;margin-top:22px}.links{display:flex;align-items:center;justify-content:center}.links .line{width:42px;height:3px;background:#cbd5e1}.result-stack{display:grid;gap:16px}.result{height:120px;padding:20px;display:flex;align-items:center;gap:15px}.result .title{font-size:20px}.result .subtitle{font-size:13px;margin-top:5px}.band{position:absolute;left:350px;right:350px;bottom:0;height:82px;display:flex;align-items:center;justify-content:center;gap:18px}.band strong{font-size:21px}
"""
    body = f"""<main class="canvas"><div class="system">
    <div class="group"><section class="panel component soft-violet">{icon('chip')}<div><div class="title">Arduino · A4988</div><div class="subtitle">방향·스텝·구동시간 제어</div></div></section><section class="panel component soft-green">{icon('motor')}<div><div class="title">스테퍼 모터 · T8</div><div class="subtitle">회전을 피스톤의 직선 운동으로 변환</div></div></section><section class="panel component soft-blue">{icon('pump')}<div><div class="title">100 mL 시린지</div><div class="subtitle">적정액 저장과 호스 주입</div></div></section></div>
    <div class="links"><span class="line"></span>{ARROW}</div>
    <section class="panel topline center-device soft-blue"><span class="kicker">REACTION</span><div class="title" style="margin-top:8px">반응 비커 · 교반기</div><div class="beaker"><div class="tube"></div><div class="drop"></div><div class="liquid"><div class="stir"></div></div></div><div class="sensor-pills"><span class="pill soft-blue">색상 ROI</span><span class="pill soft-orange">열화상 ROI</span></div></section>
    <div class="links"><span class="line"></span>{ARROW}</div>
    <div class="result-stack"><section class="panel result soft-blue">{icon('camera',True)}<div><div class="title">일반 카메라</div><div class="subtitle">RGB · HSV · 변화량</div></div></section><section class="panel result soft-orange">{icon('thermal',True)}<div><div class="title">HIKMICRO Mini2</div><div class="subtitle">겉보기 표면온도와 변화량</div></div></section><section class="panel result soft-teal">{icon('computer',True)}<div><div class="title">Windows 수집기</div><div class="subtitle">펌프 제어 · 공통 시각 · CSV 저장</div></div></section><section class="panel result soft-green">{icon('model',True)}<div><div class="title">분석·결과</div><div class="subtitle">당량점 부피 · 미지 농도</div></div></section></div></div>
    <section class="panel band soft-slate"><span class="dark-pill">통합 흐름</span><strong>주입 제어 → 비접촉 관찰 → 공통 시간축 기록 → 당량점 분석</strong></section></main>"""
    return page(css, body)


def ml_visual() -> str:
    css = r"""
.inputs{height:112px;display:grid;grid-template-columns:1fr 1fr;gap:18px}.input-panel{padding:22px 26px;display:flex;align-items:center;gap:19px}.input-panel .title{font-size:22px}.chips{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}.chip{padding:7px 10px;border-radius:10px;background:var(--soft);border:1px solid var(--border);font-size:13px;font-weight:800;color:var(--deep)}
.ml-flow{height:300px;display:grid;grid-template-columns:1fr 35px 1fr 35px 1fr 35px 1fr;align-items:center;margin-top:20px}.ml-card{height:245px;padding:24px;display:flex;flex-direction:column}.ml-card .head{display:flex;align-items:center;justify-content:space-between}.ml-card .title{margin-top:20px;font-size:23px}.ml-card .note{margin-top:auto}
.selected{margin-top:20px;display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.choice{height:135px;padding:18px 20px;border-radius:20px;background:#fff;border:1px solid #dbe3ea}.choice span{display:block;font-size:13px;color:#64748b;font-weight:700}.choice b{display:block;margin-top:7px;font-size:19px}.choice em{display:block;margin-top:6px;font-size:14px;color:#0f766e;font-weight:850;font-style:normal}.footer{margin-top:17px;height:76px;display:flex;align-items:center;justify-content:center;gap:18px}.footer strong{font-size:21px}
"""
    def mc(num: str, cls: str, ico: str, title: str, note: str) -> str:
        return f'<section class="panel topline ml-card {cls}"><div class="head"><span class="kicker">{num}</span>{icon(ico,True)}</div><div class="title">{title}</div><div class="note">{note}</div></section>'
    flow = f"""{mc('01','soft-blue','csv','CSV 한 파일 = 실험 한 번','프레임이 아니라 실험 단위로 평가')}{ARROW}{mc('02','soft-orange','branch','색·열 시계열 후보 생성','여러 시간 폭의 변화 후보를 구성')}{ARROW}{mc('03','soft-violet','repeat','실험별 외부 제외 검증','평가 실험을 학습·스케일링에서 제외')}{ARROW}{mc('04','soft-teal','target','적정 종류별 후보 평가','실험별 당량점 부피 하나를 선택')}"""
    choices = [("강산-강염기", "PLS 회귀", "MAPE 0.25%"), ("강산-약염기", "RBF 커널 릿지", "MAPE 0.32%"), ("약산-강염기", "선형 판별분석", "MAPE 0.16%"), ("약산-약염기", "이차 판별분석", "MAPE 0.45%")]
    choice_html = "".join(f'<div class="choice"><span>{a}</span><b>{b}</b><em>{c}</em></div>' for a,b,c in choices)
    body = f"""<main class="canvas"><div class="inputs"><section class="panel input-panel soft-teal">{icon('eye')}<div><div class="title">사용한 입력</div><div class="chips"><span class="chip">색상 특징</span><span class="chip">열화상 특징</span><span class="chip">적정 종류</span></div></div></section><section class="panel input-panel soft-orange">{icon('warning')}<div><div class="title">최종 모델에서 제외</div><div class="chips"><span class="chip">현재 주입량</span><span class="chip">시료 농도</span><span class="chip">이론 당량점</span><span class="chip">시간·진행률</span></div></div></section></div><div class="ml-flow">{flow}</div><div class="selected">{choice_html}</div><section class="panel footer soft-slate"><span class="dark-pill">전체 개발자료 결과</span><strong>MAE 0.078 mL · RMSE 0.091 mL · MAPE 0.30%</strong><span class="pill soft-orange">독립 검증값 아님</span></section></main>"""
    return page(css, body)


VISUALS = {
    "01_계산값_관찰값_추정값": values_visual,
    "02_개발결과_검증범위": validation_visual,
    "03_센서입력군_기여도": sensor_visual,
    "04_미세주입_자동정지_안전": auto_stop_visual,
    "05_5스텝_습식검증계획": calibration_visual,
    "06_25fps_기록파이프라인": recording_visual,
    "07_전체시스템_구성도": system_visual,
    "08_머신러닝_분석흐름": ml_visual,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder in VISUALS.items():
        (OUT / f"{name}.html").write_text(builder(), encoding="utf-8")
    print(f"generated {len(VISUALS)} HTML visuals in {OUT}")


if __name__ == "__main__":
    main()
