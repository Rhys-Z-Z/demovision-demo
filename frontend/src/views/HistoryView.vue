<template>
  <div class="history-view">
    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- 检测历史 -->
        <el-tab-pane label="检测历史" name="detection">
          <div class="filter-bar">
            <el-date-picker
              v-model="detFilter.dates"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              value-format="YYYY-MM-DD"
              size="small"
              style="width: 260px"
            />
            <el-select v-model="detFilter.quick" size="small" placeholder="快捷" style="width: 110px" @change="applyQuick(detFilter)">
              <el-option label="今天" value="today" />
              <el-option label="近7天" value="7d" />
              <el-option label="近30天" value="30d" />
            </el-select>
            <el-input v-model="detFilter.sn" placeholder="SN" clearable size="small" style="width: 160px" />
            <el-select v-model="detFilter.status" placeholder="状态" clearable size="small" style="width: 110px">
              <el-option label="完成" value="finished" />
              <el-option label="运行中" value="running" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-button type="primary" size="small" @click="loadDetection(1)">查询</el-button>
            <el-button size="small" @click="resetFilter(detFilter)">重置</el-button>
          </div>
          <el-table :data="detectionItems" stripe v-loading="detectionLoading">
            <el-table-column prop="start_time" label="开始时间" width="170" />
            <el-table-column prop="device_type" label="设备类型" width="90" />
            <el-table-column prop="test_mode" label="模式" width="90" />
            <el-table-column prop="devices_sn" label="设备 SN" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'finished' ? 'success' : row.status === 'running' ? 'warning' : 'danger'" size="small">
                  {{ row.status === 'finished' ? '完成' : row.status === 'running' ? '运行中' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.overall_status" :type="row.overall_status === 'PASS' ? 'success' : 'danger'" size="small" effect="dark">
                  {{ row.overall_status }}
                </el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="showDetail('detection', row)">详情</el-button>
                <el-button size="small" text type="primary" @click="downloadZip('detection', row)">下载zip</el-button>
                <el-button size="small" text type="primary" @click="openPrint('detection', row)">打印</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="detectionTotal"
              :page-size="pageSize" :current-page="detectionPage" @current-change="(p) => loadDetection(p)" />
          </div>
        </el-tab-pane>

        <!-- SLAM 历史 -->
        <el-tab-pane label="SLAM 历史" name="slam">
          <div class="filter-bar">
            <el-date-picker v-model="slamFilter.dates" type="daterange" range-separator="至"
              start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" size="small" style="width: 260px" />
            <el-select v-model="slamFilter.quick" size="small" placeholder="快捷" style="width: 110px" @change="applyQuick(slamFilter)">
              <el-option label="今天" value="today" />
              <el-option label="近7天" value="7d" />
              <el-option label="近30天" value="30d" />
            </el-select>
            <el-input v-model="slamFilter.sn" placeholder="SN" clearable size="small" style="width: 160px" />
            <el-select v-model="slamFilter.status" placeholder="状态" clearable size="small" style="width: 110px">
              <el-option label="完成" value="finished" />
              <el-option label="运行中" value="running" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-select v-model="slamFilter.qualified" placeholder="合格性" clearable size="small" style="width: 110px">
              <el-option label="合格" value="true" />
              <el-option label="不合格" value="false" />
            </el-select>
            <el-button type="primary" size="small" @click="loadSlam(1)">查询</el-button>
            <el-button size="small" @click="resetFilter(slamFilter)">重置</el-button>
          </div>
          <el-table :data="slamItems" stripe v-loading="slamLoading">
            <el-table-column prop="start_time" label="开始时间" width="170" />
            <el-table-column prop="sn" label="设备 SN" min-width="160" show-overflow-tooltip />
            <el-table-column label="时长(秒)" width="90"><template #default="{ row }">{{ row.duration_sec }}</template></el-table-column>
            <el-table-column label="均值(mm)" width="90"><template #default="{ row }">{{ row.mean_dist_mm != null ? row.mean_dist_mm.toFixed(2) : '—' }}</template></el-table-column>
            <el-table-column label="标准差(mm)" width="100"><template #default="{ row }">{{ row.std_dist_mm != null ? row.std_dist_mm.toFixed(2) : '—' }}</template></el-table-column>
            <el-table-column label="合格性" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.is_qualified != null" :type="row.is_qualified ? 'success' : 'danger'" size="small" effect="dark">
                  {{ row.is_qualified ? '合格' : '不合格' }}
                </el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'finished' ? 'success' : row.status === 'running' ? 'warning' : 'danger'" size="small">
                  {{ row.status === 'finished' ? '完成' : row.status === 'running' ? '运行中' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="showDetail('slam', row)">详情</el-button>
                <el-button size="small" text type="primary" @click="downloadZip('slam', row)">下载zip</el-button>
                <el-button size="small" text type="primary" @click="openPrint('slam', row)">打印</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="slamTotal"
              :page-size="pageSize" :current-page="slamPage" @current-change="(p) => loadSlam(p)" />
          </div>
        </el-tab-pane>

        <!-- IMU 校准历史 -->
        <el-tab-pane label="IMU 校准历史" name="imu">
          <div class="filter-bar">
            <el-date-picker v-model="imuFilter.dates" type="daterange" range-separator="至"
              start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" size="small" style="width: 260px" />
            <el-select v-model="imuFilter.quick" size="small" placeholder="快捷" style="width: 110px" @change="applyQuick(imuFilter)">
              <el-option label="今天" value="today" />
              <el-option label="近7天" value="7d" />
              <el-option label="近30天" value="30d" />
            </el-select>
            <el-input v-model="imuFilter.sn" placeholder="SN" clearable size="small" style="width: 160px" />
            <el-select v-model="imuFilter.status" placeholder="状态" clearable size="small" style="width: 110px">
              <el-option label="完成" value="finished" />
              <el-option label="运行中" value="running" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-select v-model="imuFilter.qualified" placeholder="合格性" clearable size="small" style="width: 110px">
              <el-option label="合格" value="true" />
              <el-option label="不合格" value="false" />
            </el-select>
            <el-button type="primary" size="small" @click="loadImu(1)">查询</el-button>
            <el-button size="small" @click="resetFilter(imuFilter)">重置</el-button>
          </div>
          <el-table :data="imuItems" stripe v-loading="imuLoading">
            <el-table-column prop="start_time" label="开始时间" width="170" />
            <el-table-column prop="sn" label="设备 SN" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'finished' ? 'success' : row.status === 'running' ? 'warning' : 'danger'" size="small">
                  {{ row.status === 'finished' ? '完成' : row.status === 'running' ? '运行中' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="是否合格" width="90">
              <template #default="{ row }">
                <el-tag v-if="row.qualified != null" :type="row.qualified ? 'success' : 'danger'" size="small" effect="dark">
                  {{ row.qualified ? '合格' : '不合格' }}
                </el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="showDetail('imu', row)">详情</el-button>
                <el-button size="small" text type="primary" @click="downloadZip('imu', row)">下载zip</el-button>
                <el-button size="small" text type="primary" @click="openPrint('imu', row)">打印</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="imuTotal"
              :page-size="pageSize" :current-page="imuPage" @current-change="(p) => loadImu(p)" />
          </div>
        </el-tab-pane>

        <!-- 操作记录 -->
        <el-tab-pane label="操作记录" name="operations">
          <div class="filter-bar">
            <el-date-picker v-model="opFilter.dates" type="daterange" range-separator="至"
              start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" size="small" style="width: 260px" />
            <el-input v-model="opFilter.action" placeholder="操作类型" clearable size="small" style="width: 160px" />
            <el-select v-model="opFilter.kind" placeholder="类型" clearable size="small" style="width: 110px">
              <el-option label="检测" value="detection" />
              <el-option label="SLAM" value="slam" />
              <el-option label="IMU" value="imu_calib" />
              <el-option label="系统" value="system" />
            </el-select>
            <el-button type="primary" size="small" @click="loadOps(1)">查询</el-button>
            <el-button size="small" @click="resetFilter(opFilter)">重置</el-button>
            <el-button size="small" type="warning" plain @click="exportOps">导出 CSV</el-button>
          </div>
          <el-table :data="opItems" stripe v-loading="opLoading">
            <el-table-column prop="ts" label="时间" width="180" />
            <el-table-column prop="action" label="操作" width="140" />
            <el-table-column prop="kind" label="类型" width="100" />
            <el-table-column prop="sn" label="SN" min-width="150" show-overflow-tooltip />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.result === 'ok' ? 'success' : 'danger'" size="small">{{ row.result }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="opTotal"
              :page-size="pageSize" :current-page="opPage" @current-change="(p) => loadOps(p)" />
          </div>
        </el-tab-pane>

        <!-- 截图历史 -->
        <el-tab-pane label="截图" name="snapshots">
          <div class="filter-bar">
            <el-date-picker v-model="shotFilter.dates" type="daterange" range-separator="至"
              start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" size="small" style="width: 260px" />
            <el-select v-model="shotFilter.quick" size="small" placeholder="快捷" style="width: 110px" @change="applyQuick(shotFilter)">
              <el-option label="今天" value="today" />
              <el-option label="近7天" value="7d" />
              <el-option label="近30天" value="30d" />
            </el-select>
            <el-input v-model="shotFilter.sn" placeholder="SN" clearable size="small" style="width: 160px" />
            <el-button type="primary" size="small" @click="loadShots(1)">查询</el-button>
            <el-button size="small" @click="resetFilter(shotFilter)">重置</el-button>
          </div>
          <el-table :data="shotItems" stripe v-loading="shotLoading">
            <el-table-column prop="ts" label="时间" width="170" />
            <el-table-column prop="sn" label="设备 SN" min-width="160" show-overflow-tooltip />
            <el-table-column prop="topic" label="话题" min-width="220" show-overflow-tooltip />
            <el-table-column prop="filename" label="文件名" min-width="180" show-overflow-tooltip />
            <el-table-column label="大小" width="100">
              <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="previewShot(row)">预览</el-button>
                <el-button size="small" text type="primary" @click="downloadShot(row)">下载</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pager">
            <el-pagination layout="total, prev, pager, next" :total="shotTotal"
              :page-size="pageSize" :current-page="shotPage" @current-change="(p) => loadShots(p)" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 详情抽屉：字段 + 产物清单 + 单文件下载 -->
    <el-drawer v-model="detailVisible" :title="`任务详情 · ${detailKind}`" size="45%">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="UUID">{{ detailTask?.task_uuid || '—' }}</el-descriptions-item>
        <el-descriptions-item label="SN">{{ detailTask?.sn || detailTask?.devices_sn || '—' }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ detailTask?.start_time || '—' }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ detailTask?.end_time || '—' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(detailTask?.status) }}</el-descriptions-item>
        <el-descriptions-item label="结果">{{ detailResult }}</el-descriptions-item>
        <el-descriptions-item label="相对路径" :span="2">{{ detailTask?.rel_path || '—' }}</el-descriptions-item>
      </el-descriptions>
      <!-- SLAM：轨迹曲线直接在网页内渲染（不依赖任何图片产物） -->
      <template v-if="detailKind === 'slam' && detailTask?.task_uuid">
        <h4 style="margin: 16px 0 8px">轨迹曲线（网页内渲染）</h4>
        <SlamTrajectoryChart :task-uuid="detailTask.task_uuid" height="300px" />
      </template>
      <h4 style="margin: 16px 0 8px">产物清单</h4>
      <el-table :data="detailArtifacts" size="small" stripe max-height="420">
        <el-table-column prop="name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.big" type="danger" size="small">大文件</el-tag>
            <span v-else>{{ row.size != null ? fmtSize(row.size) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.type !== 'dir'" size="small" text type="primary" @click="downloadFile(detailKind, detailTask.task_uuid, row.name)">下载</el-button>
            <el-tooltip v-else content="目录请用下方「下载整目录 zip」获取" placement="top">
              <span class="dir-hint">目录</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" @click="downloadZip(detailKind, detailTask)">下载整目录 zip</el-button>
        <el-button @click="openPrint(detailKind, detailTask)">打印</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import api, { downloadBlob } from '../api'
import SlamTrajectoryChart from '../components/SlamTrajectoryChart.vue'

const router = useRouter()
const activeTab = ref('detection')
const pageSize = 20

const detailVisible = ref(false)
const detailKind = ref('')
const detailTask = ref(null)
const detailArtifacts = ref([])

function fmtSize(n) {
  if (n == null) return '—'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

function statusLabel(s) {
  return { finished: '完成', running: '运行中', failed: '失败' }[s] || s || '—'
}

const detailResult = computed(() => {
  const t = detailTask.value
  if (!t) return '—'
  if (detailKind.value === 'slam') return t.is_qualified == null ? '—' : (t.is_qualified ? '合格' : '不合格')
  if (detailKind.value === 'imu') return t.qualified == null ? '—' : (t.qualified ? '合格' : '不合格')
  return t.overall_status || '—'
})

// ---- 通用筛选辅助 ----
function todayRange() {
  const d = new Date()
  const fmt = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
  return [fmt(d), fmt(d)]
}
function daysAgoRange(n) {
  const end = new Date()
  const start = new Date(end.getTime() - (n - 1) * 86400000)
  const fmt = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
  return [fmt(start), fmt(end)]
}
function applyQuick(filter) {
  const q = filter.quick
  if (q === 'today') filter.dates = todayRange()
  else if (q === '7d') filter.dates = daysAgoRange(7)
  else if (q === '30d') filter.dates = daysAgoRange(30)
  filter.quick = ''
}
function resetFilter(filter) {
  Object.keys(filter).forEach((k) => (filter[k] = ''))
  filter.dates = null
  filter.quick = ''
}

// ---- 各 tab 数据 ----
const detectionItems = ref([]); const detectionTotal = ref(0); const detectionPage = ref(1); const detectionLoading = ref(false)
const slamItems = ref([]); const slamTotal = ref(0); const slamPage = ref(1); const slamLoading = ref(false)
const imuItems = ref([]); const imuTotal = ref(0); const imuPage = ref(1); const imuLoading = ref(false)
const opItems = ref([]); const opTotal = ref(0); const opPage = ref(1); const opLoading = ref(false)
const shotItems = ref([]); const shotTotal = ref(0); const shotPage = ref(1); const shotLoading = ref(false)

const detFilter = ref({ dates: null, quick: '', sn: '', status: '' })
const slamFilter = ref({ dates: null, quick: '', sn: '', status: '', qualified: '' })
const imuFilter = ref({ dates: null, quick: '', sn: '', status: '', qualified: '' })
const opFilter = ref({ dates: null, action: '', kind: '' })
const shotFilter = ref({ dates: null, quick: '', sn: '' })

function buildParams(filter) {
  const p = {}
  if (filter.dates && filter.dates.length === 2) {
    p.date_from = filter.dates[0]
    p.date_to = filter.dates[1]
  }
  if (filter.sn) p.sn = filter.sn
  if (filter.status) p.status = filter.status
  if (filter.qualified) p.qualified = filter.qualified
  return p
}

async function loadDetection(page = 1) {
  detectionLoading.value = true; detectionPage.value = page
  try {
    const { data } = await api.get('/history/detection', { params: { page, size: pageSize, ...buildParams(detFilter.value) } })
    detectionItems.value = data.items || []; detectionTotal.value = data.total || 0
  } catch (e) { ElMessage.error('加载检测历史失败: ' + (e.message || e)) }
  finally { detectionLoading.value = false }
}
async function loadSlam(page = 1) {
  slamLoading.value = true; slamPage.value = page
  try {
    const { data } = await api.get('/history/slam', { params: { page, size: pageSize, ...buildParams(slamFilter.value) } })
    slamItems.value = data.items || []; slamTotal.value = data.total || 0
  } catch (e) { ElMessage.error('加载 SLAM 历史失败: ' + (e.message || e)) }
  finally { slamLoading.value = false }
}
async function loadImu(page = 1) {
  imuLoading.value = true; imuPage.value = page
  try {
    const { data } = await api.get('/history/imu', { params: { page, size: pageSize, ...buildParams(imuFilter.value) } })
    imuItems.value = data.items || []; imuTotal.value = data.total || 0
  } catch (e) { ElMessage.error('加载 IMU 历史失败: ' + (e.message || e)) }
  finally { imuLoading.value = false }
}
async function loadOps(page = 1) {
  opLoading.value = true; opPage.value = page
  try {
    const params = { page, size: pageSize }
    if (opFilter.value.dates && opFilter.value.dates.length === 2) {
      params.date_from = opFilter.value.dates[0]; params.date_to = opFilter.value.dates[1]
    }
    if (opFilter.value.action) params.action = opFilter.value.action
    if (opFilter.value.kind) params.kind = opFilter.value.kind
    const { data } = await api.get('/operations', { params })
    opItems.value = data.items || []; opTotal.value = data.total || 0
  } catch (e) { ElMessage.error('加载操作记录失败: ' + (e.message || e)) }
  finally { opLoading.value = false }
}

// ---- 截图历史 ----
async function loadShots(page = 1) {
  shotLoading.value = true; shotPage.value = page
  try {
    const { data } = await api.get('/snapshots', { params: { page, size: pageSize, ...buildParams(shotFilter.value) } })
    shotItems.value = data.items || []; shotTotal.value = data.total || 0
  } catch (e) { ElMessage.error('加载截图历史失败: ' + (e.message || e)) }
  finally { shotLoading.value = false }
}

function previewShot(row) {
  if (row.id != null) window.open(`/api/snapshots/${row.id}/file`, '_blank')
}

async function downloadShot(row) {
  try {
    await downloadBlob(`/snapshots/${row.id}/file`, row.filename || `snapshot_${row.id}.jpg`)
    ElMessage.success(`已下载 ${row.filename || row.id}`)
  } catch (e) {
    ElMessage.error('下载截图失败: ' + (e.message || e))
  }
}

// ---- 详情 / 下载 / 打印 ----
async function showDetail(kind, row) {
  detailKind.value = kind; detailTask.value = row; detailArtifacts.value = []
  detailVisible.value = true
  try {
    const { data } = await api.get(`/history/${kind}/${row.task_uuid}`)
    detailTask.value = data.task || row
    detailArtifacts.value = data.artifacts || []
  } catch (e) {
    ElMessage.error('加载详情失败: ' + (e.message || e))
  }
}

async function downloadZip(kind, row) {
  try {
    await downloadBlob(`/history/${kind}/${row.task_uuid}/download`, `${kind}_${row.task_uuid.slice(0, 8)}.zip`)
    ElMessage.success('已开始下载 zip')
  } catch (e) {
    ElMessage.error('下载 zip 失败: ' + (e.message || e))
  }
}

async function downloadFile(kind, uuid, name) {
  try {
    await downloadBlob(`/history/${kind}/${uuid}/files/${encodeURIComponent(name)}`, name)
  } catch (e) {
    ElMessage.error('下载文件失败: ' + (e.message || e))
  }
}

function openPrint(kind, row) {
  router.push(`/print/${kind}/${row.task_uuid}`)
}

async function exportOps() {
  try {
    const params = {}
    if (opFilter.value.dates && opFilter.value.dates.length === 2) {
      params.date_from = opFilter.value.dates[0]; params.date_to = opFilter.value.dates[1]
    }
    if (opFilter.value.action) params.action = opFilter.value.action
    if (opFilter.value.kind) params.kind = opFilter.value.kind
    await downloadBlob(`/operations/export?${new URLSearchParams(params).toString()}`, 'operation_logs.csv')
    ElMessage.success('已导出 CSV')
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.message || e))
  }
}

onMounted(() => {
  loadDetection(); loadSlam(); loadImu(); loadOps(); loadShots()
})
</script>

<style scoped>
.pager { margin-top: 14px; display: flex; justify-content: flex-end; }
.filter-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.dir-hint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
