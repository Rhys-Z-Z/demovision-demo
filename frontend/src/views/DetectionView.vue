<template>
  <div class="detection-view">
    <el-row :gutter="16">
      <!-- 左侧：任务配置 -->
      <el-col :span="8">
        <el-card shadow="never" class="cfg-card">
          <template #header>
            <div class="card-title">
              <el-icon><SetUp /></el-icon>
              <span>检测任务配置</span>
            </div>
          </template>

          <el-form label-position="top">
            <el-form-item label="设备 SN（可多选）">
              <el-select
                v-model="selectedDevices"
                multiple
                filterable
                placeholder="请选择在线设备"
                style="width: 100%"
                :loading="loadingDevices"
              >
                <el-option
                  v-for="d in devices"
                  :key="d"
                  :label="d"
                  :value="d"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="检测模式">
              <el-radio-group v-model="mode">
                <el-radio-button value="仅相机">仅相机</el-radio-button>
                <el-radio-button value="仅ToF">仅ToF</el-radio-button>
                <el-radio-button value="全功能">全功能</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="设备类型">
              <el-select v-model="deviceType" style="width: 100%">
                <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>

            <el-form-item label="各检测项目时长（秒）">
              <div class="time-grid">
                <div class="time-item">
                  <span>Color相机</span>
                  <el-input-number v-model="timeColor" :min="1" :max="3600" controls-position="right" size="small" />
                </div>
                <div class="time-item">
                  <span>Fisheye</span>
                  <el-input-number v-model="timeFisheye" :min="1" :max="3600" controls-position="right" size="small" />
                </div>
                <div class="time-item">
                  <span>SLAM</span>
                  <el-input-number v-model="timeSlam" :min="1" :max="3600" controls-position="right" size="small" />
                </div>
                <div class="time-item">
                  <span>ToF/RGBD</span>
                  <el-input-number v-model="timeTof" :min="1" :max="3600" controls-position="right" size="small" />
                </div>
              </div>
            </el-form-item>

            <el-form-item>
              <div class="btn-row">
                <el-button
                  type="primary"
                  :loading="taskStore.detection.running"
                  :disabled="taskStore.detection.running || !sdkStore.running"
                  @click="onStart"
                >
                  {{ !sdkStore.running ? '请先启动 SDK' : '开始检测' }}
                </el-button>
                <el-button
                  v-if="taskStore.detection.running"
                  type="danger"
                  @click="onStop"
                >
                  <el-icon><SwitchButton /></el-icon>
                  停止检测
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
              {{ taskStore.detection.uuid ? taskStore.detection.uuid.slice(0, 8) : '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag
                :type="taskStore.detection.running ? 'warning' : (taskStore.detection.status === 'finished' ? 'success' : 'info')"
                size="small"
              >
                {{ taskStore.detection.running ? '运行中' : (taskStore.detection.status || '未开始') }}
              </el-tag>
              <el-tag
                v-if="taskStore.detection.overall"
                :type="taskStore.detection.overall === 'PASS' ? 'success' : 'danger'"
                size="small"
                class="ml8"
              >
                结果: {{ taskStore.detection.overall }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- 右侧：实时日志 -->
      <el-col :span="16">
        <el-card shadow="never" class="log-card">
          <template #header>
            <div class="card-title">
              <el-icon><Document /></el-icon>
              <span>检测实时日志</span>
              <el-button
                size="small"
                text
                type="primary"
                class="ml-auto"
                @click="clearLogs"
              >
                清空
              </el-button>
            </div>
          </template>
          <LogTerminal :lines="taskStore.detection.logs" height="560px" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useTaskStore } from '../stores/taskStore'
import { useSdkStore } from '../stores/sdkStore'
import LogTerminal from '../components/LogTerminal.vue'

const taskStore = useTaskStore()
const sdkStore = useSdkStore()

const devices = ref([])
const loadingDevices = ref(false)
const selectedDevices = ref([])
const mode = ref('全功能')
const deviceType = ref('平动')
const deviceTypes = ['平动', '非平动', '测试', '头箍式', '简易式']
// 各检测项目时长（秒）
const timeColor = ref(120)
const timeFisheye = ref(60)
const timeSlam = ref(120)
const timeTof = ref(120)

async function refreshDevices() {
  loadingDevices.value = true
  try {
    const { data } = await api.get('/devices')
    devices.value = data.devices || []
  } catch (e) {
    ElMessage.error('设备扫描失败: ' + (e.message || e))
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
    await taskStore.startDetection({
      devices: selectedDevices.value,
      mode: mode.value,
      device_type: deviceType.value,
      times: {
        color: timeColor.value,
        fisheye: timeFisheye.value,
        slam: timeSlam.value,
        tof: timeTof.value,
      },
    })
    ElMessage.success('检测任务已启动')
  } catch (e) {
    ElMessage.error('启动失败: ' + (e.message || e))
  }
}

async function onStop() {
  if (!taskStore.detection.running) {
    ElMessage.warning('当前没有正在运行的检测任务')
    return
  }
  try {
    await taskStore.stopDetection(taskStore.detection.uuid)
    ElMessage.info('已发送停止指令，正在中断检测...')
  } catch (e) {
    ElMessage.error('停止失败: ' + (e.message || e))
  }
}

function clearLogs() {
  taskStore.detection.logs = []
}

onMounted(refreshDevices)
</script>

<style scoped>
.cfg-card,
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
.btn-row {
  display: flex;
  gap: 12px;
}
.time-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
  width: 100%;
}
.time-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.time-item .el-input-number {
  width: 120px;
}
.task-state {
  margin-top: 4px;
}
.ml8 {
  margin-left: 8px;
}
</style>
