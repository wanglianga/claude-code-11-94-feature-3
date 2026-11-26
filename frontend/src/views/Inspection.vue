<template>
  <div>
    <div class="panel">
      <h2>🧪 检测台回执</h2>
      <p class="muted small">
        设备校准过期、绝缘测试失败或热事件未结案时，梯次利用申请会被硬拦截；BMS 当前读数正常不能抵消历史碰撞/浸水。
      </p>
      <div class="grid cols-3">
        <div><label>包序列号</label><input v-model="form.serial_no" placeholder="如 P-1" /></div>
        <div>
          <label>检测设备</label>
          <select v-model="form.device_no">
            <option v-for="d in devices" :key="d.id" :value="d.device_no">
              {{ d.device_no }} - {{ d.name }}（校准至 {{ d.calibrated_until.slice(0, 10) }}）
            </option>
          </select>
        </div>
        <div>
          <label>回执类型</label>
          <select v-model="form.is_reinspection">
            <option :value="false">初检</option>
            <option :value="true">复检（碰撞/浸水后）</option>
          </select>
        </div>
        <div>
          <label>绝缘测试</label>
          <select v-model="form.insulation_pass">
            <option :value="true">通过</option>
            <option :value="false">失败</option>
          </select>
        </div>
        <div>
          <label>BMS 当前读数</label>
          <select v-model="form.bms_reading_ok">
            <option :value="true">正常</option>
            <option :value="false">异常</option>
          </select>
        </div>
        <div><label>备注</label><input v-model="form.note" /></div>
      </div>
      <div class="row end" style="margin-top:10px"><button @click="submit">提交检测回执</button></div>
      <div v-if="msg" class="msg ok" style="margin-top:10px">{{ msg }}</div>
      <div v-if="err" class="msg err" style="margin-top:10px">{{ err }}</div>
    </div>

    <div class="panel">
      <h2>检测设备与校准有效期</h2>
      <table>
        <thead><tr><th>设备编号</th><th>名称</th><th>校准有效期至</th><th>当前是否有效</th></tr></thead>
        <tbody>
          <tr v-for="d in devices" :key="d.id">
            <td class="mono">{{ d.device_no }}</td>
            <td>{{ d.name }}</td>
            <td>{{ d.calibrated_until.slice(0, 10) }}</td>
            <td><span class="tag" :class="isCalValid(d) ? 'green' : 'red'">{{ isCalValid(d) ? '有效' : '已过期' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>历史检测回执（{{ inspections.length }}）</h2>
      <table>
        <thead><tr><th>包 ID</th><th>设备</th><th>类型</th><th>绝缘</th><th>BMS</th><th>结论</th><th>时间</th><th>备注</th></tr></thead>
        <tbody>
          <tr v-for="r in inspections" :key="r.id">
            <td>{{ r.pack_id }}</td>
            <td class="small">{{ r.device.device_no }}</td>
            <td>{{ r.is_reinspection ? '复检' : '初检' }}</td>
            <td><span class="tag" :class="r.insulation_pass ? 'green' : 'red'">{{ r.insulation_pass ? '通过' : '失败' }}</span></td>
            <td><span class="tag" :class="r.bms_reading_ok ? 'green' : 'red'">{{ r.bms_reading_ok ? '正常' : '异常' }}</span></td>
            <td><span class="tag" :class="tagClass(r.result)">{{ r.result === 'pass' ? '合格' : '不合格' }}</span></td>
            <td class="small">{{ r.created_at.slice(0, 16).replace('T', ' ') }}</td>
            <td class="small">{{ r.note || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { tagClass } from '../statusLabels'

const devices = ref([])
const inspections = ref([])
const msg = ref('')
const err = ref('')
const form = reactive({
  serial_no: '', device_no: 'DEV-OK', is_reinspection: false,
  insulation_pass: true, bms_reading_ok: true, note: '',
})

function isCalValid(d) {
  return new Date(d.calibrated_until) > new Date()
}

async function load() {
  devices.value = await api.get('/api/safety/devices')
  inspections.value = await api.get('/api/safety/inspections')
}
onMounted(load)

async function submit() {
  msg.value = ''
  err.value = ''
  try {
    const r = await api.post('/api/safety/inspections', { ...form })
    msg.value = `回执已提交，结论：${r.inspection.result === 'pass' ? '合格' : '不合格'}`
    form.serial_no = ''
    form.note = ''
    await load()
  } catch (e) { err.value = e.message }
}
</script>
