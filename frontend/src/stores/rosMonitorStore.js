import { defineStore } from 'pinia'

const MAX_POINTS = 500 // Hz 数据点环形缓冲
const FLUSH_MS = 33 // 约 30 FPS

export const useRosMonitorStore = defineStore('rosMonitor', {
  state: () => ({
    hzBuffer: { t: [], rate: [] }, // Hz 实时数据环形缓冲
    currentRate: null, // 最新 Hz 值（数字面板）
    updateFn: null, // 图表批量渲染回调（仅一个页面，单回调即可）
    _timer: null,
  }),

  actions: {
    addHzData(point) {
      const { rate, t } = point
      const buf = this.hzBuffer
      buf.t.push(t)
      buf.rate.push(rate)
      this.currentRate = rate
      if (buf.t.length > MAX_POINTS) {
        const overflow = buf.t.length - MAX_POINTS
        buf.t.splice(0, overflow)
        buf.rate.splice(0, overflow)
      }
    },

    registerChart(fn) {
      this.updateFn = fn
      this._ensureTimer()
    },

    unregisterChart(fn) {
      if (this.updateFn === fn) this.updateFn = null
      if (this._timer) {
        clearInterval(this._timer)
        this._timer = null
      }
    },

    _ensureTimer() {
      if (this._timer) return
      // 30 FPS 批量渲染，绝不在每条 WS 消息时 setOption
      this._timer = setInterval(() => {
        if (!this.updateFn || this.hzBuffer.t.length === 0) return
        this.updateFn({
          t: this.hzBuffer.t.slice(),
          rate: this.hzBuffer.rate.slice(),
        })
      }, FLUSH_MS)
    },

    reset() {
      // 仅清空缓冲与当前值；渲染定时器由 registerChart/unregisterChart 管理生命周期
      this.hzBuffer = { t: [], rate: [] }
      this.currentRate = null
    },

    handleWS(msg) {
      if (msg.type === 'hz_data') {
        this.addHzData(msg)
      }
    },
  },
})
