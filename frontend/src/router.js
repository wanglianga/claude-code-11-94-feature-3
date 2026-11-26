import { createRouter, createWebHashHistory } from 'vue-router'
import { store } from './api'

const routes = [
  { path: '/login', component: () => import('./views/Login.vue') },
  { path: '/', redirect: '/receiving' },
  { path: '/receiving', component: () => import('./views/Receiving.vue'), title: '收货与隔离（模拟扫码器）' },
  { path: '/dismantling', component: () => import('./views/Dismantling.vue'), title: '拆解工单与换标' },
  { path: '/inspection', component: () => import('./views/Inspection.vue'), title: '检测台回执' },
  { path: '/safety', component: () => import('./views/Safety.vue'), title: '安全放行审批' },
  { path: '/warehouse', component: () => import('./views/Warehouse.vue'), title: '仓库拣货与核对' },
  { path: '/downstream', component: () => import('./views/Downstream.vue'), title: '下游签收端' },
  { path: '/scenario', component: () => import('./views/Scenario.vue'), title: 'L-7 策略对比场景' },
  { path: '/aftersales', component: () => import('./views/Aftersales.vue'), title: '售后客服案件台' },
  { path: '/assignment', component: () => import('./views/Assignment.vue'), title: '多案备件精确指派' },
  { path: '/audit', component: () => import('./views/Audit.vue'), title: '全链路审计日志' },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  if (to.path !== '/login' && !store.user) return '/login'
  if (to.path === '/login' && store.user) return '/receiving'
  return true
})

export default router
