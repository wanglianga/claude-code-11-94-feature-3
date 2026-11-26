<template>
  <div>
    <div class="panel scan-box">
      <h2>📷 模拟扫码器 — 收货登记</h2>
      <p class="muted small">
        模拟扫码枪扫到的序列号直接填入并提交；同一序列号重复扫码只返回原收货单，不产生重复单据。
      </p>
      <div class="grid cols-3">
        <div><label>到货批次号</label><input v-model="form.batch_no" placeholder="如 L-7" /></div>
        <div><label>包体唯一序列号（扫码）</label><input v-model="form.serial_no" placeholder="如 P-5" /></div>
        <div><label>来源车企</label><input v-model="form.oem" /></div>
        <div><label>来源车辆 VIN</label><input v-model="form.source_vehicle" /></div>
        <div><label>隔离位</label><input v-model="form.quarantine_slot" placeholder="如 Q-A-05" /></div>
        <div><label>责任班组</label><input v-model="form.responsible_team" /></div>
      </div>
      <h3>运输事件确认（碰撞 / 浸水 / 热事件）</h3>
      <div v-for="(ev, i) in form.events" :key="i" class="row">
        <select style="width: 130px" v-model="ev.event_type">
          <option value="collision">碰撞</option>
          <option value="water">浸水</option>
          <option value="thermal">热事件</option>
        </select>
        <input style="width: 180px" v-model="ev.source_doc" placeholder="回执编号" />
        <input v-model="ev.description" placeholder="事件描述" />
        <label class="row" style="margin:0"><input type="checkbox" style="width:auto" v-model="ev.case_closed" /> 已结案</label>
        <button class="ghost" @click="form.events.splice(i, 1)">删除</button>
      </div>
      <div class="row" style="margin-top: 8px">
        <button class="secondary" @click="form.events.push({ event_type: 'collision', source_doc: '', description: '', case_closed: false })">
          + 添加运输事件
        </button>
        <span style="flex:1"></span>
        <button @click="submitScan" :disabled="!canReceive">提交收货扫码</button>
      </div>
      <div v-if="message" class="msg ok" style="margin-top:12px">{{ message }}</div>
      <div v-if="error" class="msg err" style="margin-top:12px">{{ error }}</div>
      <div v-if="lastReceipt" class="panel" style="margin-top:12px">
        <h3>收货单 #{{ lastReceipt.id }} <span class="tag gray mono">{{ lastReceipt.pack.serial_no }}</span></h3>
        <div class="kv">
          <span class="k">隔离位</span><span>{{ lastReceipt.quarantine_slot || '—' }}</span>
          <span class="k">责任班组</span><span>{{ lastReceipt.responsible_team || '—' }}</span>
          <span class="k">包状态</span><span><span class="tag" :class="tagClass(lastReceipt.pack.status)">{{ PACK_STATUS[lastReceipt.pack.status] }}</span></span>
          <span class="k">未完成前置项</span>
          <span>
            <span v-if="!lastReceipt.pending_preconditions.length" class="tag green">无</span>
            <span v-else class="pill-list">
              <span v-for="(p, i) in lastReceipt.pending_preconditions" :key="i" class="tag red">{{ p }}</span>
            </span>
          </span>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>隔离策略</h2>
      <div class="grid cols-2">
        <div>
          <h3>整批隔离（同车全部冻结，减少串错；一包待查挡住无关包）</h3>
          <div class="row">
            <input v-model="batchFreezeNo" placeholder="批次号，如 L-7" style="width:160px" />
            <input v-model="batchFreezeReason" placeholder="原因" />
            <button class="danger" @click="freezeBatch">整批冻结</button>
          </div>
          <div class="row" style="margin-top:8px">
            <input v-model="unfreezeNo" placeholder="解冻批次号" style="width:160px" />
            <button class="secondary" @click="unfreezeBatch">解冻批次</button>
          </div>
        </div>
        <div>
          <h3>单包隔离（身份与风险边界核实后仅冻结该包，证据齐全者先流转）</h3>
          <div class="row">
            <input v-model="packQuarantineNo" placeholder="包序列号" style="width:160px" />
            <input v-model="packQuarantineReason" placeholder="原因" />
            <button class="danger" @click="quarantinePack">单包隔离</button>
          </div>
          <div class="row" style="margin-top:8px">
            <input v-model="releaseNo" placeholder="解除隔离包序列号" style="width:160px" />
            <button class="secondary" @click="releasePack">解除隔离</button>
          </div>
        </div>
      </div>
      <div v-if="qError" class="msg err" style="margin-top:10px">{{ qError }}</div>
    </div>

    <div class="panel">
      <h2>在库电池包（{{ packs.length }}）</h2>
      <table>
        <thead>
          <tr><th>序列号</th><th>批次</th><th>状态</th><th>隔离位</th><th>班组</th><th>运输事件</th><th>未完成前置项</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in packs" :key="p.id">
            <td class="mono">{{ p.serial_no }}</td>
            <td>{{ p.batch_no }}</td>
            <td><span class="tag" :class="tagClass(p.status)">{{ PACK_STATUS[p.status] }}</span><span v-if="p.frozen" class="tag red" style="margin-left:4px">冻结</span></td>
            <td>{{ p.quarantine_slot || '—' }}</td>
            <td>{{ p.responsible_team || '—' }}</td>
            <td>
              <span v-if="!p.transport_events.length" class="muted">无</span>
              <span class="pill-list">
                <span v-for="e in p.transport_events" :key="e.id" class="tag" :class="e.case_closed ? 'green' : 'red'">
                  {{ EVENT_TYPE[e.event_type] }} {{ e.source_doc }} {{ e.case_closed ? '已结案' : '未结案' }}
                </span>
              </span>
            </td>
            <td>
              <span v-if="!p.pending_preconditions.length" class="tag green">无</span>
              <span v-else class="pill-list"><span v-for="(x, i) in p.pending_preconditions" :key="i" class="tag red">{{ x }}</span></span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { EVENT_TYPE, PACK_STATUS, tagClass } from '../statusLabels'

const packs = ref([])
const message = ref('')
const error = ref('')
const qError = ref('')
const lastReceipt = ref(null)

const form = reactive({
  batch_no: 'L-7', serial_no: '', oem: '远景车企', source_vehicle: '',
  quarantine_slot: '', responsible_team: '收货一班', events: [],
})
const canReceive = computed(() => form.batch_no && form.serial_no && form.oem && form.source_vehicle)

const batchFreezeNo = ref('L-7')
const batchFreezeReason = ref('同车到货整批核验')
const unfreezeNo = ref('')
const packQuarantineNo = ref('')
const packQuarantineReason = ref('')
const releaseNo = ref('')

async function loadPacks() {
  packs.value = await api.get('/api/receiving/packs')
}
onMounted(loadPacks)

async function submitScan() {
  message.value = ''
  error.value = ''
  try {
    const resp = await api.post('/api/receiving/scan', { ...form })
    message.value = resp.message
    lastReceipt.value = resp.receipt
    await loadPacks()
  } catch (e) {
    error.value = e.message
  }
}

async function freezeBatch() {
  qError.value = ''
  try {
    await api.post('/api/receiving/quarantine/batch', { batch_no: batchFreezeNo.value, reason: batchFreezeReason.value })
    await loadPacks()
  } catch (e) { qError.value = e.message }
}
async function unfreezeBatch() {
  qError.value = ''
  try {
    await api.post('/api/receiving/quarantine/unfreeze-batch', { batch_no: unfreezeNo.value, note: '核验完成解冻' })
    await loadPacks()
  } catch (e) { qError.value = e.message }
}
async function quarantinePack() {
  qError.value = ''
  try {
    await api.post('/api/receiving/quarantine/pack', { serial_no: packQuarantineNo.value, reason: packQuarantineReason.value })
    await loadPacks()
  } catch (e) { qError.value = e.message }
}
async function releasePack() {
  qError.value = ''
  try {
    await api.post('/api/receiving/quarantine/release', { serial_no: releaseNo.value, note: '风险边界核实完成' })
    await loadPacks()
  } catch (e) { qError.value = e.message }
}
</script>
