import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/detection',
  },
  {
    path: '/detection',
    name: 'detection',
    component: () => import('../views/DetectionView.vue'),
    meta: { title: '检测工作台' },
  },
  {
    path: '/slam',
    name: 'slam',
    component: () => import('../views/SlamMonitorView.vue'),
    meta: { title: 'SLAM 实时大屏' },
  },
  {
    path: '/live',
    name: 'live',
    component: () => import('../views/LiveView.vue'),
    meta: { title: '实时图像' },
  },
  {
    path: '/ros-terminal',
    name: 'ros-terminal',
    component: () => import('../views/RosTerminalView.vue'),
    meta: { title: 'ROS 终端' },
  },
  {
    path: '/imu-calibration',
    name: 'imu-calibration',
    component: () => import('../views/ImuCalibrationView.vue'),
    meta: { title: 'IMU 校准' },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('../views/HistoryView.vue'),
    meta: { title: '历史报告' },
  },
  {
    path: '/print/:kind/:uuid',
    name: 'report-print',
    component: () => import('../views/ReportPrintView.vue'),
    meta: { title: '报告打印' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const NAME = 'DemoVision 设备质检平台'
  document.title = to.meta.title ? `${to.meta.title} - ${NAME}` : NAME
})

export default router
