<template>
  <div class="print-page">
    <div class="no-print" style="padding: 12px; text-align: center">
      <el-button type="primary" @click="printPage">打印 / 另存为 PDF</el-button>
      <el-button @click="$router.back()">返回</el-button>
      <el-tag v-if="loading" style="margin-left: 8px" type="info">加载中…</el-tag>
    </div>

    <div v-if="!loading && report" class="report-sheet">
      <!-- 页眉：任务信息表 -->
      <h1 class="report-title">DemoVision {{ kindLabel }} 检测报告</h1>
      <table class="meta-table">
        <tbody>
          <tr>
            <td class="meta-label">开始时间</td><td>{{ report.task.start_time || '—' }}</td>
            <td class="meta-label">结束时间</td><td>{{ report.task.end_time || '—' }}</td>
          </tr>
          <tr>
            <td class="meta-label">SN</td>
            <td>{{ snText }}</td>
            <td class="meta-label">任务 UUID</td>
            <td>{{ report.task.task_uuid }}</td>
          </tr>
          <tr>
            <td class="meta-label">状态</td><td>{{ statusText }}</td>
            <td class="meta-label">结果</td><td>{{ resultText }}</td>
          </tr>
          <tr>
            <td class="meta-label">相对路径</td>
            <td colspan="3">{{ report.task.rel_path || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 正文：报告文本 -->
      <pre class="report-body" style="white-space: pre-wrap">{{ report.report_text || '（无报告文本）' }}</pre>
      <p v-if="report.truncated" class="truncated-hint">（报告过长，已截断前 512KB）</p>

      <!-- SLAM 轨迹曲线：网页内 ECharts 直绘（无头后端不产生 PNG 产物，故以数据直绘为准） -->
      <div v-if="kind === 'slam' && uuid" class="report-image">
        <SlamTrajectoryChart :task-uuid="uuid" height="340px" />
      </div>

      <!-- SLAM 附 png（若历史上确实存在该产物） -->
      <div v-if="report.image_names && report.image_names.length" class="report-image">
        <img
          v-for="name in report.image_names"
          :key="name"
          :src="`/api/history/${kind}/${uuid}/files/${encodeURIComponent(name)}`"
          :alt="name"
          style="object-fit: contain; max-width: 100%; border: 1px solid #ccc"
        />
      </div>

      <!-- 页脚 -->
      <div class="report-footer">
        <span>生成时间：{{ report.generated_at }}</span>
        <span>{{ report.task.rel_path || '' }}</span>
      </div>
    </div>

    <el-result v-else-if="!loading && error" icon="error" :title="error" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'
import SlamTrajectoryChart from '../components/SlamTrajectoryChart.vue'

const route = useRoute()
const kind = route.params.kind
const uuid = route.params.uuid

function printPage() {
  window.print()
}

const loading = ref(true)
const error = ref('')
const report = ref(null)

const kindLabel = computed(() => ({ detection: '检测', slam: 'SLAM', imu: 'IMU 校准' }[kind] || kind))
const snText = computed(() => report.value?.task?.sn || report.value?.task?.devices_sn || '—')
const statusText = computed(() => {
  const s = report.value?.task?.status
  return { finished: '完成', running: '运行中', failed: '失败' }[s] || s || '—'
})
const resultText = computed(() => {
  const t = report.value?.task
  if (kind === 'slam') return t?.is_qualified == null ? '—' : (t.is_qualified ? '合格' : '不合格')
  if (kind === 'imu') return t?.qualified == null ? '—' : (t.qualified ? '合格' : '不合格')
  return t?.overall_status || '—'
})

onMounted(async () => {
  try {
    const { data } = await api.get(`/history/${kind}/${uuid}/report`)
    report.value = data
  } catch (e) {
    error.value = '加载报告失败: ' + (e.message || e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 报告"纸张"暗色下跟随主题；打印时强制白纸黑字（@media print 覆盖） */
.print-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 16px;
}
.report-sheet {
  background: var(--dv-surface);
  border: 1px solid var(--dv-border);
  padding: 32px;
  border-radius: var(--dv-r);
  box-shadow: var(--dv-shadow);
}
.report-title {
  text-align: center;
  font-size: 22px;
  margin: 0 0 20px;
  color: var(--dv-text);
  letter-spacing: .04em;
}
.meta-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 20px;
  font-size: 13px;
}
.meta-table td {
  border: 1px solid var(--dv-border);
  padding: 6px 10px;
  color: var(--dv-text);
}
.meta-label {
  background: var(--dv-surface-2);
  color: var(--dv-text-2);
  font-weight: 600;
  width: 110px;
}
/* 报告正文：等宽字体，数字好对齐好扫读 */
.report-body {
  font-family: var(--dv-mono);
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--dv-bg);
  color: var(--dv-text-2);
  border: 1px solid var(--dv-border);
  padding: 14px;
  border-radius: var(--dv-r-sm);
}
.truncated-hint {
  color: var(--dv-warn);
  font-size: 12px;
}
.report-image {
  margin-top: 16px;
}
.report-footer {
  margin-top: 24px;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--dv-text-3);
  font-family: var(--dv-mono);
}
@media print {
  .no-print {
    display: none !important;
  }
  .print-page {
    max-width: 100%;
    padding: 0;
  }
  .report-sheet {
    background: #fff !important;
    color: #000 !important;
    border: none !important;
    box-shadow: none;
    border-radius: 0;
    padding: 8px;
  }
  .report-title,
  .meta-table td { color: #000 !important; }
  .meta-table td { border-color: #bbb !important; }
  .meta-label { background: #f2f4f7 !important; color: #000 !important; }
  .report-body {
    background: #fff !important;
    color: #000 !important;
    border-color: #bbb !important;
  }
  .report-footer { color: #333 !important; }
}
</style>
