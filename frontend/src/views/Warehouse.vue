<template>
  <div>
    <div class="panel">
      <h2>📦 仓库拣货（只能按已批准去向拣货）</h2>
      <table>
        <thead><tr><th>拣货单</th><th>包</th><th>批准去向</th><th>放行单状态</th><th>拣货单状态</th><th>更正说明</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="p in picking" :key="p.id">
            <td>#{{ p.id }}</td>
            <td class="mono">{{ p.pack_serial }}</td>
            <td>{{ DECISION[p.decision] }}</td>
            <td><span class="tag" :class="tagClass(p.approval_status)">{{ APPROVAL_STATUS[p.approval_status] }}</span></td>
            <td><span class="tag" :class="tagClass(p.status)">{{ PICKING_STATUS[p.status] }}</span></td>
            <td class="small">{{ p.correction_note || '—' }}</td>
            <td><button class="ghost" :disabled="p.status !== 'waiting'" @click="doPick(p.id)">拣货</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="pickErr" class="msg err" style="margin-top:10px">{{ pickErr }}</div>
    </div>

    <div class="panel">
      <h2>出库单（限数量 / 用途 / 收货人）与装车</h2>
      <table>
        <thead><tr><th>出库单</th><th>包</th><th>数量</th><th>用途</th><th>收货人</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="o in outbound" :key="o.id">
            <td>#{{ o.id }}</td>
            <td class="mono">{{ o.pack_serial }}</td>
            <td>{{ o.quantity }}</td>
            <td>{{ o.purpose }}</td>
            <td>{{ o.consignee }}</td>
            <td><span class="tag" :class="tagClass(o.status)">{{ OUTBOUND_STATUS[o.status] }}</span></td>
            <td>
              <button class="ghost" :disabled="!['created', 'notified'].includes(o.status)" @click="doShip(o.id)">装车出库</button>
              <button class="danger" :disabled="!['shipped', 'signed'].includes(o.status)" @click="doRecall(o.id)">召回/退运</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="muted small">装车后的货物不能从历史删除，只能走召回或退运，召回/退运后回到隔离待核。</p>
    </div>

    <div class="panel">
      <h2>买家通知（含更正通知）</h2>
      <table>
        <thead><tr><th>出库单</th><th>收货人</th><th>通知内容</th><th>类型</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="n in notifications" :key="n.id">
            <td>#{{ n.outbound_order_id }}</td>
            <td>{{ n.consignee }}</td>
            <td class="small">{{ n.message }}</td>
            <td><span class="tag" :class="n.corrected ? 'red' : 'green'">{{ n.corrected ? '更正/作废' : '预告' }}</span></td>
            <td class="small">{{ n.created_at.slice(0, 16).replace('T', ' ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>回收称重</h2>
      <div class="row">
        <input v-model="weighSerial" placeholder="包/模组序列号" style="width:220px" />
        <input v-model.number="weighWeight" type="number" step="0.01" placeholder="重量 kg" style="width:160px" />
        <button @click="doWeigh">提交称重</button>
      </div>
      <div v-if="weighMsg" class="msg ok" style="margin-top:10px">{{ weighMsg }}</div>
      <div v-if="weighErr" class="msg err" style="margin-top:10px">{{ weighErr }}</div>
    </div>

    <div class="panel">
      <h2>批次数量核对与结清</h2>
      <div class="row">
        <input v-model="batchNo" placeholder="批次号，如 L-7" style="width:200px" />
        <button class="secondary" @click="loadRecon">查询核对</button>
      </div>
      <div v-if="recon" class="grid cols-3" style="margin-top:12px">
        <div class="kv"><span class="k">实际拆出模组</span><span>{{ recon.stats.dismantled_qty }}</span></div>
        <div class="kv"><span class="k">待核模组</span><span>{{ recon.stats.unknown_modules }}</span></div>
        <div class="kv"><span class="k">有效放行单</span><span>{{ recon.stats.released_qty }}</span></div>
        <div class="kv"><span class="k">已发数量</span><span>{{ recon.stats.shipped_qty }}</span></div>
        <div class="kv"><span class="k">回收称重 kg</span><span>{{ recon.stats.recycled_weight_kg.toFixed(2) }}</span></div>
        <div class="kv"><span class="k">放行-已发差额</span><span :class="recon.stats.difference ? 'tag red' : 'tag green'">{{ recon.stats.difference }}</span></div>
      </div>
      <div class="row" style="margin-top:12px">
        <input v-model="closeExplanation" placeholder="差额解释（有差额时必填）" style="flex:1" />
        <button class="danger" @click="closeBatch">申请结清批次</button>
      </div>
      <div v-if="closeMsg" class="msg ok" style="margin-top:10px">{{ closeMsg }}</div>
      <div v-if="closeErr" class="msg err" style="margin-top:10px">{{ closeErr }}</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { APPROVAL_STATUS, DECISION, OUTBOUND_STATUS, PICKING_STATUS, tagClass } from '../statusLabels'

const picking = ref([])
const outbound = ref([])
const notifications = ref([])
const pickErr = ref('')
const weighSerial = ref('')
const weighWeight = ref(null)
const weighMsg = ref('')
const weighErr = ref('')
const batchNo = ref('L-7')
const recon = ref(null)
const closeExplanation = ref('')
const closeMsg = ref('')
const closeErr = ref('')
const recallReason = ref('')

async function load() {
  picking.value = await api.get('/api/warehouse/picking')
  outbound.value = await api.get('/api/warehouse/outbound')
  notifications.value = await api.get('/api/warehouse/notifications')
}
onMounted(load)

async function doPick(id) {
  pickErr.value = ''
  try {
    await api.post('/api/warehouse/pick', { picking_id: id })
    await load()
  } catch (e) { pickErr.value = e.message }
}
async function doShip(id) {
  pickErr.value = ''
  try {
    await api.post('/api/warehouse/ship', { outbound_id: id })
    await load()
  } catch (e) { pickErr.value = e.message }
}
async function doRecall(id) {
  const reason = window.prompt('请输入召回/退运原因', '装车后发现风险')
  if (!reason) return
  pickErr.value = ''
  try {
    await api.post('/api/warehouse/recall', { outbound_id: id, kind: 'recall', reason })
    await load()
  } catch (e) { pickErr.value = e.message }
}
async function doWeigh() {
  weighMsg.value = ''
  weighErr.value = ''
  try {
    const r = await api.post('/api/warehouse/recycle-weighing', {
      serial_no: weighSerial.value, weight_kg: weighWeight.value,
    })
    weighMsg.value = `已记录称重 ${r.weight_kg} kg`
    weighSerial.value = ''
    weighWeight.value = null
  } catch (e) { weighErr.value = e.message }
}
async function loadRecon() {
  closeErr.value = ''
  recon.value = await api.get(`/api/warehouse/reconciliation/${batchNo.value}`)
}
async function closeBatch() {
  closeMsg.value = ''
  closeErr.value = ''
  try {
    const r = await api.post('/api/warehouse/close-batch', {
      batch_no: batchNo.value, explanation: closeExplanation.value || null,
    })
    closeMsg.value = `批次 ${r.batch.batch_no} 已结清`
    await loadRecon()
  } catch (e) { closeErr.value = e.message }
}
</script>
