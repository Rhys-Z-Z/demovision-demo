<template>
  <div class="traj-chart">
    <div class="traj-head">
      <span class="traj-title">SLAM 轨迹曲线</span>
      <span class="traj-sub">X / Y / Z / 欧式距离（mm）</span>
      <span v-if="meta" class="traj-meta dv-num">
        {{ meta.sampled }} / {{ meta.total }} 点{{ meta.total > meta.sampled ? '（已降采样）' : '' }}
      </span>
      <div class="traj-actions">
        <el-button size="small" text :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button size="small" text type="primary" :disabled="!meta" @click="exportPng">
          <el-icon><Download /></el-icon>导出 PNG
        </el-button>
      </div>
    </div>
    <div v-if="error" class="traj-error">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ error }}</span>
    </div>
    <div v-show="!error" ref="chartEl" class="traj-body" :style="{ height }"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '../api'
import { chartPalette, chartSkin, gridLineStyle, onDisplayModeChange, tooltipSkin } from '../utils/theme'

const props = defineProps({
  taskUuid: { type: String, required: true },
  height: { type: String, default: '320px' },
})

const chartEl = ref(null)
const loading = ref(false)
const error = ref('')
const meta = ref(null)

let chart = null
let offMode = null
let onResize = null

const SERIES = ['X', 'Y', 'Z', '欧式距离']

function buildOption(d) {
  const s = chartSkin()
  const p = chartPalette()
  const toPairs = (arr) => (arr || []).map((v, i) => [d.t[i], v])
  const series = SERIES.map((name, i) => {
    const key = ['x', 'y', 'z', 'dist'][i]
    return {
      name,
      type: 'line',
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: { width: i === 3 ? 2 : 1.4, color: p[i], type: i === 3 ? 'dashed' : 'solid' },
      itemStyle: { color: p[i] },
      data: toPairs(d[key]),
    }
  })
  return {
    backgroundColor: 'transparent',
    animation: false,
    grid: { left: 52, right: 20, top: 34, bottom: 52 },
    tooltip: { trigger: 'axis', ...tooltipSkin() },
    legend: { top: 2, textStyle: { color: s.text2, fontSize: 11 }, data: SERIES },
    toolbox: { show: false },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      { type: 'slider', xAxisIndex: 0, height: 16, bottom: 6 },
    ],
    xAxis: {
      type: 'value',
      name: 't (s)',
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    yAxis: {
      type: 'value',
      name: 'mm',
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    series,
  }
}

/** 只改外观不动数据（显示模式切换时用） */
function applySkin() {
  if (!chart || !meta.value) return
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
    series: SERIES.map((_, i) => ({ lineStyle: { color: p[i] }, itemStyle: { color: p[i] } })),
  })
}

async function load() {
  if (!props.taskUuid) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get(`/history/slam/${props.taskUuid}/trajectory`, {
      params: { max_points: 3000 },
    })
    if (!data || !data.t || !data.t.length) {
      error.value = '该任务没有可绘制的轨迹数据'
      meta.value = null
      return
    }
    meta.value = { total: data.total, sampled: data.sampled, csv: data.csv_name }
    await nextTick()
    if (!chart && chartEl.value) {
      chart = echarts.init(chartEl.value)
      chart.setOption(buildOption(data))
      onResize = () => chart && chart.resize()
      window.addEventListener('resize', onResize)
      offMode = onDisplayModeChange(() => applySkin())
    } else {
      // 切任务/刷新：整体替换（含数据）
      chart && chart.setOption(buildOption(data), true)
    }
  } catch (e) {
    const st = e?.response?.status
    error.value = st === 404
      ? '该任务没有轨迹 CSV 产物'
      : ('曲线加载失败: ' + (e?.response?.data?.detail || e.message || e))
    meta.value = null
  } finally {
    loading.value = false
  }
}

function exportPng() {
  if (!chart) return
  const a = document.createElement('a')
  a.href = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: chartSkin().bg })
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  a.download = `SLAM_trajectory_${props.taskUuid.slice(0, 8)}_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
  ElMessage.success('曲线图已导出 PNG')
}

onMounted(load)
onBeforeUnmount(() => {
  if (onResize) window.removeEventListener('resize', onResize)
  if (offMode) offMode()
  if (chart) chart.dispose()
  chart = null
})
</script>

<style scoped>
.traj-chart {
  border: 1px solid var(--dv-border);
  border-radius: var(--dv-r);
  background: var(--dv-surface-2);
  padding: 10px 12px 6px;
  box-sizing: border-box;
}
.traj-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--dv-border);
}
.traj-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--dv-text);
  letter-spacing: .04em;
}
.traj-sub { font-size: 11px; color: var(--dv-text-3); }
.traj-meta { font-size: 11px; color: var(--dv-text-3); }
.traj-actions { margin-left: auto; display: flex; align-items: center; gap: 2px; flex: none; }
.traj-actions .el-button { padding: 4px 6px; height: 24px; font-size: 12px; }
.traj-body { width: 100%; }
.traj-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 120px;
  color: var(--dv-text-3);
  font-size: 13px;
}
</style>
