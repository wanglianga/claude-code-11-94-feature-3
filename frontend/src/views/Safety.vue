<template>
  <div>
    <div class="panel">
      <h2>🛡️ 安全工程师放行审批</h2>
      <div class="row">
        <input v-model="checkSerial" placeholder="输入包序列号查看梯次利用门禁" style="width:260px" />
        <button class="secondary" @click="checkBlockers">检查放行门禁</button>
      </div>
      <div v-if="blockers" class="panel" style="margin-top:12px">
        <h3>{{ checkSerial }} 的梯次利用门禁</h3>
        <div v-if="!blockers.blocked" class="msg ok">无阻塞项，可以批准梯次利用。</div>
        <div v-else class="msg err">
          <div v-for="(b, i) in blockers.blockers" :key="i">• {{ b }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>提交审批决定</h2>
      <div class="grid cols-3">
        <div><label>包序列号</label><input v-model="form.serial_no" /></div>
        <div>
          <label>决定</label>
          <select v-model="form.decision">
            <option value="echelon">梯次利用</option>
            <option value="recycle">回收</option>
            <option value="reinspect">退回补检（旧放行单失效）</option>
          </select>
        </div>
        <div><label>用途（梯次利用必填）</label><input v-model="form.purpose" placeholder="如 储能调峰" /></div>
        <div><label>收货人（梯次利用必填）</label><input v-model="form.consignee" placeholder="如 华东储能公司" /></div>
        <div><label>限数量（梯次利用必填）</label><input type="number" v-model.number="form.quantity_limit" min="1" /></div>
        <div><label>说明</label><input v-model="form.rationale" /></div>
      </div>
      <div class="row end" style="margin-top:10px"><button @click="submit">提交审批</button></div>
      <div v-if="msg" class="msg ok" style="margin-top:10px">{{ msg }}</div>
      <div v-if="err" class="msg err" style="margin-top:10px">{{ err }}</div>
    </div>

    <div class="panel">
      <h2>放行单（版本与失效记录）</h2>
      <table>
        <thead><tr><th>ID</th><th>包</th><th>版本</th><th>决定</th><th>状态</th><th>用途/收货人/限数量</th><th>失效原因</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="a in approvals" :key="a.id">
            <td>#{{ a.id }}</td>
            <td class="mono">{{ a.pack_serial }}</td>
            <td>v{{ a.version }}</td>
            <td>{{ DECISION[a.decision] }}</td>
            <td><span class="tag" :class="tagClass(a.status)">{{ APPROVAL_STATUS[a.status] }}</span></td>
            <td class="small">{{ [a.purpose, a.consignee, a.quantity_limit != null ? a.quantity_limit + ' 件' : ''].filter(Boolean).join(' / ') || '—' }}</td>
            <td class="small">{{ a.voided_reason || '—' }}</td>
            <td class="small">{{ a.created_at.slice(0, 16).replace('T', ' ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>热事件结案</h2>
      <div class="row">
        <input v-model="thermalEventId" type="number" placeholder="热事件 ID" style="width:160px" />
        <button class="secondary" @click="closeThermal">标记结案</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { APPROVAL_STATUS, DECISION, tagClass } from '../statusLabels'

const approvals = ref([])
const checkSerial = ref('')
const blockers = ref(null)
const thermalEventId = ref(null)
const msg = ref('')
const err = ref('')
const form = reactive({
  serial_no: '', decision: 'echelon', purpose: '', consignee: '',
  quantity_limit: 1, rationale: '',
})

async function load() {
  approvals.value = await api.get('/api/safety/approvals')
}
onMounted(load)

async function checkBlockers() {
  blockers.value = await api.get(`/api/safety/echelon-blockers/${checkSerial.value}`)
}
async function submit() {
  msg.value = ''
  err.value = ''
  try {
    const r = await api.post('/api/safety/approvals', { ...form })
    msg.value = `审批已提交：${r.approval.pack_serial} → ${DECISION[r.approval.decision]}（v${r.approval.version}）`
    await load()
  } catch (e) { err.value = e.message }
}
async function closeThermal() {
  err.value = ''
  try {
    await api.post('/api/safety/thermal/close', { event_id: thermalEventId.value, closed: true })
    msg.value = '热事件已结案'
  } catch (e) { err.value = e.message }
}
</script>
