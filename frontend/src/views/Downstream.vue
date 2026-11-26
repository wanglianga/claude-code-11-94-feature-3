<template>
  <div>
    <div class="panel">
      <h2>🚚 下游签收端</h2>
      <p class="muted small">
        买家可签收或拒收；拒收货物只能退回中心隔离待复核，<b>不会自动回到可用库存</b>，须重新核实与审批。
      </p>
      <table>
        <thead><tr><th>出库单</th><th>包</th><th>用途</th><th>收货人</th><th>状态</th><th>签收</th><th>拒收</th></tr></thead>
        <tbody>
          <tr v-for="o in outbound" :key="o.id">
            <td>#{{ o.id }}</td>
            <td class="mono">{{ o.pack_serial }}</td>
            <td>{{ o.purpose }}</td>
            <td>{{ o.consignee }}</td>
            <td><span class="tag" :class="tagClass(o.status)">{{ OUTBOUND_STATUS[o.status] }}</span></td>
            <td><button class="ghost" :disabled="o.status !== 'shipped'" @click="sign(o.id, 'signed')">确认签收</button></td>
            <td><button class="danger" :disabled="o.status !== 'shipped'" @click="sign(o.id, 'rejected')">拒收退回</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="msg" class="msg ok" style="margin-top:12px">{{ msg }}</div>
      <div v-if="err" class="msg err" style="margin-top:12px">{{ err }}</div>
    </div>

    <div class="panel">
      <h2>签收/拒收记录</h2>
      <table>
        <thead><tr><th>出库单</th><th>动作</th><th>签收人</th><th>备注</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="s in signoffs" :key="s.id">
            <td>#{{ s.outbound_order_id }}</td>
            <td><span class="tag" :class="s.action === 'signed' ? 'green' : 'red'">{{ s.action === 'signed' ? '签收' : '拒收' }}</span></td>
            <td>{{ s.signer }}</td>
            <td class="small">{{ s.note || '—' }}</td>
            <td class="small">{{ s.created_at.slice(0, 16).replace('T', ' ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { OUTBOUND_STATUS, tagClass } from '../statusLabels'

const outbound = ref([])
const signoffs = ref([])
const msg = ref('')
const err = ref('')

async function load() {
  outbound.value = await api.get('/api/warehouse/outbound')
  signoffs.value = await api.get('/api/warehouse/sign-offs')
}
onMounted(load)

async function sign(id, action) {
  msg.value = ''
  err.value = ''
  const signer = window.prompt('请输入签收人姓名', '周买家')
  if (!signer) return
  let note = ''
  if (action === 'rejected') note = window.prompt('请输入拒收原因', '外观/资料不符') || ''
  try {
    await api.post('/api/warehouse/sign-off', { outbound_id: id, action, signer, note })
    msg.value = action === 'signed' ? '签收完成' : '已拒收，货物退回中心隔离待复核'
    await load()
  } catch (e) { err.value = e.message }
}
</script>
