<template>
  <div class="login-wrap">
    <div class="panel">
      <h2>登录（选择测试账号）</h2>
      <p class="muted small">演示系统采用账号头鉴权，登录后所有请求自动携带 X-Username。</p>
      <label>账号</label>
      <select v-model="username" @change="doLogin">
        <option value="" disabled>请选择…</option>
        <option v-for="u in users" :key="u.username" :value="u.username">
          {{ u.display_name }} — {{ roleName(u.role) }}（{{ u.username }}）
        </option>
      </select>
      <div style="height: 12px"></div>
      <button style="width: 100%" @click="doLogin" :disabled="!username">登录</button>
      <div v-if="error" class="msg err" style="margin-top: 12px">{{ error }}</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, store } from '../api'

const router = useRouter()
const users = ref([])
const username = ref('')
const error = ref('')

const ROLE_NAMES = {
  receiver: '接收员', dismantler: '拆解员', safety: '安全工程师',
  warehouse: '仓库', downstream: '下游买家', admin: '管理员',
  service: '售后客服', engineer: '工程人员', finance: '财务',
}
const roleName = (r) => ROLE_NAMES[r] || r

onMounted(async () => {
  users.value = await api.get('/api/auth/users')
})

async function doLogin() {
  if (!username.value) return
  try {
    const resp = await api.post('/api/auth/login', { username: username.value })
    if (!resp.ok) throw new Error(resp.message)
    store.setUser(resp.user)
    router.push('/receiving')
  } catch (e) {
    error.value = e.message
  }
}
</script>
