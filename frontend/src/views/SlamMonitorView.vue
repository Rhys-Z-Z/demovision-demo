<template>
  <div class="slam-view">
    <!-- 控制条 -->
    <el-card shadow="never" class="control-card">
      <div class="control-row">
        <el-form inline class="control-form">
          <el-form-item label="设备 SN">
            <el-select
              v-model="selectedDevices"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="自动发现或手动输入"
              style="min-width: 320px"
              :loading="loadingDevices"
            >
              <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
            </el-select>
          </el-form-item>
          <el-form-item label="录制时长(秒)">
            <el-input-number v-model="duration" :min="10" :max="3600" :step="10" />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              :loading="taskStore.slam.running"
              :disabled="taskStore.slam.running || !sdkStore.running"
              @click="onStart"
            >
              <el-icon><VideoPlay /></el-icon>
              {{ !sdkStore.running ? '请先启动 SDK' : '开始记录' }}
            </el-button>
            <el-button
              type="danger"
              plain
              :disabled="!taskStore.slam.running"
              @click="onStop"
            >
              <el-icon><VideoPause /></el-icon>
              停止记录
            </el-button>
            <el-button @click="refreshDevices">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-form-item>
        </el-form>
        <el-tag v-if="taskStore.slam.running" type="warning" effect="dark" size="large">
          ● 记录中 {{ taskStore.slam.uuid ? taskStore.slam.uuid.slice(0, 8) : '' }}
        </el-tag>
      </div>
    </el-card>

    <!-- 实时大屏 -->
    <div v-if="activeSns.length" class="screen-grid">
      <MultiChart
        v-for="sn in activeSns"
        :key="sn"
        :sn="sn"
        class="screen-item"
      />
    </div>
    <el-empty
      v-else
      description="暂无实时曲线：开始 SLAM 记录后此处展示每个设备的实时曲线（30 FPS 渲染）；若任务已在运行，5 秒内会自动接管"
    />

    <!-- 日志 -->
    <el-card shadow="never" class="log-card">
      <template #header>
        <div class="card-title">
          <el-icon><Document /></el-icon>
          <span>SLAM 任务日志</span>
          <el-button size="small" text type="primary" class="ml-auto" @click="clearLogs">
            清空
          </el-button>
        </div>
      </template>
      <LogTerminal :lines="taskStore.slam.logs" height="220px" />
    </el-card>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useTaskStore } from '../stores/taskStore'
import { useSlamStore } from '../stores/slamStore'
import { useSdkStore } from '../stores/sdkStore'
import LogTerminal from '../components/LogTerminal.vue'
import MultiChart from '../components/MultiChart.vue'

const taskStore = useTaskStore()
const sdkStore = useSdkStore()
const slamStore = useSlamStore()

const devices = ref([])
const loadingDevices = ref(false)
const selectedDevices = ref([])
const duration = ref(120)
const activeSns = ref([])
let watchTimer = null

async function refreshDevices() {
  loadingDevices.value = true
  try {
    const { data } = await api.get('/devices')
    devices.value = data.devices || []
  } catch (e) {
    // 无 ROS 环境时静默
  } finally {
    loadingDevices.value = false
  }
}

async function onStart() {
  if (!sdkStore.running) {
    ElMessage.warning('请先在右上角启动 SDK')
    return
  }
  if (!selectedDevices.value.length) {
    ElMessage.warning('请至少选择一个设备')
    return
  }
  try {
    const data = await taskStore.startSlam({
      devices: selectedDevices.value,
      duration: duration.value,
    })
    // 新一次录制：清掉上一次的曲线数据。
    // ROS pose 时间戳基准（设备 uptime）每次会话都可能不同，残留旧点会把横轴撑爆 → 曲线变竖线。
    slamStore.clearBuffers()
    // 渲染大屏
    activeSns.value = data.devices || selectedDevices.value.slice()
    // 轨道 B：确保订阅（后端已订阅，此处兜底）
    activeSns.value.forEach((sn) => sendWS({ type: 'subscribe_slam', sn }))
    ElMessage.success('SLAM 记录已启动')
  } catch (e) {
    ElMessage.error('启动失败: ' + (e.message || e))
  }
}

async function onStop() {
  if (!taskStore.slam.uuid) return
  try {
    await taskStore.stopSlam(taskStore.slam.uuid)
    ElMessage.success('已停止，统计已落盘')
  } catch (e) {
    ElMessage.error('停止失败: ' + (e.message || e))
  }
}

function sendWS(msg) {
  const ws = taskStore.ws
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
  }
}

function clearLogs() {
  taskStore.slam.logs = []
}

/**
 * 恢复大屏曲线（🔴 修「任务在跑但曲线永不出现」的根因）。
 *
 * `activeSns` 是本组件的本地 ref，只在点「开始记录」时被赋值；一旦刷新页面
 * 或离开大屏再回来，组件重建 → activeSns 变回 []，于是**哪怕任务正在跑、
 * slam_data 正在推，大屏也永远只剩空状态，且界面没有任何办法让它恢复**。
 *
 * 这里在挂载时（以及大屏为空时定期）回填：
 *   1. 优先用 Pinia 里本次会话记住的 SN；
 *   2. 再用后端「运行中的 SLAM 任务」补（覆盖 F5、在别的标签页启动的情况）；
 * 并补发 subscribe_slam（后端订阅是持久的，此处是幂等兜底）。
 * slamStore 一直在缓冲所有 SN 的数据，所以恢复后曲线会立刻带着近 10 秒历史出现。
 */
async function restoreRunning() {
  try {
    let uuid = taskStore.slam.uuid
    let sns = (taskStore.slam.sns || []).slice()

    const { data } = await api.get('/history/slam', {
      params: { status: 'running', page: 1, size: 20 },
    })
    const items = (data && data.items) || []
    if (items.length) {
      const liveSns = [...new Set(items.map((it) => it.sn).filter(Boolean))]
      if (liveSns.length) {
        sns = liveSns
        uuid = items[0].task_uuid || uuid
        taskStore.adoptRunningSlam({ uuid, sns })
      }
    }
    if (sns.length && sns.join(',') !== activeSns.value.join(',')) {
      activeSns.value = sns
      sns.forEach((sn) => sendWS({ type: 'subscribe_slam', sn }))
    }
  } catch (e) {
    // 无 ROS 环境 / 后端未就绪时静默
  }
}

onMounted(() => {
  refreshDevices()
  restoreRunning()
  // 兜底：大屏为空时每 5 秒探一次，覆盖“任务在别的页面或标签页启动”的情况
  watchTimer = setInterval(() => {
    if (!activeSns.value.length) restoreRunning()
  }, 5000)
})

onBeforeUnmount(() => {
  if (watchTimer) { clearInterval(watchTimer); watchTimer = null }
})
</script>

<style scoped>
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
.screen-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.screen-item {
  height: 300px;
}
.log-card {
  border-radius: 8px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.ml-auto {
  margin-left: auto;
}
</style>
