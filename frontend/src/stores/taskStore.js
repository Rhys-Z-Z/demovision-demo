import { defineStore } from 'pinia'
import api from '../api'

export const useTaskStore = defineStore('task', {
  state: () => ({
    wsConnected: false,
    ws: null, // 全局 WebSocket 实例（App.vue 建立后注入）
    // 检测任务
    detection: {
      uuid: null,
      running: false,
      status: '',
      overall: '',
      logs: [],
    },
    // SLAM 任务
    slam: {
      uuid: null,
      running: false,
      status: '',
      sns: [], // 本次任务涉及的设备 SN（刷新页面后用于恢复大屏曲线）
      logs: [],
    },
  }),

  actions: {
    async startDetection(payload) {
      const { data } = await api.post('/detection/start', payload)
      if (data.error) throw new Error(data.error)
      this.detection.uuid = data.task_uuid
      this.detection.running = true
      this.detection.status = 'running'
      this.detection.logs = []
      this._pushLog('detection', `>>> 检测任务已提交: ${data.task_uuid}`)
      return data
    },

    async stopDetection(uuid) {
      if (!this.detection.running || !uuid) return
      const { data } = await api.post(`/detection/stop/${uuid}`)
      this._pushLog('detection', `>>> 正在停止检测任务 (${data.status})`)
      return data
    },

    async startSlam(payload) {
      const { data } = await api.post('/slam/start', payload)
      if (data.error) throw new Error(data.error)
      this.slam.uuid = data.task_uuid
      this.slam.running = true
      this.slam.status = 'running'
      this.slam.sns = data.devices || payload.devices || []
      this.slam.logs = []
      this._pushLog('slam', `>>> SLAM 记录任务已启动: ${data.task_uuid}`)
      return data
    },

    /** 任务结束后恢复大屏状态用（页面刷新后从 /api/history/slam?status=running 回填） */
    adoptRunningSlam({ uuid, sns }) {
      this.slam.uuid = uuid || this.slam.uuid
      this.slam.running = true
      this.slam.status = 'running'
      this.slam.sns = sns && sns.length ? sns : this.slam.sns
    },

    async stopSlam(uuid) {
      if (!uuid) return
      const { data } = await api.post(`/slam/stop/${uuid}`)
      this.slam.running = false
      this._pushLog('slam', `>>> SLAM 记录已手动停止 (${data.status})`)
      return data
    },

    _pushLog(kind, line) {
      if (kind === 'slam') {
        this.slam.logs.push(line)
      } else {
        this.detection.logs.push(line)
      }
    },

    handleWS(msg) {
      const { type } = msg
      if (type === 'log_message') {
        const line = msg.line || ''
        if (msg.task_uuid && msg.task_uuid === this.slam.uuid) {
          this.slam.logs.push(line)
        } else if (msg.task_uuid && msg.task_uuid === this.detection.uuid) {
          this.detection.logs.push(line)
        } else if (!msg.task_uuid) {
          this.detection.logs.push(line)
        }
        return
      }
      if (type === 'task_finished') {
        if (msg.kind === 'slam' && msg.task_uuid === this.slam.uuid) {
          this.slam.running = false
          this.slam.status = msg.status
          this._pushLog('slam', `>>> SLAM 任务结束: ${msg.status}${msg.error ? ` (${msg.error})` : ''}`)
        } else if (msg.kind === 'detection' && msg.task_uuid === this.detection.uuid) {
          this.detection.running = false
          this.detection.status = msg.status
          this.detection.overall = msg.overall_status || ''
          this._pushLog('detection', `>>> 检测任务结束: ${msg.status}${msg.overall_status ? ` (${msg.overall_status})` : ''}${msg.error ? ` (${msg.error})` : ''}`)
        }
      }
    },
  },
})
