<template>
  <div class="live-view">
    <!-- 图像服务未运行警告（web_video_server 8080） -->
    <el-alert
      v-if="!sdkStore.videoServerRunning"
      type="warning"
      show-icon
      :closable="false"
      class="video-warn"
      title="图像服务未启动，请在右上角启动 SDK"
      description="后端未检测到 web_video_server (8080)。启动 SDK 或自行执行 rosrun web_video_server web_video_server 后，刷新页面即可正常显示图像。"
    />

    <!-- 控制条 -->
    <el-card shadow="never" class="control-card">
      <div class="control-row">
        <el-form inline class="control-form">
          <el-form-item label="图像话题">
            <el-select
              v-model="selectedTopic"
              filterable
              placeholder="选择 ROS 图像话题"
              style="min-width: 380px"
              :loading="loadingTopics"
            >
              <el-option v-for="t in topics" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :disabled="streaming" @click="onStart">
              <el-icon><VideoPlay /></el-icon>
              开始显示
            </el-button>
            <el-button type="danger" plain :disabled="!streaming" @click="onStop">
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
            <el-button type="success" plain :disabled="!streaming || snapping" :loading="snapping" @click="onSnapshot">
              <el-icon><Camera /></el-icon>
              截图
            </el-button>
            <el-button @click="refreshTopics">
              <el-icon><Refresh /></el-icon>
              刷新话题
            </el-button>
          </el-form-item>
        </el-form>
        <el-tag v-if="streaming" type="success" effect="dark" size="large">● 实时图像（≤30 FPS）</el-tag>
      </div>
    </el-card>

    <!-- 视频主区 -->
    <el-card shadow="never" class="video-card">
      <div ref="videoContainer" class="video-container">
        <canvas ref="videoCanvas"></canvas>
        <div v-if="!streaming" class="video-placeholder">
          选择图像话题后点击「开始显示」，此处将以 MJPEG 代理实时渲染图像
        </div>
        <div v-else-if="!hasFrame" class="video-placeholder">
          等待视频帧...
        </div>

        <!-- 最近截图缩略图（inline 预览，非下载） -->
        <div v-if="shotPreview" class="shot-thumb">
          <img
            :src="`/api/snapshots/${shotPreview.id}/file?t=${shotPreview.ts}`"
            :alt="shotPreview.name"
            title="点击在新标签查看原图"
            @click="openShotPreview()"
          />
          <span class="shot-thumb-name">{{ shotPreview.name }}</span>
          <el-icon class="shot-thumb-close" @click.stop="shotPreview = null"><Close /></el-icon>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useTaskStore } from '../stores/taskStore'
import { useSdkStore } from '../stores/sdkStore'

const taskStore = useTaskStore()
const sdkStore = useSdkStore()

const topics = ref([])
const loadingTopics = ref(false)
const selectedTopic = ref('')
const streaming = ref(false)
const hasFrame = ref(false)
const snapping = ref(false)
const shotPreview = ref(null)   // {id,name,ts}：最近一次截图的内嵌缩略图

const videoContainer = ref(null)
const videoCanvas = ref(null)
let latestFrame = null // 只保留最新帧（丢帧策略）
let rafId = null

async function refreshTopics() {
  loadingTopics.value = true
  try {
    const { data } = await api.get('/image_topics')
    topics.value = data.topics || []
    if (!selectedTopic.value && topics.value.length) {
      selectedTopic.value = topics.value[0]
    }
  } catch (e) {
    ElMessage.warning('获取图像话题失败（ROS 未就绪？）')
  } finally {
    loadingTopics.value = false
  }
}

function sendWS(msg) {
  const ws = taskStore.ws
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
  }
}

function onStart() {
  if (!selectedTopic.value) {
    ElMessage.warning('请先选择图像话题')
    return
  }
  sendWS({ type: 'start_video_stream', topic: selectedTopic.value })
  streaming.value = true
  hasFrame.value = false
  latestFrame = null
  startRenderLoop()
}

function onStop() {
  sendWS({ type: 'stop_video_stream' })
  streaming.value = false
  stopRenderLoop()
  clearCanvas()
}

function parseSnFromTopic(topic) {
  // topic 形如 /dv_sdk/{sn}/.../image → 取第二段；无则空串（后端兜底 _unknown/picture）
  if (topic && topic.startsWith('/dv_sdk/')) {
    const parts = topic.split('/')
    if (parts.length >= 3 && parts[2]) return parts[2]
  }
  return ''
}

async function onSnapshot() {
  if (!selectedTopic.value) {
    ElMessage.warning('请先选择图像话题')
    return
  }
  snapping.value = true
  try {
    const { data } = await api.post('/snapshot', {
      sn: parseSnFromTopic(selectedTopic.value),
      topic: selectedTopic.value,
    })
    ElMessage.success(`已保存 ${data.filename}`)
    // 内嵌缩略图预览（走 inline 原图接口，非下载）
    shotPreview.value = { id: data.id, name: data.filename, ts: Date.now() }
  } catch (e) {
    const msg = e.response?.data?.detail || '截图失败'
    ElMessage.error(msg)
  } finally {
    snapping.value = false
  }
}

// 点击缩略图 → 新标签内嵌预览（后端走 inline disposition，非下载）
function openShotPreview() {
  if (shotPreview.value) {
    window.open(`/api/snapshots/${shotPreview.value.id}/file`, '_blank')
  }
}

// ---------- Canvas 渲染 ----------
function resizeCanvas() {
  const c = videoCanvas.value
  const box = videoContainer.value
  if (!c || !box) return
  const rect = box.getBoundingClientRect()
  const dpr = window.devicePixelRatio || 1
  c.width = Math.max(1, Math.round(rect.width * dpr))
  c.height = Math.max(1, Math.round(rect.height * dpr))
}

function startRenderLoop() {
  stopRenderLoop()
  const tick = () => {
    if (!streaming.value) return
    drawLatest()
    rafId = requestAnimationFrame(tick)
  }
  rafId = requestAnimationFrame(tick)
}

function stopRenderLoop() {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function drawLatest() {
  const c = videoCanvas.value
  if (!latestFrame || !c) return
  const img = new Image()
  img.onload = () => {
    if (!streaming.value) return
    const ctx = c.getContext('2d')
    // 等比缩放（contain 模式），居中绘制，避免变形
    const scale = Math.min(c.width / img.width, c.height / img.height)
    const dw = img.width * scale
    const dh = img.height * scale
    const dx = (c.width - dw) / 2
    const dy = (c.height - dh) / 2
    ctx.drawImage(img, dx, dy, dw, dh)
    hasFrame.value = true
  }
  img.src = 'data:image/jpeg;base64,' + latestFrame
  latestFrame = null // 丢帧策略：只渲染最新帧
}

function clearCanvas() {
  const c = videoCanvas.value
  if (c) {
    const ctx = c.getContext('2d')
    ctx.clearRect(0, 0, c.width, c.height)
  }
}

function onWindowMessage(e) {
  const msg = e.detail
  if (!msg) return
  if (msg.type === 'video_frame' && streaming.value) {
    // 仅接收当前所选话题的帧
    if (msg.topic && selectedTopic.value && msg.topic !== selectedTopic.value) return
    latestFrame = msg.data
  }
}

onMounted(() => {
  refreshTopics()
  resizeCanvas()
  window.addEventListener('resize', resizeCanvas)
  window.addEventListener('ws-message', onWindowMessage)
})

onBeforeUnmount(() => {
  sendWS({ type: 'stop_video_stream' })
  streaming.value = false
  stopRenderLoop()
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('ws-message', onWindowMessage)
})
</script>

<style scoped>
.video-warn {
  margin-bottom: 16px;
}
.control-card {
  border-radius: 8px;
  margin-bottom: 16px;
}
.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.control-form {
  margin: 0;
}
.video-card {
  border-radius: 8px;
}
.video-card :deep(.el-card__body) {
  padding: 0;
}
.video-container {
  position: relative;
  height: calc(100vh - 220px);
  min-height: 420px;
  background: var(--dv-surface);
}
.video-container canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.video-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--dv-text-2);
  font-size: 14px;
}
.shot-thumb {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  width: 220px;
  background: color-mix(in srgb, var(--dv-surface) 92%, transparent);
  border: 1px solid var(--dv-border-2);
  border-radius: 6px;
  padding: 6px;
}
.shot-thumb img {
  width: 100%;
  height: 132px;
  object-fit: contain;
  background: #000;
  border-radius: 4px;
  cursor: pointer;
}
.shot-thumb-name {
  margin-top: 4px;
  font-size: 12px;
  color: var(--dv-text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.shot-thumb-close {
  position: absolute;
  top: 6px;
  right: 6px;
  cursor: pointer;
  /* 关闭按钮压在缩略图（黑底）上，三种模式下都保持白字黑底 */
  color: #fff;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 50%;
  font-size: 14px;
}
</style>
