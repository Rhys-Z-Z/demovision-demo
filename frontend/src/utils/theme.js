/**
 * 主题工具 —— 把设计 token（CSS 变量）喂给 ECharts 等 canvas 渲染。
 *
 * 为什么需要它：CSS 变量对 <canvas> 无效，图表的轴/网格/曲线颜色必须在运行时
 * 从 :root 读取。显示模式切换时 App.vue 会派发 `dv-mode-change` 事件，
 * 图表组件监听后重新应用外观即可跟随主题（暗色 / 高对比 / 洁净室）。
 */

export const XV_MODE_EVENT = 'dv-mode-change'
export const XV_MODE_KEY = 'dv-display-mode'

/** 读取单个设计 token（返回原始字符串，未定义时回退） */
export function dvColor(name, fallback = '#888888') {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue('--dv-' + name)
    .trim()
  return v || fallback
}

/**
 * 图表通用外观：轴、网格、提示框、文字。
 * 每次调用都重新读取，所以在模式切换后调用即生效。
 */
export function chartSkin() {
  return {
    text: dvColor('text', '#E8EEF4'),
    text2: dvColor('text-2', '#A9B5C4'),
    grid: dvColor('border', '#232734'),
    border: dvColor('border-2', '#2E3444'),
    surface: dvColor('surface-2', '#181B24'),
    bg: dvColor('bg', '#0B0C10'),
  }
}

/** 信号色顺序：信息 → 正常 → 告警 → 主色 → 异常 → 紫（备用） */
export function chartPalette() {
  return [
    dvColor('info', '#59B6FF'),
    dvColor('ok', '#2DD4A0'),
    dvColor('warn', '#F5B041'),
    dvColor('primary', '#00E5C9'),
    dvColor('err', '#FF5A6A'),
    '#B58CFF',
  ]
}

/** 网格线：用 token 色 + 极低透明度，避免抢视线 */
export function gridLineStyle(opacity = 0.5) {
  return { color: dvColor('border', '#232734'), opacity, type: 'dashed' }
}

/** 提示框外观（与 .dv-card 一致：surface-2 底 + 细边） */
export function tooltipSkin() {
  const s = chartSkin()
  return {
    backgroundColor: s.surface,
    borderColor: s.border,
    borderWidth: 1,
    textStyle: { color: s.text, fontSize: 12 },
    extraCssText: 'border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.5);',
  }
}

/** 把当前模式应用到 <html>（与 index.html 首屏脚本保持同一套规则） */
export function applyDisplayMode(mode) {
  const m = ['dash', 'contrast', 'clean'].includes(mode) ? mode : 'dash'
  const el = document.documentElement
  el.setAttribute('data-dv-mode', m)
  el.classList.toggle('dark', m !== 'clean')
  try {
    localStorage.setItem(XV_MODE_KEY, m)
  } catch (e) { /* 隐私模式忽略 */ }
  window.dispatchEvent(new CustomEvent(XV_MODE_EVENT, { detail: m }))
  return m
}

/** 订阅显示模式变化，返回取消订阅函数 */
export function onDisplayModeChange(fn) {
  const handler = (e) => fn(e.detail)
  window.addEventListener(XV_MODE_EVENT, handler)
  return () => window.removeEventListener(XV_MODE_EVENT, handler)
}
