import { defineStore } from 'pinia'

const MAX_POINTS = 1000 // 每个设备最多保留 1000 个数据点
const FLUSH_MS = 33 // 约 30 FPS
// 抽稀周期（毫秒）：DemoVision 设备 slam/pose 实测 ~500Hz。
// 按 20ms 抽稀（≈50Hz）后，1000 点正好覆盖「最近 20 秒」的滑动窗口 ——
// 长时间录制时点数恒定，曲线与内存开销都不增长（不会越跑越卡）。
const SAMPLE_MS = 20
// 时间基准跳变阈值（秒）：ROS 的 pose 时间戳来自设备 uptime，
// 换一次录制会话/设备重启就会整体跳变（实测见过 1162 / 35396 / 35431 / 36351）。
// 若把两个基准的点混在一条曲线里，横轴范围会被撑到几万秒，
// 真实数据只占其中几秒 → 曲线被挤成一根竖线（用户实际症状）。故跨越此阈值即丢弃旧基准数据。
const BASE_JUMP_SEC = 5

// 供 UI 显示窗口时长用
export const SLAM_MAX_POINTS = MAX_POINTS
export const SLAM_SAMPLE_MS = SAMPLE_MS
export const SLAM_WINDOW_SEC = (MAX_POINTS * SAMPLE_MS) / 1000

function emptyBuffer() {
  return { t: [], x: [], y: [], z: [], dist: [] }
}

export const useSlamStore = defineStore('slam', {
  state: () => ({
    buffers: {}, // sn -> { t:[], x:[], y:[], z:[], dist:[] }
    charts: {}, // sn -> Set<updateFn>
    _timer: null,
  }),

  actions: {
    _ensureBuffer(sn) {
      if (!this.buffers[sn]) {
        this.buffers[sn] = emptyBuffer()
      }
      return this.buffers[sn]
    },

    /** 清空所有设备的曲线数据（开始新一次录制时调用，避免上一次的点污染横轴） */
    clearBuffers() {
      this.buffers = {}
    },

    addData(point) {
      const { sn, t, x, y, z, dist } = point
      if (!sn || typeof t !== 'number' || !isFinite(t)) return
      let buf = this._ensureBuffer(sn)

      // 时间基准跳变 → 丢弃旧基准数据，否则横轴会被撑爆（曲线变竖线）
      if (buf._lastT !== undefined && Math.abs(t - buf._lastT) > BASE_JUMP_SEC) {
        this.buffers[sn] = emptyBuffer()
        buf = this.buffers[sn]
      }

      // 抽稀：距上次「已提交」采样不足一个周期就丢弃。
      // 基准必须是独立的 _lastT —— 若拿 buf.t 末点比较并在窗口内覆盖末点，
      // 500Hz 下每条消息都落在窗口内，缓冲会永远停在 1 个点（实测 count=1）。
      const last = buf._lastT
      if (last !== undefined && t - last >= 0 && t - last < SAMPLE_MS / 1000) return
      buf._lastT = t // t 回退时差值 <0 会走到这里，自动自愈

      buf.t.push(t)
      buf.x.push(x)
      buf.y.push(y)
      buf.z.push(z)
      buf.dist.push(dist)
      if (buf.t.length > MAX_POINTS) {
        const overflow = buf.t.length - MAX_POINTS
        buf.t.splice(0, overflow)
        buf.x.splice(0, overflow)
        buf.y.splice(0, overflow)
        buf.z.splice(0, overflow)
        buf.dist.splice(0, overflow)
      }
    },

    registerChart(sn, updateFn) {
      if (!this.charts[sn]) this.charts[sn] = new Set()
      this.charts[sn].add(updateFn)
      this._ensureTimer()
    },

    unregisterChart(sn, updateFn) {
      if (this.charts[sn]) this.charts[sn].delete(updateFn)
      if (this.charts[sn] && this.charts[sn].size === 0) {
        delete this.charts[sn]
      }
    },

    _ensureTimer() {
      if (this._timer) return
      this._timer = setInterval(() => {
        // 30 FPS：从缓冲区取数据做增量渲染，绝不在每条 WS 消息时 setOption
        for (const [sn, fns] of Object.entries(this.charts)) {
          const buf = this.buffers[sn]
          if (!buf || buf.t.length === 0) continue
          const snapshot = {
            t: buf.t.slice(),
            x: buf.x.slice(),
            y: buf.y.slice(),
            z: buf.z.slice(),
            dist: buf.dist.slice(),
          }
          fns.forEach((fn) => fn(sn, snapshot))
        }
      }, FLUSH_MS)
    },

    reset() {
      this.buffers = {}
      Object.keys(this.charts).forEach((sn) => delete this.charts[sn])
    },

    handleWS(msg) {
      if (msg.type === 'slam_data') {
        this.addData(msg)
      }
    },
  },
})
