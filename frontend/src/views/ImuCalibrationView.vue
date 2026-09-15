<template>
  <div class="imu-view">
    <el-row :gutter="16">
      <!-- 左：控制区 -->
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>
            <div class="card-title">
              <el-icon><SetUp /></el-icon>
              <span>IMU 陀螺仪校准</span>
            </div>
          </template>

          <el-form label-position="top">
            <el-form-item label="设备 SN">
              <el-select
                v-model="selectedDevice"
                filterable
                placeholder="请选择在线设备"
                style="width: 100%"
                :loading="loadingDevices"
              >
                <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
              </el-select>
              <div v-if="!devices.length" class="usb-tip">
                未检测到 DemoVision vSLAM 设备（Demo 模式自动返回模拟设备，可点击刷新）
              </div>
            </el-form-item>
            <el-form-item label="录制时长（秒）">
              <el-input-number v-model="durationSec" :min="1" :max="120" style="width: 100%" />
            </el-form-item>
            <el-form-item>
              <div class="btn-row">
                <el-button type="primary" size="large" :loading="running" :disabled="running" @click="onStart">
                  ⚡ 开始 IMU 校准
                </el-button>
                <el-button @click="refreshDevices">
                  <el-icon><Refresh /></el-icon>
                  刷新设备
                </el-button>
              </div>
            </el-form-item>
          </el-form>

          <el-descriptions :column="1" size="small" border class="task-state">
            <el-descriptions-item label="当前任务">
              {{ taskUuid ? taskUuid.slice(0, 8) : '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="running ? 'warning' : (result ? (result.status === 'finished' ? 'success' : 'danger') : 'info')" size="small">
                {{ running ? '运行中' : (result ? (result.status === 'finished' ? '完成' : '失败') : '未开始') }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <!-- 校准结果卡片 -->
          <div v-if="result && result.status === 'finished'" class="result-card">
            <div class="result-title">校准结果</div>
            <div class="result-row">
              <span class="result-label">合格性</span>
              <el-tag :type="result.qualified ? 'success' : 'danger'" size="small" effect="dark">
                {{ result.qualified ? '合格' : '不合格' }}
              </el-tag>
            </div>
            <div v-if="summaryValues" class="result-row">
              <span class="result-label">偏置 X / Y / Z</span>
              <span class="result-values">{{ fmtBias(summaryValues.gyro_bias_x) }} / {{ fmtBias(summaryValues.gyro_bias_y) }} / {{ fmtBias(summaryValues.gyro_bias_z) }} (rad/s)</span>
            </div>
            <div class="result-actions">
              <el-button size="small" type="primary" plain :disabled="!result.txt_file_path" @click="openDownload(result.txt_file_path)">
                <el-icon><Document /></el-icon>
                下载 TXT
              </el-button>
              <el-button size="small" type="warning" plain :disabled="!result.bin_file_path" @click="openDownload(result.bin_file_path)">
                <el-icon><Box /></el-icon>
                下载 BIN
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右：日志终端 -->
      <el-col :span="16">
        <el-card shadow="never" class="log-card">
          <template #header>
            <div class="card-title">
              <el-icon><Monitor /></el-icon>
              <span>校准日志（reset → calib → verify）</span>
            </div>
          </template>
          <LogTerminal :lines="logLines" height="520px" :dark="true" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { openDownload } from '../api'
import LogTerminal from '../components/LogTerminal.vue'

const devices = ref([])
const selectedDevice = ref('')
const loadingDevices = ref(false)
const durationSec = ref(5)

const running = ref(false)
const taskUuid = ref('')
const logLines = ref([])
const result = ref(null)

const summaryValues = computed(() => {
  if (!result.value || !result.value.summary_json) return null
  try {
    const obj = JSON.parse(result.value.summary_json)
    if (obj.gyro_bias_x != null || obj.gyro_bias_vec) return obj
    return obj.values || null
  } catch (e) {
    return null
  }
})

function fmtBias(v) {
  return v != null ? Number(v).toFixed(5) : '—'
}

async function refreshDevices() {
  loadingDevices.value = true
  try {
    // 通过 lsusb 检测 DemoVision vSLAM USB 设备，无需启动 ROS/SDK
    const { data } = await api.get('/imu/devices')
    devices.value = data.devices || []
    if (devices.value.length && !selectedDevice.value) {
      selectedDevice.value = devices.value[0]
    }
  } catch (e) {
    ElMessage.error('获取设备列表失败: ' + (e.message || e))
  } finally {
    loadingDevices.value = false
  }
}

async function onStart() {
  if (!devices.value.length) {
    ElMessage.warning('未检测到 DemoVision vSLAM 设备，请先连接 USB')
    return
  }
  running.value = true
  logLines.value = []
  result.value = null
  taskUuid.value = ''
  try {
    const { data } = await api.post('/imu/calibrate', {
      devices: [selectedDevice.value || 'DemoVision-vSLAM-USB'],
      duration: durationSec.value,
    })
    if (data.error) throw new Error(data.error)
    taskUuid.value = data.task_uuid
  } catch (e) {
    running.value = false
    ElMessage.error('启动校准失败: ' + (e.message || e))
  }
}

async function loadStatus() {
  try {
    const { data } = await api.get(`/imu/status/${taskUuid.value}`)
    if (data.error) throw new Error(data.error)
    result.value = data
  } catch (e) {
    ElMessage.error('获取校准状态失败: ' + (e.message || e))
  }
}

function onWSMessage(e) {
  const msg = e.detail
  if (!msg) return
  if (msg.type === 'log_message' && msg.task_uuid && msg.task_uuid === taskUuid.value) {
    logLines.value.push(msg.line || '')
  } else if (msg.type === 'task_finished' && msg.task_uuid === taskUuid.value && msg.kind === 'imu_calib') {
    running.value = false
    loadStatus()
  }
}

onMounted(() => {
  refreshDevices()
  window.addEventListener('ws-message', onWSMessage)
})

onBeforeUnmount(() => {
  window.removeEventListener('ws-message', onWSMessage)
})
</script>

<style scoped>
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.btn-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.usb-tip {
  margin-top: 6px;
  font-size: 12px;
  color: var(--xv-warn);
  line-height: 1.5;
}
.task-state {
  margin-top: 8px;
}
.result-card {
  margin-top: 14px;
  padding: 12px;
  background: var(--xv-surface);
  border: 1px solid var(--xv-border);
  border-radius: 8px;
}
.result-title {
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--xv-text);
}
.result-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  margin-bottom: 8px;
}
.result-label {
  color: var(--xv-text-2);
}
.result-values {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  color: var(--xv-warn);
}
.result-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
</style>
