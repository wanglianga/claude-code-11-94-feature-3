<template>
  <div class="panel">
    <h2>📜 全链路审计日志（最近 {{ logs.length }} 条）</h2>
    <table>
      <thead><tr><th>ID</th><th>操作者 ID</th><th>动作</th><th>对象</th><th>对象 ID</th><th>详情</th><th>时间</th></tr></thead>
      <tbody>
        <tr v-for="l in logs" :key="l.id">
          <td>{{ l.id }}</td>
          <td>{{ l.actor_id ?? '—' }}</td>
          <td><span class="tag gray">{{ l.action }}</span></td>
          <td>{{ l.entity }}</td>
          <td>{{ l.entity_id || '—' }}</td>
          <td class="small mono">{{ JSON.stringify(l.detail) }}</td>
          <td class="small">{{ l.created_at?.slice(0, 19).replace('T', ' ') }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const logs = ref([])
onMounted(async () => {
  logs.value = await api.get('/api/audit/logs')
})
</script>
