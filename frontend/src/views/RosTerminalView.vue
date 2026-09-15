<template>
  <div class="ros-terminal">
    <el-container class="terminal-container">
      <!-- 左：资源面板 -->
      <el-aside width="320px" class="topic-aside">
        <div class="topic-header">
          <el-radio-group v-model="mode" size="small">
            <el-radio-button label="topic">话题</el-radio-button>
            <el-radio-button label="service">服务</el-radio-button>
          </el-radio-group>
          <el-button size="small" type="primary" plain :loading="loadingTopics" @click="refreshList">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
        <div class="topic-header">
          <el-input
            v-model="keyword"
            size="small"
            clearable
            placeholder="搜索..."
            style="width: 100%"
          />
        </div>
        <el-tree
          ref="treeRef"
          :data="treeData"
          :props="{ label: 'label', children: 'children' }"
          node-key="key"
          default-expand-all
          highlight-current
          :filter-node-method="filterNode"
          class="topic-tree"
          @node-click="onNodeClick"
        />
        <div class="topic-footer">
          <template v-if="selectedItem">
            <div class="selected-topic" :title="selectedItem">{{ selectedItem }}</div>
            <div class="topic-actions">
              <!-- 话题模式：Echo / Hz -->
              <template v-if="mode === 'topic'">
                <el-button
                  size="small"
                  :type="echoRunning ? 'danger' : 'primary'"
                  plain
                  @click="echoRunning ? stopEcho() : startEcho()"
                >
                  <el-icon><VideoPlay v-if="!echoRunning" /><VideoPause v-else /></el-icon>
                  &nbsp;{{ echoRunning ? '停止 Echo' : 'Echo 数据' }}
                </el-button>
                <el-button
                  size="small"
                  :type="hzRunning ? 'danger' : 'warning'"
                  plain
                  @click="hzRunning ? stopHz() : startHz()"
                >
                  <el-icon><DataLine v-if="!hzRunning" /><VideoPause v-else /></el-icon>
                  &nbsp;{{ hzRunning ? '停止 Hz' : 'Hz 频率' }}
                </el-button>
              </template>
              <!-- 服务模式：调用服务 -->
              <template v-else>
                <el-button
                  size="small"
                  :type="serviceRunning ? 'danger' : 'success'"
                  plain
                  @click="serviceRunning ? stopServiceCall() : startServiceCall()"
                >
                  <el-icon><VideoPlay v-if="!serviceRunning" /><VideoPause v-else /></el-icon>
                  &nbsp;{{ serviceRunning ? '停止调用' : '调用服务' }}
                </el-button>
              </template>
            </div>
          </template>
          <el-empty v-else description="请选择左侧{{ mode === 'topic' ? '话题' : '服务' }}" :image-size="60" />
        </div>
      </el-aside>

      <!-- 右：Echo / Hz / Service 视图 -->
      <el-main class="topic-main">
        <el-tabs v-model="activeTab" class="topic-tabs">
          <el-tab-pane label="Echo 数据" name="echo">
            <div class="echo-wrap">
              <LogTerminal :lines="echoLines" height="100%" :dark="true" />
            </div>
          </el-tab-pane>
          <el-tab-pane label="Hz 频率" name="hz">
            <div class="hz-wrap">
              <div class="hz-panel">
                <div class="hz-value">
                  <span class="hz-num">{{ rosStore.currentRate !== null ? rosStore.currentRate.toFixed(2) : '--' }}</span>
                  <span class="hz-unit">Hz</span>
                </div>
                <div class="hz-topic" :title="selectedItem || '未选择话题'">
                  {{ selectedItem || '未选择话题' }}
                </div>
              </div>
              <div ref="hzChartEl" class="hz-chart"></div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="Service 调用" name="service">
            <div class="echo-wrap">
              <LogTerminal :lines="serviceLines" height="100%" :dark="true" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import api from '../api'
import { chartPalette, chartSkin, gridLineStyle, onDisplayModeChange, tooltipSkin } from '../utils/theme'
import LogTerminal from '../components/LogTerminal.vue'
import { useTaskStore } from '../stores/taskStore'
import { useRosMonitorStore } from '../stores/rosMonitorStore'

const taskStore = useTaskStore()
const rosStore = useRosMonitorStore()

// ---------- 模式与列表 ----------
const mode = ref('topic') // 'topic' | 'service'
const items = ref([])
const treeData = ref([])
const keyword = ref('')
const treeRef = ref(null)
const selectedItem = ref('')
const loadingTopics = ref(false)
const activeTab = ref('echo')

// ---------- 运行状态 ----------
const echoRunning = ref(false)
const hzRunning = ref(false)
const serviceRunning = ref(false)

// ---------- Echo 缓冲（防卡顿：100ms 批量追加 + 只保留 100 行） ----------
const ECHO_MAX_LINES = 100
const echoLines = ref([])
let echoPending = []
let echoFlushTimer = null

// ---------- Service 结果（一次性输出，直接追加 + 上限保护） ----------
const SERVICE_MAX_LINES = 1000
const serviceLines = ref([])

// ---------- Hz 图表 ----------
const hzChartEl = ref(null)
let hzChart = null
let onResize = null
let offMode = null

// ---------- 树构建（话题/服务通用） ----------
function buildTree(list) {
  const roots = []
  const map = {}
  list.forEach((t) => {
    const parts = t.split('/').filter(Boolean)
    if (!parts.length) return
    let cur = roots
    let path = ''
    parts.forEach((part, i) => {
      path += '/' + part
      let node = map[path]
      if (!node) {
        node = {
          label: part,
          key: path,
          children: [],
          isLeaf: i === parts.length - 1,
        }
        if (node.isLeaf) node.value = t
        map[path] = node
        cur.push(node)
      }
      cur = node.children
    })
  })
  return roots
}

function filterNode(value, data) {
  if (!value) return true
  return data.key.includes(value) || data.label.includes(value)
}

async function refreshList() {
  loadingTopics.value = true
  try {
    const url = mode.value === 'topic' ? '/ros/topics' : '/ros/services'
    const { data } = await api.get(url)
    items.value = mode.value === 'topic' ? (data.topics || []) : (data.services || [])
    treeData.value = buildTree(items.value)
    if (treeRef.value) treeRef.value.filter(keyword.value)
  } catch (e) {
    ElMessage.warning('获取列表失败（ROS 未就绪？）')
  } finally {
    loadingTopics.value = false
  }
}

function onNodeClick(data) {
  if (data.isLeaf) selectedItem.value = data.value
}

watch(keyword, (val) => {
  treeRef.value && treeRef.value.filter(val)
})

// ---------- 切换模式：停止运行任务并重建列表 ----------
watch(mode, async () => {
  stopRunningTasks()
  echoLines.value = []
  echoPending = []
  serviceLines.value = []
  rosStore.reset()
  if (hzChart) hzChart.setOption({ series: [{ data: [] }] })
  selectedItem.value = ''
  activeTab.value = mode.value === 'service' ? 'service' : 'echo'
  await refreshList()
})

// ---------- WS 发送 ----------
function sendWS(msg) {
  const ws = taskStore.ws
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
  }
}

// ---------- Echo ----------
function startEcho() {
  if (!selectedItem.value) return
  sendWS({ type: 'start_echo', topic: selectedItem.value })
  echoLines.value = []
  echoPending = []
  echoRunning.value = true
  activeTab.value = 'echo'
}

function stopEcho() {
  sendWS({ type: 'stop_echo' })
  echoRunning.value = false
}

// ---------- Hz ----------
function startHz() {
  if (!selectedItem.value) return
  sendWS({ type: 'start_hz', topic: selectedItem.value })
  rosStore.reset()
  hzRunning.value = true
  activeTab.value = 'hz'
  if (hzChart) {
    hzChart.setOption({ series: [{ data: [] }] })
  }
}

function stopHz() {
  sendWS({ type: 'stop_hz' })
  hzRunning.value = false
}

// ---------- Service Call ----------
function startServiceCall() {
  if (!selectedItem.value) return
  sendWS({ type: 'start_service_call', service: selectedItem.value })
  serviceLines.value = []
  serviceRunning.value = true
  activeTab.value = 'service'
}

function stopServiceCall() {
  sendWS({ type: 'stop_service_call' })
  serviceRunning.value = false
}

function stopRunningTasks() {
  if (echoRunning.value) sendWS({ type: 'stop_echo' })
  if (hzRunning.value) sendWS({ type: 'stop_hz' })
  if (serviceRunning.value) sendWS({ type: 'stop_service_call' })
  echoRunning.value = false
  hzRunning.value = false
  serviceRunning.value = false
}

// ---------- Hz 图表渲染（30 FPS 批量） ----------
function renderHz(data) {
  if (!hzChart) return
  const pairs = (tArr, rArr) => tArr.map((t, i) => [t, rArr[i]])
  hzChart.setOption({
    series: [{ data: pairs(data.t, data.rate) }],
  })
}

function makeHzOption() {
  const s = chartSkin()
  const line = chartPalette()[2] // 琥珀：频率曲线
  return {
    backgroundColor: 'transparent',
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: 'axis', ...tooltipSkin() },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
      { type: 'slider', xAxisIndex: 0, height: 16, bottom: 2 },
    ],
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    yAxis: {
      type: 'value',
      name: 'Hz',
      scale: true,
      nameTextStyle: { color: s.text2 },
      axisLine: { lineStyle: { color: s.grid } },
      axisLabel: { color: s.text2 },
      splitLine: { lineStyle: gridLineStyle(0.5) },
    },
    series: [
      {
        name: 'rate',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 1.6, color: line },
        itemStyle: { color: line },
        areaStyle: { color: line, opacity: 0.12 },
        data: [],
      },
    ],
  }
}

// 只刷外观、不动数据（显示模式切换时调用）
function applyHzSkin() {
  if (!hzChart) return
  const s = chartSkin()
  const line = chartPalette()[2]
  hzChart.setOption({
    tooltip: tooltipSkin(),
    xAxis: { axisLine: { lineStyle: { color: s.grid } }, axisLabel: { color: s.text2 }, splitLine: { lineStyle: gridLineStyle(0.5) } },
    yAxis: { nameTextStyle: { color: s.text2 }, axisLine: { lineStyle: { color: s.grid } }, axisLabel: { color: s.text2 }, splitLine: { lineStyle: gridLineStyle(0.5) } },
    series: [{ lineStyle: { color: line }, itemStyle: { color: line }, areaStyle: { color: line, opacity: 0.12 } }],
  })
}

// ---------- WS 消息 ----------
function onWindowMessage(e) {
  const msg = e.detail
  if (!msg) return
  if (msg.type === 'echo_data' && echoRunning.value) {
    echoPending.push(msg.line || '')
  } else if (msg.type === 'service_data') {
    serviceLines.value.push(msg.line || '')
    if (serviceLines.value.length > SERVICE_MAX_LINES) {
      serviceLines.value.splice(0, serviceLines.value.length - SERVICE_MAX_LINES)
    }
  } else if (msg.type === 'service_done') {
    // 服务调用已结束，恢复按钮状态
    serviceRunning.value = false
  }
}

// ---------- 生命周期 ----------
onMounted(() => {
  refreshList()
  window.addEventListener('ws-message', onWindowMessage)
  // 100ms 批量刷新 Echo 终端
  echoFlushTimer = setInterval(() => {
    if (!echoPending.length) return
    if (echoRunning.value) {
      echoLines.value.push(...echoPending)
      if (echoLines.value.length > ECHO_MAX_LINES) {
        echoLines.value.splice(0, echoLines.value.length - ECHO_MAX_LINES)
      }
    }
    echoPending = []
  }, 100)
  // Hz 图表
  nextTick(() => {
    if (hzChartEl.value) {
      hzChart = echarts.init(hzChartEl.value)
      hzChart.setOption(makeHzOption())
      rosStore.registerChart(renderHz)
    }
  })
  onResize = () => hzChart && hzChart.resize()
  window.addEventListener('resize', onResize)
  // 显示模式切换后重新应用图表外观
  offMode = onDisplayModeChange(() => applyHzSkin())
})

onBeforeUnmount(() => {
  // 停止所有运行中的任务，防止后端产生孤儿进程
  stopRunningTasks()
  if (echoFlushTimer) clearInterval(echoFlushTimer)
  window.removeEventListener('ws-message', onWindowMessage)
  rosStore.unregisterChart(renderHz)
  rosStore.reset()
  if (onResize) window.removeEventListener('resize', onResize)
  if (offMode) offMode()
  if (hzChart) hzChart.dispose()
  hzChart = null
})
</script>

<style scoped>
.ros-terminal {
  height: 100%;
}
.terminal-container {
  height: 100%;
  gap: 12px;
}
.topic-aside {
  background: var(--xv-surface);
  border: 1px solid var(--xv-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 10px;
  box-sizing: border-box;
}
.topic-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.topic-tree {
  flex: 1;
  overflow: auto;
  border: 1px solid var(--xv-border);
  border-radius: 6px;
  padding: 6px;
  background: var(--xv-bg);
}
.topic-tree :deep(.el-tree-node__content) {
  height: 28px;
}
.topic-footer {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--xv-border);
  min-height: 92px;
}
.selected-topic {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  color: var(--xv-text);
  background: var(--xv-bg);
  border: 1px solid var(--xv-border);
  border-radius: 4px;
  padding: 6px 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 8px;
}
.topic-actions {
  display: flex;
  gap: 8px;
}
.topic-main {
  padding: 0 !important;
  display: flex;
  flex-direction: column;
}
.topic-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.topic-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
}
.topic-tabs :deep(.el-tab-pane) {
  height: 100%;
}
.echo-wrap {
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--xv-border);
}
.hz-wrap {
  height: 100%;
  background: var(--xv-surface);
  border: 1px solid var(--xv-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.hz-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--xv-border);
}
.hz-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.hz-num {
  font-size: 32px;
  font-weight: 700;
  color: var(--xv-warn);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}
.hz-unit {
  font-size: 14px;
  color: var(--xv-text-2);
}
.hz-topic {
  font-size: 12px;
  color: var(--xv-text-2);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  max-width: 60%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hz-chart {
  flex: 1;
  min-height: 0;
}
</style>
