<template>
  <el-container class="app-shell">
    <!-- ===== 左侧固定导轨（68px，悬停展开文字） ===== -->
    <el-aside width="68px" class="app-aside">
      <div class="rail-logo" :title="PLATFORM_NAME">
        <el-icon :size="20"><Monitor /></el-icon>
        <span class="rail-logo-label">{{ RAIL_LABEL }}</span>
      </div>

      <nav class="rail-nav">
        <router-link
          v-for="item in NAV"
          :key="item.path"
          :to="item.path"
          class="rail-item"
          :class="{ 'is-active': $route.path === item.path }"
        >
          <el-icon :size="17" class="rail-icon"><component :is="item.icon" /></el-icon>
          <span class="rail-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="rail-foot">
        <div class="rail-item rail-item--static" :title="taskStore.wsConnected ? '实时通道已连接' : '实时通道断开'">
          <span class="xv-dot" :class="taskStore.wsConnected ? 'xv-dot--ok xv-dot--live' : 'xv-dot--err'"></span>
          <span class="rail-label">{{ taskStore.wsConnected ? '实时通道已连接' : '实时通道断开' }}</span>
        </div>
      </div>
    </el-aside>

    <el-container>
      <!-- ===== 顶部状态栏 ===== -->
      <el-header height="56px" class="app-header">
        <!-- 平台徽章（改下方 PLATFORM_NAME 即可） -->
        <div class="line-badge" :title="PLATFORM_NAME">
          <span class="line-badge-mark"></span>
          <span class="line-badge-name">{{ PLATFORM_NAME }}</span>
        </div>

        <!-- 工作时段 / 当前作业 -->
        <div class="header-meta">
          <span class="xv-badge" :class="workStatus.cls">
            <span class="xv-dot" :class="workStatus.dot"></span>{{ workStatus.text }}
          </span>
          <span class="xv-badge">
            <el-icon :size="12"><Clock /></el-icon>
            <span class="xv-num">{{ clockText }}</span>
          </span>
          <span class="xv-badge" :class="taskBadge.cls">
            <span class="xv-dot" :class="taskBadge.dot"></span>{{ taskBadge.text }}
          </span>
        </div>

        <!-- 状态灯 + SDK + 显示模式 -->
        <div class="header-right">
          <div class="lamp-group">
            <span class="lamp" :title="`实时通道：${taskStore.wsConnected ? '已连接' : '断开'}`">
              <span class="xv-dot" :class="taskStore.wsConnected ? 'xv-dot--ok' : 'xv-dot--err'"></span>通道
            </span>
            <span class="lamp" :title="`SDK：${sdkRunning ? '运行中' : '未启动'}`">
              <span class="xv-dot" :class="sdkRunning ? 'xv-dot--ok xv-dot--live' : 'xv-dot--err'"></span>SDK
            </span>
            <span class="lamp" :title="`实时图像：${sdkStore.videoServerRunning ? '可用' : '不可用'}`">
              <span class="xv-dot" :class="sdkStore.videoServerRunning ? 'xv-dot--ok' : 'xv-dot--warn'"></span>图像
            </span>
          </div>

          <!-- SDK / 固件版本 -->
          <div class="ver-group">
            <span class="ver-badge" title="DV SDK 版本">
              <span class="ver-label">SDK</span>
              <span class="ver-value">{{ sdkVersion || '—' }}</span>
            </span>
            <span class="ver-badge" title="设备固件版本">
              <span class="ver-label">固件</span>
              <span class="ver-value">{{ firmwareVersion || '—' }}</span>
            </span>
          </div>

          <div class="sdk-switch">
            <template v-if="sdkBusy">
              <el-icon class="is-loading sdk-spin"><Loading /></el-icon>
              <span class="sdk-label">{{ sdkAction === 'start' ? '启动中…' : '停止中…' }}</span>
            </template>
            <template v-else-if="sdkRunning">
              <el-button size="small" type="danger" plain @click="toggleSdk('stop')">
                <el-icon><VideoPause /></el-icon>停止 SDK
              </el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" @click="toggleSdk('start')">
                <el-icon><VideoPlay /></el-icon>启动 SDK
              </el-button>
            </template>
          </div>

          <!-- 显示模式：暗色 / 高对比 / 洁净室 -->
          <div class="mode-switch" role="group" aria-label="显示模式">
            <button
              v-for="m in MODES"
              :key="m.id"
              type="button"
              class="mode-btn"
              :class="{ 'is-active': displayMode === m.id }"
              :aria-pressed="displayMode === m.id"
              :title="m.tip"
              @click="setMode(m.id)"
            >{{ m.label }}</button>
          </div>
        </div>
      </el-header>

      <!-- ===== 主区域 ===== -->
      <el-main class="app-main">
        <svg class="xv-watermark" aria-hidden="true">
          <defs>
            <pattern id="xv-wm-pattern" width="230" height="150" patternUnits="userSpaceOnUse" patternTransform="rotate(-22)">
              <text x="0" y="18" font-size="13" letter-spacing="6" fill="currentColor">DemoVision</text>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#xv-wm-pattern)" />
        </svg>

        <div class="app-main-inner">
          <router-view />
        </div>

        <!-- 署名（低对比，不抢视线） -->
        <div class="app-sign" aria-hidden="true">DemoVision</div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from './api'
import { applyDisplayMode } from './utils/theme'
import { useSdkStore } from './stores/sdkStore'
import { useTaskStore } from './stores/taskStore'
import { useSlamStore } from './stores/slamStore'
import { useRosMonitorStore } from './stores/rosMonitorStore'

/* ===== 平台名称与工作时段（现场按需改这几行即可） ===== */
const PLATFORM_NAME = 'DemoVision 设备质检平台'
const RAIL_LABEL = 'DemoVision'
const WORK_START = 9   // 工作时段起始（含）
const WORK_END = 18    // 工作时段结束（不含）

const NAV = [
  { path: '/detection', label: '检测工作台', icon: 'Cpu' },
  { path: '/slam', label: 'SLAM 实时大屏', icon: 'Odometer' },
  { path: '/live', label: '实时图像', icon: 'VideoCamera' },
  { path: '/ros-terminal', label: 'ROS 终端', icon: 'SwitchButton' },
  { path: '/imu-calibration', label: 'IMU 校准', icon: 'MagicStick' },
  { path: '/history', label: '历史报告', icon: 'Tickets' },
]

const MODES = [
  { id: 'dash', label: '暗色', tip: '深色精密仪表（默认）' },
  { id: 'contrast', label: '高对比', tip: '强光 / 远距离 / 大屏扫读' },
  { id: 'clean', label: '洁净室', tip: '明亮环境（亮底）' },
]

const taskStore = useTaskStore()
const slamStore = useSlamStore()
const rosMonitorStore = useRosMonitorStore()
const sdkStore = useSdkStore()

/* ===== 显示模式 ===== */
const displayMode = ref(document.documentElement.getAttribute('data-xv-mode') || 'dash')

function setMode(id) {
  // 同步 <html> 属性 + 落 localStorage + 通知图表重绘
  displayMode.value = applyDisplayMode(id)
}

/* ===== 工作时段 / 时钟（每 10 秒刷新） ===== */
const now = ref(new Date())
let clockTimer = null

const workStatus = computed(() => {
  const d = now.value
  const h = d.getHours() + d.getMinutes() / 60
  const p = (n) => String(n).padStart(2, '0')
  const span = `${p(WORK_START)}:00–${p(WORK_END)}:00`
  const inWork = h >= WORK_START && h < WORK_END
  return inWork
    ? { text: `工作时段 ${span}`, cls: 'xv-badge--ok', dot: 'xv-dot--ok xv-dot--live' }
    : { text: `非工作时段 ${span}`, cls: 'xv-badge--warn', dot: 'xv-dot--warn' }
})

const clockText = computed(() => {
  const p = (n) => String(n).padStart(2, '0')
  const d = now.value
  return `${p(d.getHours())}:${p(d.getMinutes())}`
})

const taskBadge = computed(() => {
  if (taskStore.detection.running) return { text: '检测执行中', cls: 'xv-badge--info', dot: 'xv-dot--ok xv-dot--live' }
  if (taskStore.slam.running) return { text: 'SLAM 记录中', cls: 'xv-badge--info', dot: 'xv-dot--ok xv-dot--live' }
  return { text: '空闲', cls: '', dot: '' }
})

/* ===== SDK 启停控制 ===== */
const sdkRunning = ref(false)
const sdkBusy = ref(false)
const sdkAction = ref('')
const sdkVersion = ref('')
const firmwareVersion = ref('')

let sdkPollTimer = null

async function refreshSdkStatus() {
  try {
    const { data } = await api.get('/sdk/status')
    sdkRunning.value = !!data.is_running
    sdkStore.setRunning(sdkRunning.value)
    sdkStore.setVideoServerRunning(!!data.video_server_running)
    if (data.sdk_version) sdkVersion.value = data.sdk_version
    if (data.firmware_version) firmwareVersion.value = data.firmware_version
  } catch (e) {
    // 后端不可达时保持上次状态，不打断轮询
  }
}

async function toggleSdk(action) {
  if (sdkBusy.value) return
  sdkBusy.value = true
  sdkStore.setBusy(true)
  sdkAction.value = action
  try {
    const { data } = await api.post(`/sdk/${action}`)
    if (data.status === 'started' || data.status === 'already_running') {
      sdkRunning.value = true
      sdkStore.setRunning(true)
      ElMessage.success(action === 'start' ? 'SDK 已启动' : 'SDK 已停止')
    } else if (data.status === 'stopped' || data.status === 'not_running') {
      sdkRunning.value = false
      sdkStore.setRunning(false)
    } else if (data.error) {
      ElMessage.error('SDK 操作失败: ' + data.error)
    }
    // 短暂延迟后刷新真实状态（启动 roslaunch / 优雅停止需要时间）
    setTimeout(refreshSdkStatus, action === 'start' ? 3000 : 1500)
  } catch (e) {
    ElMessage.error('SDK 操作失败: ' + (e.message || e))
  } finally {
    sdkBusy.value = false
    sdkStore.setBusy(false)
    sdkAction.value = ''
  }
}

let ws = null
let retryTimer = null

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onopen = () => {
    taskStore.wsConnected = true
    taskStore.ws = ws
  }
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      taskStore.handleWS(msg)
      slamStore.handleWS(msg)
      rosMonitorStore.handleWS(msg)
      // SDK 状态推送（进程意外退出时同步）
      if (msg.type === 'sdk_status') {
        sdkRunning.value = !!msg.is_running
        sdkStore.setRunning(sdkRunning.value)
      }
      // 分发原始消息事件，供 LiveView/RosTerminal 等按需消费（video_frame/echo_data 等）
      window.dispatchEvent(new CustomEvent('ws-message', { detail: msg }))
    } catch (err) {
      // 忽略无法解析的消息
    }
  }
  ws.onclose = () => {
    taskStore.wsConnected = false
    retryTimer = setTimeout(connectWS, 3000)
  }
  ws.onerror = () => {
    ws && ws.close()
  }
}

onMounted(() => {
  connectWS()
  refreshSdkStatus()
  // 每 10 秒轮询一次 SDK 状态（兼容手动启停）
  sdkPollTimer = setInterval(refreshSdkStatus, 10000)
  // 工作时段 / 时钟每 10 秒刷新
  clockTimer = setInterval(() => { now.value = new Date() }, 10000)
})
onBeforeUnmount(() => {
  clearTimeout(retryTimer)
  clearInterval(sdkPollTimer)
  clearInterval(clockTimer)
  if (ws) ws.close()
})
</script>

<style>
/* App 外壳布局：本节为全局样式（其他页面依赖 --xv-* token 与 .xv-* 基础类） */

.app-shell { height: 100%; }

/* ---------- 左侧导轨 ---------- */
.app-aside {
  width: 68px;
  flex: none;
  background: var(--xv-bg);
  border-right: 1px solid var(--xv-border);
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 30;              /* 悬停展开的胶囊需盖住主区 */
  overflow: visible;
  transition: border-color var(--xv-dur) var(--xv-ease);
}

.rail-logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 16px;
  color: var(--xv-primary);
  border-bottom: 1px solid var(--xv-border);
  white-space: nowrap;
  overflow: hidden;
}
.rail-logo-label {
  font-size: 14px;
  font-weight: 800;
  letter-spacing: .16em;
  color: var(--xv-text);
  opacity: 0;
  transition: opacity var(--xv-dur) var(--xv-ease);
}
.app-aside:hover .rail-logo-label { opacity: 1; }

.rail-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
}
.rail-foot {
  padding: 8px 8px 12px;
  border-top: 1px solid var(--xv-border);
}

/* 胶囊：默认 52px（仅图标），导轨悬停时展开显示文字 */
.rail-item {
  display: flex;
  align-items: center;
  gap: 11px;
  height: 40px;
  width: 52px;
  padding: 0 17px;
  border-radius: var(--xv-r);
  color: var(--xv-text-3);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  background: var(--xv-surface);
  transition: width var(--xv-dur) var(--xv-ease),
              background-color var(--xv-dur) var(--xv-ease),
              color var(--xv-dur) var(--xv-ease),
              box-shadow var(--xv-dur) var(--xv-ease);
}
.app-aside:hover .rail-item { width: 186px; }

.rail-item .rail-icon {
  flex: none;
  width: 18px;
  transition: transform var(--xv-dur) var(--xv-ease);
}
.rail-item .rail-label {
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  transition: opacity var(--xv-dur) var(--xv-ease);
}
.app-aside:hover .rail-item .rail-label { opacity: 1; }

.rail-item:hover {
  background: var(--xv-surface-2);
  color: var(--xv-text);
  box-shadow: var(--xv-shadow);
}
.rail-item:hover .rail-icon { transform: translateX(2px); }

.rail-item.is-active {
  background: color-mix(in srgb, var(--xv-primary) 14%, var(--xv-surface));
  color: var(--xv-primary);
  box-shadow: inset 2px 0 0 var(--xv-primary);
}
.rail-item--static { cursor: default; background: transparent; }
.rail-item--static:hover { background: var(--xv-surface); box-shadow: none; }

/* ---------- 顶部状态栏 ---------- */
.app-header {
  height: 56px;
  padding: 0 16px;
  background: var(--xv-surface);
  border-bottom: 1px solid var(--xv-border);
  display: flex;
  align-items: center;
  gap: 16px;
  z-index: 20;
}

.line-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  border-radius: var(--xv-r-sm);
  background: var(--xv-surface-2);
  border: 1px solid var(--xv-border);
  flex: none;
  white-space: nowrap;
}
.line-badge-mark {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--xv-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--xv-primary) 18%, transparent);
  flex: none;
}
.line-badge-name { font-size: 13.5px; font-weight: 700; color: var(--xv-text); letter-spacing: .04em; }

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.header-meta .xv-badge { white-space: nowrap; }
.header-meta .xv-badge .el-icon { margin-right: 1px; }

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: none;
}

.lamp-group { display: flex; align-items: center; gap: 12px; }
.lamp {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--xv-text-3);
  cursor: default;
}
.lamp .xv-dot { width: 7px; height: 7px; }

.ver-group { display: flex; align-items: center; gap: 8px; flex: none; }
.ver-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 9px;
  border-radius: var(--xv-r-sm);
  background: var(--xv-surface-2);
  border: 1px solid var(--xv-border);
  white-space: nowrap;
}
.ver-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--xv-primary);
  letter-spacing: .04em;
}
.ver-value {
  font-family: var(--xv-mono);
  font-size: 12px;
  color: var(--xv-text);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sdk-switch { display: flex; align-items: center; gap: 8px; }
.sdk-spin { color: var(--xv-primary); }
.sdk-label { font-size: 12px; color: var(--xv-text-2); white-space: nowrap; }

/* 显示模式切换（紧凑分段控件） */
.mode-switch {
  display: inline-flex;
  padding: 2px;
  gap: 2px;
  border-radius: var(--xv-r-sm);
  background: var(--xv-surface-2);
  border: 1px solid var(--xv-border);
}
.mode-btn {
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--xv-text-3);
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  height: 24px;
  padding: 0 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color var(--xv-dur) var(--xv-ease),
              color var(--xv-dur) var(--xv-ease);
}
.mode-btn:hover { color: var(--xv-text); background: var(--xv-surface-3); }
.mode-btn.is-active {
  color: var(--xv-on-primary);
  background: var(--xv-primary);
}

/* ---------- 主区域 ---------- */
.app-main {
  position: relative;
  padding: 14px;
  background: var(--xv-bg);
  overflow: auto;
  z-index: 1;
}
.app-main-inner { position: relative; z-index: 2; }

/* 水印：斜向重复，极低对比 */
.xv-watermark {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  color: var(--xv-text);
  opacity: var(--xv-wm-opacity);
}

/* 角落署名 */
.app-sign {
  position: fixed;
  right: 16px;
  bottom: 8px;
  font-family: var(--xv-mono);
  font-size: 12px;
  letter-spacing: .22em;
  color: var(--xv-text);
  opacity: var(--xv-sign-opacity);
  pointer-events: none;
  user-select: none;
  z-index: 10;
}

/* 打印：隐藏外壳装饰与署名，只留内容 */
@media print {
  .app-aside,
  .app-header,
  .xv-watermark,
  .app-sign { display: none !important; }
  .app-main { padding: 0 !important; background: #fff !important; overflow: visible !important; }
  .app-shell { height: auto !important; }
}
</style>
