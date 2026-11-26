<template>
  <div>
    <div class="panel">
      <h2>🧩 多案竞争备件 · 带约束剪枝的精确指派搜索</h2>
      <p class="small" style="line-height:1.8;margin:0">
        优化目标按字典序：<b>① 最大化可发件数量 → ② 最小化整数调配费用 → ③ 等价方案按稳定编号决胜</b>
        （需求/备件编号排序，取分配向量字典序最小）。搜索为精确 DFS：用剩余二分图最大匹配数做数量上界、
        用最小边费用和做费用下界剪枝；<b>不是会漏掉可兑现案件的贪心</b>。候选方案不占库存，
        批准出库时行锁原子复核“全部序列号仍可用、资格有效、兼容/费用未变、需求未履行”，任一变化整案退回。
      </p>
      <div class="tabs">
        <button v-for="b in batches" :key="b.key" class="tab"
                :class="{ active: batch === b.key }" @click="switchBatch(b.key)">{{ b.label }}</button>
      </div>
    </div>

    <div v-if="msg" class="msg ok">{{ msg }}</div>
    <div v-if="err" class="msg err">{{ err }}</div>

    <!-- 安全资格撤回一键演示 -->
    <div class="panel" style="border-left:4px solid var(--warn)">
      <h2>🛡️ 演示：分配后安全资格撤回 → 旧方案原子退回</h2>
      <div class="row">
        <button class="secondary" :disabled="running" @click="runSafetyDemo">
          {{ running ? '演示执行中…' : '一键真实执行：求解 → 撤回 SS-1 资格 → 批准旧方案 → 重算' }}
        </button>
        <button class="ghost" @click="loadAll">刷新数据</button>
      </div>
      <div v-if="safetySteps.length" class="steps">
        <div v-for="(s, i) in safetySteps" :key="i" class="step" :class="s.expected_rejection ? 'reject' : (s.ok ? 'ok' : 'bad')">
          <b>[{{ s.step }}]</b> {{ s.message }}
          <div v-if="s.details && s.details.reasons" class="small danger">
            <div v-for="(r, j) in s.details.reasons" :key="j">⚠ {{ r }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="asg-grid">
      <!-- 批次输入 -->
      <div>
        <div class="panel" v-if="bd">
          <h2>本批已批准需求（{{ bd.demands.length }}）</h2>
          <table>
            <thead><tr><th>稳定编号</th><th>说明</th><th>批准</th><th>履行</th></tr></thead>
            <tbody>
              <tr v-for="d in bd.demands" :key="d.code">
                <td class="mono"><b>{{ d.code }}</b></td>
                <td class="small">{{ d.title || (d.case_id ? '案件 #' + d.case_id : '样例需求') }}</td>
                <td><span class="tag green" v-if="d.approved">已批准</span><span class="tag red" v-else>撤回</span></td>
                <td><span class="tag gray" v-if="d.fulfilled">已履行</span><span class="tag amber" v-else>未履行</span></td>
              </tr>
            </tbody>
          </table>

          <h3>物理库存 / 备件（{{ bd.units.length }}）</h3>
          <table>
            <thead><tr><th>序列号</th><th>型号</th><th>状态</th><th>安全资格</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="u in bd.units" :key="u.serial_no">
                <td class="mono">
                  {{ u.serial_no }}
                  <span v-if="u.whole_exchange_blocked" class="tag red">禁止整机换出</span>
                </td>
                <td class="small">{{ u.model_code }}</td>
                <td><span class="tag" :class="asTagClass(u.status)">{{ UNIT_STATUS[u.status] || u.status }}</span></td>
                <td>
                  <span class="tag green" v-if="u.safety_released">已放行</span>
                  <span class="tag red" v-else>已撤回</span>
                </td>
                <td>
                  <button v-if="u.safety_released" class="ghost xs"
                          @click="setSafety(u.serial_no, false)">撤回资格</button>
                  <button v-else class="secondary xs"
                          @click="setSafety(u.serial_no, true)">恢复资格</button>
                </td>
              </tr>
            </tbody>
          </table>

          <h3>固定兼容表与整数费用（{{ bd.edges.length }} 条边）</h3>
          <div class="edge-box">
            <span v-for="e in bd.edges" :key="e.demand_code + e.supply_code" class="edge-chip">
              {{ e.demand_code }}→{{ e.supply_code }} <b>¥{{ e.cost }}</b>
            </span>
          </div>

          <div class="row" style="margin-top:12px">
            <button @click="solve" :disabled="solving">
              {{ solving ? '搜索中…' : `对 ${batch} 运行精确指派搜索（生成候选，不占库存）` }}
            </button>
          </div>
        </div>

        <!-- 补库 / 加兼容边 -->
        <div class="panel">
          <h2>补库 / 维护兼容依据</h2>
          <div class="row wrap">
            <input v-model="restock.serial_no" placeholder="新备件序列号，如 SP-705" style="width:170px" />
            <input v-model="restock.model_code" placeholder="型号 PM-X3" style="width:120px" />
            <button class="secondary xs" @click="doRestock">补库到 {{ batch }}</button>
          </div>
          <div class="row wrap" style="margin-top:8px">
            <input v-model="edge.demand_code" placeholder="需求编号" style="width:120px" />
            <input v-model="edge.supply_code" placeholder="备件序列号" style="width:150px" />
            <input type="number" v-model.number="edge.cost" placeholder="费用" style="width:90px" />
            <button class="ghost xs" @click="doAddEdge">新增/更新兼容边（当前批次）</button>
          </div>
          <p class="small muted" style="margin-bottom:0">
            提示：O-31 批次 REAL 初始仅 SP-701 一台兼容件；补 SP-705 并加 D-O32→SP-705 边后重算即可同时满足两案。
          </p>
        </div>
      </div>

      <!-- 搜索结果与方案 -->
      <div>
        <div class="panel" v-if="lastPlan">
          <h2>🔎 最近搜索结果 {{ lastPlan.plan_no ? '· ' + lastPlan.plan_no : '' }}</h2>
          <div class="stat-grid">
            <div class="stat"><label>可发件数量</label><b>{{ lastPlan.fulfilled_count }}</b></div>
            <div class="stat"><label>总调配代价</label><b>¥{{ lastPlan.total_cost }}</b></div>
            <div class="stat"><label>展开分支数</label><b>{{ lastPlan.stats.branches_expanded }}</b></div>
            <div class="stat"><label>DFS 节点</label><b>{{ lastPlan.stats.dfs_nodes }}</b></div>
            <div class="stat"><label>完成耗时</label><b>{{ lastPlan.stats.elapsed_ms }} ms</b></div>
            <div class="stat" v-if="lastPlan.stats.complete_space">
              <label>完整一对一空间</label><b>{{ lastPlan.stats.complete_space.toLocaleString() }}</b>
            </div>
          </div>
          <p class="small muted" v-if="lastPlan.stats.complete_space">
            6 需求 × 8 备件全部兼容：P(8,6)=8!/2!=20160 个完整一对一指派；
            剪枝后实际展开 {{ lastPlan.stats.branches_expanded }} 个决策分支
            （指派 {{ lastPlan.stats.assign_branches }} / 跳过 {{ lastPlan.stats.skip_branches }}），
            搜索与独立暴力枚举最优解一致。
          </p>
          <table>
            <thead><tr><th>需求</th><th>指派备件</th><th>费用</th></tr></thead>
            <tbody>
              <tr v-for="i in lastPlan.items" :key="i.demand_code">
                <td class="mono">{{ i.demand_code }}</td>
                <td class="mono"><b>{{ i.supply_code }}</b></td>
                <td>¥{{ i.cost }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="lastPlan.unmet && lastPlan.unmet.length" class="small" style="margin-top:6px">
            未满足：<span class="tag amber" v-for="u in lastPlan.unmet" :key="u" style="margin-right:4px">{{ u }}</span>
          </div>
          <div class="row" style="margin-top:10px" v-if="lastPlan.id">
            <button @click="approve(lastPlan.id)">原子批准出库（复核全部序列号/需求/兼容依据）</button>
            <span class="tag" :class="asTagClass(lastPlan.status)">{{ PLAN_STATUS[lastPlan.status] }}</span>
          </div>
          <div v-for="(r, j) in lastPlan.stale_reasons" :key="j" class="msg err" style="margin-top:8px">⚠ {{ r }}</div>
        </div>

        <div class="panel">
          <h2>📋 历史方案（最近 50）</h2>
          <table>
            <thead><tr><th>方案号</th><th>批次</th><th>数量</th><th>代价</th><th>状态</th><th>操作/原因</th></tr></thead>
            <tbody>
              <tr v-for="p in plans" :key="p.id">
                <td class="mono small">{{ p.plan_no }}</td>
                <td class="small">{{ p.batch }}</td>
                <td>{{ p.fulfilled_count }}</td>
                <td>¥{{ p.total_cost }}</td>
                <td><span class="tag" :class="asTagClass(p.status)">{{ PLAN_STATUS[p.status] }}</span></td>
                <td class="small">
                  <button v-if="p.status==='candidate'" class="xs" @click="approve(p.id)">批准</button>
                  <span v-for="(r, j) in p.stale_reasons" :key="j" class="danger">⚠ {{ r }} </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { UNIT_STATUS, PLAN_STATUS, asTagClass } from '../statusLabels'

const batches = [
  { key: 'REAL', label: 'REAL · O-31/O-32 竞争最后备件' },
  { key: 'R-DEMO', label: 'R1/R2 并发样例' },
  { key: 'FULL68', label: '6×8 全兼容（20160）' },
  { key: 'SAFE', label: '安全撤回演示批' },
  { key: 'CASE-EX', label: '案件复检换货 CASE-EX' },
]
const batch = ref('REAL')
const state = ref({ batches: [] })
const plans = ref([])
const lastPlan = ref(null)
const msg = ref('')
const err = ref('')
const solving = ref(false)
const running = ref(false)
const safetySteps = ref([])
const restock = reactive({ serial_no: '', model_code: 'PM-X3' })
const edge = reactive({ demand_code: '', supply_code: '', cost: 1 })

const bd = computed(() => state.value.batches.find((b) => b.batch === batch.value))

async function loadState() {
  state.value = await api.get('/api/aftersales/assignment/state')
}
async function loadPlans() {
  plans.value = await api.get('/api/aftersales/plans')
}
async function loadAll() {
  await loadState()
  await loadPlans()
}
function switchBatch(k) {
  batch.value = k
  lastPlan.value = null
  msg.value = ''; err.value = ''
}

async function solve() {
  solving.value = true; msg.value = ''; err.value = ''
  try {
    const r = await api.post(`/api/aftersales/assignment/${batch.value}/solve`, {})
    lastPlan.value = r.plan
    msg.value = `搜索完成：可发 ${r.plan.fulfilled_count} 件，代价 ¥${r.plan.total_cost}，展开分支 ${r.plan.stats.branches_expanded}`
    await loadPlans()
  } catch (e) { err.value = e.message } finally { solving.value = false }
}

async function approve(id) {
  msg.value = ''; err.value = ''
  try {
    const r = await api.post(`/api/aftersales/plans/${id}/approve`, {})
    lastPlan.value = r.plan
    msg.value = `${r.plan.plan_no} 已原子批准：替换件出库单已生成，需求已履行、备件已占用`
    await loadAll()
  } catch (e) {
    err.value = e.message
    if (e.details && e.details.reasons) err.value += '｜' + e.details.reasons.join('；')
    const p = plans.value.find((x) => x.id === id)
    if (p) p.status = 'stale'
    const fresh = await api.get('/api/aftersales/plans').catch(() => null)
    if (fresh) plans.value = fresh
    if (lastPlan.value && lastPlan.value.id === id && fresh) {
      lastPlan.value = fresh.find((x) => x.id === id) || lastPlan.value
    }
  }
}

async function setSafety(serial, released) {
  err.value = ''
  try {
    await api.post(`/api/aftersales/units/${serial}/safety`, { released, note: released ? '资格恢复' : '演示撤回' })
    msg.value = `${serial} 安全资格已${released ? '恢复' : '撤回'}；此前生成的候选方案批准时会被原子复核拦截`
    await loadState()
  } catch (e) { err.value = e.message }
}

async function doRestock() {
  if (!restock.serial_no.trim()) { err.value = '请填写序列号'; return }
  try {
    await api.post('/api/aftersales/units/restock', { ...restock, batch: batch.value })
    msg.value = `备件 ${restock.serial_no} 已补库到 ${batch.value}`
    restock.serial_no = ''
    await loadState()
  } catch (e) { err.value = e.message }
}

async function doAddEdge() {
  if (!edge.demand_code || !edge.supply_code) { err.value = '需求/备件编号必填'; return }
  try {
    await api.post('/api/aftersales/compat-edges', { ...edge, batch: batch.value })
    msg.value = '兼容边已保存'
    await loadState()
  } catch (e) { err.value = e.message }
}

async function runSafetyDemo() {
  running.value = true; safetySteps.value = []; err.value = ''
  try {
    const r = await api.post('/api/aftersales/demo/safety-withdrawal', {})
    safetySteps.value = r.steps
    await loadAll()
    batch.value = 'SAFE'
    lastPlan.value = r.steps.find((s) => s.step === 'resolve').plan
  } catch (e) { err.value = e.message } finally { running.value = false }
}

onMounted(loadAll)
</script>

<style scoped>
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
button.tab {
  background: #fff; color: var(--primary-dark); border: 1px solid var(--border);
  padding: 7px 12px; border-radius: 20px; font-size: 13px;
}
button.tab.active { background: var(--primary); color: #fff; border-color: var(--primary); }
.asg-grid { display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 16px; align-items: start; }
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 10px 0; }
.stat { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.stat label { display: block; font-size: 11px; color: var(--muted); }
.stat b { font-size: 18px; }
.edge-box { display: flex; flex-wrap: wrap; gap: 6px; max-height: 150px; overflow: auto; }
.edge-chip { font-size: 12px; border: 1px solid var(--border); background: #f8fafc; border-radius: 6px; padding: 3px 8px; }
.steps { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.step { font-size: 13px; border-radius: 7px; padding: 8px 10px; background: #f2f4f7; border-left: 3px solid #98a2b3; }
.step.ok { background: #ecfdf3; border-left-color: var(--ok); }
.step.reject { background: #fef3f2; border-left-color: var(--danger); }
.step.bad { background: #fef3f2; border-left-color: var(--danger); }
.xs { padding: 3px 8px; font-size: 12px; }
.danger { color: var(--danger); }
.row.wrap { flex-wrap: wrap; }
@media (max-width: 1100px) { .asg-grid { grid-template-columns: 1fr; } }
</style>
