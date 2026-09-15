// SDK 运行状态共享 store（App.vue 轮询更新，依赖 SDK 的页面读取禁用按钮）
import { defineStore } from 'pinia'

export const useSdkStore = defineStore('sdk', {
  state: () => ({
    running: false,          // /dv_sdk 节点是否在线
    busy: false,             // 启/停操作进行中
    videoServerRunning: false, // web_video_server (8080) 是否运行
  }),
  actions: {
    setRunning(v) {
      this.running = !!v
    },
    setBusy(v) {
      this.busy = !!v
    },
    setVideoServerRunning(v) {
      this.videoServerRunning = !!v
    },
  },
})
