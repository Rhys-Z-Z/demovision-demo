<template>
  <div class="multi-chart">
    <div class="chart-header">
      <span class="chart-sn">{{ sn.slice(-8) }}</span>
      <span class="chart-sub">X / Y / Z / 欧式距离（mm）· 最近 {{ windowSec }} 秒</span>
      <div class="chart-actions">
        <el-tooltip content="导出为 PNG 图片（下载到本机）" placement="top" :show-after="300">
          <el-button size="small" text @click="exportPng">
            <el-icon><Download /></el-icon>导出 PNG
          </el-button>
        </el-tooltip>
        <el-tooltip
          content="存入该 SLAM 任务的产物目录（随任务归档，可在『历史报告』页下载）"
          placement="top"
          :show-after="300"
        >
          <el-button
            size="small"
            text
            type="primary"
            :loading="saving"
            :disabled="!taskStore.slam.uuid"
            @click="saveToTask"
          >
            <el-icon><FolderAdd /></el-icon>存入报告
          </el-button>
        </el-tooltip>
      </div>
    </div>
    <div ref="chartEl" class="chart-body"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '../api'
import { useSlamStore, SLAM_WINDOW_SEC } from '../stores/slamStore'
import { useTaskStore } from '../stores/taskStore'
import { chartPalette, chartSkin, gridLineStyle, onDisplayModeChange, tooltipSkin } from '../utils/theme'

const props = defineProps({
  sn: { type: String, required: true },
})

const slamStore = useSlamStore()
const taskStore = useTaskStore()
const windowSec = SLAM_WINDOW_SEC
const chartEl = ref(null)
let chart = null
let onResize = null
let offMode = null

// 曲线配色取设计 token 调色板：X=冰蓝 / Y=青绿 / Z=琥珀 / 欧式距离=电光青（主指标突出）
function makeBaseOption() {
  const s = chartSkin()
  const p = chartPalette()
  return {
    backgroundColor: 'transparent',
    animation: false, // 实时曲线：关闭动画，避免每次 setOption 触发过渡 → 抖动 + 长时间录制发卡
    grid: { left: 50, right: 20, top: 36, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      ...tooltipSkin(),
    },
    legend: {
      top: 2,
      textStyle: { color: s.text2, fontSize: 11 },
      data: ['X', 'Y', 'Z', '欧式距离'],
    },
    xAxis: {
      // 固定 [-窗口, 0] 的滑动窗口：0 = 现在（右端），负值 = 过去。
      // 🔴 绝不能直接用 ROS 原始时间戳当 X：它是设备 uptime 基准，
      // 换一次录制会话就整体跳变（实测 1162 / 35396 / 35431 / 36351），
      // 两个基准的点混在一条曲线里会把横轴撑到几万秒 → 几秒的真实数据被挤成一根竖线。
      type: 'value',
      name: '相对现在 (s)',
      min: -windowSec,
      max: 0,
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    yAxis: {
      type: 'value',
      name: 'mm',
      // 位置漂移是亚毫米量级：不加 scale 会把 0 硬塞进范围，曲线被压成一条扁带
      scale: true,
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    series: [
      { name: 'X', type: 'line', showSymbol: false, lineStyle: { width: 1.4, color: p[0] }, itemStyle: { color: p[0] }, data: [] },
      { name: 'Y', type: 'line', showSymbol: false, lineStyle: { width: 1.4, color: p[1] }, itemStyle: { color: p[1] }, data: [] },
      { name: 'Z', type: 'line', showSymbol: false, lineStyle: { width: 1.4, color: p[2] }, itemStyle: { color: p[2] }, data: [] },
      { name: '欧式距离', type: 'line', showSymbol: false, lineStyle: { width: 2, color: p[3], type: 'dashed' }, itemStyle: { color: p[3] }, data: [] },
    ],
  }
}

// 只刷外观、不动数据（显示模式切换时调用，否则会把曲线清空）
function applySkin() {
  if (!chart) return
  const s = chartSkin()
  const p = chartPalette()
  chart.setOption({
    tooltip: tooltipSkin(),
    legend: { textStyle: { color: s.text2 } },
    xAxis: {
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    yAxis: {
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    series: p.slice(0, 4).map((c) => ({ lineStyle: { color: c }, itemStyle: { color: c } })),
  })
}
const saving = ref(false)

/** 把当前曲线图导出为 PNG dataURL（底色取当前主题，避免透明底贴进文档发黑） */
function chartPngDataUrl(ratio = 2) {
  return chart.getDataURL({
    type: 'png',
    pixelRatio: ratio,
    backgroundColor: chartSkin().bg,
  })
}

/** 时间戳片段：YYYYMMDD_HHMMSS */
function stamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/** 导出到本机（浏览器下载） */
function exportPng() {
  if (!chart) return
  const a = document.createElement('a')
  a.href = chartPngDataUrl(2)
  a.download = `SLAM_${props.sn.slice(-8)}_${stamp()}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
  ElMessage.success('曲线图已导出 PNG')
}

/** 存入该 SLAM 任务的产物目录（随任务归档，历史报告页可下载） */
async function saveToTask() {
  const uuid = taskStore.slam.uuid
  if (!uuid) {
    ElMessage.warning('当前没有可关联的 SLAM 任务，请先开始一次记录')
    return
  }
  if (!chart) return
  saving.value = true
  try {
    const { data } = await api.post(`/slam/${uuid}/chart`, {
      sn: props.sn,
      image_base64: chartPngDataUrl(2),
    })
    if (data.saved) {
      ElMessage.success(`已存入任务产物：${data.name}`)
    } else {
      ElMessage.warning('保存未生效，请检查后端日志')
    }
  } catch (e) {
    const detail = e?.response?.data?.detail || e.message || e
    ElMessage.error('存入失败: ' + detail)
  } finally {
    saving.value = false
  }
}

// 30 FPS 增量渲染回调（由 slamStore 定时器调用）
function render(sn, data) {
  if (!chart || !data || !data.t || !data.t.length) return
  const mm = (arr) => arr.map((v) => +(v * 1000).toFixed(2))
  // X 轴用「相对最新点」的秒数（0 = 现在，负值 = 过去），与 xAxis 的 [-窗口, 0] 对应。
  // 这样与 ROS 时间戳的绝对基准完全解耦：无论基准怎么跳，窗口始终是最近 N 秒。
  const tRef = data.t[data.t.length - 1]
  const xs = data.t.map((t) => +(t - tRef).toFixed(3))
  const pairs = (arr) => xs.map((x, i) => [x, arr[i]])
  const X = mm(data.x)
  const Y = mm(data.y)
  const Z = mm(data.z)
  const D = mm(data.dist)
  chart.setOption({
    series: [
      { data: pairs(X) },
      { data: pairs(Y) },
      { data: pairs(Z) },
      { data: pairs(D) },
    ],
  })
}

onMounted(() => {
  chart = echarts.init(chartEl.value)
  chart.setOption(makeBaseOption())
  slamStore.registerChart(props.sn, render)
  onResize = () => chart && chart.resize()
  window.addEventListener('resize', onResize)
  // 显示模式切换后重新应用图表外观
  offMode = onDisplayModeChange(() => applySkin())
})

onBeforeUnmount(() => {
  slamStore.unregisterChart(props.sn, render)
  if (onResize) window.removeEventListener('resize', onResize)
  if (offMode) offMode()
  if (chart) chart.dispose()
  chart = null
})
</script>

<style scoped>
.multi-chart {
  background: var(--dv-surface);
  border: 1px solid var(--dv-border);
  border-radius: 8px;
  padding: 10px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}
.chart-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--dv-border);
}
.chart-sn {
  font-size: 14px;
  font-weight: 700;
  color: var(--dv-text);
  letter-spacing: 1px;
}
.chart-sub {
  font-size: 11px;
  color: var(--dv-text-2);
}
.chart-tag {
  margin-left: auto;
}
.chart-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
  flex: none;
}
.chart-actions .el-button {
  padding: 4px 6px;
  height: 24px;
  font-size: 12px;
}
.chart-body {
  flex: 1;
  min-height: 220px;
}
</style>
