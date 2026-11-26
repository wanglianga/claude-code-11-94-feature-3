<template>
  <div>
    <div class="panel">
      <h2>拆解工单</h2>
      <div class="row">
        <input v-model="woSerial" placeholder="包序列号，如 P-2" style="width:200px" />
        <input v-model="woNote" placeholder="工单说明" style="flex:1" />
        <button @click="createWO">开立拆解工单</button>
      </div>
      <div v-if="woError" class="msg err" style="margin-top:10px">{{ woError }}</div>
      <table style="margin-top:12px">
        <thead><tr><th>工单号</th><th>包</th><th>状态</th><th>见证双方</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="w in workOrders" :key="w.id">
            <td>#{{ w.id }}</td>
            <td class="mono">{{ w.pack_serial }}</td>
            <td><span class="tag" :class="tagClass(w.status)">{{ WO_STATUS[w.status] }}</span></td>
            <td class="small">
              <template v-if="w.witness1 && w.witness2">{{ w.witness1.display_name }} ＋ {{ w.witness2.display_name }}</template>
              <span v-else class="muted">未见证</span>
            </td>
            <td><button class="ghost" :disabled="w.status === 'completed' || w.status === 'pending_verification'" @click="completeWO(w.id)">关闭工单</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>双方见证扫码 — 建立包→模组父子关系</h2>
      <p class="muted small">两名不同操作者分别扫码见证后才建立关系；同一人重复担任见证者会被拒绝。</p>
      <div class="grid cols-2">
        <div>
          <label>工单</label>
          <select v-model="linkForm.work_order_id">
            <option :value="null" disabled>选择工单</option>
            <option v-for="w in openWorkOrders" :key="w.id" :value="w.id">#{{ w.id }} - {{ w.pack_serial }}</option>
          </select>
        </div>
        <div><label>模组序列号（扫码）</label><input v-model="linkForm.module_serial" placeholder="如 M-P2-01" /></div>
        <div><label>见证者一</label><select v-model="linkForm.witness1"><option v-for="u in dismantlers" :key="u.username" :value="u.username">{{ u.display_name }}</option></select></div>
        <div><label>见证者二</label><select v-model="linkForm.witness2"><option v-for="u in dismantlers" :key="u.username" :value="u.username">{{ u.display_name }}</option></select></div>
      </div>
      <div class="row end" style="margin-top:10px"><button @click="linkModule">见证扫码建立关系</button></div>
      <div v-if="linkMsg" class="msg ok" style="margin-top:10px">{{ linkMsg }}</div>
      <div v-if="linkErr" class="msg err" style="margin-top:10px">{{ linkErr }}</div>
    </div>

    <div class="panel">
      <h2>无法确认父子关系的模组 — 隔离待核</h2>
      <p class="muted small">重贴标签与在档序列号均不匹配时登记为待核；系统不会自动归到最相似序列号，工单同步挂起。</p>
      <div class="row">
        <select v-model="unknownForm.work_order_id" style="width:200px">
          <option :value="null" disabled>选择工单</option>
          <option v-for="w in openWorkOrders" :key="w.id" :value="w.id">#{{ w.id }} - {{ w.pack_serial }}</option>
        </select>
        <input v-model="unknownForm.module_serial" placeholder="失配模组序列号" style="width:200px" />
        <input v-model="unknownForm.reason" placeholder="失配原因" style="flex:1" />
        <button class="danger" @click="registerUnknown">登记隔离待核</button>
      </div>
      <h3>人工核实后挂回父包</h3>
      <div class="row">
        <input v-model="resolveModule" placeholder="待核模组序列号" style="width:200px" />
        <input v-model="resolveParent" placeholder="核实后的父包序列号" style="width:200px" />
        <button class="secondary" @click="resolveUnknown">核实挂回</button>
      </div>
    </div>

    <div class="panel">
      <h2>重贴标签（两人分别确认，旧号/操作者/时间全程留痕）</h2>
      <div class="grid cols-3">
        <div><label>对象类型</label><select v-model="relabelForm.entity_type"><option value="pack">电池包</option><option value="module">模组</option></select></div>
        <div><label>旧序列号</label><input v-model="relabelForm.old_serial" /></div>
        <div><label>新序列号</label><input v-model="relabelForm.new_serial" /></div>
      </div>
      <div class="row" style="margin-top:10px">
        <button @click="relabelRequest">第一人发起换标</button>
        <select v-model="relabelForm.operator2" style="width:220px">
          <option value="" disabled>第二确认人</option>
          <option v-for="u in allUsers" :key="u.username" :value="u.username">{{ u.display_name }}（{{ u.username }}）</option>
        </select>
        <button class="secondary" @click="relabelConfirm">第二人确认生效</button>
      </div>
      <div v-if="relabelMsg" class="msg info" style="margin-top:10px">{{ relabelMsg }}</div>
      <div v-if="relabelErr" class="msg err" style="margin-top:10px">{{ relabelErr }}</div>
      <table style="margin-top:12px">
        <thead><tr><th>对象</th><th>旧号</th><th>新号</th><th>状态</th><th>发起人</th><th>确认人</th><th>确认时间</th></tr></thead>
        <tbody>
          <tr v-for="h in labelHistory" :key="h.id">
            <td>{{ h.entity_type === 'pack' ? '电池包' : '模组' }}</td>
            <td class="mono">{{ h.old_serial }}</td>
            <td class="mono">{{ h.new_serial }}</td>
            <td><span class="tag" :class="h.confirmed ? 'green' : 'amber'">{{ h.confirmed ? '已生效' : '待第二人确认' }}</span></td>
            <td>{{ h.operator1_id }}</td>
            <td>{{ h.operator2_id || '—' }}</td>
            <td class="small">{{ h.confirmed_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>模组清单（{{ modules.length }}）</h2>
      <table>
        <thead><tr><th>模组序列号</th><th>父包 ID</th><th>工单</th><th>状态</th><th>父子关系</th></tr></thead>
        <tbody>
          <tr v-for="m in modules" :key="m.id">
            <td class="mono">{{ m.serial_no }}</td>
            <td>{{ m.pack_id ?? '—' }}</td>
            <td>{{ m.work_order_id ?? '—' }}</td>
            <td><span class="tag" :class="tagClass(m.status)">{{ MODULE_STATUS[m.status] }}</span></td>
            <td><span class="tag" :class="m.unknown_parent ? 'red' : 'green'">{{ m.unknown_parent ? '无法确认（隔离待核）' : '已确认' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { MODULE_STATUS, WO_STATUS, tagClass } from '../statusLabels'

const workOrders = ref([])
const modules = ref([])
const labelHistory = ref([])
const allUsers = ref([])
const dismantlers = computed(() => allUsers.value.filter((u) => u.role === 'dismantler' || u.role === 'admin'))
const openWorkOrders = computed(() => workOrders.value.filter((w) => w.status !== 'completed'))

const woSerial = ref('')
const woNote = ref('')
const woError = ref('')
const linkForm = reactive({ work_order_id: null, module_serial: '', witness1: 'u_dismantler', witness2: 'u_dismantler2' })
const linkMsg = ref('')
const linkErr = ref('')
const unknownForm = reactive({ work_order_id: null, module_serial: '', reason: '' })
const resolveModule = ref('')
const resolveParent = ref('')
const relabelForm = reactive({ entity_type: 'pack', old_serial: '', new_serial: '', operator2: '' })
const relabelMsg = ref('')
const relabelErr = ref('')

async function load() {
  workOrders.value = await api.get('/api/dismantling/work-orders')
  modules.value = await api.get('/api/dismantling/modules')
  labelHistory.value = await api.get('/api/dismantling/label-history')
  allUsers.value = await api.get('/api/auth/users')
}
onMounted(load)

async function createWO() {
  woError.value = ''
  try {
    await api.post('/api/dismantling/work-orders', { serial_no: woSerial.value, note: woNote.value })
    woSerial.value = ''
    woNote.value = ''
    await load()
  } catch (e) { woError.value = e.message }
}
async function completeWO(id) {
  woError.value = ''
  try {
    await api.post(`/api/dismantling/work-orders/${id}/complete`, {})
    await load()
  } catch (e) { woError.value = e.message }
}
async function linkModule() {
  linkMsg.value = ''
  linkErr.value = ''
  try {
    const r = await api.post('/api/dismantling/link-module', { ...linkForm })
    linkMsg.value = `模组 ${r.module.serial_no} 已在双方见证下建立父子关系`
    linkForm.module_serial = ''
    await load()
  } catch (e) { linkErr.value = e.message }
}
async function registerUnknown() {
  linkErr.value = ''
  try {
    await api.post('/api/dismantling/unknown-module', { ...unknownForm })
    unknownForm.module_serial = ''
    unknownForm.reason = ''
    await load()
  } catch (e) { linkErr.value = e.message }
}
async function resolveUnknown() {
  linkMsg.value = ''
  linkErr.value = ''
  try {
    await api.post('/api/dismantling/resolve-unknown', {
      module_serial: resolveModule.value, parent_serial: resolveParent.value,
    })
    resolveModule.value = ''
    resolveParent.value = ''
    await load()
  } catch (e) { linkErr.value = e.message }
}
async function relabelRequest() {
  relabelMsg.value = ''
  relabelErr.value = ''
  try {
    const r = await api.post('/api/dismantling/relabel', {
      entity_type: relabelForm.entity_type, old_serial: relabelForm.old_serial,
      new_serial: relabelForm.new_serial, confirm: false,
    })
    relabelMsg.value = `换标申请已登记（#${r.label_history.id}），等待第二名操作者确认`
    await load()
  } catch (e) { relabelErr.value = e.message }
}
async function relabelConfirm() {
  relabelMsg.value = ''
  relabelErr.value = ''
  try {
    const r = await api.post('/api/dismantling/relabel', {
      entity_type: relabelForm.entity_type, old_serial: relabelForm.old_serial,
      new_serial: relabelForm.new_serial, operator2: relabelForm.operator2, confirm: true,
    })
    relabelMsg.value = `换标已生效：${r.label_history.old_serial} → ${r.label_history.new_serial}`
    await load()
  } catch (e) { relabelErr.value = e.message }
}
</script>
